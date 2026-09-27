"""Runde 82: CBOE-Strategieindizes WPUT, BXMD, CNDR, BFLY vs S&P 500 TR."""
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from tradingbot.research.history import fetch_yahoo

tr = fetch_yahoo("^SP500TR", Path("data_cache/yahoo_unseen"), until=date(2026, 9, 26))["close"].astype(float)
tr.index = pd.to_datetime(tr.index)
tb = pd.read_pickle("data_cache/fred/TB3MS.pkl") / 100
tb.index = pd.to_datetime(tb.index)
COST = {"WPUT": 0.03, "BXMD": 0.01, "CNDR": 0.01, "BFLY": 0.01}
for sym, c in COST.items():
    s = pd.read_csv(f"data_cache/cboe/{sym}.csv", header=None, names=["d", "v"], skiprows=1)
    s = pd.Series(pd.to_numeric(s["v"], errors="coerce").to_numpy(), index=pd.to_datetime(s["d"], format="%m/%d/%Y", errors="coerce"))
    s = s[s.index.notna()].dropna().sort_index()
    s = s[~s.index.duplicated()]
    both = pd.concat([s, tr], axis=1, join="inner").dropna()
    r = both.pct_change().dropna()
    gap = r.index.to_series().diff().dt.days.fillna(1)
    rf = tb.reindex(r.index, method="ffill").fillna(0) * gap / 360
    e = r.iloc[:, 0] - c / 252 - rf
    m = r.iloc[:, 1] - rf
    ok = True
    print(f"{sym} (Daten ab {both.index[0].date()})")
    for p, a, b, th in [("Entdeckung", "1986", "2009", 2.5), ("Bestätigung 2010-2025-09", "2010", "2025-09-19", 2.0),
                        ("unberührt", "2025-09-22", "2026-09-25", None)]:
        x, y = e[a:b], m[a:b]
        beta = np.cov(x, y)[0, 1] / y.var()
        al = x - beta * y
        t = al.mean() / al.std() * np.sqrt(len(al))
        cg = (1 + r.iloc[:, 0][a:b] - c / 252).prod() ** (252 / len(x)) - 1
        ch = (1 + r.iloc[:, 1][a:b]).prod() ** (252 / len(x)) - 1
        eq = (1 + r.iloc[:, 0][a:b] - c / 252).cumprod()
        dd = (eq / eq.cummax() - 1).min()
        sh = x.mean() / x.std() * np.sqrt(252)
        print(f"  {p:26s} {cg*100:5.1f} % p.a. (S&P TR {ch*100:5.1f} %) MaxDD {dd*100:5.1f} % Sharpe {sh:4.2f} "
              f"Beta {beta:4.2f} Alpha {al.mean()*252*100:5.1f} % t {t:5.2f}")
        ok &= (t >= th) if th else (al.mean() > 0)
    print("  ->", "BESTANDEN" if ok else "NICHT BESTANDEN")

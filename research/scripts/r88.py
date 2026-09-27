"""Runde 73: Monatsend-Überrendite IEF/TLT (letzte 3 Handelstage)."""
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from tradingbot.research.history import fetch_yahoo

COST = 1e-4
tb = pd.read_pickle("data_cache/fred/TB3MS.pkl") / 100
tb.index = pd.to_datetime(tb.index)


def run(sym):
    px = fetch_yahoo(sym, Path("data_cache/yahoo_unseen"), until=date(2026, 9, 26))["adjclose"].astype(float)
    px.index = pd.to_datetime(px.index)
    r = px.pct_change().dropna()
    gap = r.index.to_series().diff().dt.days.fillna(1)
    rf = tb.reindex(r.index, method="ffill").fillna(0) * gap / 360
    ex = r - rf
    ym = ex.index.to_period("M")
    rows = []
    for p in ym.unique():
        x = ex[ym == p]
        if len(x) < 15:
            continue
        rows.append((p.to_timestamp(), x.iloc[-3:].sum() - 2 * COST, x.iloc[:-3].sum()))
    return pd.DataFrame(rows, columns=["m", "eom", "rest"]).set_index("m")


for sym, th1 in (("LQD", 2.39), ("TIP", 2.39), ("MBB", 2.39)):
    d = run(sym)
    print(sym)
    for name, s, e in [("Entdeckung bis 2018", "2002", "2018"), ("Bestätigung 2019-2025-08", "2019", "2025-08"),
                       ("unberührt 2025-09..2026-08", "2025-09", "2026-08")]:
        x = d[s:e]
        t = x["eom"].mean() / x["eom"].std() * np.sqrt(len(x))
        print(f"  {name:26s} Monate {len(x):3d} Monatsende netto {x['eom'].mean()*1e4:6.1f} bp t {t:5.2f} "
              f"Treffer {(x['eom'] > 0).mean():.2f} | übrige Tage {x['rest'].mean()*1e4:6.1f} bp")

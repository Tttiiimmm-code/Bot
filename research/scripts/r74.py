"""Runde 74: Monatsend-Überrendite Euro-Staatsanleihen (SXRQ.DE, EXX6.DE)."""
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from tradingbot.research.history import fetch_yahoo

COST = 1e-4
rf = pd.read_pickle("data_cache/fred/IR3TIB01EZM156N.pkl") / 100
rf.index = pd.to_datetime(rf.index)
for sym in ("SXRQ.DE", "EXX6.DE"):
    px = fetch_yahoo(sym, Path("data_cache/yahoo_unseen"), until=date(2026, 9, 26))["adjclose"].astype(float)
    px.index = pd.to_datetime(px.index)
    r = px.pct_change().dropna()
    r = r[r.abs() < 0.2]
    gap = r.index.to_series().diff().dt.days.fillna(1)
    ex = r - rf.reindex(r.index, method="ffill").fillna(0) * gap / 360
    ym = ex.index.to_period("M")
    rows = [(p.to_timestamp(), ex[ym == p].iloc[-3:].sum() - 2 * COST, ex[ym == p].iloc[:-3].sum())
            for p in ym.unique() if (ym == p).sum() >= 15]
    d = pd.DataFrame(rows, columns=["m", "eom", "rest"]).set_index("m")
    print(sym, px.index[0].date())
    for name, s, e in [("Entdeckung 2010-2018", "2010", "2018"), ("Bestätigung 2019-2025-08", "2019", "2025-08"),
                       ("unberührt 2025-09..2026-08", "2025-09", "2026-08")]:
        x = d[s:e]
        t = x["eom"].mean() / x["eom"].std() * np.sqrt(len(x))
        print(f"  {name:26s} Monate {len(x):3d} Monatsende netto {x['eom'].mean()*1e4:6.1f} bp t {t:5.2f} "
              f"Treffer {(x['eom'] > 0).mean():.2f} | übrige Tage {x['rest'].mean()*1e4:6.1f} bp")

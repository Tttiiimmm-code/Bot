"""Runde 85: Gotobi in EUR/JPY und AUD/JPY (Ask->Bid), Vergleich mit USD/JPY."""
import importlib.util
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from tradingbot.research import gold

spec = importlib.util.spec_from_file_location("ft", sys.argv[1])
ft = importlib.util.module_from_spec(spec); sys.modules["ft"] = ft; spec.loader.exec_module(ft)
NOW = pd.Timestamp("2026-09-26", tz="UTC")
Y = Path("data_cache/dukascopy/yen_cross")


def trades(bid, ask):
    g = pd.DataFrame(ft.gotobi_trades(bid, ask, date(2017, 1, 1), date(2026, 9, 25), 0.35e-4, NOW))
    return g.set_index(pd.to_datetime(g["date"]))["net_bp"] / 1e4


ub = pd.concat([gold.load_fx("usdjpy"), gold.load_fx("usdjpy", Path("data_cache/dukascopy/unseen_fx"))])
usd = trades(ub[~ub.index.duplicated()].sort_index(), gold.load_fx("usdjpy", Path("data_cache/dukascopy/fx_ask")))
res = {"usdjpy": usd}
for p in ("eurjpy", "audjpy"):
    res[p] = trades(gold.load_fx(f"{p}_bid", Y), gold.load_fx(f"{p}_ask", Y))
for p, r in res.items():
    ok = True
    for name, a, b, th in [("2017-2025-09", "2017", "2025-09-19", 2.24), ("unberührt", "2025-09-22", "2026-09-25", None)]:
        x = r[a:b]
        t = x.mean() / x.std() * np.sqrt(len(x))
        print(f"{p} {name:14s} n {len(x):3d} Ø netto {x.mean()*1e4:5.2f} bp t {t:5.2f} Treffer {(x>0).mean():.2f}")
        ok &= (t >= th) if th else (x.mean() > 0)
    if p != "usdjpy":
        print(f"  Korrelation mit USD/JPY-Trades: {r.corr(usd):.2f} ->", "BESTANDEN" if ok else "NICHT BESTANDEN")

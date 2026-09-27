"""Runde 89: Nikkei long 05:00->09:55 JST an Gotobi-Tagen."""
import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from tradingbot.research import gold

spec = importlib.util.spec_from_file_location("ft", sys.argv[1])
ft = importlib.util.module_from_spec(spec); sys.modules["ft"] = ft; spec.loader.exec_module(ft)
nk = pd.concat([gold.load_minutes(Path("data_cache/dukascopy/idx"), "jpnidxjpy_*.csv"),
                gold.load_minutes(Path("data_cache/dukascopy/unseen"), "jpnidxjpy_*.csv")])["open"]
nk = nk[~nk.index.duplicated()].sort_index()
got = ft.gotobi_days(2013, 2026)
g, o = {}, {}
for d in pd.bdate_range("2013-10-01", "2026-09-25"):
    a = gold.price_at(nk, pd.Timestamp(d.date()).tz_localize("Asia/Tokyo").replace(hour=5).tz_convert("UTC"))
    b = gold.price_at(nk, pd.Timestamp(d.date()).tz_localize("Asia/Tokyo").replace(hour=9, minute=55).tz_convert("UTC"))
    if a and b:
        (g if d.date() in got else o)[d] = b / a - 1 - 2e-4
G, O = pd.Series(g), pd.Series(o)
ok = True
for name, s, e, th in [("Entdeckung 2013-2019", "2013", "2019", 2.0), ("Bestätigung 2020-2025-09", "2020", "2025-09-19", 2.0),
                       ("unberührt", "2025-09-22", "2026-09-25", None)]:
    x = G[s:e]
    t = x.mean() / x.std() * np.sqrt(len(x))
    print(f"{name:26s} Gotobi n {len(x):3d} Ø {x.mean()*1e4:6.2f} bp t {t:5.2f} Treffer {(x>0).mean():.2f} | andere Tage Ø {O[s:e].mean()*1e4:5.2f} bp")
    ok &= (t >= th) if th else (x.mean() > 0)
print("->", "BESTANDEN" if ok else "NICHT BESTANDEN")

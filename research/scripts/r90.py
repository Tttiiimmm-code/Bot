"""Runde 90: SPY über Nacht nach VIX-Anstieg >= 10 %."""
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from tradingbot.research.history import fetch_yahoo

spy = pd.read_pickle("data_cache/yahoo_unseen/SPY_full.pkl")[["open", "close"]].astype(float)
spy.index = pd.to_datetime(spy.index)
vix = fetch_yahoo("^VIX", Path("data_cache/yahoo_unseen"), until=date(2026, 9, 26))["close"].astype(float)
vix.index = pd.to_datetime(vix.index)
dv = vix.pct_change()
night = (spy["open"].shift(-1) / spy["close"] - 1).dropna() - 2e-4
sig = dv.reindex(night.index) >= 0.10
ok = True
for name, s, e, th in [("Entdeckung 2011-2018", "2011", "2018", 2.0), ("Bestätigung 2019-2025-09", "2019", "2025-09-19", 2.0),
                       ("unberührt", "2025-09-22", "2026-09-25", None)]:
    x = night[s:e][sig[s:e]]; c = night[s:e][~sig[s:e]]
    t = x.mean() / x.std() * np.sqrt(len(x))
    print(f"{name:26s} Signalnächte {len(x):3d} Ø {x.mean()*1e4:6.1f} bp t {t:5.2f} Treffer {(x>0).mean():.2f} | übrige Nächte Ø {c.mean()*1e4:5.1f} bp")
    ok &= (t >= th) if th else (x.mean() > 0)
print("->", "BESTANDEN" if ok else "NICHT BESTANDEN")

"""Runde 64: Intraday-Momentum am Nikkei (letzte 30 min der OSE-Tagessitzung)."""
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from tradingbot.research import gold

COST = 0.75e-4
CHANGE = date(2024, 11, 5)
PERIODS = [("Entdeckung", "2013-01-01", "2019-12-31", 2.0), ("Bestätigung", "2020-01-01", "2025-09-19", 2.0),
           ("unberührt", "2025-09-22", "2026-09-25", None)]

m = pd.concat([gold.load_minutes(Path("data_cache/dukascopy/idx"), "jpnidxjpy_*.csv"),
               gold.load_minutes(Path("data_cache/dukascopy/unseen"), "jpnidxjpy_*.csv")])
px = m[~m.index.duplicated()].sort_index()["open"]


def close_ts(d):
    h, mi = (15, 45) if d.date() >= CHANGE else (15, 15)
    return pd.Timestamp(d.date()).tz_localize("Asia/Tokyo") + pd.Timedelta(hours=h, minutes=mi)


def at(ts):
    return gold.price_at(px, ts.tz_convert("UTC"))


res, prev_close = {}, None
for d in pd.date_range("2013-01-01", "2026-09-25", freq="B"):
    s = close_ts(d)
    p30, pc = at(s - pd.Timedelta(minutes=30)), at(s)
    # Vortagesschluss nur von einem echten Handelstag (Kurs vorhanden)
    if p30 and pc and prev_close:
        sig = np.sign(p30 / prev_close - 1)
        if sig != 0:
            res[d] = sig * (pc / p30 - 1) - 2 * COST
    if pc:
        prev_close = pc
r = pd.Series(res)
ok = True
for name, s, e, th in PERIODS:
    v = r[s:e]
    t = v.mean() / v.std() * np.sqrt(len(v))
    print(f"{name:12s} n {len(v):5d} netto {v.mean()*1e4:6.2f} bp brutto {(v.mean()+2*COST)*1e4:6.2f} bp t {t:5.2f} "
          f"Treffer {(v > 0).mean():.3f}")
    ok &= (t >= th) if th else (v.mean() > 0)
print("je Jahr netto bp:", " ".join(f"{y}:{x:.1f}" for y, x in (r.groupby(r.index.year).mean() * 1e4).items()))
print("->", "BESTANDEN" if ok else "NICHT BESTANDEN")

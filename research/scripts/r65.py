"""Runde 65: Bitcoin short 09:30-10:30 New York an US-Handelstagen."""
from pathlib import Path

import numpy as np
import pandas as pd

from tradingbot.research import gold

COST = 5e-4
frames = []
for p in sorted(Path("data_cache/btc_1m").glob("BTCUSDT-1m-*.csv")):
    d = pd.read_csv(p, header=None, usecols=[0, 1])
    ts = d[0].where(d[0] < 1e14, d[0] // 1000)
    frames.append(pd.Series(d[1].to_numpy(float), index=pd.to_datetime(ts, unit="ms", utc=True)))
px = pd.concat(frames)
px = px[~px.index.duplicated()].sort_index()
spy_days = set(pd.read_pickle("data_cache/yahoo_unseen/SPY_full.pkl").index)

res = {}
for d in pd.date_range("2020-01-01", "2026-09-25", freq="B"):
    if d.date() not in spy_days:
        continue
    ny = pd.Timestamp(d.date()).tz_localize("America/New_York")
    a = gold.price_at(px, (ny + pd.Timedelta(hours=9, minutes=30)).tz_convert("UTC"))
    b = gold.price_at(px, (ny + pd.Timedelta(hours=10, minutes=30)).tz_convert("UTC"))
    if a and b:
        res[d] = -(b / a - 1) - 2 * COST
r = pd.Series(res)
ok = True
for name, s, e, th in [("Kontrolle vor ETF", "2020-01-01", "2024-01-10", None),
                       ("Entdeckung", "2024-01-11", "2025-06-30", 2.0),
                       ("Bestätigung", "2025-07-01", "2026-09-25", 2.0)]:
    v = r[s:e]
    t = v.mean() / v.std() * np.sqrt(len(v))
    print(f"{name:18s} n {len(v):4d} netto {v.mean()*1e4:6.2f} bp brutto {(v.mean()+2*COST)*1e4:6.2f} bp t {t:5.2f} "
          f"Short-Treffer {((v + 2*COST) > 0).mean():.3f}")
    if th:
        ok &= t >= th
print("Halbjahre brutto bp:", " ".join(f"{k}:{x:.1f}" for k, x in ((r + 2*COST).groupby(
    [r.index.year, (r.index.month - 1) // 6]).mean() * 1e4).items()))
print("->", "BESTANDEN" if ok else "NICHT BESTANDEN")

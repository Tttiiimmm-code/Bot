"""Runde 71: Spot-BTC-ETF-Flüsse -> BTC-Rendite 14:00 UTC t+1 bis 14:00 UTC t+2."""
import json
from pathlib import Path

import numpy as np
import pandas as pd

from tradingbot.research import gold

COST = 5e-4
flows = {}
for line in json.load(open("data_cache/farside_btc_etf.json", encoding="utf-8")).split("\n"):
    d, v = line.split(";")
    try:
        ts = pd.Timestamp(d)
    except Exception:
        continue
    v = v.replace(",", "")
    if v in ("", "-"):
        continue
    flows[ts] = -float(v[1:-1]) if v.startswith("(") else float(v)
F = pd.Series(flows).sort_index()
print("Flusstage", len(F), F.index[0].date(), F.index[-1].date())

frames = []
for p in sorted(Path("data_cache/btc_1m").glob("BTCUSDT-1m-*.csv")):
    d = pd.read_csv(p, header=None, usecols=[0, 1])
    ts = d[0].where(d[0] < 1e14, d[0] // 1000)
    frames.append(pd.Series(d[1].to_numpy(float), index=pd.to_datetime(ts, unit="ms", utc=True)))
px = pd.concat(frames)
px = px[~px.index.duplicated()].sort_index()

rows = []
for t, f in F.items():
    if f == 0:
        continue
    t0 = (t + pd.Timedelta(days=1, hours=14)).tz_localize("UTC")
    a, b = gold.price_at(px, t0), gold.price_at(px, t0 + pd.Timedelta(days=1))
    c0, c1 = gold.price_at(px, (t + pd.Timedelta(hours=14, minutes=30)).tz_localize("UTC")), \
        gold.price_at(px, (t + pd.Timedelta(hours=21)).tz_localize("UTC"))
    if a and b:
        rows.append((t, f, np.sign(f) * (b / a - 1) - 2 * COST, (c1 / c0 - 1) if c0 and c1 else np.nan))
r = pd.DataFrame(rows, columns=["t", "F", "net", "same"]).set_index("t")
print("Korrelation Fluss / gleichzeitige Rendite (US-Sitzung):", round(r["F"].corr(r["same"]), 3))
for name, s, e in [("Entdeckung", "2024-01-11", "2025-04-30"), ("Bestätigung", "2025-05-01", "2026-09-25")]:
    x = r[s:e]
    for lab, y in (("alle", x), ("|F|>200", x[x["F"].abs() > 200])):
        v = y["net"]
        t = v.mean() / v.std() * np.sqrt(len(v))
        print(f"{name:12s} {lab:8s} n {len(v):3d} netto {v.mean()*1e4:7.2f} bp brutto {(v.mean()+2*COST)*1e4:7.2f} bp "
              f"t {t:5.2f} Treffer {(v > 0).mean():.2f}")

"""Runde 77: Short neu gelisteter Binance-Token (L+1 .. L+30), abgesichert gegen BTC."""
from pathlib import Path

import numpy as np
import pandas as pd

COST = 0.001 + 30 * 0.0003
btc = pd.read_pickle("data_cache/crypto/BTCUSDT.pkl")["close"]
btc.index = pd.to_datetime(btc.index)
rows = []
for p in Path("data_cache/crypto").glob("*USDT.pkl"):
    d = pd.read_pickle(p)
    d.index = pd.to_datetime(d.index)
    if len(d) < 32 or d.index[0] < pd.Timestamp("2020-01-01") or p.stem in ("BTCUSDT",):
        continue
    L = d.index[0]
    t0, t1 = d.index[1], d.index[30]
    if (t1 - t0).days != 29 or d.loc[t0, "quote_volume"] < 5e6 or t0 not in btc.index or t1 not in btc.index:
        continue
    tok = d.loc[t1, "close"] / d.loc[t0, "close"] - 1
    b = btc[t1] / btc[t0] - 1
    rows.append((L, p.stem, -(tok - b) - COST, -tok - COST))
r = pd.DataFrame(rows, columns=["L", "sym", "abn", "raw"]).sort_values("L")
print("Listings:", len(r))
for name, s, e, th in [("Entdeckung 2020-2023", "2020", "2023-12-31", 2), ("Bestätigung 2024-2025-08", "2024", "2025-08-20", 2),
                       ("unberührt", "2025-08-21", "2026-08-26", None)]:
    x = r[(r["L"] >= s) & (r["L"] <= e)]
    t = x["abn"].mean() / x["abn"].std() * np.sqrt(len(x))
    print(f"{name:26s} n {len(x):3d} Ø netto {x['abn'].mean()*100:6.2f} % t {t:5.2f} Median {x['abn'].median()*100:6.2f} % "
          f"Treffer {(x['abn']>0).mean():.2f} schlimmster {x['abn'].min()*100:7.1f} % | ohne Absicherung Ø {x['raw'].mean()*100:6.2f} %")

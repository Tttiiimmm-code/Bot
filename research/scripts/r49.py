"""Runde 49: Gotobi mit echten Bid/Ask-Kursen."""
import sys
from datetime import date
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, "research/scripts")
from gotobi import gotobi_days
from tradingbot.research import gold

COMM = 0.000035  # ~0,35 bp je Seite


def load(base, pattern):
    frames = [pd.read_csv(p) for p in sorted(Path(base).glob(pattern))]
    df = pd.concat(frames)
    s = pd.Series(df["open"].to_numpy(float), index=pd.to_datetime(df["timestamp"], unit="ms", utc=True))
    s = s[~s.index.duplicated()].sort_index()
    s.index = s.index.tz_convert("Asia/Tokyo")
    return s


bid = pd.concat([load("data_cache/dukascopy/fx", "usdjpy_20*.csv"), load("data_cache/dukascopy/unseen_fx", "usdjpy_2026.csv")])
bid = bid[~bid.index.duplicated()].sort_index()
ask = load("data_cache/dukascopy/fx_ask", "usdjpy_*.csv")
G = gotobi_days(2016, 2026)
rows, spreads = {}, []
for d in sorted(G):
    if d < date(2017, 1, 1) or d > date(2026, 9, 25):
        continue
    t0 = pd.Timestamp(f"{d} 05:00", tz="Asia/Tokyo")
    t1 = pd.Timestamp(f"{d} 09:55", tz="Asia/Tokyo")
    a0, b0, b1, a1 = gold.price_at(ask, t0), gold.price_at(bid, t0), gold.price_at(bid, t1), gold.price_at(ask, t1)
    if None in (a0, b1, b0, a1):
        continue
    rows[d] = b1 / a0 - 1 - 2 * COMM
    spreads.append(((a0 - b0) / b0 * 1e4, (a1 - b1) / b1 * 1e4))
r = pd.Series(rows).sort_index()
sp = np.array(spreads)
print(f"mittlerer Spread 05:00 {np.mean(sp[:, 0]):.2f} bp (Median {np.median(sp[:, 0]):.2f}), 09:55 {np.mean(sp[:, 1]):.2f} bp (Median {np.median(sp[:, 1]):.2f})")
for name, (a, b) in (("2017-2025", (date(2017, 1, 1), date(2025, 9, 19))), ("unberührt", (date(2025, 9, 22), date(2026, 9, 25)))):
    x = r[(r.index >= a) & (r.index <= b)]
    t = x.mean() / x.std() * np.sqrt(len(x))
    print(f"{name:10s} Trades {len(x):4d} Ø netto {x.mean() * 1e4:5.2f} bp Treffer {(x > 0).mean():.0%} Summe {x.sum():6.2%} t {t:5.2f}")

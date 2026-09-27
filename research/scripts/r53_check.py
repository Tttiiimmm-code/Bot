"""Kontrolle Runde 53: Nikkei-Nacht zu OSE-Future-Zeiten (Dukascopy-CFD)."""
from datetime import date
from pathlib import Path
import numpy as np, pandas as pd
from tradingbot.research import anomalies, gold

frames = [gold.load_minutes(Path("data_cache/dukascopy/idx"), "jpnidxjpy_*.csv"),
          gold.load_minutes(Path("data_cache/dukascopy/unseen"), "jpnidxjpy_*.csv")]
m = pd.concat(frames)
m = m[~m.index.duplicated()].sort_index()
o = m["open"].copy()
o.index = o.index.tz_convert("Asia/Tokyo")
rate = anomalies.fetch_fred("IR3TIB01JPM156N") / 100


def at(d, hh, mm):
    ts = pd.Timestamp(f"{d} {hh:02d}:{mm:02d}", tz="Asia/Tokyo")
    p = o.index.searchsorted(ts)
    if p >= len(o) or o.index[p] - ts > pd.Timedelta(minutes=5):
        return None
    return float(o.iloc[p])


days = sorted({d for d in o.index.date if pd.Timestamp(d).weekday() < 5})
rows = {}
for a, b in zip(days[:-1], days[1:]):
    close_t = (15, 45) if a >= date(2024, 11, 5) else (15, 15)
    c, n = at(a, *close_t), at(b, 8, 45)
    if c is None or n is None:
        continue
    rf = rate[rate.index <= pd.Timestamp(a)]
    rf = max(float(rf.iloc[-1]), 0.0) if len(rf) else 0.0
    rows[b] = n / c - 1 - 2 * 0.00005 - rf / 360 * (b - a).days
s = pd.Series(rows).sort_index()
for name, (a, b) in (("2013-2018", (date(2013, 1, 1), date(2018, 12, 31))), ("2019-2025", (date(2019, 1, 1), date(2025, 9, 19))),
                     ("2013-2025", (date(2013, 1, 1), date(2025, 9, 19))), ("unberührt", (date(2025, 9, 22), date(2026, 9, 25)))):
    x = s[(s.index >= a) & (s.index <= b)]
    print(f"{name:10s} Nächte {len(x):4d} Ø netto {x.mean() * 1e4:5.2f} bp ({(1 + x).prod() ** (252 / len(x)) - 1:6.1%} p.a.) "
          f"t {x.mean() / x.std() * np.sqrt(len(x)):5.2f}")

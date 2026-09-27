"""Runde 45: unberührtes Jahr 2025-09-22..2026-09-25 für den Nachteffekt."""
from datetime import date
from pathlib import Path
import numpy as np, pandas as pd
from tradingbot.research import anomalies, gold
from tradingbot.research.__main__ import _log_trial
from tradingbot.research.engine import CostModel, BacktestResult

SPEC = {  # Instrument: (Zeitzone, Schluss, Eröffnung, Zinsreihe)
    "deuidxeur": ("Europe/Berlin", (17, 30), (9, 0), "IR3TIB01EZM156N"),
    "usa500idxusd": ("America/New_York", (16, 0), (9, 30), "IR3TIB01USM156N"),
    "usatechidxusd": ("America/New_York", (16, 0), (9, 30), "IR3TIB01USM156N"),
    "gbridxgbp": ("Europe/London", (16, 30), (8, 0), "IR3TIB01GBM156N"),
    "fraidxeur": ("Europe/Paris", (17, 30), (9, 0), "IR3TIB01EZM156N"),
    "jpnidxjpy": ("Asia/Tokyo", (15, 0), (9, 0), "IR3TIB01JPM156N"),
}
nets = {}
for inst, (tz, (ch, cm), (oh, om), rser) in SPEC.items():
    m = gold.load_minutes(Path("data_cache/dukascopy/unseen"), f"{inst}_*.csv")
    o = m["open"].copy()
    o.index = o.index.tz_convert(tz)
    rate = anomalies.fetch_fred(rser) / 100
    days = sorted({d for d in o.index.date if pd.Timestamp(d).weekday() < 5 and date(2025, 9, 19) <= d <= date(2026, 9, 25)})

    def at(d, hh, mm):
        ts = pd.Timestamp(f"{d} {hh:02d}:{mm:02d}", tz=tz)
        p = o.index.searchsorted(ts)
        if p >= len(o) or o.index[p] - ts > pd.Timedelta(minutes=5):
            return None
        return float(o.iloc[p])

    rows = {}
    for a, b in zip(days[:-1], days[1:]):
        c, n = at(a, ch, cm), at(b, oh, om)
        if c is None or n is None:
            continue
        rf = rate[rate.index <= pd.Timestamp(a)]
        rf = max(float(rf.iloc[-1]), 0.0) if len(rf) else 0.0
        rows[b] = n / c - 1 - 2 * 0.00005 - rf / 360 * (b - a).days
    nets[inst] = pd.Series(rows).sort_index()

for inst, x in nets.items():
    x = x[x.index >= date(2025, 9, 22)]
    print(f"{inst:14s} Nächte {len(x):3d} Ø netto {x.mean() * 1e4:6.2f} bp t {x.mean() / x.std() * np.sqrt(len(x)):5.2f} "
          f"Jahr {(1 + x).prod() - 1:6.1%} -> {'bestätigt' if x.mean() > 0 else 'verworfen'}")
df = pd.DataFrame(nets)
df = df[df.index >= date(2025, 9, 22)]
for name, cols in (("5-Index-Portfolio", [c for c in df.columns if c != "deuidxeur"]), ("6-Index-Portfolio", list(df.columns))):
    p = df[cols].mean(axis=1, skipna=True).dropna()
    print(f"{name}: Nächte {len(p)} Ø {p.mean() * 1e4:5.2f} bp t {p.mean() / p.std() * np.sqrt(len(p)):5.2f} Jahr {(1 + p).prod() - 1:6.1%} "
          f"-> {'bestätigt' if p.mean() > 0 else 'verworfen'}")

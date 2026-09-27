"""Runde 43: Replikation des Nachteffekts an 5 Indizes (Dukascopy-CFD)."""
from datetime import date
from pathlib import Path
import numpy as np, pandas as pd
from tradingbot.research import anomalies, gold
from tradingbot.research.__main__ import _log_trial
from tradingbot.research.engine import CostModel, BacktestResult

SPEC = {  # Instrument: (Zeitzone, Schluss, Eröffnung, Zinsreihe)
    "usa500idxusd": ("America/New_York", (16, 0), (9, 30), "IR3TIB01USM156N"),
    "usatechidxusd": ("America/New_York", (16, 0), (9, 30), "IR3TIB01USM156N"),
    "gbridxgbp": ("Europe/London", (16, 30), (8, 0), "IR3TIB01GBM156N"),
    "fraidxeur": ("Europe/Paris", (17, 30), (9, 0), "IR3TIB01EZM156N"),
    "jpnidxjpy": ("Asia/Tokyo", (15, 0), (9, 0), "IR3TIB01JPM156N"),
}
nets = {}
for inst, (tz, (ch, cm), (oh, om), rser) in SPEC.items():
    m = gold.load_minutes(Path("data_cache/dukascopy/idx"), f"{inst}_*.csv")
    o = m["open"].copy()
    o.index = o.index.tz_convert(tz)
    rate = anomalies.fetch_fred(rser) / 100
    days = sorted({d for d in o.index.date if pd.Timestamp(d).weekday() < 5 and d <= date(2025, 9, 19)})

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

halves = (("2013-2018", date(2013, 1, 1), date(2018, 12, 31)), ("2019-2025", date(2019, 1, 1), date(2025, 9, 19)))
pos = 0
for inst, s in nets.items():
    parts = []
    for name, a, b in halves:
        x = s[(s.index >= a) & (s.index <= b)]
        parts.append(f"{name}: Ø {x.mean() * 1e4:5.2f} bp t {x.mean() / x.std() * np.sqrt(len(x)):5.2f}")
    pos += s.mean() > 0
    print(f"{inst:14s} Nächte {len(s):4d} gesamt Ø {s.mean() * 1e4:5.2f} bp/Nacht t {s.mean() / s.std() * np.sqrt(len(s)):5.2f} | " + " | ".join(parts))
port = pd.DataFrame(nets).mean(axis=1, skipna=True).dropna()
t_all = port.mean() / port.std() * np.sqrt(len(port))
means = []
for name, a, b in halves:
    x = port[(port.index >= a) & (port.index <= b)]
    means.append(x.mean())
    print(f"Portfolio {name}: Ø {x.mean() * 1e4:5.2f} bp, {(1 + x).prod() ** (252 / len(x)) - 1:6.1%} p.a., "
          f"Sharpe {x.mean() / x.std() * np.sqrt(252):4.2f}, t {x.mean() / x.std() * np.sqrt(len(x)):5.2f}")
print(f"Portfolio gesamt: Ø {port.mean() * 1e4:5.2f} bp, t {t_all:5.2f}; Indizes netto positiv: {pos}/5")
_log_trial("night_replication", "5 index CFDs", {"cost": "future"}, CostModel(slippage_bps=0.5), 1.0, BacktestResult("night5", port))
ok = t_all >= 2 and all(x > 0 for x in means) and pos >= 4
print("->", "BESTANDEN" if ok else "NICHT BESTANDEN")

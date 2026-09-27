"""Runde 56: Nachteffekt Hang Seng und ASX 200."""
from datetime import date
from pathlib import Path
import numpy as np, pandas as pd
from tradingbot.research import anomalies, gold
from tradingbot.research.__main__ import _log_trial
from tradingbot.research.engine import CostModel, BacktestResult

SPEC = {"hkgidxhkd": ("Asia/Hong_Kong", (16, 0), (9, 30), "IR3TIB01USM156N"),
        "ausidxaud": ("Australia/Sydney", (16, 0), (10, 0), "IR3TIB01AUM156N")}
nets = {}
for inst, (tz, (ch, cm), (oh, om), rser) in SPEC.items():
    m = pd.concat([gold.load_minutes(Path("data_cache/dukascopy/idx"), f"{inst}_*.csv"),
                   gold.load_minutes(Path("data_cache/dukascopy/unseen"), f"{inst}_*.csv")])
    o = m["open"]
    o = o[~o.index.duplicated()].sort_index()
    o.index = o.index.tz_convert(tz)
    rate = anomalies.fetch_fred(rser) / 100
    days = sorted({d for d in o.index.date if d.weekday() < 5 and d <= date(2026, 9, 25)})

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
P = {"2013-2018": (date(2013, 1, 1), date(2018, 12, 31)), "2019-2025": (date(2019, 1, 1), date(2025, 9, 19)),
     "2013-2025": (date(2013, 1, 1), date(2025, 9, 19)), "unberührt": (date(2025, 9, 22), date(2026, 9, 25))}
for inst, s in nets.items():
    print(inst, " | ".join(f"{k}: Ø {s[(s.index >= a) & (s.index <= b)].mean() * 1e4:5.2f} bp t "
                           f"{s[(s.index >= a) & (s.index <= b)].mean() / s[(s.index >= a) & (s.index <= b)].std() * np.sqrt(((s.index >= a) & (s.index <= b)).sum()):5.2f}"
                           for k, (a, b) in P.items()))
port = pd.DataFrame(nets).mean(axis=1, skipna=True).dropna()
res = {}
for k, (a, b) in P.items():
    x = port[(port.index >= a) & (port.index <= b)]
    res[k] = (x.mean() / x.std() * np.sqrt(len(x)), x.mean())
    print(f"Portfolio {k:10s} Nächte {len(x):4d} Ø {x.mean() * 1e4:5.2f} bp ({(1 + x).prod() ** (252 / len(x)) - 1:6.1%} p.a.) t {res[k][0]:5.2f}")
full = port[(port.index >= date(2013, 1, 1)) & (port.index <= date(2025, 9, 19))]
_log_trial("night_asia_pacific", "HSI/ASX", {}, CostModel(slippage_bps=0.5), 1.0, BacktestResult("night hk au", full))
ok = res["2013-2025"][0] >= 2 and all(s[(s.index <= date(2025, 9, 19))].mean() > 0 for s in nets.values()) and res["unberührt"][1] > 0
print("->", "BESTANDEN" if ok else "NICHT BESTANDEN")

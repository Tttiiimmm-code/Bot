"""Runde 53: Nikkei-Nachteffekt 1994-2013."""
from datetime import date
from pathlib import Path
import numpy as np, pandas as pd
from tradingbot.research import anomalies, history
from tradingbot.research.__main__ import _log_trial
from tradingbot.research.engine import CostModel, BacktestResult

df = history.fetch_yahoo_ohlc("^N225", base=Path("data_cache/yahoo_unseen"), until=date(2026, 9, 26))
rate = anomalies.fetch_fred("IR3TIB01JPM156N") / 100
idx = df.index
night = df["open"] / df["close"].shift(1) - 1
nights = pd.Series([np.nan] + [(b - a).days for a, b in zip(idx[:-1], idx[1:])], index=idx)
ym = pd.PeriodIndex([pd.Timestamp(d) for d in idx], freq="M").to_timestamp()
rf = pd.Series(rate.reindex(ym, method="ffill").to_numpy(), index=idx).ffill().bfill().clip(lower=0)
net = (night - 2 * 0.00005 - rf.shift(1) / 360 * nights).dropna()
day = df["close"] / df["open"] - 1
for name, (a, b) in (("1994-2003", (date(1994, 1, 1), date(2003, 12, 31))), ("2004-2013", (date(2004, 1, 1), date(2013, 9, 29))),
                     ("1994-2013 gesamt", (date(1994, 1, 1), date(2013, 9, 29)))):
    x = net[(net.index >= a) & (net.index <= b)]
    g = night.reindex(x.index)
    d = day[(day.index >= a) & (day.index <= b)]
    t = x.mean() / x.std() * np.sqrt(len(x))
    print(f"{name:17s} Nächte {len(x):4d} brutto Ø {g.mean() * 1e4:5.2f} bp, netto Ø {x.mean() * 1e4:5.2f} bp "
          f"({(1 + x).prod() ** (252 / len(x)) - 1:6.1%} p.a.), t {t:5.2f} | Tagsüber Ø {d.mean() * 1e4:5.2f} bp")
x = net[(net.index >= date(1994, 1, 1)) & (net.index <= date(2013, 9, 29))]
_log_trial("night_nikkei_early", "^N225", {}, CostModel(slippage_bps=0.5), 1.0, BacktestResult("n225 night", x))
t = x.mean() / x.std() * np.sqrt(len(x))
print("->", "BESTANDEN" if t >= 2 and x.mean() > 0 else "NICHT BESTANDEN")

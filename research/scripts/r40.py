"""Runde 40: DAX-Nachteffekt per CFD."""
from datetime import date
import pandas as pd
from tradingbot.research import anomalies, history, swing
from tradingbot.research.__main__ import _log_trial
from tradingbot.research.engine import CostModel, BacktestResult
from tradingbot.research.metrics import compute_metrics

df = history.fetch_yahoo_ohlc("^GDAXI")
df = df[df.index <= date(2025, 9, 19)]
rate = anomalies.fetch_fred("IR3TIB01EZM156N") / 100
ym = pd.PeriodIndex([pd.Timestamp(d) for d in df.index], freq="M").to_timestamp()
r = pd.Series(rate.reindex(ym, method="ffill").to_numpy(), index=df.index).bfill()
nights = pd.Series([(b - a).days for a, b in zip(df.index[:-1], df.index[1:])], index=df.index[1:])
night = df["open"] / df["close"].shift(1) - 1
fin = (r.shift(1) + 0.025) / 360 * nights
net = (night - 2 * 0.0001 - fin).dropna()
hold = df["close"].pct_change().reindex(net.index)
for name, (a, b) in (("Entdeckung", (date(1993, 1, 1), date(2008, 12, 31))), ("Bestätigung", (date(2009, 1, 1), date(2025, 9, 19)))):
    m_ = (net.index >= a) & (net.index <= b)
    s, h, g = net[m_], hold[m_], night.reindex(net.index)[m_]
    ms, mh = compute_metrics(BacktestResult("s", s)), compute_metrics(BacktestResult("h", h))
    al, t, beta = swing.alpha_vs_benchmark(s, h)
    print(f"{name:11s} brutto Ø {g.mean() * 1e4:5.2f} bp/Nacht ({(1 + g).prod() ** (252 / len(g)) - 1:6.1%} p.a.) | netto {ms.cagr:6.1%} p.a. "
          f"Sharpe {ms.sharpe:4.2f} MaxDD {ms.max_drawdown:6.1%} | Halten {mh.cagr:6.1%} {mh.sharpe:4.2f} {mh.max_drawdown:6.1%} | "
          f"Finanzierung Ø {fin.reindex(s.index).mean() * 1e4:4.2f} bp | Alpha {al:6.1%} t {t:5.2f} beta {beta:4.2f}")
    if name == "Entdeckung":
        _log_trial("dax_night", "^GDAXI", {"cfd": True}, CostModel(slippage_bps=1.0), 1.0, BacktestResult("dax night", s))

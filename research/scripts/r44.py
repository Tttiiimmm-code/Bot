"""Runde 44: CBOE PutWrite vs. S&P 500 TR."""
from datetime import date
import pandas as pd
from tradingbot.research import swing
from tradingbot.research.__main__ import _log_trial
from tradingbot.research.engine import CostModel, BacktestResult
from tradingbot.research.metrics import compute_metrics, yearly_returns
exec(open("research/scripts/r38.py", encoding="utf-8").read().split("tb = anomalies")[0].split('"""', 2)[2])
put, spx = long_history("^PUT"), long_history("^SP500TR")
df = pd.DataFrame({"put": put, "spx": spx}).dropna()
r = df.pct_change().dropna()
for name, (a, b) in (("Entdeckung", (date(1996, 8, 1), date(2009, 12, 31))), ("Bestätigung", (date(2010, 1, 1), date(2025, 9, 19)))):
    x = r[(r.index >= a) & (r.index <= b)]
    mp, ms = compute_metrics(BacktestResult("p", x["put"])), compute_metrics(BacktestResult("s", x["spx"]))
    al, t, beta = swing.alpha_vs_benchmark(x["put"], x["spx"])
    print(f"{name:11s} PUT {mp.cagr:6.1%} Sharpe {mp.sharpe:4.2f} MaxDD {mp.max_drawdown:6.1%} | S&P TR {ms.cagr:6.1%} {ms.sharpe:4.2f} "
          f"{ms.max_drawdown:6.1%} | Alpha {al:6.1%} t {t:5.2f} beta {beta:4.2f}")
    if name == "Entdeckung":
        _log_trial("putwrite", "^PUT", {}, CostModel(slippage_bps=0.0), 1.0, BacktestResult("put", x["put"]))

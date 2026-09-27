"""Runde 59: Prämie an Makro-Ankündigungstagen."""
import json
from datetime import date
from pathlib import Path
import numpy as np, pandas as pd
from tradingbot.research import anomalies, history
from tradingbot.research.__main__ import _log_trial
from tradingbot.research.engine import CostModel, BacktestResult

t = open("data_cache/bls_release_dates.json", encoding="utf-8").read()
j = json.loads(t[t.index("{"):t.rindex("}") + 1])
ev = {"NFP": {date.fromisoformat(x) for x in j["empsit"]}, "CPI": {date.fromisoformat(x) for x in j["cpi"]},
      "FOMC": set(anomalies.fomc_decision_days())}
spy = history.fetch_yahoo("SPY", base=Path("data_cache/yahoo_unseen"), until=date(2026, 9, 26))["adjclose"]
r = spy.pct_change().dropna()
r = r[r.index >= date(2002, 7, 1)]
tb = anomalies.fetch_fred("TB3MS") / 100
ym = pd.PeriodIndex([pd.Timestamp(d) for d in r.index], freq="M").to_timestamp()
rf = pd.Series(tb.reindex(ym, method="ffill").to_numpy(), index=r.index).ffill() / 252
ex = r - rf
ann = pd.Series([any(d in s for s in ev.values()) for d in r.index], index=r.index)
print("Termine im Datenbereich:", {k: sum(1 for d in v if r.index[0] <= d <= r.index[-1]) for k, v in ev.items()},
      "FOMC-Bereich:", min(ev["FOMC"]), max(ev["FOMC"]))
P = {"2002-07..2012 (vor Veröff.)": (date(2002, 7, 1), date(2012, 12, 31)), "2013..2025-09 (nach Veröff.)": (date(2013, 1, 1), date(2025, 9, 19)),
     "unberührt": (date(2025, 9, 22), date(2026, 9, 25))}
res = {}
for name, (a, b) in P.items():
    m = (r.index >= a) & (r.index <= b)
    x = ex[m & ann.to_numpy()] - 2 * 0.0001
    other = ex[m & ~ann.to_numpy()]
    tt = x.mean() / x.std() * np.sqrt(len(x))
    res[name] = (tt, x.mean())
    print(f"{name:30s} Ankündigungstage {len(x):3d} Ø netto {x.mean() * 1e4:6.2f} bp t {tt:5.2f} | übrige Tage Ø {other.mean() * 1e4:5.2f} bp")
    for k, s in ev.items():
        y = ex[m & np.array([d in s for d in r.index])]
        print(f"      {k:4s}: {len(y):3d} Tage Ø {y.mean() * 1e4:6.2f} bp t {y.mean() / y.std() * np.sqrt(len(y)):5.2f}")
post = ex[(r.index >= date(2013, 1, 1)) & (r.index <= date(2025, 9, 19))]
strat = post.where(ann.reindex(post.index), 0.0)
_log_trial("announcement_days", "SPY", {}, CostModel(slippage_bps=1.0), 1.0, BacktestResult("ann", strat))
ok = res["2013..2025-09 (nach Veröff.)"][0] >= 2 and res["unberührt"][1] > 0
print("->", "BESTANDEN" if ok else "NICHT BESTANDEN")

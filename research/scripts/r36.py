"""Runde 36: Anomalien bei europäischen Aktien (research/PROTOCOL.md)."""
import json
from datetime import date
from pathlib import Path
import numpy as np, pandas as pd
from tradingbot.research import anomalies, swing, history
from tradingbot.research.__main__ import _log_trial
from tradingbot.research.engine import CostModel, BacktestResult
from tradingbot.research.metrics import compute_metrics

base = Path("data_cache/europe")
until = date(2025, 9, 20)
fx = {s: history.fetch_yahoo(f"{s}EUR=X", base=base, until=until)["close"] for s in ("GBP", "CHF", "SEK")}
cur = {".L": "GBP", ".SW": "CHF", ".ST": "SEK"}
px = {}
for p in sorted(base.glob("*_full.pkl")):
    s = p.stem[:-5]
    if s.endswith("=X") or s.startswith("^") or s == "EXSA.DE":
        continue
    px[s] = pd.read_pickle(p)["adjclose"]
close = pd.DataFrame(px).sort_index()
close = close[close.index <= date(2025, 9, 19)]
ret = close.pct_change(fill_method=None)
# Datenfehler-Regel
bad = ((ret.abs() > 0.5) & (ret.shift(-1) * np.sign(ret) < -0.5 * ret.abs() / (1 + ret)))
ret = ret.mask(bad | bad.shift(1, fill_value=False), 0.0)
for suf, c in cur.items():
    cols = [s for s in ret.columns if s.endswith(suf)]
    f = fx[c].reindex(ret.index).ffill().pct_change(fill_method=None).fillna(0.0)
    ret[cols] = (1 + ret[cols]).mul(1 + f, axis=0) - 1
ret = ret.where(close.notna())
hist = close.notna().cumsum()
univ = (hist >= 252) & close.notna()
lvl = (1 + ret.fillna(0)).cumprod().where(close.notna())
ew = ret.where(univ.shift(1, fill_value=False)).mean(axis=1).fillna(0.0)

scores = {
    "BK": (lvl.shift(21) / lvl.shift(252) - 1, True),
    "BL": (ret.rolling(252, min_periods=200).std(), False),
    "BM": (lvl / lvl.shift(21) - 1, False),
}
stamp = np.array([c.endswith(".L") for c in close.columns])
periods = {"Entdeckung": (date(2003, 1, 1), date(2013, 12, 31)), "Bestätigung": (date(2014, 1, 1), date(2025, 9, 19))}
table = {}
for fam, (score, highest) in scores.items():
    for n in (20, 40):
        w = anomalies.cross_section_weights(lvl, univ, score, n, highest)
        W = w.to_numpy()
        held = np.vstack([np.zeros(W.shape[1]), W[:-1]])
        gross = np.nansum(held * ret.fillna(0.0).to_numpy(), axis=1)
        dW = W - held
        cost = 0.001 * np.abs(dW).sum(axis=1) + 0.005 * np.clip(dW[:, stamp], 0, None).sum(axis=1)
        net = pd.Series(gross - np.concatenate([[0.0], cost[:-1]]), index=ret.index)
        label = f"{fam} n={n}"
        row = {}
        for name, (a, b) in periods.items():
            r = net[(net.index >= a) & (net.index <= b)]
            bb = ew.reindex(r.index)
            m, mb = compute_metrics(BacktestResult(label, r)), compute_metrics(BacktestResult("b", bb))
            al, t, beta = swing.alpha_vs_benchmark(r, bb)
            row[name] = t
            print(f"{label:8s} {name:11s} {m.cagr:7.1%} Sharpe {m.sharpe:5.2f} (EW {mb.cagr:6.1%}, {mb.sharpe:4.2f}) "
                  f"MaxDD {m.max_drawdown:6.1%} (EW {mb.max_drawdown:6.1%}) Alpha {al:6.1%} t {t:5.2f} beta {beta:4.2f} "
                  f"Universum {univ.reindex(r.index).sum(axis=1).mean():4.0f}")
            if name == "Entdeckung":
                _log_trial("europe_anomalies", "europe379", {"variant": label}, CostModel(slippage_bps=10.0), 1.0,
                           BacktestResult(label, r))
        table[label] = row
for fam in scores:
    ls = [k for k in table if k.startswith(fam)]
    best = max(ls, key=lambda k: table[k]["Entdeckung"])
    ok = table[best]["Entdeckung"] >= 2.39 and table[best]["Bestätigung"] >= 2
    print(f"Familie {fam}: {best} {table[best]} -> {'BESTANDEN' if ok else 'NICHT BESTANDEN'}")

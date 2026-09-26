import re
from datetime import date as _date
import numpy as np, pandas as pd
from tradingbot.research import anomalies, crypto, swing
from tradingbot.research.universe import UNIVERSE_DIR, load_daily_panel
from tradingbot.research.__main__ import _FUND_NAME, _log_trial, HOLDOUT_START
from tradingbot.research.engine import CostModel, BacktestResult
from tradingbot.research.metrics import compute_metrics

disc, conf = (_date(2016,1,1), _date(2020,12,31)), (_date(2021,1,1), _date(2025,9,19))
assets = pd.read_pickle(UNIVERSE_DIR / "assets.pkl")
funds = set(assets.loc[assets["name"].fillna("").str.contains(re.compile(_FUND_NAME, re.I)), "symbol"])
panel = load_daily_panel()
panel = panel[panel.index.get_level_values("date") < HOLDOUT_START]
bench = panel.xs("SPY", level="symbol")["close"].pct_change().dropna()
stocks = panel[~panel.index.get_level_values("symbol").isin(funds)]
_, closes, mask = swing.reversal_matrices(stocks, universe_size=1000)
m121 = closes.shift(21) / closes.shift(252) - 1
m61 = closes.shift(21) / closes.shift(126) - 1
m127 = closes.shift(147) / closes.shift(252) - 1
def top_decile(x):
    x = x.where(mask)
    return x.ge(x.quantile(0.9, axis=1), axis=0)
cons = mask & top_decile(m61) & top_decile(m127)
q80 = m121.where(mask).quantile(0.8, axis=1)
frog_u = mask & m121.ge(q80, axis=0)
dr = closes.pct_change()
pos = (dr > 0).astype(float).where(dr.notna()).shift(21).rolling(231, min_periods=200).mean()
neg = (dr < 0).astype(float).where(dr.notna()).shift(21).rolling(231, min_periods=200).mean()
ID = np.sign(m121) * (neg - pos)

def weights_upto(universe, score, n, highest):
    # wie cross_section_weights, aber bei < n Kandidaten alle mit 1/n
    is_end = anomalies._month_ends(closes.index)
    S, U, avail = score.to_numpy(float), universe.to_numpy(bool), closes.notna().to_numpy()
    W = np.zeros(closes.shape); cur = np.zeros(closes.shape[1])
    for t in range(len(closes.index)):
        if is_end[t]:
            s = np.where(U[t] & np.isfinite(S[t]), S[t], np.nan)
            valid = np.flatnonzero(~np.isnan(s)); cur = np.zeros(closes.shape[1])
            order = valid[np.argsort(s[valid])]
            pick = order[-n:] if highest else order[:n]
            if len(pick): cur[pick] = 1.0 / n
        W[t] = np.where(avail[t], cur, 0.0)
    return pd.DataFrame(W, index=closes.index, columns=closes.columns)

variants = {}
for n in (20, 100):
    variants[f"BA konsistent n={n}"] = weights_upto(cons, m121, n, True)
    variants[f"BB Frog n={n}"] = weights_upto(frog_u, ID, n, False)
def sl(x, p): return x[(x.index >= p[0]) & (x.index <= p[1])]
table = {}
for label, w in variants.items():
    res = crypto.run_weights(w, closes, 0.0010, "mom").daily_returns
    row = {}
    for name, p in (("Entdeckung", disc), ("Bestätigung", conf)):
        r, b = sl(res, p), sl(bench, p)
        m = compute_metrics(BacktestResult(label, r))
        al, t, beta = swing.alpha_vs_benchmark(r, b)
        row[name] = t
        print(f"{label:20s} {name:11s} {m.cagr:7.1%} Sharpe {m.sharpe:5.2f} MaxDD {m.max_drawdown:6.1%} Alpha {al:6.1%} t {t:5.2f} beta {beta:4.2f} investiert {sl(w.sum(axis=1),p).mean():.0%}")
        if name == "Entdeckung":
            _log_trial("momentum_variants", "top1000", {"variant": label}, CostModel(slippage_bps=10.0), 1.0, BacktestResult(label, r))
    table[label] = row
for fam in ("BA", "BB"):
    ls = [k for k in table if k.startswith(fam)]
    best = max(ls, key=lambda k: table[k]["Entdeckung"])
    ok = table[best]["Entdeckung"] >= 2.24 and table[best]["Bestätigung"] >= 2
    print(f"Familie {fam}: {best} {table[best]} -> {'BESTANDEN' if ok else 'NICHT BESTANDEN'}")

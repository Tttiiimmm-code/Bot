"""Runde 35: Dividenden-Effekte (research/PROTOCOL.md)."""
import re
from datetime import date as _date
import numpy as np, pandas as pd
from tradingbot.research import crypto, swing
from tradingbot.research.universe import UNIVERSE_DIR, load_daily_panel
from tradingbot.research.__main__ import _FUND_NAME, _log_trial, HOLDOUT_START
from tradingbot.research.engine import CostModel, BacktestResult
from tradingbot.research.metrics import compute_metrics

disc, conf = (_date(2016, 1, 1), _date(2020, 12, 31)), (_date(2021, 1, 1), _date(2025, 9, 19))
assets = pd.read_pickle(UNIVERSE_DIR / "assets.pkl")
funds = set(assets.loc[assets["name"].fillna("").str.contains(re.compile(_FUND_NAME, re.I)), "symbol"])
panel = load_daily_panel()
panel = panel[panel.index.get_level_values("date") < HOLDOUT_START]
allclose = panel["close"].unstack("symbol")
stocks = panel[~panel.index.get_level_values("symbol").isin(funds)]
_, closes, mask = swing.reversal_matrices(stocks, universe_size=1000)
idx = closes.index

div = pd.read_pickle("data_cache/dividends.pkl")
div = div[~div["special"].astype(bool)].copy()
div["ex_date"] = pd.to_datetime(div["ex_date"]).dt.date
spl = pd.read_pickle("data_cache/splits.pkl")
spl["ex_date"] = pd.to_datetime(spl["ex_date"]).dt.date
spl["ratio"] = spl["new_rate"].astype(float) / spl["old_rate"].astype(float)
factor = []
by_sym = {s: g for s, g in spl.groupby("symbol")}
for sym, ex in zip(div["symbol"], div["ex_date"]):
    g = by_sym.get(sym)
    factor.append(float(g.loc[g["ex_date"] > ex, "ratio"].prod()) if g is not None else 1.0)
div["adj"] = div["rate"].astype(float) / np.array(factor)
div = div.drop_duplicates(["symbol", "ex_date"])


def dividend_matrix(cols):
    d = div[div["symbol"].isin(cols)]
    m = d.pivot_table(index="ex_date", columns="symbol", values="adj", aggfunc="sum")
    return m.reindex(index=idx, columns=cols).fillna(0.0)


def tr_close(px):
    d = dividend_matrix(px.columns)
    r = ((px + d) / px.shift(1) - 1).fillna(0.0)
    return (1 + r).cumprod().where(px.notna())


spy_px = allclose["SPY"].reindex(idx)
spy_tr = tr_close(spy_px.to_frame("SPY"))["SPY"]
closes_tr = tr_close(closes)
ym = pd.Series([(d.year, d.month) for d in idx], index=idx)
div_months = div.assign(ym=[(d.year, d.month) for d in div["ex_date"]]).groupby("symbol")["ym"].apply(set)


def shift_month(y, m, k):
    t = y * 12 + (m - 1) - k
    return t // 12, t % 12 + 1


def sl(x, p):
    return x[(x.index >= p[0]) & (x.index <= p[1])]


variants = {}
for lag, name in ((3, "BI m-3"), (12, "BI m-12")):
    W = np.zeros(closes.shape)
    cols = list(closes.columns)
    M = mask.to_numpy()
    month_end = (ym != ym.shift(-1)).to_numpy()
    cur = np.zeros(len(cols))
    for t in range(len(idx)):
        if month_end[t]:
            y, m = ym.iloc[t]
            ny, nm = shift_month(y, m, -1)
            target = shift_month(ny, nm, lag)
            pick = [j for j, c in enumerate(cols) if M[t, j] and target in div_months.get(c, ())]
            cur = np.zeros(len(cols))
            if pick:
                cur[pick] = 1.0 / len(pick)
        W[t] = cur
    variants[name] = (pd.DataFrame(W, index=idx, columns=cols), closes_tr, spy_tr.pct_change())

for K in (5, 10):
    W = pd.DataFrame(0.0, index=idx, columns=closes.columns)
    n_ev = 0
    for sym, g in div[div["symbol"].isin(closes.columns)].groupby("symbol"):
        ex = sorted(g["ex_date"])
        for i in range(3, len(ex)):
            gaps = [(ex[j] - ex[j - 1]).days for j in range(i - 2, i + 1)]
            if not all(80 <= x <= 100 for x in gaps):
                continue
            pred = ex[i] + pd.Timedelta(days=int(np.median(gaps)))
            nxt = ex[i + 1] if i + 1 < len(ex) else pred
            stop = min(pred, nxt)
            p_pred = idx.searchsorted(pred)
            p_exit = idx.searchsorted(stop) - 1
            p_in = p_pred - K
            if p_in <= 0 or p_exit <= p_in or p_exit >= len(idx):
                continue
            if not mask[sym].iloc[p_in]:
                continue
            W.iloc[p_in:p_exit, W.columns.get_loc(sym)] = 1.0
            n_ev += 1
    W = W.div(W.sum(axis=1).replace(0, np.nan), axis=0).fillna(0.0)
    print(f"BJ K={K}: {n_ev} Ereignisse")
    variants[f"BJ K={K}"] = (W, closes, spy_px.pct_change())

table = {}
for label, (w, px, bench) in variants.items():
    res = crypto.run_weights(w, px, 0.0010, label).daily_returns
    row = {}
    for name, p in (("Entdeckung", disc), ("Bestätigung", conf)):
        r = sl(res, p)
        b = bench.reindex(r.index).fillna(0.0)
        m, mb = compute_metrics(BacktestResult(label, r)), compute_metrics(BacktestResult("b", b))
        al, t, beta = swing.alpha_vs_benchmark(r, b)
        row[name] = t
        print(f"{label:9s} {name:11s} {m.cagr:7.1%} Sharpe {m.sharpe:5.2f} (SPY {mb.cagr:6.1%}) MaxDD {m.max_drawdown:6.1%} "
              f"Alpha {al:6.1%} t {t:5.2f} beta {beta:4.2f} Ø Titel {sl((w > 0).sum(axis=1), p).mean():5.0f}")
        if name == "Entdeckung":
            _log_trial("dividends", "top1000", {"variant": label}, CostModel(slippage_bps=10.0), 1.0, BacktestResult(label, r))
    table[label] = row
for fam in ("BI", "BJ"):
    ls = [k for k in table if k.startswith(fam)]
    best = max(ls, key=lambda k: table[k]["Entdeckung"])
    ok = table[best]["Entdeckung"] >= 2.24 and table[best]["Bestätigung"] >= 2
    print(f"Familie {fam}: {best} {table[best]} -> {'BESTANDEN' if ok else 'NICHT BESTANDEN'}")

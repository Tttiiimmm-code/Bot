"""Gemeinsame Bausteine für Europa-Momentum (Runden 36/37)."""
from datetime import date
from pathlib import Path
import numpy as np, pandas as pd
from tradingbot.research import anomalies, history

CUR = {".L": "GBP", ".SW": "CHF", ".ST": "SEK"}


def load_returns(base: Path, until: date, last: date):
    fx = {s: history.fetch_yahoo(f"{s}EUR=X", base=base, until=until)["close"] for s in ("GBP", "CHF", "SEK")}
    px = {}
    for p in sorted(base.glob("*_full.pkl")):
        s = p.stem[:-5]
        if s.endswith("=X") or s.startswith("^") or s == "EXSA.DE":
            continue
        px[s] = pd.read_pickle(p)["adjclose"]
    close = pd.DataFrame(px).sort_index()
    close = close[close.index <= last]
    ret = close.pct_change(fill_method=None)
    bad = ((ret.abs() > 0.5) & (ret.shift(-1) * np.sign(ret) < -0.5 * ret.abs() / (1 + ret)))
    ret = ret.mask(bad | bad.shift(1, fill_value=False), 0.0)
    for suf, c in CUR.items():
        cols = [s for s in ret.columns if s.endswith(suf)]
        f = fx[c].reindex(ret.index).ffill().pct_change(fill_method=None).fillna(0.0)
        ret[cols] = (1 + ret[cols]).mul(1 + f, axis=0) - 1
    ret = ret.where(close.notna())
    return close, ret


def momentum_run(close, ret, univ, n=20, cost=0.001, stamp_duty=0.005):
    lvl = (1 + ret.fillna(0)).cumprod().where(close.notna())
    score = lvl.shift(21) / lvl.shift(252) - 1
    w = anomalies.cross_section_weights(lvl, univ, score, n, True)
    W = w.to_numpy()
    held = np.vstack([np.zeros(W.shape[1]), W[:-1]])
    gross = np.nansum(held * ret.fillna(0.0).to_numpy(), axis=1)
    dW = W - held
    stamp = np.array([c.endswith(".L") for c in close.columns])
    c = cost * np.abs(dW).sum(axis=1) + stamp_duty * np.clip(dW[:, stamp], 0, None).sum(axis=1)
    net = pd.Series(gross - np.concatenate([[0.0], c[:-1]]), index=ret.index)
    ew = ret.where(univ.shift(1, fill_value=False)).mean(axis=1).fillna(0.0)
    turnover = pd.Series(np.abs(dW).sum(axis=1), index=ret.index)
    return net, ew, w, turnover

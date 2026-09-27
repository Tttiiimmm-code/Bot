"""Runde 84: Ridge-Filter für den Nikkei-Nachteffekt, streng walk-forward."""
import importlib.util
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from tradingbot.research import gold
from tradingbot.research.history import fetch_yahoo

spec = importlib.util.spec_from_file_location("ft", sys.argv[1])
ft = importlib.util.module_from_spec(spec); sys.modules["ft"] = ft; spec.loader.exec_module(ft)
nk = pd.concat([gold.load_minutes(Path("data_cache/dukascopy/idx"), "jpnidxjpy_*.csv"),
                gold.load_minutes(Path("data_cache/dukascopy/unseen"), "jpnidxjpy_*.csv")])["open"]
nk = nk[~nk.index.duplicated()].sort_index()
fx = pd.concat([gold.load_fx("usdjpy"), gold.load_fx("usdjpy", Path("data_cache/dukascopy/unseen_fx"))])
fx = fx[~fx.index.duplicated()].sort_index()
n = pd.DataFrame(ft.nikkei_trades(nk, date(2013, 10, 1), date(2026, 9, 25), 0.5e-4, 0.0075, pd.Timestamp("2026-09-26", tz="UTC")))
n["entry"] = pd.to_datetime(n["entry_time"], utc=True)
n["exit_day"] = pd.to_datetime(n["date"])
n["ret"] = n["net_bp"] / 1e4
spy = pd.read_pickle("data_cache/yahoo_unseen/SPY_full.pkl")["adjclose"].astype(float); spy.index = pd.to_datetime(spy.index)
spr = spy.pct_change()
vix = fetch_yahoo("^VIX", Path("data_cache/yahoo_unseen"), until=date(2026, 9, 26))["close"].astype(float); vix.index = pd.to_datetime(vix.index)
vz = (vix - vix.rolling(250).mean()) / vix.rolling(250).std()
gdays = ft.gotobi_days(2013, 2026)
rows = []
prev_night = np.nan
for _, t in n.iterrows():
    e = t["entry"].tz_convert("Asia/Tokyo")
    d = e.normalize().tz_localize(None)
    op = gold.price_at(nk, pd.Timestamp(e.date()).tz_localize("Asia/Tokyo").replace(hour=8, minute=45).tz_convert("UTC"))
    day_ret = t["entry_price"] / op - 1 if op else np.nan
    us = spr[spr.index < d].iloc[-1] if (spr.index < d).any() else np.nan
    f0 = gold.price_at(fx, pd.Timestamp(e.date()).tz_localize("Asia/Tokyo").replace(hour=5).tz_convert("UTC"))
    f1 = gold.price_at(fx, t["entry"])
    fxr = f1 / f0 - 1 if f0 and f1 else np.nan
    v = vz[vz.index < d].iloc[-1] if (vz.index < d).any() else np.nan
    rows.append(dict(exit_day=t["exit_day"], ret=t["ret"], day=day_ret, prev=prev_night, us=us, fx=fxr, vix=v,
                     fri=float(d.weekday() == 4), gotobi=float(t["exit_day"].date() in gdays)))
    prev_night = t["ret"]
X = pd.DataFrame(rows).set_index("exit_day")
X["vol20"] = X["ret"].rolling(20).std().shift(1)
X["month_end"] = X.index.to_series().groupby(X.index.to_period("M")).transform(lambda s: s.rank(ascending=False) <= 2).astype(float)
feats = ["day", "prev", "us", "fx", "vix", "fri", "gotobi", "vol20", "month_end"]
X = X.dropna()
pred = pd.Series(np.nan, index=X.index)
for yr in range(2017, 2027):
    tr, te = X[X.index.year < yr], X[X.index.year == yr]
    if te.empty:
        continue
    mu, sd = tr[feats].mean(), tr[feats].std().replace(0, 1)
    A = ((tr[feats] - mu) / sd).to_numpy(); y = tr["ret"].to_numpy()
    w = np.linalg.solve(A.T @ A + 10 * np.eye(len(feats)), A.T @ (y - y.mean()))
    pred[te.index] = y.mean() + ((te[feats] - mu) / sd).to_numpy() @ w
    if yr in (2017, 2025):
        print(yr, "Gewichte:", dict(zip(feats, np.round(w * 1e4, 2))))
X["pred"] = pred
X = X.dropna(subset=["pred"])
X["ml"] = np.where(X["pred"] > 0, X["ret"], 0.0)
X["diff"] = X["ml"] - X["ret"]
for p, a, b, th in [("Walk-forward 2017-2025-09", "2017", "2025-09-19", 2.0), ("unberührt", "2025-09-22", "2026-09-25", None)]:
    x = X[a:b]
    t = x["diff"].mean() / x["diff"].std() * np.sqrt(len(x))
    sh = lambda s: s.mean() / s.std() * np.sqrt(245)
    print(f"{p:26s} Nächte {len(x):4d} gehandelt {(x['pred']>0).mean()*100:3.0f} % | immer Ø {x['ret'].mean()*1e4:5.2f} bp "
          f"(Sharpe {sh(x['ret']):4.2f}) | ML Ø {x['ml'].mean()*1e4:5.2f} bp (Sharpe {sh(x['ml']):4.2f}) | Differenz t {t:5.2f}")

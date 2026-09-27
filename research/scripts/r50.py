"""Runde 50: Querschnitts-Funding-Carry."""
import json
from datetime import date
import numpy as np, pandas as pd
from tradingbot.research import anomalies, crypto
from tradingbot.research.__main__ import _log_trial
from tradingbot.research.engine import CostModel, BacktestResult

close, vol = crypto.load_panel(allow_holdout=True)
close.index = pd.to_datetime(close.index); vol.index = close.index
U = crypto.universe_mask(close, vol, 30)
cmap = json.load(open("data_cache/crypto_hourly/carry_map.json"))
P, F = {}, {}
for spot, perp in cmap.items():
    try:
        df = crypto.fetch_perp(perp)
    except Exception:
        continue
    df.index = pd.to_datetime(df.index)
    P[spot], F[spot] = df["perp_close"], df["funding"]
cols = [c for c in close.columns if c in P]
S = close[cols]
P = pd.DataFrame(P).reindex(index=S.index, columns=cols)
F = pd.DataFrame(F).reindex(index=S.index, columns=cols)
U = U[cols] & P.notna() & S.notna()
coin_r = 0.5 * (S.pct_change(fill_method=None) - P.pct_change(fill_method=None) + F.fillna(0.0))
coin_r = coin_r.fillna(0.0)
score = F.rolling(7, min_periods=7).mean()
tb = anomalies.fetch_fred("TB3MS") / 100
ym = pd.PeriodIndex(S.index, freq="M").to_timestamp()
rf = pd.Series(tb.reindex(ym, method="ffill").to_numpy(), index=S.index).ffill() / 365
sunday = S.index.weekday == 6
periods = {"Entdeckung": ("2020-01-01", "2022-12-31"), "Bestätigung": ("2023-01-01", "2025-09-21"), "unberührt": ("2025-09-22", "2026-09-25")}
table = {}
for k in (5, 10):
    W = np.zeros(S.shape); cur = np.zeros(S.shape[1])
    sc, uu = score.to_numpy(), U.to_numpy()
    for t in range(len(S)):
        if sunday[t]:
            s = np.where(uu[t] & (sc[t] > 0), sc[t], np.nan)
            v = np.flatnonzero(~np.isnan(s))
            cur = np.zeros(S.shape[1])
            if len(v):
                pick = v[np.argsort(s[v])][-k:]
                cur[pick] = 1.0 / k
        W[t] = cur
    W = pd.DataFrame(W, index=S.index, columns=cols)
    held = W.shift(1).fillna(0.0)
    gross = (held * coin_r).sum(axis=1)
    turnover = (W - held).abs().sum(axis=1)
    net = gross - (turnover * 0.5 * (0.001 + 0.0005)).shift(1).fillna(0.0)
    ex = net - rf
    row = {}
    for name, (a, b) in periods.items():
        x, e = net[a:b], ex[a:b]
        h = held[a:b]
        maxperp = (P.pct_change(fill_method=None)[a:b].where(h > 0)).max().max()
        eq = (1 + x).cumprod()
        t = e.mean() / e.std() * np.sqrt(len(e))
        row[name] = (t, e.mean())
        print(f"k={k:2d} {name:11s} {(1 + x).prod() ** (365 / len(x)) - 1:6.1%} p.a. (über T-Bill {e.mean() * 365:6.1%}) "
              f"Sharpe {x.mean() / x.std() * np.sqrt(365):5.2f} MaxDD {(eq / eq.cummax() - 1).min():6.1%} "
              f"schlechtester Tag {x.min():6.2%} größte Perp-Tagesrendite gehalten {maxperp:6.1%} Ø Coins {(h > 0).sum(axis=1).mean():4.1f} t {t:5.2f}")
        if name == "Entdeckung":
            _log_trial("funding_carry_xs", "top30", {"k": k}, CostModel(slippage_bps=10.0), 1.0, BacktestResult(f"carry k={k}", x), 365)
    table[k] = row
best = max(table, key=lambda k: table[k]["Entdeckung"][0])
r = table[best]
ok = r["Entdeckung"][0] >= 2.24 and r["Bestätigung"][0] >= 2 and r["unberührt"][1] > 0
print(f"gewählt k={best}: {r} -> {'BESTANDEN' if ok else 'NICHT BESTANDEN'}")

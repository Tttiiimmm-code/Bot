"""Runde 48: Monatsend-Rebalancing (Aktien-Anleihen-Spread)."""
from datetime import date
from pathlib import Path
import numpy as np, pandas as pd
from tradingbot.research import history
from tradingbot.research.__main__ import _log_trial
from tradingbot.research.engine import CostModel, BacktestResult

base = Path("data_cache/yahoo_unseen")
px = pd.DataFrame({s: history.fetch_yahoo(s, base=base, until=date(2026, 9, 26))["adjclose"] for s in ("SPY", "TLT")}).dropna()
r = px.pct_change().dropna()
spread = r["SPY"] - r["TLT"]
idx = px.index
ym = pd.Series([(d.year, d.month) for d in idx], index=idx)
pos_from_end = ym.groupby(ym).cumcount(ascending=False)  # 0 = letzter Handelstag
# Monatsrendite bis Schluss t (ab letztem Vormonatsschluss)
month_start_px = px.groupby(ym.values).transform(lambda x: x.iloc[0])
prev_close = px.shift(1)
first_of_month = ym != ym.shift(1)
anchor = prev_close.where(first_of_month).ffill()
mtd = px / anchor - 1
s = np.sign(mtd["SPY"] - mtd["TLT"])
w = pd.Series(0.0, index=idx)
nxt = pos_from_end.shift(-1)  # Position für Tag t+1, bestimmt am Schluss t
same_month = ym.shift(-1) == ym
w_next = np.where(nxt.isna(), 0.0,
         np.where(nxt == 0, np.where(same_month, s, 0.0), np.where(nxt <= 4, -s, 0.0)))
# Signal für den letzten Tag nur, wenn t im selben Monat liegt (sonst ist t+1 ein neuer Monat)
w = pd.Series(w_next, index=idx).shift(1).fillna(0.0)
costs = w.diff().abs().fillna(0.0) * 2 * 0.0002
pnl = (w * spread.reindex(idx).fillna(0.0) - costs).iloc[1:]
for name, (a, b) in (("Entdeckung", (date(2003, 1, 1), date(2014, 12, 31))), ("Bestätigung", (date(2015, 1, 1), date(2025, 9, 19))),
                     ("nach Veröff.", (date(2025, 2, 1), date(2026, 9, 25)))):
    x = pnl[(pnl.index >= a) & (pnl.index <= b)]
    act = x[w.reindex(x.index) != 0]
    t = x.mean() / x.std() * np.sqrt(len(x))
    print(f"{name:12s} aktive Tage {len(act):4d} Ø {act.mean() * 1e4:6.2f} bp/aktivem Tag Treffer {(act > 0).mean():.0%} "
          f"Summe/Jahr {x.sum() / ((b - a).days / 365.25):6.1%} Sharpe {x.mean() / x.std() * np.sqrt(252):5.2f} t {t:5.2f}")
    if name == "Entdeckung":
        _log_trial("rebalancing", "SPY-TLT", {}, CostModel(slippage_bps=2.0), 1.0, BacktestResult("rebal", x))

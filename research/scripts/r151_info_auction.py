"""Runde 151, NACHTRÄGLICH (nur Info, kein Ergebnis): Kosten wie Auktions-Orders (nur SEC-Gebühr 0,28 bp auf Verkäufe).
Bestehenskriterium der Runde (5 bp je Seite) bleibt maßgeblich."""
import itertools, sys
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).parent))
import r151 as R

dates, cols, w, x935 = R.panel()
O, H, L, C, V = w["open"], w["high"], w["low"], w["close"], w["volume"]
rng = H - L
with np.errstate(invalid="ignore", divide="ignore"):
    ibs = np.where(rng > 0, (C - L) / rng, np.nan)
    r = np.clip(np.vstack([O[1:], np.full((1, C.shape[1]), np.nan)]) / C - 1, -0.9, 5)
dv = pd.DataFrame(C * V).rolling(20, min_periods=15).mean().to_numpy()
rank = pd.DataFrame(np.where((C > 5) & np.isfinite(dv), dv, np.nan)).rank(axis=1, ascending=False).to_numpy()
per = (dates >= R.START) & (dates <= R.END)
spy = pd.read_pickle(R.SPY); spy.index = pd.DatetimeIndex([pd.Timestamp(d) for d in spy.index])
spy_d = spy["adjclose"].pct_change().reindex(dates[per]).fillna(0)
pa = lambda x: float((1 + x).prod() ** (252 / len(x)) - 1)
mo = lambda x: (1 + x).groupby(x.index.to_period("M")).prod() - 1
dd = lambda x: float(((1 + x).cumprod() / (1 + x).cumprod().cummax() - 1).min())
print(f"NACHTRÄGLICH, nur Info -- Kosten nur SEC 0,28 bp je Nacht (Auktions-Orders); SPY {pa(spy_d):+.1%} p.a., "
      f"größter Verlust {dd(spy_d):.0%}")
for th, n in itertools.product((0.05, 0.10, 0.20), (500, 1500)):
    sig = (rank <= n) & (ibs <= th) & np.isfinite(r)
    k = sig.sum(1)
    g = np.where(sig, r, 0).sum(1) / np.maximum(k, 1)
    s = pd.Series(np.where(k >= 5, g - 0.28e-4, 0.0), index=dates)[per]
    t = R.tstat(mo(s) - mo(spy_d))
    yrs = {y: pa(s[s.index.year == y]) - pa(spy_d[spy_d.index.year == y]) for y in range(2016, 2027)}
    neg = [y for y, v in yrs.items() if v < 0]
    print(f"  IBS <= {th:.2f} Top {n:4d}: {pa(s):+7.1%} p.a., t ggü. SPY {t:+5.2f}, größter Verlust {dd(s):.0%}, "
          f"Jahre unter SPY: {neg}")

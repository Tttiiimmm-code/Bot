"""Hebel- und Positionsgrößen-Analyse für Gotobi + Nikkei-Nacht (Backtest 2017-2026, echte Kosten)."""
import importlib.util
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from tradingbot.research import gold

spec = importlib.util.spec_from_file_location("ft", sys.argv[1])
ft = importlib.util.module_from_spec(spec); sys.modules["ft"] = ft; spec.loader.exec_module(ft)
NOW = pd.Timestamp("2026-09-26", tz="UTC")
S, E = date(2017, 1, 1), date(2026, 9, 25)

nk = pd.concat([gold.load_minutes(Path("data_cache/dukascopy/idx"), "jpnidxjpy_*.csv"),
                gold.load_minutes(Path("data_cache/dukascopy/unseen"), "jpnidxjpy_*.csv")])["open"]
nk = nk[~nk.index.duplicated()].sort_index()
bid = pd.concat([gold.load_fx("usdjpy"), gold.load_fx("usdjpy", Path("data_cache/dukascopy/unseen_fx"))])
bid = bid[~bid.index.duplicated()].sort_index()
ask = gold.load_fx("usdjpy", Path("data_cache/dukascopy/fx_ask"))

n = pd.DataFrame(ft.nikkei_trades(nk, S, E, 0.5e-4, 0.0075, NOW))
g = pd.DataFrame(ft.gotobi_trades(bid, ask, S, E, 0.35e-4, NOW))
rn = n.groupby(pd.to_datetime(n["date"]))["net_bp"].sum() / 1e4
rg = g.groupby(pd.to_datetime(g["date"]))["net_bp"].sum() / 1e4
print(f"Nikkei-Nacht: {len(rn)} Trades Ø {rn.mean()*1e4:.2f} bp, Std {rn.std()*1e4:.1f} bp, schlechtester {rn.min()*100:.2f} %")
print(f"Gotobi:       {len(rg)} Trades Ø {rg.mean()*1e4:.2f} bp, Std {rg.std()*1e4:.1f} bp, schlechtester {rg.min()*100:.2f} %")
for name, r in (("Nikkei", rn), ("Gotobi", rg)):
    print(f"  Kelly-Hebel {name}: {r.mean()/r.var():.1f}x (halbes Kelly {r.mean()/r.var()/2:.1f}x)")
    print(f"  je Jahr Ø bp: {(r.groupby(r.index.year).mean()*1e4).round(1).to_dict()}")
days = pd.date_range("2017-01-01", "2026-09-25", freq="D")
df = pd.DataFrame({"n": rn.reindex(days).fillna(0), "g": rg.reindex(days).fillna(0)})
print("Korrelation an gemeinsamen Tagen:", round(df[(df.n != 0) & (df.g != 0)].corr().iloc[0, 1], 3))


def stats(Ln, Lg, cost_mult=1.0, frame=df):
    extra_n = (frame.n != 0) * 2 * 0.5e-4 * (cost_mult - 1)
    extra_g = (frame.g != 0) * 2 * 0.35e-4 * (cost_mult - 1)
    r = Ln * (frame.n - extra_n) + Lg * (frame.g - extra_g)
    eq = (1 + r).cumprod()
    yrs = len(frame) / 365.25
    dd = (eq / eq.cummax() - 1).min()
    return eq.iloc[-1] ** (1 / yrs) - 1, dd, r.min(), (eq.resample("YE").last().pct_change().fillna(eq.resample("YE").last().iloc[0] - 1) < 0).sum()


print("\nHebel Nikkei / Gotobi -> CAGR, MaxDD, schlechtester Tag, Verlustjahre (von 10) | mit doppelten Kosten: CAGR, MaxDD")
for Ln, Lg in [(1, 1), (2, 3), (3, 5), (4, 5), (5, 8), (6, 10), (8, 12)]:
    c, d, w, ly = stats(Ln, Lg)
    c2, d2, _, _ = stats(Ln, Lg, 2.0)
    print(f"  {Ln:2d}x / {Lg:2d}x: {c*100:6.1f} % p.a., MaxDD {d*100:6.1f} %, schlechtester Tag {w*100:6.2f} %, "
          f"Verlustjahre {ly} | doppelte Kosten {c2*100:6.1f} %, MaxDD {d2*100:6.1f} %")

rng = np.random.default_rng(0)
print("\nBootstrap (1 Jahr, 10.000 Pfade, Blöcke à 20 Tage): P(Verlust), P(DD < -30 %), Median-Rendite")
arr = df.to_numpy()
for Ln, Lg in [(2, 3), (3, 5), (5, 8)]:
    res = []
    for _ in range(10000):
        idx = np.concatenate([np.arange(s, s + 20) for s in rng.integers(0, len(arr) - 20, 19)])[:365]
        r = Ln * arr[idx, 0] + Lg * arr[idx, 1]
        eq = np.cumprod(1 + r)
        res.append((eq[-1] - 1, (eq / np.maximum.accumulate(eq) - 1).min()))
    res = np.array(res)
    print(f"  {Ln}x/{Lg}x: P(Verlust) {(res[:,0] < 0).mean():.2f}, P(DD<-30 %) {(res[:,1] < -0.3).mean():.3f}, "
          f"Median {np.median(res[:,0])*100:5.1f} %, 5-%-Quantil {np.quantile(res[:,0], 0.05)*100:6.1f} %")

print("\nGetrennte Hebel (Nikkei klein, Gotobi groß):")
for Ln, Lg in [(0, 5), (0, 10), (1, 5), (1, 10), (1.5, 8), (1.5, 10), (2, 10)]:
    c, d, w, ly = stats(Ln, Lg)
    c2, d2, _, _ = stats(Ln, Lg, 2.0)
    print(f"  {Ln:3.1f}x / {Lg:2d}x: {c*100:6.1f} % p.a., MaxDD {d*100:6.1f} %, schlechtester Tag {w*100:6.2f} %, "
          f"Verlustjahre {ly} | doppelte Kosten {c2*100:6.1f} %, MaxDD {d2*100:6.1f} %")

# Stopp in der Nachtsitzung: Nacht wird bei -3 % (vom Einstieg, Minuten-Tiefs des CFD) glattgestellt
lo = pd.concat([gold.load_minutes(Path("data_cache/dukascopy/idx"), "jpnidxjpy_*.csv"),
                gold.load_minutes(Path("data_cache/dukascopy/unseen"), "jpnidxjpy_*.csv")])["low"]
lo = lo[~lo.index.duplicated()].sort_index()
stopped = []
for _, t in n.iterrows():
    seg = lo[pd.Timestamp(t["entry_time"]).tz_convert("UTC"):pd.Timestamp(t["exit_time"]).tz_convert("UTC")]
    r = t["net_bp"] / 1e4
    if len(seg) and seg.min() / t["entry_price"] - 1 <= -0.03:
        r = -0.03 - 2 * 0.5e-4 - 0.0005  # Stopp inkl. 5 bp Schlupf
    stopped.append((pd.Timestamp(t["date"]), r))
rs = pd.Series(dict(stopped)).groupby(level=0).sum()
print(f"\nNikkei mit -3-%-Stopp: Ø {rs.mean()*1e4:.2f} bp (ohne {rn.mean()*1e4:.2f}), schlechtester {rs.min()*100:.2f} %, "
      f"Stopps {int((rs < -0.029).sum())}")
df_s = pd.DataFrame({"n": rs.reindex(days).fillna(0), "g": rg.reindex(days).fillna(0)})
for Ln, Lg in [(1, 10), (1.5, 10), (2, 10), (3, 10)]:
    c, d, w, ly = stats(Ln, Lg, frame=df_s)
    print(f"  mit Stopp {Ln:3.1f}x / {Lg:2d}x: {c*100:6.1f} % p.a., MaxDD {d*100:6.1f} %, schlechtester Tag {w*100:6.2f} %, Verlustjahre {ly}")

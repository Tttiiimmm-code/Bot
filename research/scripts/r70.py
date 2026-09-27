"""Runde 70: Halten Hyperliquid-Top-Verdiener ihren Vorsprung? (28-Tage-Fenster)."""
import json
from pathlib import Path

import numpy as np
import pandas as pd

D = Path("data_cache/hyperliquid")
rows = json.load(open(D / "leaderboard_2026-09-27.json", encoding="utf-8"))["leaderboardRows"]
vol = {r["ethAddress"]: float(dict(r["windowPerformances"])["allTime"]["vlm"]) for r in rows}

T = pd.date_range("2025-01-01", "2026-08-30", freq="28D")
W = pd.Timedelta(days=28)
pnl, av = {}, {}
for p in (D / "portfolio").glob("*.json"):
    try:
        d = dict(json.loads(p.read_text()))["perpAllTime"]
    except Exception:
        continue
    h, v = d["pnlHistory"], d["accountValueHistory"]
    if len(h) < 3:
        continue
    ts = np.array([x[0] for x in h], dtype=float)
    need = np.unique([(t - W).value / 1e6 for t in T] + [t.value / 1e6 for t in T] + [(t + W).value / 1e6 for t in T])
    grid = pd.Series(np.interp(need, ts, [float(x[1]) for x in h]), index=need)
    grid[(need < ts[0]) | (need > ts[-1])] = np.nan
    tv = np.array([x[0] for x in v], dtype=float)
    ag = pd.Series(np.interp(need, tv, [float(x[1]) for x in v]), index=need)
    ag[(need < tv[0]) | (need > tv[-1])] = np.nan
    pnl[p.stem], av[p.stem] = grid, ag
print("Konten mit Historie:", len(pnl))

res = []
for t in T:
    a, b, c = (t - W).value / 1e6, t.value / 1e6, (t + W).value / 1e6
    recs = []
    for k in pnl:
        P, A = pnl[k], av[k]
        if np.isnan([P[a], P[b], P[c], A[a], A[b]]).any() or A[a] < 1e5 or A[b] < 1e5:
            continue
        recs.append((k, P[b] - P[a], (P[b] - P[a]) / A[a], (P[c] - P[b]) / A[b], vol[k] / max(A[a], 1)))
    if len(recs) < 100:
        continue
    df = pd.DataFrame(recs, columns=["addr", "pnl_f", "ret_f", "ret_n", "turn"])
    med = df["ret_n"].median()
    for g, col in (("G1 Top20 PnL", "pnl_f"), ("G2 Top20 Rendite", "ret_f")):
        top = df.nlargest(20, col)
        res.append((t, g, len(df), top["ret_n"].mean(), top["ret_n"].mean() - med, med, (top["turn"] > 1000).mean(),
                    top["ret_f"].mean()))
r = pd.DataFrame(res, columns=["T", "gruppe", "n", "folge", "ueber", "median", "mm_anteil", "formation"])
print(r.groupby("gruppe")[["n", "formation", "folge", "median", "mm_anteil"]].mean().round(4))
for g in r["gruppe"].unique():
    ok_g = True
    for name, yr, th in (("2025", 2025, 2.24), ("2026", 2026, 2.0)):
        x = r[(r["gruppe"] == g) & (r["T"].dt.year == yr)]
        t = x["ueber"].mean() / x["ueber"].std() * np.sqrt(len(x))
        print(f"{g:18s} {name}: Stichtage {len(x):2d} Ø Folgerendite {x['folge'].mean()*100:6.2f} % "
              f"Überschuss {x['ueber'].mean()*100:6.2f} % t {t:5.2f} | Formation Ø {x['formation'].mean()*100:6.1f} %")
        ok_g &= bool(t >= th and x["folge"].mean() > 0)
    print(g, "->", "BESTANDEN" if ok_g else "NICHT BESTANDEN")

"""Runde 93: ML-Ranking US-Aktien, wöchentlich, long-only (Vorab-Registrierung in PROTOCOL.md)."""
import pickle
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

from tradingbot.research import ml_rank as ml

OUT = Path("data_cache/r93")
OUT.mkdir(parents=True, exist_ok=True)
PANEL = OUT / "panel.pkl"
TRAIN_START = pd.Timestamp("2017-01-01")
FIRST_TEST = pd.Timestamp("2018-01-01")
PERIODS = {
    "P1 2018-2021": (pd.Timestamp("2018-01-01"), pd.Timestamp("2021-12-31")),
    "P2 2022-2025-09": (pd.Timestamp("2022-01-01"), pd.Timestamp("2025-09-19")),
    "unberührt 2025-09..": (pd.Timestamp("2025-09-22"), pd.Timestamp("2026-12-31")),
}

t0 = time.time()
if PANEL.exists():
    panel = pickle.loads(PANEL.read_bytes())
else:
    wide = ml.load_wide()
    print("Wide:", wide["close"].shape, f"{time.time() - t0:.0f}s", flush=True)
    panel = ml.build_panel(wide)
    PANEL.write_bytes(pickle.dumps(panel))
    del wide
sizes = [len(p.y) for p in panel]
print(f"Panel: {len(panel)} Wochen, Ø {np.mean(sizes):.0f} Titel (min {min(sizes)}, max {max(sizes)}), "
      f"{panel[0].week.signal.date()}..{panel[-1].week.signal.date()}, {time.time() - t0:.0f}s", flush=True)

MODELS = {
    "LGBM-A (PRIMÄR)": ml.lgbm_fit({"num_leaves": 15, "learning_rate": 0.05, "num_boost_round": 200,
                                    "min_child_samples": 1000, "subsample": 0.8, "bagging_freq": 1,
                                    "colsample_bytree": 0.8}),
    "Ridge": lambda X, y: ml.ridge_fit(X, y, alpha=1.0),
    "LGBM-B": ml.lgbm_fit({"num_leaves": 31, "learning_rate": 0.05, "num_boost_round": 400,
                           "min_child_samples": 1000, "subsample": 0.8, "bagging_freq": 1,
                           "colsample_bytree": 0.8}),
    "LGBM-C": ml.lgbm_fit({"num_leaves": 7, "learning_rate": 0.05, "num_boost_round": 100,
                           "min_child_samples": 1000, "subsample": 0.8, "bagging_freq": 1,
                           "colsample_bytree": 0.8}),
}
SCORES = OUT / "scores.pkl"
scores = pickle.loads(SCORES.read_bytes()) if SCORES.exists() else {}
for name, fit in MODELS.items():
    if name in scores:
        continue
    scores[name] = ml.walk_forward(panel, fit, FIRST_TEST, TRAIN_START, retrain_every=4)
    SCORES.write_bytes(pickle.dumps(scores))
    print(f"{name}: {len(scores[name])} Prognosewochen, {time.time() - t0:.0f}s", flush=True)

mom_i = ml.FEATURES.index("mom12_1")
test_weeks = set(scores["LGBM-A (PRIMÄR)"])
mom_scores = {p.week.signal: p.X[:, mom_i].astype(float) for p in panel if p.week.signal in test_weeks}
ew = ml.simulate(panel, None, weeks=test_weeks).frame()
mom = ml.simulate(panel, mom_scores).frame()


def per(s: pd.Series, a, b):
    return s[(s.index >= a) & (s.index <= b)]


def row(label, df, ic=None):
    ex = df["net"] - ew["net"].reindex(df.index)
    exm = df["net"] - mom["net"].reindex(df.index)
    parts = [f"{label:28s}"]
    for pname, (a, b) in PERIODS.items():
        e, g, em = per(ex, a, b), per(df["gross"] - ew["gross"].reindex(df.index), a, b), per(exm, a, b)
        icp = f" IC {per(ic, a, b).mean():+.4f}" if ic is not None else ""
        parts.append(f"| {pname}: n {len(e)} Überr. netto {e.mean() * 1e4:+.1f} bp/Wo (t {ml.t_stat(e):+.2f}), "
                     f"brutto {g.mean() * 1e4:+.1f}, vs Mom {em.mean() * 1e4:+.1f} (t {ml.t_stat(em):+.2f}){icp}")
    parts.append(f"| Umschlag Ø {df['turnover'].iloc[1:].mean():.2f}/Wo, Titel Ø {df['n'].mean():.0f}")
    print("\n   ".join(parts))
    return ex


print("\nNetto 10 bp je Seite. Überrendite = Portfolio - gleichgewichtetes Universum (gleiche Wochen, gleiche Kosten).")
for pname, (a, b) in PERIODS.items():
    e = per(ew["net"], a, b)
    print(f"EW-Universum {pname}: {e.mean() * 1e4:+.1f} bp/Wo, {(np.prod(1 + e) ** (52 / max(len(e), 1)) - 1) * 100:+.1f} % p.a.")
row("Momentum 12-1 (Vergleich b)", mom)
res = {}
for name in MODELS:
    ic = ml.rank_ic(panel, scores[name])
    df = ml.simulate(panel, scores[name]).frame()
    res[name] = row(name, df, ic)
print("\nBerichtet (PRIMÄR-Varianten):")
prim = scores["LGBM-A (PRIMÄR)"]
row("PRIMÄR ohne Puffer (10/10)", ml.simulate(panel, prim, top=0.10, keep=0.10).frame())
row("PRIMÄR Top-50 (50/100)", ml.simulate(panel, prim, top=50, keep=100).frame())

ex = res["LGBM-A (PRIMÄR)"]
y = ex.groupby(ex.index.year).apply(lambda s: np.prod(1 + s) - 1)
print("\nPRIMÄR Überrendite je Jahr:", " ".join(f"{k}: {v * 100:+.1f}%" for k, v in y.items()))
p1, p2, u = (per(ex, *PERIODS[k]) for k in PERIODS)
em = ml.simulate(panel, prim).frame()["net"] - mom["net"]
em1, em2 = per(em, *PERIODS["P1 2018-2021"]), per(em, *PERIODS["P2 2022-2025-09"])
ok = ml.t_stat(p1) >= 2 and ml.t_stat(p2) >= 2 and u.mean() > 0 and em1.mean() > 0 and em2.mean() > 0
print(f"\nKriterien: t P1 {ml.t_stat(p1):+.2f} (>=2), t P2 {ml.t_stat(p2):+.2f} (>=2), unberührt {u.mean() * 1e4:+.1f} bp (>0), "
      f"vs Mom P1 {em1.mean() * 1e4:+.1f} / P2 {em2.mean() * 1e4:+.1f} bp (>0) -> {'BESTANDEN' if ok else 'NICHT BESTANDEN'}")

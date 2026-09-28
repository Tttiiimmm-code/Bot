"""Runde 95: ML-Ranking US-Aktien monatlich mit Fundamentaldaten (Vorab-Registrierung in PROTOCOL.md)."""
import pickle
import time
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

from tradingbot.research import edgar
from tradingbot.research import ml_rank as ml

OUT = Path("data_cache/r95")
OUT.mkdir(parents=True, exist_ok=True)
PANEL = OUT / "panel.pkl"
TRAIN_START = pd.Timestamp("2017-01-01")
FIRST_TEST = pd.Timestamp("2018-01-01")
PERIODS = {
    "P1 2018-2021": (pd.Timestamp("2018-01-01"), pd.Timestamp("2021-12-31")),
    "P2 2022-2025-09": (pd.Timestamp("2022-01-01"), pd.Timestamp("2025-09-19")),
    "unberührt 2025-09..": (pd.Timestamp("2025-09-22"), pd.Timestamp("2026-12-31")),
}
INSTANT = {"assets": ("Assets", "us-gaap", "USD"), "liabilities": ("Liabilities", "us-gaap", "USD"),
           "equity": ("StockholdersEquity", "us-gaap", "USD"),
           "shares": ("EntityCommonStockSharesOutstanding", "dei", "shares")}
ANNUAL = {"ni": ["NetIncomeLoss"], "rev": ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues"],
          "gp": ["GrossProfit"], "oi": ["OperatingIncomeLoss"], "cfo": ["NetCashProvidedByUsedInOperatingActivities"]}


def by_symbol(frame: pd.DataFrame, sym_cik: pd.Series) -> pd.Series:
    vals = frame.drop_duplicates("cik", keep="last").set_index("cik")["val"].astype(float)
    return sym_cik.map(vals).dropna()


def fundamentals(signals: pd.DatetimeIndex, close: pd.DataFrame) -> dict[str, pd.DataFrame]:
    mapping = edgar.symbol_to_cik(pd.read_pickle("data_cache/edgar/insider_purchases.pkl"))
    sym_cik = pd.Series({s: c for s, c in mapping.items() if s in close.columns})
    print(f"CIK-Zuordnung: {len(sym_cik)} von {close.shape[1]} Symbolen", flush=True)
    q_rows = {k: {} for k in list(INSTANT) + ["assets_1y", "shares_1y"]}
    for y in range(2015, 2027):
        for qq in range(1, 5):
            if (y, qq) > (2026, 1):
                continue
            quarter_end = pd.Timestamp(year=y, month=3 * qq, day=1) + pd.offsets.MonthEnd(0)
            avail = quarter_end + pd.DateOffset(months=3) + pd.offsets.MonthEnd(0)
            for k, (concept, tax, unit) in INSTANT.items():
                q_rows[k][avail] = by_symbol(edgar.xbrl_frame(concept, y, qq, True, taxonomy=tax, unit=unit), sym_cik)
                if k in ("assets", "shares") and y > 2015:
                    q_rows[k + "_1y"][avail] = by_symbol(
                        edgar.xbrl_frame(concept, y - 1, qq, True, taxonomy=tax, unit=unit), sym_cik)
    a_rows = {k: {} for k in list(ANNUAL) + ["rev_1y"]}
    annual_vals = {}
    for y in range(2015, 2026):
        avail = pd.Timestamp(year=y + 1, month=5, day=31)
        for k, concepts in ANNUAL.items():
            s = pd.Series(dtype=float)
            for concept in concepts:
                s = s.combine_first(by_symbol(edgar.xbrl_frame(concept, y, None, False), sym_cik))
            annual_vals[(k, y)] = s
            a_rows[k][avail] = s
        if y > 2015:
            a_rows["rev_1y"][avail] = annual_vals[("rev", y - 1)]
    cols = close.columns
    q = {k: ml.as_of(pd.DataFrame(v).T.reindex(columns=cols), signals, 190) for k, v in q_rows.items()}
    a = {k: ml.as_of(pd.DataFrame(v).T.reindex(columns=cols), signals, 370) for k, v in a_rows.items()}
    splits = pd.read_pickle("data_cache/splits.pkl")
    price = close.loc[signals] * ml.split_factor(splits, signals, cols)
    f = ml.fundamental_features(q, a, price)
    for k, v in f.items():
        print(f"  {k}: Abdeckung Ø {v.notna().sum(axis=1).mean():.0f} Symbole je Monat", flush=True)
    return f


t0 = time.time()
if PANEL.exists():
    panel = pickle.loads(PANEL.read_bytes())
else:
    wide = ml.load_wide()
    print("Wide:", wide["close"].shape, f"{time.time() - t0:.0f}s", flush=True)
    months = ml.weekly_schedule(wide["close"].index, "M")
    signals = pd.DatetimeIndex([m.signal for m in months])
    fund = fundamentals(signals, wide["close"])
    panel = ml.build_panel(wide, weeks=months, extra=fund)
    PANEL.write_bytes(pickle.dumps(panel))
    del wide
sizes = [len(p.y) for p in panel]
print(f"Panel: {len(panel)} Monate, Ø {np.mean(sizes):.0f} Titel, {panel[0].X.shape[1]} Merkmale, "
      f"{panel[0].week.signal.date()}..{panel[-1].week.signal.date()}, {time.time() - t0:.0f}s", flush=True)
names = ml.FEATURES + ml.FUNDAMENTALS
cov = np.mean([np.mean(p.X[:, len(ml.FEATURES):] != 0.5) for p in panel])
print(f"Anteil vorhandener Fundamentalwerte im Universum: {cov:.0%}", flush=True)

LGBM = {"learning_rate": 0.05, "min_child_samples": 1000, "subsample": 0.8, "bagging_freq": 1,
        "colsample_bytree": 0.8}
MODELS = {
    "LGBM-A (PRIMÄR)": ml.lgbm_fit({"num_leaves": 15, "num_boost_round": 200, **LGBM}),
    "Ridge": lambda X, y: ml.ridge_fit(X, y, alpha=1.0),
    "LGBM-C": ml.lgbm_fit({"num_leaves": 7, "num_boost_round": 100, **LGBM}),
}
SCORES = OUT / "scores.pkl"
scores = pickle.loads(SCORES.read_bytes()) if SCORES.exists() else {}
for name, fit in MODELS.items():
    if name in scores:
        continue
    scores[name] = ml.walk_forward(panel, fit, FIRST_TEST, TRAIN_START, retrain_every=1)
    SCORES.write_bytes(pickle.dumps(scores))
    print(f"{name}: {len(scores[name])} Prognosemonate, {time.time() - t0:.0f}s", flush=True)

test_weeks = set(scores["LGBM-A (PRIMÄR)"])
good = [names.index(k) for k in ("bm", "ep", "cfp", "gpa", "roa")]
bad = [names.index(k) for k in ("ag", "issuance", "accruals")]
scores["Mix ohne ML"] = {p.week.signal: (p.X[:, good].sum(axis=1) + (1 - p.X[:, bad]).sum(axis=1)) / 8
                         for p in panel if p.week.signal in test_weeks}
mom_i = names.index("mom12_1")
mom_scores = {p.week.signal: p.X[:, mom_i].astype(float) for p in panel if p.week.signal in test_weeks}
ew = ml.simulate(panel, None, weeks=test_weeks).frame()
mom = ml.simulate(panel, mom_scores).frame()


def per(s, a, b):
    return s[(s.index >= a) & (s.index <= b)]


def row(label, df, ic=None):
    ex = df["net"] - ew["net"].reindex(df.index)
    exm = df["net"] - mom["net"].reindex(df.index)
    parts = [f"{label:28s}"]
    for pname, (a, b) in PERIODS.items():
        e, g, em = per(ex, a, b), per(df["gross"] - ew["gross"].reindex(df.index), a, b), per(exm, a, b)
        icp = f" IC {per(ic, a, b).mean():+.4f}" if ic is not None else ""
        parts.append(f"| {pname}: n {len(e)} Überr. netto {e.mean() * 1e4:+.1f} bp/Mo (t {ml.t_stat(e):+.2f}), "
                     f"brutto {g.mean() * 1e4:+.1f}, vs Mom {em.mean() * 1e4:+.1f} (t {ml.t_stat(em):+.2f}){icp}")
    parts.append(f"| Umschlag Ø {df['turnover'].iloc[1:].mean():.2f}/Mo, Titel Ø {df['n'].mean():.0f}")
    print("\n   ".join(parts))
    return ex


print("\nNetto 10 bp je Seite. Überrendite = Portfolio - gleichgewichtetes Universum (gleiche Monate, gleiche Kosten).")
for pname, (a, b) in PERIODS.items():
    e = per(ew["net"], a, b)
    print(f"EW-Universum {pname}: {e.mean() * 1e4:+.1f} bp/Mo, "
          f"{(np.prod(1 + e) ** (12 / max(len(e), 1)) - 1) * 100:+.1f} % p.a.")
row("Momentum 12-1 (Vergleich b)", mom)
res = {}
for name in list(MODELS) + ["Mix ohne ML"]:
    ic = ml.rank_ic(panel, scores[name])
    res[name] = row(name, ml.simulate(panel, scores[name]).frame(), ic)

# Merkmalswichtigkeit eines Modells auf allen Daten -- nur berichtet, nicht Teil der Wertung.
train = [p for p in panel if p.week.signal >= TRAIN_START]
bst = lgb.train({"objective": "regression", "verbosity": -1, "seed": 93, "num_leaves": 15, **LGBM},
                lgb.Dataset(np.vstack([p.X for p in train]), np.concatenate([p.y for p in train])), 200)
imp = pd.Series(bst.feature_importance("gain"), index=names).sort_values(ascending=False)
print("\nWichtigste Merkmale (Gain, nur berichtet):",
      ", ".join(f"{k} {v / imp.sum():.0%}" for k, v in imp.head(10).items()))

ex = res["LGBM-A (PRIMÄR)"]
y = ex.groupby(ex.index.year).apply(lambda s: np.prod(1 + s) - 1)
print("\nPRIMÄR Überrendite je Jahr:", " ".join(f"{k}: {v * 100:+.1f}%" for k, v in y.items()))
p1, p2, u = (per(ex, *PERIODS[k]) for k in PERIODS)
em = ml.simulate(panel, scores["LGBM-A (PRIMÄR)"]).frame()["net"] - mom["net"]
em1, em2 = per(em, *PERIODS["P1 2018-2021"]), per(em, *PERIODS["P2 2022-2025-09"])
ok = ml.t_stat(p1) >= 2 and ml.t_stat(p2) >= 2 and u.mean() > 0 and em1.mean() > 0 and em2.mean() > 0
print(f"\nKriterien: t P1 {ml.t_stat(p1):+.2f} (>=2), t P2 {ml.t_stat(p2):+.2f} (>=2), "
      f"unberührt {u.mean() * 1e4:+.1f} bp (>0), vs Mom P1 {em1.mean() * 1e4:+.1f} / P2 {em2.mean() * 1e4:+.1f} bp (>0) "
      f"-> {'BESTANDEN' if ok else 'NICHT BESTANDEN'}")

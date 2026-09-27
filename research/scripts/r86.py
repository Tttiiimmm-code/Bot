"""Runde 86: Lazy Prices -- Quintile nach Kosinus-Ähnlichkeit aufeinanderfolgender 10-K."""
import gzip
import json
import math
import pickle
from pathlib import Path

import numpy as np
import pandas as pd

L = Path("data_cache/lazy")
u = pd.read_pickle(L / "universe.pkl")
sym_cik = json.load(open(L / "sym_cik.json"))


def cos(a, b):
    common = set(a) & set(b)
    num = sum(a[w] * b[w] for w in common)
    den = math.sqrt(sum(v * v for v in a.values())) * math.sqrt(sum(v * v for v in b.values()))
    return num / den if den else np.nan


sims = {}
for cik in sorted(set(sym_cik.values())):
    files = sorted(L.glob(f"{cik}_2*.pkl.gz"))
    prev = None
    for f in files:
        with gzip.open(f) as fh:
            c = pickle.load(fh)
        fd = pd.Timestamp(f.name.split("_")[1][:10])
        if prev is not None and sum(c.values()) > 2000 and sum(prev[1].values()) > 2000 and 250 <= (fd - prev[0]).days <= 500:
            sims[(cik, fd)] = cos(prev[1], c)
        prev = (fd, c)
S = pd.Series(sims)
print("Ähnlichkeiten:", len(S), "Median", round(S.median(), 3))

syms = sorted(set(u["symbol"]) & set(sym_cik))
closes = []
for p in sorted(Path("data_cache/universe/daily").glob("batch_*.pkl")):
    d = pd.read_pickle(p)
    if d.empty:
        continue
    d = d[d.index.get_level_values(0).isin(syms)]
    if d.empty:
        continue
    c = d["close"].copy()
    c.index = pd.MultiIndex.from_arrays([c.index.get_level_values(0), c.index.get_level_values(1).tz_convert("America/New_York").normalize().tz_localize(None)])
    closes.append(c.unstack(0))
C = pd.concat(closes, axis=1).sort_index()
C = C.loc[:, ~C.columns.duplicated()]
me = C.resample("ME").last().index
me = [C.index[C.index <= m][-1] for m in me if (C.index <= m).any()]
rows = []
prev_w = {}
for i, m in enumerate(me[:-1]):
    nxt = me[i + 1]
    yr_uni = set(u.loc[u["year"] == min(m.year - 1, 2024), "symbol"]) if m.year > 2015 else set()
    recs = []
    for s in yr_uni & set(C.columns):
        cik = sym_cik.get(s)
        if cik is None or cik not in S.index.get_level_values(0):
            continue
        ss = S[cik]
        ss = ss[(ss.index + pd.Timedelta(days=1) <= m) & (ss.index > m - pd.Timedelta(days=365))]
        if ss.empty or pd.isna(C.at[m, s]):
            continue
        after = C[s].loc[m:nxt].dropna()
        r = after.iloc[-1] / C.at[m, s] - 1 if len(after) > 1 else 0.0
        recs.append((s, ss.iloc[-1], r))
    if len(recs) < 50:
        continue
    df = pd.DataFrame(recs, columns=["s", "sim", "r"])
    df["q"] = pd.qcut(df["sim"].rank(method="first"), 5, labels=False)
    q5, q1 = set(df.loc[df.q == 4, "s"]), set(df.loc[df.q == 0, "s"])
    to5 = 1 - len(q5 & prev_w.get("q5", set())) / max(len(q5), 1)
    to1 = 1 - len(q1 & prev_w.get("q1", set())) / max(len(q1), 1)
    prev_w = {"q5": q5, "q1": q1}
    r5, r1, ru = df.loc[df.q == 4, "r"].mean(), df.loc[df.q == 0, "r"].mean(), df["r"].mean()
    rows.append((nxt, r5 - r1 - 2 * 0.001 * (to5 + to1), r5 - ru - 2 * 0.001 * to5, len(df), to5))
R = pd.DataFrame(rows, columns=["m", "ls", "lo", "n", "turn"]).set_index("m")
print("Ø Titel je Monat", round(R["n"].mean()), "Umschlag Q5 je Monat", round(R["turn"].mean(), 2))
for name, a, b in [("Entdeckung 2016-2020", "2016", "2020"), ("Bestätigung 2021-2025-09", "2021", "2025-09-30")]:
    x = R[a:b]
    for col, lab in (("ls", "Long-Short Q5-Q1"), ("lo", "Long-only Q5 - Universum")):
        t = x[col].mean() / x[col].std() * np.sqrt(len(x))
        print(f"{name:26s} {lab:26s} Monate {len(x):3d} Ø {x[col].mean()*100:5.2f} % je Monat t {t:5.2f}")

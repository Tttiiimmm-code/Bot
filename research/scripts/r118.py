"""Runde 118: 1.800 Faktor-Kombinationen (Kurs- und SEC-Kennzahlen), monatlich, nur long -- Vorab: r118_prereg.md."""
from __future__ import annotations

import itertools
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).with_name("ri")))           # research/ideas-Worktree (WeekData-Klasse)
OUT = Path(__file__).with_name("r118_results.pkl")
NAMES = ["r5", "r21", "mom12_1", "mom6_1", "vol21", "vol63", "ldv20", "dv5_63", "hi52", "lo52", "max21", "on21",
         "in21", "amihud21", "hl21", "bm", "ep", "sp", "cfp", "roe", "roa", "gpa", "opm", "lev", "ag", "accruals",
         "issuance", "sgrowth"]
COMBO = ["bm", "ep", "sp", "cfp", "roe", "roa", "gpa", "opm", "lev", "ag", "accruals", "issuance", "sgrowth",
         "mom12_1", "r21", "vol63", "hi52"]
PERIODS = {"Training": ("2017-01-01", "2019-12-31"), "Bestätigung": ("2020-01-01", "2022-12-31"),
           "Endtest": ("2023-01-01", "2026-12-31")}


def tstat(x):
    return float(x.mean() / x.std(ddof=1) * np.sqrt(len(x))) if len(x) > 2 and x.std() > 0 else float("nan")


def main():
    t0 = time.time()
    panel = pd.read_pickle("data_cache/r95/panel.pkl")
    assert panel[0].X.shape[1] == len(NAMES)
    months = [w.week.entry for w in panel]
    rets = [np.clip(np.nan_to_num(w.ret), -0.95, 5) for w in panel]
    bench = np.array([r.mean() for r in rets])
    specs = []
    for f, sg in itertools.product(range(len(NAMES)), (1, -1)):
        specs.append(((f,), (sg,), f"{'hoch' if sg > 0 else 'niedrig'} {NAMES[f]}"))
    ci = [NAMES.index(c) for c in COMBO]
    for (a, b), (sa, sb) in itertools.product(itertools.combinations(ci, 2), itertools.product((1, -1), (1, -1))):
        specs.append(((a, b), (sa, sb), f"{'hoch' if sa > 0 else 'niedrig'} {NAMES[a]} + "
                                        f"{'hoch' if sb > 0 else 'niedrig'} {NAMES[b]}"))
    results = []
    for (fs, sgs, nm), N in itertools.product(specs, (20, 50, 100)):
        prev, out = set(), []
        for w, r, bm in zip(panel, rets, bench):
            sc = sum(s * (w.X[:, f] - 0.5) for f, s in zip(fs, sgs))
            top = np.argsort(-sc)[:N]
            cur = set(w.symbols[top])
            turn = (len(cur - prev) + len(prev - cur)) / N        # Käufe + Verkäufe als Anteil am Depot
            out.append(r[top].mean() - bm - 0.001 * turn)
            prev = cur
        results.append(dict(name=f"{nm}, Top {N}", feats=dict(n_f=len(fs), N=N, first=NAMES[fs[0]]),
                            monthly=pd.Series(out, index=pd.DatetimeIndex(months))))
    print(f"{len(results)} Varianten ({time.time() - t0:.0f} s)", flush=True)
    pd.to_pickle(results, OUT)

    def per(s_, nm):
        a, b = PERIODS[nm]
        return s_[(s_.index >= a) & (s_.index <= b)].to_numpy()

    def desc(x):
        return f"Monate {len(x)}  Ø {x.mean() * 100:+.2f} %/Monat  t {tstat(x):+.2f}"

    rows = []
    for i, x in enumerate(results):
        a, b = per(x["monthly"], "Training"), per(x["monthly"], "Bestätigung")
        rows.append(dict(i=i, avg=a.mean(), t=tstat(a), conf=b.mean(), tc=tstat(b), **x["feats"]))
    tr = pd.DataFrame(rows)
    print(f"Training 2017-2019: t >= 2: {(tr.t >= 2).sum()} | t >= 3: {(tr.t >= 3).sum()} | t >= 4: {(tr.t >= 4).sum()}"
          f" | Ø > 0: {(tr.avg > 0).sum()} von {len(tr)}")
    print(f"Bestätigung: Ø > 0: {(tr.conf > 0).sum()}; Korrelation Training->Bestätigung über Varianten: "
          f"{tr[['avg', 'conf']].corr().iloc[0, 1]:+.2f}")
    print(f"Mit t >= 2 in BEIDEN (Information): {((tr.t >= 2) & (tr.tc >= 2)).sum()}")
    for _, row in tr[(tr.t >= 2) & (tr.tc >= 2)].sort_values("tc", ascending=False).head(8).iterrows():
        print(f"  {results[int(row.i)]['name']}: {row.avg * 100:+.2f}% (t {row.t:.2f}) / {row.conf * 100:+.2f}% (t {row.tc:.2f})")

    def show(row, count):
        x = results[int(row.i)]
        print(f"\n=== {x['name']}")
        print(f"  Training:    {desc(per(x['monthly'], 'Training'))}")
        b = per(x["monthly"], "Bestätigung")
        ok = b.mean() > 0 and tstat(b) >= 2.4
        print(f"  Bestätigung: {desc(b)}  -> {'BESTANDEN' if ok else 'nicht bestanden'}")
        if count and ok:
            e_ = per(x["monthly"], "Endtest")
            fin = e_.mean() > 0 and tstat(e_) >= 2
            print(f"  Endtest:     {desc(e_)}  -> {'BESTANDEN' if fin else 'nicht bestanden'}")
        elif count:
            print("  Endtest: nicht angesehen")

    el = tr[(tr.avg > 0) & (tr.t >= 4)].sort_values("t", ascending=False).head(3)
    print(f"\n--- Zählende Auswahl (Ø > 0, t >= 4): {len(el)}")
    for _, row in el.iterrows():
        show(row, True)
    if el.empty:
        print("  keine -> RUNDE NICHT BESTANDEN")
    print("\n--- Nur Information: 3 beste Trainings-t")
    for _, row in tr[tr.avg > 0].sort_values("t", ascending=False).head(3).iterrows():
        show(row, False)
    print(f"Laufzeit {time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()

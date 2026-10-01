"""Runde 117: 768 Varianten Paarhandel mit Einzelaktien (Distanzmethode) -- Vorab: r117_prereg.md."""
from __future__ import annotations

import itertools
import time
from pathlib import Path

import numba
import numpy as np
import pandas as pd

WIDE = Path(__file__).with_name("r114_wide.npz")
OUT = Path(__file__).with_name("r117_results.pkl")
PERIODS = {"Training": ("2016-01-01", "2019-12-31"), "Bestätigung": ("2020-01-01", "2022-12-31"),
           "Endtest": ("2023-01-01", "2026-12-31")}
MAXK = 50


@numba.njit(cache=True)
def simulate(S, Ri, Rj, sig, k, exit_half, stop, delay):
    P, D = S.shape
    out = np.zeros((P, D))
    for p in range(P):
        pos, pend = 0, 0
        for d in range(D):
            ri, rj = Ri[p, d], Rj[p, d]
            if np.isnan(ri) or np.isnan(rj) or np.isnan(S[p, d]):
                if pos != 0:
                    out[p, d] -= 0.002          # Schließen zum letzten Kurs
                break
            if pos != 0:
                out[p, d] += pos * (ri - rj)
            s, sg = S[p, d], sig[p]
            last = d == D - 1
            if pos != 0:
                cross = (pos > 0 and s >= 0) or (pos < 0 and s <= 0)
                near = exit_half and abs(s) <= 0.5 * sg
                stp = stop and abs(s) >= 4 * sg
                if cross or near or stp or last:
                    out[p, d] -= 0.002
                    pos = 0
                continue
            if pend != 0 and not last:
                pos, pend = pend, 0
                out[p, d] -= 0.002
                continue
            if abs(s) >= k * sg and not last:
                side = -1 if s > 0 else 1       # s = Pi - Pj > 0: i teurer -> i short, j long -> pos -1
                if delay:
                    pend = side
                else:
                    pos = side
                    out[p, d] -= 0.002
    return out


def tstat(x):
    return float(x.mean() / x.std(ddof=1) * np.sqrt(len(x))) if len(x) > 2 and x.std() > 0 else float("nan")


def main():
    t0 = time.time()
    z = np.load(WIDE, allow_pickle=True)
    C, V = z["C"].astype(np.float64), z["V"]
    dates = pd.DatetimeIndex(z["dates"])
    T = len(dates)
    dv = pd.DataFrame(C * V).rolling(20, min_periods=15).mean().shift(1).to_numpy()
    rank = pd.DataFrame(np.where((C > 5) & np.isfinite(dv), dv, np.nan)).rank(axis=1, ascending=False).to_numpy()
    keep = np.nanmin(np.where(np.isfinite(rank), rank, 1e9), axis=0) <= 1500
    C, rank = C[:, keep], rank[:, keep]
    del V, dv
    R = np.vstack([np.full((1, C.shape[1]), np.nan), C[1:] / C[:-1] - 1])
    R[np.abs(R) > 0.5] = np.nan          # Tagessprünge > 50 %: Datenfehler/Split -> Paar wird geschlossen
    print(f"{C.shape[1]} Symbole ({time.time() - t0:.0f} s)", flush=True)
    inner = list(itertools.product((5, 20, 50), (1.5, 2.0, 2.5, 3.0), (False, True), (False, True), (False, True)))
    acc = {}
    for F, Tt, un in itertools.product((126, 252), (63, 126), (500, 1500)):
        for s in range(F + 1, T - 1, Tt):
            e = min(s + Tt, T)
            u = np.flatnonzero((rank[s] <= un) & (C[s - 1] > 5) & np.isfinite(C[s - F:s]).all(0))
            if len(u) < 20:
                continue
            Pn = C[s - F:e, u] / C[s - F, u]
            form = Pn[:F]
            sq = (form ** 2).sum(0)
            ssd = sq[:, None] + sq[None, :] - 2 * form.T @ form
            iu = np.triu_indices(len(u), 1)
            vals = ssd[iu]
            order = np.argsort(vals)
            used, pairs = set(), []
            for o in order:
                a, b = iu[0][o], iu[1][o]
                if a in used or b in used:
                    continue
                used.update((a, b))
                pairs.append((a, b))
                if len(pairs) == MAXK:
                    break
            pa = np.array([p[0] for p in pairs])
            pb = np.array([p[1] for p in pairs])
            spread = Pn[:, pa] - Pn[:, pb]
            sig = spread[:F].std(0)
            S = np.ascontiguousarray(spread[F:].T)
            Ri = np.ascontiguousarray(R[s:e, u[pa]].T)
            Rj = np.ascontiguousarray(R[s:e, u[pb]].T)
            for K, k, eh, st, dl in inner:
                pnl = simulate(S[:K], Ri[:K], Rj[:K], sig[:K], k, eh, st, dl).mean(0)
                acc.setdefault((F, Tt, un, K, k, eh, st, dl), []).append(pd.Series(pnl, index=dates[s:e]))
        print(f"F{F} T{Tt} U{un} ({time.time() - t0:.0f} s)", flush=True)
    results = []
    for key, parts in acc.items():
        F, Tt, un, K, k, eh, st, dl = key
        results.append(dict(name=f"Formation {F} Tage, Handel {Tt} Tage, Top{un}, {K} Paare, Schwelle {k} Sigma, "
                                 f"Ausstieg {'0,5 Sigma' if eh else 'Kreuzung'}{', Stop 4 Sigma' if st else ''}"
                                 f"{', 1 Tag warten' if dl else ''}",
                            feats=dict(F=F, Tt=Tt, univ=un, K=K, k=k, exit=eh, stop=st, delay=dl),
                            daily=pd.concat(parts).sort_index()))
    pd.to_pickle(results, OUT)

    def per(s_, nm):
        a, b = PERIODS[nm]
        return s_[(s_.index >= a) & (s_.index <= b)].to_numpy()

    def desc(x):
        return f"Ø {x.mean() * 1e4:+.2f} bp/Tag ({x.mean() * 252:+.1%} p.a.)  t {tstat(x):+.2f}"

    rows = []
    for i, x in enumerate(results):
        a, b = per(x["daily"], "Training"), per(x["daily"], "Bestätigung")
        rows.append(dict(i=i, avg=a.mean(), t=tstat(a), conf=b.mean(), tc=tstat(b), **x["feats"]))
    tr = pd.DataFrame(rows)
    print(f"\nTraining: {len(tr)} | t >= 2: {(tr.t >= 2).sum()} | t >= 3: {(tr.t >= 3).sum()} | t >= 4: {(tr.t >= 4).sum()}"
          f" | Ø > 0: {(tr.avg > 0).sum()}")
    for c_ in ("F", "Tt", "univ", "K", "k", "exit", "stop", "delay"):
        g = tr.groupby(c_)
        print(f"  {c_}: " + ", ".join(f"{a} {b * 1e4:+.2f}->{c * 1e4:+.2f}" for a, b, c in
                                      zip(g.groups.keys(), g.avg.median(), g.conf.median())))

    def show(row, count):
        x = results[int(row.i)]
        print(f"\n=== {x['name']}")
        print(f"  Training:    {desc(per(x['daily'], 'Training'))}")
        b = per(x["daily"], "Bestätigung")
        ok = b.mean() > 0 and tstat(b) >= 2.4
        print(f"  Bestätigung: {desc(b)}  -> {'BESTANDEN' if ok else 'nicht bestanden'}")
        if count and ok:
            e_ = per(x["daily"], "Endtest")
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
    pos = tr[tr.avg > 0]
    print(f"\nFamilie: {len(pos)} im Training positiv; davon Bestätigung positiv {(pos.conf > 0).mean():.0%}")
    print(f"Laufzeit {time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()

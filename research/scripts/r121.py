"""Runde 121: 252 Varianten Saisonalität einzelner Aktien -- Vorab: r121_prereg.md."""
from __future__ import annotations

import itertools
import time
from pathlib import Path

import numpy as np
import pandas as pd

WIDE = Path(__file__).with_name("r114_wide.npz")
OUT = Path(__file__).with_name("r121_results.pkl")
PERIODS = {"Training": ("2019-01-01", "2021-12-31"), "Bestätigung": ("2022-01-01", "2023-12-31"),
           "Endtest": ("2024-01-01", "2026-12-31")}


def tstat(x):
    return float(x.mean() / x.std(ddof=1) * np.sqrt(len(x))) if len(x) > 2 and x.std() > 0 else float("nan")


def pick(sig_row, valid_row, N, side):
    s = np.where(valid_row & np.isfinite(sig_row), sig_row, np.nan)
    ok = np.flatnonzero(np.isfinite(s))
    if len(ok) < 2 * N:
        return None
    order = ok[np.argsort(s[ok])]
    return order[-N:] if side == "Top" else order[:N]


def main():
    t0 = time.time()
    z = np.load(WIDE, allow_pickle=True)
    C, V = z["C"].astype(np.float64), z["V"]
    dates = pd.DatetimeIndex(z["dates"])
    dv = pd.DataFrame(C * V).rolling(20, min_periods=15).mean().shift(1).to_numpy()
    rank = pd.DataFrame(np.where((C > 5) & np.isfinite(dv), dv, np.nan)).rank(axis=1, ascending=False).to_numpy()
    keep = np.nanmin(np.where(np.isfinite(rank), rank, 1e9), axis=0) <= 3000
    C, rank = C[:, keep], rank[:, keep]
    del V, dv
    T, M = C.shape
    R = np.vstack([np.full((1, M), np.nan), C[1:] / C[:-1] - 1])
    R[np.abs(R) > 0.5] = np.nan
    side_cost = np.where(rank <= 1500, 0.001, 0.0025)
    print(f"{M} Symbole ({time.time() - t0:.0f} s)", flush=True)
    results = []
    combos = list(itertools.product(("Top", "Bottom"), (20, 50, 100), (500, 1500, 3000)))

    # ---- A Kalendermonat
    per_m = dates.to_period("M")
    me = np.flatnonzero(np.r_[per_m[1:] != per_m[:-1], True])          # letzter Handelstag je Monat
    Cm = pd.DataFrame(C).ffill().to_numpy()[me]
    MR = Cm[1:] / Cm[:-1] - 1
    MR[np.abs(MR) > 3] = np.nan
    K = len(MR)
    for kind, Y in itertools.product(("roh", "minus übrige"), (3, 5, 99)):
        sig = np.full((K, M), np.nan)
        for k in range(K):
            past = [k - 12 * y for y in range(1, 11) if k - 12 * y >= 0][:Y]
            if len(past) < 3:
                continue
            same = np.nanmean(MR[past], axis=0)
            if kind == "roh":
                sig[k] = same
            else:
                lo = max(0, k - 12 * len(past))
                allm = np.nanmean(MR[lo:k], axis=0)
                sig[k] = same - allm
        for side, N, un in combos:
            out, idx, prev = [], [], set()
            for k in range(K):
                if not np.isfinite(sig[k]).any():
                    continue
                d0 = me[k]                                               # Kauf zum Schluss des Vormonats
                U = rank[d0] <= un
                sel = pick(sig[k], U & np.isfinite(MR[k]), N, side)
                if sel is None:
                    continue
                cur = set(sel)
                turn = len(cur ^ prev) / N
                cost = side_cost[d0, sel].mean() * turn
                bench = np.nanmean(np.where(U, MR[k], np.nan))
                out.append(np.nanmean(MR[k, sel]) - bench - cost)
                idx.append(dates[me[k + 1]])
                prev = cur
            results.append(dict(name=f"Kalendermonat {kind}, {Y if Y < 99 else 'alle'} Jahre, {side}-{N}, Top{un}",
                                feats=dict(fam="Monat", kind=kind, L=Y, side=side, N=N, univ=un),
                                s=pd.Series(out, index=pd.DatetimeIndex(idx))))
    print(f"A fertig ({time.time() - t0:.0f} s)", flush=True)

    # ---- B Wochentag
    wd = dates.weekday.to_numpy()
    Rz = np.nan_to_num(R)
    Rc = (~np.isnan(R)).astype(float)
    cs_all, cn_all = np.cumsum(Rz, 0), np.cumsum(Rc, 0)
    nxt_R = np.vstack([R[1:], np.full((1, M), np.nan)])                # Rendite des Folgetags (Haltetag)
    for L in (52, 104, 156):
        W = 5 * L
        sig_by = {}

        def win(cs):
            out = cs.copy()
            out[W:] = cs[W:] - cs[:-W]
            return out
        sa, na = win(cs_all), win(cn_all)
        for w in range(5):
            mw = (wd == w)[:, None]
            sw, nw = win(np.cumsum(Rz * mw, 0)), win(np.cumsum(Rc * mw, 0))
            same = np.where(nw >= L * 0.7, sw / np.maximum(nw, 1), np.nan)
            other = np.where(na - nw > 0, (sa - sw) / np.maximum(na - nw, 1), np.nan)
            sig_by[w] = (same, same - other)
        for kind_i, kind in enumerate(("roh", "minus übrige")):
            for side, N, un in combos:
                out, idx, prev = [], [], set()
                for t in range(W, T - 1):
                    w = wd[t + 1]
                    if w > 4:
                        continue
                    sg = sig_by[w][kind_i][t]
                    U = rank[t] <= un
                    sel = pick(sg, U & np.isfinite(nxt_R[t]), N, side)
                    if sel is None:
                        continue
                    cur = set(sel)
                    cost = side_cost[t, sel].mean() * len(cur ^ prev) / N
                    out.append(np.nanmean(nxt_R[t, sel]) - np.nanmean(np.where(U, nxt_R[t], np.nan)) - cost)
                    idx.append(dates[t + 1])
                    prev = cur
                results.append(dict(name=f"Wochentag {kind}, {L} Wochen, {side}-{N}, Top{un}",
                                    feats=dict(fam="Wochentag", kind=kind, L=L, side=side, N=N, univ=un),
                                    s=pd.Series(out, index=pd.DatetimeIndex(idx))))
        print(f"B L{L} fertig ({time.time() - t0:.0f} s)", flush=True)

    # ---- C Monatswechsel je Aktie
    starts = np.flatnonzero(np.r_[True, per_m[1:] != per_m[:-1]])     # erster Handelstag je Monat
    Cf = pd.DataFrame(C).ffill().to_numpy()
    for wname in ("erste 3", "letzte 3"):
        if wname == "erste 3":
            wins = [(s - 1, s + 2) for s in starts if s >= 1 and s + 2 < T]   # Schluss Vortag -> Schluss Tag 3
        else:
            wins = [(e - 3, e) for e in me if e >= 3]
        WR = np.array([Cf[b] / Cf[a] - 1 for a, b in wins])
        WR[np.abs(WR) > 1] = np.nan
        for side, N, un in combos:
            out, idx = [], []
            for k in range(36, len(wins)):
                sg = np.nanmean(WR[k - 36:k], axis=0)
                a, b = wins[k]
                U = rank[a] <= un
                sel = pick(sg, U & np.isfinite(WR[k]), N, side)
                if sel is None:
                    continue
                cost = 2 * side_cost[a, sel].mean()
                out.append(np.nanmean(WR[k, sel]) - np.nanmean(np.where(U, WR[k], np.nan)) - cost)
                idx.append(dates[b])
            results.append(dict(name=f"Monatswechsel {wname} Tage, 36 Monate, {side}-{N}, Top{un}",
                                feats=dict(fam="Monatswechsel", kind=wname, L=36, side=side, N=N, univ=un),
                                s=pd.Series(out, index=pd.DatetimeIndex(idx))))
    print(f"C fertig ({time.time() - t0:.0f} s)", flush=True)
    pd.to_pickle(results, OUT)

    def per(s_, nm):
        a, b = PERIODS[nm]
        return s_[(s_.index >= a) & (s_.index <= b)].to_numpy()

    def desc(x):
        return f"n {len(x)}  Ø {x.mean() * 1e4:+.1f} bp/Fenster  t {tstat(x):+.2f}" if len(x) > 2 else f"n {len(x)}"

    rows = []
    for i, x in enumerate(results):
        a, b = per(x["s"], "Training"), per(x["s"], "Bestätigung")
        rows.append(dict(i=i, avg=a.mean() if len(a) else np.nan, t=tstat(a), conf=b.mean() if len(b) else np.nan,
                         tc=tstat(b), **x["feats"]))
    tr = pd.DataFrame(rows)
    print(f"\nTraining 2019-2021: {len(tr)} | t >= 2: {(tr.t >= 2).sum()} | t >= 3: {(tr.t >= 3).sum()} | t >= 4: "
          f"{(tr.t >= 4).sum()} | Ø > 0: {(tr.avg > 0).sum()}")
    for c_ in ("fam", "kind", "side", "N", "univ"):
        g = tr.groupby(c_)
        print(f"  {c_}: " + ", ".join(f"{k} {a * 1e4:+.1f}->{b * 1e4:+.1f}" for k, a, b in
                                      zip(g.groups.keys(), g.avg.median(), g.conf.median())))
    print(f"  t >= 2 in beiden: {((tr.t >= 2) & (tr.tc >= 2)).sum()}")

    def show(row, count):
        x = results[int(row.i)]
        print(f"\n=== {x['name']}")
        print(f"  Training:    {desc(per(x['s'], 'Training'))}")
        b = per(x["s"], "Bestätigung")
        ok = len(b) > 2 and b.mean() > 0 and tstat(b) >= 2.4
        print(f"  Bestätigung: {desc(b)}  -> {'BESTANDEN' if ok else 'nicht bestanden'}")
        if count and ok:
            e_ = per(x["s"], "Endtest")
            fin = len(e_) > 2 and e_.mean() > 0 and tstat(e_) >= 2
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

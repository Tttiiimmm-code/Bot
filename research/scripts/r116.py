"""Runde 116: 540 Varianten Leerverkaufs-Volumen (FINRA) im Aktien-Querschnitt -- Vorab: r116_prereg.md."""
from __future__ import annotations

import itertools
import time
from pathlib import Path

import numpy as np
import pandas as pd

WIDE = Path(__file__).with_name("r114_wide.npz")
FIN = Path("data_cache/finra_short")
OUT = Path(__file__).with_name("r116_results.pkl")
PERIODS = {"Training": ("2016-01-01", "2019-12-31"), "Bestätigung": ("2020-01-01", "2022-12-31"),
           "Endtest": ("2023-01-01", "2026-12-31")}


def tstat(x):
    return float(x.mean() / x.std(ddof=1) * np.sqrt(len(x))) if len(x) > 2 and x.std() > 0 else float("nan")


def main():
    t0 = time.time()
    z = np.load(WIDE, allow_pickle=True)
    O, C, V = z["O"], z["C"], z["V"]
    dates, syms = pd.DatetimeIndex(z["dates"]), np.array(z["syms"])
    T = len(dates)
    dv = pd.DataFrame(C.astype(np.float64) * V).rolling(20, min_periods=15).mean().shift(1).to_numpy()
    elig = (C > 5) & np.isfinite(dv)
    rank = pd.DataFrame(np.where(elig, dv, np.nan)).rank(axis=1, ascending=False).to_numpy(np.float32)
    keep = np.nanmin(np.where(np.isfinite(rank), rank, 1e9), axis=0) <= 3000
    O, C, rank, syms = O[:, keep].astype(np.float64), C[:, keep], rank[:, keep], syms[keep]
    del V, dv, elig
    M = len(syms)
    col = pd.Index(syms)
    print(f"{M} Symbole im Universum ({time.time() - t0:.0f} s)", flush=True)
    Sh = np.full((T, M), np.nan, np.float32)
    Tot = np.full((T, M), np.nan, np.float32)
    for f in sorted(FIN.glob("*.pkl")):
        x = pd.read_pickle(f)
        di = dates.get_indexer(pd.DatetimeIndex(x["date"]))
        ci = col.get_indexer(x["symbol"])
        ok = (di >= 0) & (ci >= 0)
        Sh[di[ok], ci[ok]] = x["short"].to_numpy()[ok]
        Tot[di[ok], ci[ok]] = x["total"].to_numpy()[ok]
    print(f"FINRA geladen ({time.time() - t0:.0f} s), Abdeckung {np.isfinite(Tot).mean():.0%}", flush=True)
    shd, totd = pd.DataFrame(Sh), pd.DataFrame(Tot)

    def ratio(L):
        return (shd.rolling(L, min_periods=max(1, L * 3 // 4)).sum() /
                totd.rolling(L, min_periods=max(1, L * 3 // 4)).sum()).to_numpy(np.float32)

    s1, s5, s20, s60 = Sh / np.where(Tot > 0, Tot, np.nan), ratio(5), ratio(20), ratio(60)
    sigs = {"SVR1": s1, "SVR5": s5, "SVR20": s20, "SVR5-SVR60": s5 - s60, "SVR1-SVR20": s1 - s20}
    volok = Tot >= totd.rolling(20, min_periods=15).mean().shift(1).to_numpy(np.float32)
    del shd, totd
    Roo = np.vstack([O[1:] / O[:-1] - 1, np.zeros((1, M))])          # Eröffnung t -> Eröffnung t+1
    Roo = np.nan_to_num(np.clip(Roo, -0.9, 5))
    nxt = np.vstack([Roo[1:], np.zeros((1, M))])                      # gilt für Signal t: Eröffnung t+1 -> t+2
    sidec = np.where(rank <= 1500, 0.001, 0.0025)
    print(f"Signale ({time.time() - t0:.0f} s)", flush=True)
    results = []
    rows_idx = np.arange(T)
    for (sn, S), un, vf in itertools.product(sigs.items(), (500, 1500, 3000), (False, True)):
        Uu = rank <= un
        valid_m = Uu & np.isfinite(S) & (volok if vf else True)
        Sm = np.where(valid_m, S, np.nan)
        valid = np.isfinite(Sm).sum(1)
        order = np.argsort(np.where(np.isfinite(Sm), Sm, np.inf), axis=1)        # aufsteigend
        cnt = Uu.sum(1)
        bench = np.where(cnt > 0, (Uu * nxt).sum(1) / np.maximum(cnt, 1), 0.0)
        for side, N, H in itertools.product(("niedrigste", "höchste"), (20, 50, 100), (1, 5, 20)):
            W = np.zeros((T, M))
            ok = valid >= 2 * N
            for j in range(N):
                c_ = order[:, j] if side == "niedrigste" else order[rows_idx, np.maximum(valid - 1 - j, 0)]
                W[rows_idx[ok], c_[ok]] = 1.0 / N
            if H > 1:
                W = W[(np.arange(T) // H) * H]
            pnl = (W * nxt).sum(1)
            dW = np.abs(np.diff(W, axis=0, prepend=np.zeros((1, M))))
            c10 = (dW * sidec).sum(1)
            c2 = dW.sum(1) * 0.0002
            inv = W.sum(1) > 0
            ex10 = pd.Series(pnl - c10 - bench * inv, index=dates)[:-2]
            ex2 = pd.Series(pnl - c2 - bench * inv, index=dates)[:-2]
            results.append(dict(name=f"{side} {N} nach {sn}, alle {H} Tage, Top{un}{', Volumenfilter' if vf else ''}",
                                feats=dict(sig=sn, side=side, N=N, H=H, univ=un, vol=vf), d10=ex10, d2=ex2))
        print(f"{sn} Top{un} vol={vf} ({time.time() - t0:.0f} s)", flush=True)
    pd.to_pickle(results, OUT)

    def per(s, nm):
        a, b = PERIODS[nm]
        return s[(s.index >= a) & (s.index <= b)].to_numpy()

    def desc(x):
        return f"Ø {x.mean() * 1e4:+.1f} bp/Tag ({x.mean() * 252:+.0%} p.a.)  t {tstat(x):+.2f}"

    rows = []
    for i, x in enumerate(results):
        a, b = per(x["d10"], "Training"), per(x["d10"], "Bestätigung")
        rows.append(dict(i=i, avg=a.mean(), t=tstat(a), conf=b.mean(), tc=tstat(b),
                         t2=tstat(per(x["d2"], "Training")), tc2=tstat(per(x["d2"], "Bestätigung")), **x["feats"]))
    tr = pd.DataFrame(rows)
    print(f"\nTraining (Kosten 10/25 bp): t >= 2: {(tr.t >= 2).sum()} | t >= 3: {(tr.t >= 3).sum()} | t >= 4: "
          f"{(tr.t >= 4).sum()} | Ø > 0: {(tr.avg > 0).sum()} von {len(tr)}")
    print(f"Information 2 bp: Training t >= 4: {(tr.t2 >= 4).sum()}; davon Bestätigung t >= 2: "
          f"{((tr.t2 >= 4) & (tr.tc2 >= 2)).sum()}")
    for c_ in ("sig", "side", "N", "H", "univ", "vol"):
        g = tr.groupby(c_)
        print(f"  {c_}: " + ", ".join(f"{k} {a * 1e4:+.1f}->{b * 1e4:+.1f}" for k, a, b in
                                      zip(g.groups.keys(), g.avg.median(), g.conf.median())))

    def show(row, count):
        x = results[int(row.i)]
        print(f"\n=== {x['name']}")
        print(f"  Training:    {desc(per(x['d10'], 'Training'))}   (2 bp: t {row.t2:+.2f})")
        b = per(x["d10"], "Bestätigung")
        ok = b.mean() > 0 and tstat(b) >= 2.4
        print(f"  Bestätigung: {desc(b)}  -> {'BESTANDEN' if ok else 'nicht bestanden'}   (2 bp: t {row.tc2:+.2f})")
        if count and ok:
            e = per(x["d10"], "Endtest")
            fin = e.mean() > 0 and tstat(e) >= 2
            print(f"  Endtest:     {desc(e)}  -> {'BESTANDEN' if fin else 'nicht bestanden'}")
        elif count:
            print("  Endtest: nicht angesehen")

    el = tr[(tr.avg > 0) & (tr.t >= 4)].sort_values("t", ascending=False).head(3)
    print(f"\n--- Zählende Auswahl (Ø > 0, t >= 4): {len(el)}")
    for _, row in el.iterrows():
        show(row, True)
    if el.empty:
        print("  keine -> RUNDE NICHT BESTANDEN")
    print("\n--- Nur Information: 3 beste Trainings-t und 3 beste bei 2 bp")
    for _, row in tr[tr.avg > 0].sort_values("t", ascending=False).head(3).iterrows():
        show(row, False)
    for _, row in tr.sort_values("t2", ascending=False).head(3).iterrows():
        show(row, False)
    print(f"Laufzeit {time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()

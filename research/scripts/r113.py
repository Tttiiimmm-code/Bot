"""Runde 113: 1.296 Varianten Nacht-/Tag-Renditen im Aktien-Querschnitt -- Vorab: r113_prereg.md."""
from __future__ import annotations

import itertools
import time
from pathlib import Path

import numpy as np
import pandas as pd

U = Path("data_cache/universe/daily")
WIDE = Path(__file__).with_name("r113_wide.npz")
OUT = Path(__file__).with_name("r113_results.pkl")
PERIODS = {"Training": ("2016-01-01", "2019-12-31"), "Bestätigung": ("2020-01-01", "2022-12-31"),
           "Endtest": ("2023-01-01", "2026-12-31")}


def build():
    Os, Cs, Vs = [], [], []
    for p in sorted(U.glob("batch_*.pkl")):
        x = pd.read_pickle(p)
        if not len(x):
            continue
        d = pd.to_datetime(x.index.get_level_values("timestamp").tz_convert("America/New_York").date)
        df = pd.DataFrame({"symbol": x.index.get_level_values("symbol"), "date": d, "open": x["open"].to_numpy(),
                           "close": x["close"].to_numpy(), "volume": x["volume"].to_numpy()})
        df = df.drop_duplicates(["date", "symbol"])
        for col, acc in (("open", Os), ("close", Cs), ("volume", Vs)):
            acc.append(df.pivot(index="date", columns="symbol", values=col).astype(np.float32))
        print(p.name, flush=True)
    O, C, V = (pd.concat(a, axis=1).sort_index() for a in (Os, Cs, Vs))
    O = O.loc[:, ~O.columns.duplicated()]
    C, V = C.loc[:, ~C.columns.duplicated()][O.columns], V.loc[:, ~V.columns.duplicated()][O.columns]
    np.savez(WIDE, O=O.to_numpy(np.float32), C=C.to_numpy(np.float32), V=V.to_numpy(np.float32),
             dates=O.index.to_numpy())


def tstat(x):
    return float(x.mean() / x.std(ddof=1) * np.sqrt(len(x))) if len(x) > 2 and x.std() > 0 else float("nan")


def main():
    t0 = time.time()
    if not WIDE.exists():
        build()
    z = np.load(WIDE, allow_pickle=True)
    O, C, V, dates = z["O"].astype(np.float64), z["C"].astype(np.float64), z["V"], pd.DatetimeIndex(z["dates"])
    T, M = C.shape
    print(f"{M} Symbole, {T} Tage ({time.time() - t0:.0f} s)", flush=True)
    pc = np.vstack([np.full((1, M), np.nan), C[:-1]])
    ON = np.clip(O / pc - 1, -0.9, 5)
    ID = np.clip(C / O - 1, -0.9, 5)
    CC = np.clip(C / pc - 1, -0.9, 5)
    dv = pd.DataFrame(C * V).rolling(20, min_periods=15).mean().shift(1).to_numpy()
    elig = (C > 5) & np.isfinite(dv) & np.isfinite(C)
    univ = {}
    for n in (500, 1500):
        rk = pd.DataFrame(np.where(elig, dv, np.nan)).rank(axis=1, ascending=False).to_numpy()
        univ[n] = rk <= n
    nxt = {"Nacht": np.nan_to_num(np.vstack([ON[1:], np.zeros((1, M))])),
           "Tag": np.nan_to_num(np.vstack([ID[1:], np.zeros((1, M))])),
           "voll": np.nan_to_num(np.vstack([CC[1:], np.zeros((1, M))]))}
    sigs = {}
    for L in (5, 20, 60):
        on = pd.DataFrame(ON).rolling(L, min_periods=L).mean().to_numpy()
        idr = pd.DataFrame(ID).rolling(L, min_periods=L).mean().to_numpy()
        cc = pd.DataFrame(np.log1p(CC)).rolling(L, min_periods=L).sum().to_numpy()
        sigs[("Nacht", L)], sigs[("Tag", L)], sigs[("Nacht-Tag", L)], sigs[("gesamt", L)] = on, idr, on - idr, cc
    print(f"Signale ({time.time() - t0:.0f} s)", flush=True)
    results = []
    rows_idx = np.arange(T)
    for (sname, L), n in itertools.product(sigs, (500, 1500)):
        Uu = univ[n]
        S = np.where(Uu & np.isfinite(sigs[(sname, L)]), sigs[(sname, L)], np.nan)
        valid = np.isfinite(S).sum(1)
        order = np.argsort(np.where(np.isfinite(S), -S, np.inf), axis=1)
        cnt = Uu.sum(1)
        for side, win, H, N in itertools.product(("Top", "Bottom"), ("Nacht", "Tag", "voll"), (1, 5, 20), (20, 50, 100)):
            W = np.zeros((T, M))
            ok = valid >= 2 * N
            for j in range(N):
                col = order[:, j] if side == "Top" else order[rows_idx, np.maximum(valid - 1 - j, 0)]
                W[rows_idx[ok], col[ok]] = 1.0 / N
            if H > 1:
                W = W[(np.arange(T) // H) * H]
            R = nxt[win]
            pnl = (W * R).sum(1)
            gross = W.sum(1)
            if win == "voll":
                turn = np.abs(np.diff(W, axis=0, prepend=np.zeros((1, M)))).sum(1)
            else:
                turn = 2 * gross
            bench = np.where(cnt > 0, (Uu * R).sum(1) / np.maximum(cnt, 1), 0.0)
            ex10 = pd.Series(pnl - 0.001 * turn - bench * (gross > 0), index=dates)[:-1]
            ex2 = pd.Series(pnl - 0.0002 * turn - bench * (gross > 0), index=dates)[:-1]
            results.append(dict(name=f"{side}-{N} nach {sname} L{L}, Fenster {win}, alle {H} Tage, Top{n}-Universum",
                                feats=dict(sig=sname, L=L, side=side, win=win, H=H, N=N, n=n), d10=ex10, d2=ex2))
        print(f"{sname} L{L} n{n} ({time.time() - t0:.0f} s)", flush=True)
    pd.to_pickle(results, OUT)

    def per(s, nm):
        a, b = PERIODS[nm]
        return s[(s.index >= a) & (s.index <= b)].to_numpy()

    def desc(x):
        return f"Ø {x.mean() * 1e4:+.1f} bp/Tag ({x.mean() * 252:+.0%} p.a.)  t {tstat(x):+.2f}"

    rows = []
    for i, x in enumerate(results):
        a, b = per(x["d10"], "Training"), per(x["d10"], "Bestätigung")
        a2, b2 = per(x["d2"], "Training"), per(x["d2"], "Bestätigung")
        rows.append(dict(i=i, avg=a.mean(), t=tstat(a), conf=b.mean(), tc=tstat(b), t2=tstat(a2), tc2=tstat(b2),
                         **x["feats"]))
    tr = pd.DataFrame(rows)
    print(f"\nTraining (10 bp): t >= 2: {(tr.t >= 2).sum()} | t >= 3: {(tr.t >= 3).sum()} | t >= 4: {(tr.t >= 4).sum()} | "
          f"Ø > 0: {(tr.avg > 0).sum()} von {len(tr)}")
    print(f"Information 2 bp: Training t >= 4: {(tr.t2 >= 4).sum()}, davon Bestätigung t >= 2: "
          f"{((tr.t2 >= 4) & (tr.tc2 >= 2)).sum()}")
    for col in ("sig", "L", "side", "win", "H", "N", "n"):
        g = tr.groupby(col)
        print(f"  {col}: " + ", ".join(f"{k} {a * 1e4:+.1f}->{b * 1e4:+.1f}" for k, a, b in
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
    print(f"\n--- Zählende Auswahl (Ø > 0, t >= 4, 10 bp): {len(el)}")
    for _, row in el.iterrows():
        show(row, True)
    if el.empty:
        print("  keine -> RUNDE NICHT BESTANDEN")
    print("\n--- Nur Information: 3 beste Trainings-t (10 bp) und 3 beste bei 2 bp")
    for _, row in tr[tr.avg > 0].sort_values("t", ascending=False).head(3).iterrows():
        show(row, False)
    for _, row in tr.sort_values("t2", ascending=False).head(3).iterrows():
        show(row, False)
    print(f"Laufzeit {time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()

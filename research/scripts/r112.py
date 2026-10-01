"""Runde 112: 8.640 Varianten ETF-Nachzügler im Minutenbereich -- Vorab: r112_prereg.md."""
from __future__ import annotations

import itertools
import time
from pathlib import Path

import numba
import numpy as np
import pandas as pd

ETFS = ("SPY", "QQQ", "IWM", "DIA", "EFA", "EEM", "TLT", "IEF", "GLD", "SLV", "DBC", "SMH", "VNQ", "XLE", "XLF", "XLK")
OUT = Path(__file__).with_name("r112_results.npz")
PERIODS = {"Training": ("2016-01-01", "2019-12-31"), "Bestätigung": ("2020-01-01", "2022-12-31"),
           "Endtest": ("2023-01-01", "2026-12-31")}
KS = (5, 15, 30)
THS = np.array([2.0, 3.0, 4.0])
HS = np.array([5, 15, 30, 60], dtype=np.int64)


def grids(days):
    C, O = {}, {}
    for s in ETFS:
        x = pd.read_pickle(f"data_cache/{s}_1min.pkl")
        d = pd.DatetimeIndex(x.index.date)
        m = np.asarray(x.index.hour * 60 + x.index.minute - 570)
        di = days.get_indexer(d)
        ok = (di >= 0) & (m >= 0) & (m < 390)
        o = np.full((len(days), 390), np.nan)
        c = np.full((len(days), 390), np.nan)
        o[di[ok], m[ok]] = x["open"].to_numpy()[ok]
        c[di[ok], m[ok]] = x["close"].to_numpy()[ok]
        C[s] = pd.DataFrame(c).T.ffill().T.to_numpy()      # innerhalb des Tages vortragen
        O[s] = o
    return C, O


@numba.njit(parallel=True, cache=True)
def kernel(cA, cB, oB, k, ths, hs):
    D = cA.shape[0]
    d = np.full((D, 390), np.nan)
    v = np.full(D, np.nan)
    for i in range(D):
        acc, acc2, n = 0.0, 0.0, 0
        for t in range(k, 390):
            a0, a1, b0, b1 = cA[i, t - k], cA[i, t], cB[i, t - k], cB[i, t]
            if a0 > 0 and a1 > 0 and b0 > 0 and b1 > 0:
                x = np.log(a1 / a0) - np.log(b1 / b0)
                d[i, t] = x
                acc += x
                acc2 += x * x
                n += 1
        if n >= 30:
            v[i] = acc2 / n - (acc / n) ** 2
    sig = np.full(D, np.nan)
    for i in range(20, D):
        s, n = 0.0, 0
        for j in range(i - 20, i):
            if not np.isnan(v[j]):
                s += v[j]
                n += 1
        if n >= 15:
            sig[i] = np.sqrt(s / n)
    nt, nh = len(ths), len(hs)
    sums = np.zeros((nt * nh, D), dtype=np.float32)
    cnts = np.zeros((nt * nh, D), dtype=np.float32)
    for q in numba.prange(nt * nh):
        th, h = ths[q // nh], hs[q % nh]
        for i in range(D):
            sg = sig[i]
            if not sg > 0:
                continue
            last = np.nan
            for t in range(389, -1, -1):
                if not np.isnan(oB[i, t]):
                    last = cB[i, t]
                    break
            t = 15
            while t <= 330:
                x = d[i, t]
                if np.isnan(x) or abs(x) < th * sg:
                    t += 1
                    continue
                side = 1.0 if x > 0 else -1.0
                e = -1
                for u in range(t + 1, min(t + 3, 390)):
                    if not np.isnan(oB[i, u]):
                        e = u
                        break
                if e < 0:
                    t += 1
                    continue
                entry = oB[i, e]
                ex, xm = last, 389
                for u in range(e + h, 390):
                    if not np.isnan(oB[i, u]):
                        ex, xm = oB[i, u], u
                        break
                pnl = side * (ex / entry - 1.0) * 1e4 - 2.0 * (1.0 + 0.01 / entry * 1e4)
                sums[q, i] += pnl
                cnts[q, i] += 1
                t = xm + 1
    return sums, cnts


def tstat(x):
    return float(x.mean() / x.std(ddof=1) * np.sqrt(len(x))) if len(x) > 2 and x.std() > 0 else float("nan")


def main():
    t0 = time.time()
    spy = pd.read_pickle("data_cache/SPY_1min.pkl")
    days = pd.DatetimeIndex(sorted(set(spy.index.date)))
    C, O = grids(days)
    print(f"Daten bereit ({time.time() - t0:.0f} s), {len(days)} Tage", flush=True)
    names, S, N = [], [], []
    for a, b in itertools.permutations(ETFS, 2):
        for k in KS:
            s, n = kernel(C[a], C[b], O[b], k, THS, HS)
            S.append(s)
            N.append(n)
            for th, h in itertools.product(THS, HS):
                names.append(f"{a} führt {b} k{k} Schwelle {th:.0f} Sigma Halten {h} Min")
        print(f"{a}->{b} ({time.time() - t0:.0f} s)", flush=True)
    S, N = np.concatenate(S), np.concatenate(N)
    np.savez(OUT, sums=S, cnts=N, dates=days.to_numpy(), names=np.array(names))
    dates = days.to_numpy()

    def per(i, nm):
        a, b = PERIODS[nm]
        m = (dates >= np.datetime64(a)) & (dates <= np.datetime64(b)) & (N[i] > 0)
        return S[i][m].astype(float), N[i][m].sum()

    def desc(i, nm):
        x, n = per(i, nm)
        return f"Trades {int(n):5d}  Ø {x.sum() / max(n, 1):+.2f} bp/Trade  t(Tage) {tstat(x):+.2f}"

    rows = []
    for i in range(len(names)):
        x, n = per(i, "Training")
        y, m = per(i, "Bestätigung")
        rows.append(dict(i=i, n=n, avg=x.sum() / max(n, 1), t=tstat(x), conf=y.sum() / max(m, 1), tc=tstat(y)))
    tr = pd.DataFrame(rows)
    print(f"\nTraining: {len(tr)} | t >= 2: {(tr.t >= 2).sum()} | t >= 3: {(tr.t >= 3).sum()} | t >= 4: {(tr.t >= 4).sum()}"
          f" | Ø > 0: {(tr.avg > 0).sum()} | Median {tr.avg.median():+.2f} bp/Trade")
    tr["k"] = [int(nm.split(" k")[1].split()[0]) for nm in names]
    tr["h"] = [int(nm.split("Halten ")[1].split()[0]) for nm in names]
    tr["th"] = [nm.split("Schwelle ")[1].split()[0] for nm in names]
    for col in ("k", "h", "th"):
        g = tr.groupby(col)
        print(f"  {col}: " + ", ".join(f"{a} {b:+.2f}->{c:+.2f}" for a, b, c in
                                       zip(g.groups.keys(), g.avg.median(), g.conf.median())))

    def show(row, count):
        i = int(row.i)
        print(f"\n=== {names[i]}")
        print(f"  Training:    {desc(i, 'Training')}")
        y, m = per(i, "Bestätigung")
        ok = y.sum() > 0 and tstat(y) >= 2.4
        print(f"  Bestätigung: {desc(i, 'Bestätigung')}  -> {'BESTANDEN' if ok else 'nicht bestanden'}")
        if count and ok:
            z, _ = per(i, "Endtest")
            fin = z.sum() > 0 and tstat(z) >= 2
            print(f"  Endtest:     {desc(i, 'Endtest')}  -> {'BESTANDEN' if fin else 'nicht bestanden'}")
        elif count:
            print("  Endtest: nicht angesehen")

    el = tr[(tr.n >= 200) & (tr.avg > 0) & (tr.t >= 4)].sort_values("t", ascending=False).head(3)
    print(f"\n--- Zählende Auswahl (>= 200 Trades, Ø > 0, t >= 4): {len(el)}")
    for _, row in el.iterrows():
        show(row, True)
    if el.empty:
        print("  keine -> RUNDE NICHT BESTANDEN")
    print("\n--- Nur Information: 5 beste Trainings-t ohne Hürde")
    for _, row in tr[(tr.n >= 200) & (tr.avg > 0)].sort_values("t", ascending=False).head(5).iterrows():
        show(row, False)
    pos = tr[(tr.avg > 0) & (tr.n >= 200)]
    print(f"\nFamilie: {len(pos)} im Training positiv (>= 200 Trades); davon Bestätigung positiv {(pos.conf > 0).mean():.0%}")
    print(f"Laufzeit {time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()

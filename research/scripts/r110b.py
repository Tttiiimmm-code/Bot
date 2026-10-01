"""Runde 110b (korrigiert: beide Seiten in einer Stunde = -1R): 1.152 Sitzungs-Range-Konfigurationen (H1, 24 Märkte) -- Vorab: r110_prereg.md."""
from __future__ import annotations

import itertools
import sys
import time
from pathlib import Path

import numba
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from r102 import load  # noqa: E402
from r105 import MARKETS  # noqa: E402

OUT = Path(__file__).with_name("r110b_results.pkl")
PERIODS = {"Training": ("2012-07-01", "2017-12-31"), "Bestätigung": ("2018-01-01", "2021-12-31"),
           "Endtest": ("2022-01-01", "2026-12-31")}
# Stunden ab 19:00 NY (verschoben um +5 h): (Range-Beginn, Range-Ende, Handel bis)
RANGES = (("Asien 19-02", 0, 7, 16), ("Vor-London 00-03", 5, 8, 16), ("London 03-05", 8, 10, 16),
          ("NY 09-10", 14, 15, 19))
EXIT_SH = 21          # 16:00 NY
MODES = ("Ausbruch", "Fehlausbruch")
STOPS = (("Range", 1.0), ("halbe Range", 0.5))
EXITS = (("Ziel 1R", 1.0), ("Ziel 2R", 2.0), ("16:00 NY", 0.0))


@numba.njit(cache=False)
def run(dstart, sh, bo, bh, bl, bc, ao, ah, al, ac, ra, rb, tend, mode, sfrac, tpr):
    nd = len(dstart) - 1
    out = np.full(nd, np.nan)
    for d in range(nd):
        s, e_ = dstart[d], dstart[d + 1]
        rh, rl, cnt = -1e30, 1e30, 0
        for i in range(s, e_):
            if ra <= sh[i] < rb:
                rh, rl, cnt = max(rh, bh[i]), min(rl, bl[i]), cnt + 1
        if cnt < rb - ra or not rh > rl:
            continue
        rs = rh - rl
        e, side, entry = -1, 0, 0.0
        for i in range(s, e_):
            if sh[i] < rb:
                continue
            if sh[i] >= tend:
                break
            up, dn = bh[i] > rh, bl[i] < rl
            if up and dn:
                e = -2
                break
            spr = ao[i] - bo[i]
            if up:
                e = i
                if mode == 0:
                    side, entry = 1, max(ao[i], rh + spr)
                else:
                    side, entry = -1, max(bo[i], rh)
                break
            if dn:
                e = i
                if mode == 0:
                    side, entry = -1, min(bo[i], rl)
                else:
                    side, entry = 1, min(ao[i], rl + spr)
                break
        if e == -2:
            out[d] = -1.0
            continue
        if e < 0:
            continue
        sd = sfrac * rs
        stop = entry - side * sd
        use_tp = tpr > 0
        tp = entry + side * tpr * sd
        ex = bc[e_ - 1] if side > 0 else ac[e_ - 1]
        for i in range(e, e_):
            if i > e and sh[i] >= EXIT_SH:
                ex = bo[i] if side > 0 else ao[i]
                break
            if side > 0:
                if i > e and (bo[i] <= stop or (use_tp and bo[i] >= tp)):
                    ex = bo[i]
                    break
                if bl[i] <= stop:
                    ex = stop
                    break
                if i > e and use_tp and bh[i] >= tp:
                    ex = tp
                    break
            else:
                if i > e and (ao[i] >= stop or (use_tp and ao[i] <= tp)):
                    ex = ao[i]
                    break
                if ah[i] >= stop:
                    ex = stop
                    break
                if i > e and use_tp and al[i] <= tp:
                    ex = tp
                    break
        out[d] = side * (ex - entry) / sd - 0.5e-4 * entry / sd
    return out


def tstat(r):
    return float(r.mean() / r.std(ddof=1) * np.sqrt(len(r))) if len(r) > 2 and r.std() > 0 else float("nan")


def describe(r):
    if len(r) < 3:
        return f"n {len(r)}"
    w, l_ = r[r > 0].sum(), -r[r < 0].sum()
    return (f"n {len(r):5d}  Ø R {r.mean():+.3f}  t {tstat(r):+.2f}  Treffer {(r > 0).mean():.0%}  "
            f"PF {w / l_ if l_ > 0 else float('inf'):.2f}  Summe {r.sum():+.0f} R")


def main():
    t0 = time.time()
    results = []
    for sym in MARKETS:
        bid, ask = load(sym)
        ny = bid.index.tz_convert("America/New_York")
        shifted = ny + pd.Timedelta(hours=5)
        sh = np.asarray(shifted.hour, dtype=np.int64)
        day = np.asarray((shifted.tz_localize(None).normalize() - pd.Timestamp("2000-01-01")).days)
        dstart = np.concatenate([[0], np.flatnonzero(np.diff(day)) + 1, [len(day)]]).astype(np.int64)
        dlabel = shifted.tz_localize(None).normalize()[dstart[:-1]].to_numpy()
        arrs = [bid[c].to_numpy() for c in ("open", "high", "low", "close")] + \
               [ask[c].to_numpy() for c in ("open", "high", "low", "close")]
        for (rn, ra, rb, te), mi, (sn, sf), (en, tp) in itertools.product(RANGES, range(2), STOPS, EXITS):
            r = run(dstart, sh, *arrs, ra, rb, te, mi, sf, tp)
            m = ~np.isnan(r)
            results.append(dict(key=(sym, rn, MODES[mi], sn, en), t=dlabel[m], r=r[m]))
        print(f"{sym} fertig ({time.time() - t0:.0f} s)", flush=True)
    pd.to_pickle(results, OUT)

    def period(x, nm):
        a, b = PERIODS[nm]
        m = (x["t"] >= np.datetime64(a)) & (x["t"] <= np.datetime64(b))
        return x["r"][m]

    rows = []
    for i, x in enumerate(results):
        a, b = period(x, "Training"), period(x, "Bestätigung")
        sym, rn, mo, sn, en = x["key"]
        rows.append(dict(i=i, n=len(a), avg=a.mean() if len(a) else np.nan, t=tstat(a), conf=b.mean() if len(b) else np.nan,
                         tc=tstat(b), sym=sym, rng=rn, mode=mo, stop=sn, exit=en))
    tr = pd.DataFrame(rows)
    print(f"\nTraining: {len(tr)} | t >= 2: {(tr.t >= 2).sum()} (Zufall ~{0.023 * len(tr):.0f}) | t >= 3: {(tr.t >= 3).sum()}"
          f" | t >= 4: {(tr.t >= 4).sum()} | Ø > 0: {(tr.avg > 0).sum()} | Median {tr.avg.median():+.3f} R")
    for col in ("rng", "mode", "stop", "exit"):
        g = tr.groupby(col)
        print(f"  {col}: " + ", ".join(f"{k} {a:+.3f}->{b:+.3f}" for k, a, b in
                                       zip(g.groups.keys(), g.avg.median(), g.conf.median())))
    g = tr.groupby("sym")
    print("  je Markt (Median Training -> Bestätigung): " + ", ".join(
        f"{k} {a:+.2f}->{b:+.2f}" for k, a, b in zip(g.groups.keys(), g.avg.median(), g.conf.median())))

    def show(row, count):
        x = results[int(row.i)]
        print(f"\n=== {' '.join(x['key'])}")
        print(f"  Training:    {describe(period(x, 'Training'))}")
        r = period(x, "Bestätigung")
        ok = len(r) > 2 and r.mean() > 0 and tstat(r) >= 2.4
        print(f"  Bestätigung: {describe(r)}  -> {'BESTANDEN' if ok else 'nicht bestanden'}")
        if count and ok:
            r = period(x, "Endtest")
            fin = len(r) > 2 and r.mean() > 0 and tstat(r) >= 2
            print(f"  Endtest:     {describe(r)}  -> {'BESTANDEN' if fin else 'nicht bestanden'}")
        elif count:
            print("  Endtest: nicht angesehen")

    el = tr[(tr.n >= 200) & (tr.avg > 0) & (tr.t >= 4)].sort_values("t", ascending=False).head(3)
    print(f"\n--- Zählende Auswahl (n >= 200, Ø > 0, t >= 4): {len(el)}")
    for _, row in el.iterrows():
        show(row, True)
    if el.empty:
        print("  keine -> RUNDE NICHT BESTANDEN")
    print("\n--- Nur Information: 3 beste Trainings-t ohne Hürde")
    for _, row in tr[(tr.n >= 200) & (tr.avg > 0)].sort_values("t", ascending=False).head(3).iterrows():
        show(row, False)
    pos = tr[tr.avg > 0]
    print(f"\nFamilie: {len(pos)} im Training positiv; davon Bestätigung positiv {(pos.conf > 0).mean():.0%}; "
          f"alle: Median Bestätigung {tr.conf.median():+.3f}")
    print(f"Laufzeit {time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()

"""Runde 108: ~2.900 Intraday-Setups auf "Stocks in Play" -- Vorab: r108_prereg.md (Daten-Cache aus Runde 107)."""
from __future__ import annotations

import itertools
import sys
import time
from pathlib import Path

import numba
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from r107 import CACHE, PERIODS, stats  # noqa: E402

OUT = Path(__file__).with_name("r108_results.pkl")
EXIT_NAMES = ("Ziel 1R", "Ziel 2R", "Tagesschluss", "Einstand+Schluss", "Lückenschluss")


@numba.njit(cache=True)
def do_exit(o, h, l, c, e, end, side, entry, stop, mode, tp):
    """mode 0: Ziel tp, 2: Tagesschluss, 3: Einstand ab +1R, sonst Tagesschluss."""
    sd = (entry - stop) * side
    use_tp = mode == 0
    ex = c[end - 1]
    for j in range(e, end):
        if side > 0:
            if j > e:
                if o[j] <= stop or (use_tp and o[j] >= tp):
                    return o[j]
            if l[j] <= stop:
                return stop
            if j > e and use_tp and h[j] >= tp:
                return tp
            if mode == 3 and h[j] >= entry + sd and stop < entry:
                stop = entry
        else:
            if j > e:
                if o[j] >= stop or (use_tp and o[j] <= tp):
                    return o[j]
            if h[j] >= stop:
                return stop
            if j > e and use_tp and l[j] <= tp:
                return tp
            if mode == 3 and l[j] <= entry - sd and stop > entry:
                stop = entry
    return ex


@numba.njit(parallel=True, cache=True)
def sim(o, h, l, c, v, mi, start, n, rank, atr, gap, setup, p1, p2, p3, dirm, sfrac, emode, topn, cutoff):
    nd = len(start)
    out = np.full(nd, np.nan)
    for d in numba.prange(nd):
        if rank[d] >= topn:
            continue
        s, L = start[d], n[d]
        end = s + L
        A = atr[d]
        if mi[s] != 0 or not (A > 0) or L < 2:
            continue
        e, side, entry, stop, special = -1, 0, 0.0, 0.0, np.nan
        if setup == 1 or setup == 2:
            g = gap[d]
            if g <= -0.99 or abs(g) < p1:
                continue
            gs = 1 if g > 0 else -1
            if (dirm == 1 and g < 0) or (dirm == 2 and g > 0):
                continue
            side = -gs if setup == 1 else gs
            j = s
            while j < end and mi[j] < p2:
                j += 1
            if j >= end or mi[j] > p2 + 2:
                continue
            e, entry = j, o[j]
            special = o[s] / (1.0 + g)
        elif setup == 3:
            cpv, cv = 0.0, 0.0
            for j in range(s, end):
                if mi[j] > cutoff:
                    break
                if mi[j] >= p1 and j > s and cv > 0:
                    vw = cpv / cv
                    up = c[j - 1] - o[s] >= p2 * A and c[j - 1] > vw
                    dn = dirm == 0 and o[s] - c[j - 1] >= p2 * A and c[j - 1] < vw
                    if up and l[j] <= vw:
                        e, side, entry = j, 1, min(o[j], vw)
                        break
                    if dn and h[j] >= vw:
                        e, side, entry = j, -1, max(o[j], vw)
                        break
                cpv += (h[j] + l[j] + c[j]) / 3.0 * v[j]
                cv += v[j]
        elif setup == 4:
            orh, orl, dhi, dlo = -1e30, 1e30, -1e30, 1e30
            k = s
            while k < end and mi[k] < p1:
                orh, orl = max(orh, h[k]), min(orl, l[k])
                k += 1
            dhi, dlo = orh, orl
            bkh, bkl = -1, -1
            for j in range(k, end - 1):
                if mi[j] > cutoff:
                    break
                if h[j] > orh and bkh == -1:
                    bkh = mi[j]
                if dirm == 0 and l[j] < orl and bkl == -1:
                    bkl = mi[j]
                dhi, dlo = max(dhi, h[j]), min(dlo, l[j])
                if bkh >= 0 and mi[j] - bkh <= p2 and c[j] < orh:
                    e, side, entry = j + 1, -1, o[j + 1]
                    if sfrac == 0:
                        stop = dhi
                    break
                if bkl >= 0 and mi[j] - bkl <= p2 and c[j] > orl:
                    e, side, entry = j + 1, 1, o[j + 1]
                    if sfrac == 0:
                        stop = dlo
                    break
                if bkh >= 0 and mi[j] - bkh > p2:
                    bkh = -2
                if bkl >= 0 and mi[j] - bkl > p2:
                    bkl = -2
        elif setup == 5:
            j = s + 1
            while j < end and mi[j] < p1:
                j += 1
            if j >= end or mi[j] > p1 + 5:
                continue
            mv = (c[j - 1] - o[s]) / A
            if abs(mv) < p2:
                continue
            sg = 1 if mv > 0 else -1
            side = sg if p3 == 0 else -sg
            e, entry = j, o[j]
        else:
            cpv, cv = 0.0, 0.0
            dhi, dlo = -1e30, 1e30
            for j in range(s, end):
                if mi[j] > cutoff:
                    break
                if mi[j] >= p1 and j > s and cv > 0:
                    vw = cpv / cv
                    okl = p3 == 0 or c[j - 1] > vw
                    oks = p3 == 0 or c[j - 1] < vw
                    if h[j] > dhi and okl:
                        e, side, entry = j, 1, max(o[j], dhi)
                        break
                    if dirm == 0 and l[j] < dlo and oks:
                        e, side, entry = j, -1, min(o[j], dlo)
                        break
                dhi, dlo = max(dhi, h[j]), min(dlo, l[j])
                cpv += (h[j] + l[j] + c[j]) / 3.0 * v[j]
                cv += v[j]
        if e < 0 or e >= end:
            continue
        if not (setup == 4 and sfrac == 0):
            stop = entry - side * sfrac * A
        sd = (entry - stop) * side
        if not sd > 0:
            continue
        if emode == 4:
            tp = special
            if not side * (tp - entry) > 0:
                continue
            mode = 0
        elif emode <= 1:
            tp = entry + side * (emode + 1) * sd
            mode = 0
        else:
            tp = 0.0
            mode = emode
        ex = do_exit(o, h, l, c, e, end, side, entry, stop, mode, tp)
        out[d] = side * (ex - entry) / sd - 2.0 * (0.0001 * entry + 0.01) / sd
    return out


def build_grid():
    g = []
    for gp, x, dm, sf, em, tn in itertools.product((0.02, 0.04, 0.08), (0, 5, 15), (0, 1, 2), (0.25, 0.5, 1.0),
                                                   range(5), (5, 20)):
        dn = ("beide", "nur Aufwärtslücke", "nur Abwärtslücke")[dm]
        g.append(dict(setup=1, p1=gp, p2=x, p3=0, dirm=dm, sfrac=sf, emode=em, topn=tn, cutoff=330,
                      name=f"S1 Lücke ausblenden >= {gp:.0%} ab Min {x} {dn} Stop {sf} ATR {EXIT_NAMES[em]} Top{tn}"))
    for gp, x, dm, sf, em, tn in itertools.product((0.02, 0.04, 0.08), (0, 5, 15), (0, 1, 2), (0.25, 0.5, 1.0),
                                                   range(4), (5, 20)):
        dn = ("beide", "nur Aufwärtslücke", "nur Abwärtslücke")[dm]
        g.append(dict(setup=2, p1=gp, p2=x, p3=0, dirm=dm, sfrac=sf, emode=em, topn=tn, cutoff=330,
                      name=f"S2 Lücke mitgehen >= {gp:.0%} ab Min {x} {dn} Stop {sf} ATR {EXIT_NAMES[em]} Top{tn}"))
    for t0, k, sf, em, cut, dm, tn in itertools.product((30, 60), (0.25, 0.5, 1.0), (0.25, 0.5, 1.0), range(4),
                                                        (150, 330), (0, 1), (5, 20)):
        g.append(dict(setup=3, p1=t0, p2=k, p3=0, dirm=dm, sfrac=sf, emode=em, topn=tn, cutoff=cut,
                      name=f"S3 VWAP-Rücksetzer ab Min {t0} Trend {k} ATR {'beide' if dm == 0 else 'nur long'} "
                           f"Stop {sf} ATR {EXIT_NAMES[em]} bis {'12:00' if cut == 150 else '15:00'} Top{tn}"))
    for orl, w, sf, em, dm, tn in itertools.product((5, 15, 30), (5, 15, 30), (0.0, 0.25, 0.5), range(4), (0, 1),
                                                    (5, 20)):
        g.append(dict(setup=4, p1=orl, p2=w, p3=0, dirm=dm, sfrac=sf, emode=em, topn=tn, cutoff=330,
                      name=f"S4 Fehlausbruch OR{orl} binnen {w} Min {'beide' if dm == 0 else 'nur Hoch'} "
                           f"Stop {'Tagesextrem' if sf == 0 else f'{sf} ATR'} {EXIT_NAMES[em]} Top{tn}"))
    for t, m, wa, sf, em, tn in itertools.product((270, 330, 360), (0.25, 0.5, 1.0), (0, 1), (0.25, 0.5, 1.0), (2, 3),
                                                  (5, 20)):
        g.append(dict(setup=5, p1=t, p2=m, p3=wa, dirm=0, sfrac=sf, emode=em, topn=tn, cutoff=390,
                      name=f"S5 Nachmittag {9 + (30 + t) // 60}:{(30 + t) % 60:02d} Bewegung >= {m} ATR "
                           f"{'mit' if wa == 0 else 'gegen'} Stop {sf} ATR {EXIT_NAMES[em]} Top{tn}"))
    for t, ft, sf, em, dm, tn in itertools.product((60, 120), (0, 1), (0.25, 0.5, 1.0), range(4), (0, 1), (5, 20)):
        g.append(dict(setup=6, p1=t, p2=0.0, p3=ft, dirm=dm, sfrac=sf, emode=em, topn=tn, cutoff=330,
                      name=f"S6 neues Tageshoch ab Min {t} {'VWAP-Filter' if ft else 'ohne Filter'} "
                           f"{'beide' if dm == 0 else 'nur long'} Stop {sf} ATR {EXIT_NAMES[em]} Top{tn}"))
    return g


def main():
    t0 = time.time()
    z = np.load(CACHE)
    arrs = [z[k] for k in ("o", "h", "l", "c", "v", "mi", "start", "n", "rank", "atr", "gap")]
    dates = z["date"]
    grid = build_grid()
    print(f"{len(grid)} Konfigurationen", flush=True)
    results = []
    for gi, cfg in enumerate(grid):
        r = sim(*arrs, cfg["setup"], float(cfg["p1"]), float(cfg["p2"]), cfg["p3"], cfg["dirm"], float(cfg["sfrac"]),
                cfg["emode"], cfg["topn"], cfg["cutoff"])
        results.append(dict(cfg=cfg, r=r.astype(np.float32)))
        if gi % 500 == 0:
            print(f"{gi}/{len(grid)} ({time.time() - t0:.0f} s)", flush=True)
    pd.to_pickle(dict(dates=dates, results=results), OUT)

    rows = []
    for i, x in enumerate(results):
        r = x["r"].astype(float)
        a = stats(r, dates, *PERIODS["Training"])
        b = stats(r, dates, *PERIODS["Bestätigung"])
        rows.append(dict(i=i, setup=f"S{x['cfg']['setup']}", n=a["n"], avg=a["avg"], t=a["t"], conf=b["avg"],
                         tc=b["t"]))
    tr = pd.DataFrame(rows)
    print(f"\nTraining 2016-2019: {len(tr)} Konfigurationen | t >= 2: {(tr.t >= 2).sum()} | t >= 3: {(tr.t >= 3).sum()} "
          f"| t >= 4: {(tr.t >= 4).sum()} | Ø R > 0: {(tr.avg > 0).sum()} | Median Ø R {tr.avg.median():+.3f}")
    print("Je Setup (Median Ø R Training -> Bestätigung, Anteil positiv in Bestätigung, max t Training):")
    for sname, gdf in tr.groupby("setup"):
        print(f"  {sname}: {gdf.avg.median():+.3f} -> {gdf.conf.median():+.3f}, {(gdf.conf > 0).mean():.0%} positiv, "
              f"max t {gdf.t.max():.2f}, n Konfig {len(gdf)}")

    def show(row, count):
        x = results[int(row.i)]
        r = x["r"].astype(float)
        print(f"\n=== {x['cfg']['name']}")
        print(f"  Training:    {stats(r, dates, *PERIODS['Training'])['desc']}")
        s = stats(r, dates, *PERIODS["Bestätigung"])
        ok = s["n"] > 2 and s["avg"] > 0 and s["t"] >= 2.4
        print(f"  Bestätigung: {s['desc']}  -> {'BESTANDEN' if ok else 'nicht bestanden'}")
        if count and ok:
            s = stats(r, dates, *PERIODS["Endtest"])
            fin = s["n"] > 2 and s["avg"] > 0 and s["t"] >= 2
            print(f"  Endtest:     {s['desc']}  -> {'BESTANDEN' if fin else 'nicht bestanden'}")
        elif count:
            print("  Endtest: nicht angesehen")

    el = tr[(tr.n >= 200) & (tr.avg > 0) & (tr.t >= 4)].sort_values("t", ascending=False).head(3)
    print(f"\n--- Zählende Auswahl (n >= 200, Ø R > 0, t >= 4): {len(el)} Konfiguration(en)")
    for _, row in el.iterrows():
        show(row, True)
    if el.empty:
        print("  keine -> RUNDE NICHT BESTANDEN")
    print("\n--- Nur zur Information: 5 beste Trainings-t ohne t-4-Hürde (Endtest wird nicht angesehen)")
    for _, row in tr[(tr.n >= 200) & (tr.avg > 0)].sort_values("t", ascending=False).head(5).iterrows():
        show(row, False)
    both = tr[(tr.n >= 200) & (tr.t >= 2) & (tr.tc >= 2)]
    print(f"\nInformation: {len(both)} Konfigurationen mit t >= 2 in Training UND Bestätigung")
    for _, row in both.sort_values("tc", ascending=False).head(8).iterrows():
        print(f"  {results[int(row.i)]['cfg']['name']}: t {row.t:.2f} / {row.tc:.2f}, Ø {row.avg:+.3f} / {row.conf:+.3f}")
    print(f"\nLaufzeit {time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()

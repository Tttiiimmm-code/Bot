"""Runden 119 (Intraday-Momentum, 768) und 120 (Makro-Termine, 1.152) auf 16 ETFs -- Vorab: r119_prereg.md."""
from __future__ import annotations

import itertools
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from r112 import ETFS, grids  # noqa: E402

OUT = Path(__file__).with_name("r119_results.pkl")
PERIODS = {"Training": ("2016-01-01", "2019-12-31"), "Bestätigung": ("2020-01-01", "2022-12-31"),
           "Endtest": ("2023-01-01", "2026-12-31")}
HOLD_NAMES = {330: "15:00-16:00", 360: "15:30-16:00"}


def tstat(x):
    return float(x.mean() / x.std(ddof=1) * np.sqrt(len(x))) if len(x) > 2 and x.std() > 0 else float("nan")


def main():
    t0 = time.time()
    spy = pd.read_pickle("data_cache/SPY_1min.pkl")
    days = pd.DatetimeIndex(sorted(set(spy.index.date)))
    D = len(days)
    Cg, Og = grids(days)
    print(f"Daten ({time.time() - t0:.0f} s)", flush=True)
    bls = json.load(open("data_cache/bls_release_dates.json"))
    events = {"FOMC": json.load(open("data_cache/fomc.json")), "CPI": bls["cpi"], "Arbeitsmarkt": bls["empsit"]}
    ev_idx = {k: days.get_indexer(pd.DatetimeIndex(v)) for k, v in events.items()}
    ev_idx = {k: v[v >= 0] for k, v in ev_idx.items()}
    print({k: len(v) for k, v in ev_idx.items()}, flush=True)
    results = []
    for s in ETFS:
        C, O = Cg[s], Og[s]
        real = ~np.isnan(O)
        idx = np.where(real, np.arange(390)[None, :], 390)
        nxt = np.minimum.accumulate(idx[:, ::-1], axis=1)[:, ::-1]
        prev_close = np.concatenate([[np.nan], C[:-1, 389]])

        def seg(start, end):
            """Eröffnung des ersten echten Bars ab start -> Schluss vor end; (Einstieg, Ausstieg) je Tag."""
            k = nxt[:, start]
            ok = k < end
            entry = np.where(ok, O[np.arange(D), np.minimum(k, 389)], np.nan)
            return entry, C[:, end - 1]

        open_px = seg(0, 390)[0]
        sigs = {"Vortag->10:00": C[:, 29] / prev_close - 1, "Eröffnung->10:00": C[:, 29] / open_px - 1,
                "Eröffnung->12:00": C[:, 149] / open_px - 1, "Vortag->15:00": C[:, 329] / prev_close - 1}
        for (sn, sig), (hs, he), wa, th in itertools.product(sigs.items(), ((330, 390), (360, 390)), (1, -1),
                                                             (0.0, 0.5, 1.0)):
            ent, ex = seg(hs, he)
            sd = pd.Series(sig).rolling(60, min_periods=40).std().shift(1).to_numpy()
            m = np.isfinite(sig) & np.isfinite(ent) & np.isfinite(ex) & (ent > 0)
            if th > 0:
                m &= np.abs(sig) >= th * sd
            side = np.sign(sig) * wa
            m &= side != 0
            r = side * (ex / ent - 1) * 1e4 - 2 * (1 + 0.01 / ent * 1e4)
            results.append(dict(rnd=119, name=f"{s}: Signal {sn}, Halten {HOLD_NAMES[hs]}, "
                                              f"{'mit' if wa > 0 else 'gegen'} Signal, Schwelle {th} Sigma",
                                feats=dict(etf=s, sig=sn, hold=hs, wa=wa, th=th), r=r[m], d=days[m].to_numpy()))
        segs = {"Eröffnung->Schluss": seg(0, 390), "Eröffnung->12:00": seg(0, 150), "12:00->Schluss": seg(150, 390),
                "Vortag->Schluss": (prev_close, C[:, 389])}
        for (en, ei), off, (gn, (ent, ex)), dr in itertools.product(ev_idx.items(), (-1, 0, 1), segs.items(), (1, -1)):
            di = ei + off
            di = di[(di >= 1) & (di < D)]
            e_, x_ = ent[di], ex[di]
            m = np.isfinite(e_) & np.isfinite(x_) & (e_ > 0)
            r = dr * (x_[m] / e_[m] - 1) * 1e4 - 2 * (1 + 0.01 / e_[m] * 1e4)
            results.append(dict(rnd=120, name=f"{s}: {en} Tag {off:+d}, {gn}, {'long' if dr > 0 else 'short'}",
                                feats=dict(etf=s, event=en, off=off, seg=gn, dir=dr), r=r, d=days[di][m].to_numpy()))
        print(f"{s} ({time.time() - t0:.0f} s)", flush=True)
    pd.to_pickle(results, OUT)

    def per(x, nm):
        a, b = PERIODS[nm]
        m = (x["d"] >= np.datetime64(a)) & (x["d"] <= np.datetime64(b))
        return x["r"][m]

    def desc(r):
        return f"n {len(r):5d}  Ø {r.mean():+.2f} bp  t {tstat(r):+.2f}  Treffer {(r > 0).mean():.0%}" if len(r) > 2 else f"n {len(r)}"

    for rnd, nmin in ((119, 200), (120, 30)):
        rows = []
        for i, x in enumerate(results):
            if x["rnd"] != rnd:
                continue
            a, b = per(x, "Training"), per(x, "Bestätigung")
            rows.append(dict(i=i, n=len(a), avg=a.mean() if len(a) else np.nan, t=tstat(a),
                             conf=b.mean() if len(b) else np.nan, tc=tstat(b), **x["feats"]))
        tr = pd.DataFrame(rows)
        print(f"\n######## Runde {rnd}: {len(tr)} | t >= 2: {(tr.t >= 2).sum()} | t >= 3: {(tr.t >= 3).sum()} | "
              f"t >= 4: {(tr.t >= 4).sum()} | Ø > 0: {(tr.avg > 0).sum()} | Median {tr.avg.median():+.2f} bp")
        for c_ in [c for c in tr.columns if c not in ("i", "n", "avg", "t", "conf", "tc", "etf")]:
            g = tr.groupby(c_)
            print(f"  {c_}: " + ", ".join(f"{k} {a:+.2f}->{b:+.2f}" for k, a, b in
                                          zip(g.groups.keys(), g.avg.median(), g.conf.median())))
        print(f"  t >= 2 in Training UND Bestätigung (Information): {((tr.t >= 2) & (tr.tc >= 2)).sum()}")
        for _, row in tr[(tr.t >= 2) & (tr.tc >= 2)].sort_values("tc", ascending=False).head(6).iterrows():
            print(f"    {results[int(row.i)]['name']}: {row.avg:+.2f} bp (t {row.t:.2f}) / {row.conf:+.2f} bp (t {row.tc:.2f})")

        def show(row, count):
            x = results[int(row.i)]
            print(f"\n=== {x['name']}")
            print(f"  Training:    {desc(per(x, 'Training'))}")
            b = per(x, "Bestätigung")
            ok = len(b) > 2 and b.mean() > 0 and tstat(b) >= 2.4
            print(f"  Bestätigung: {desc(b)}  -> {'BESTANDEN' if ok else 'nicht bestanden'}")
            if count and ok:
                e_ = per(x, "Endtest")
                fin = len(e_) > 2 and e_.mean() > 0 and tstat(e_) >= 2
                print(f"  Endtest:     {desc(e_)}  -> {'BESTANDEN' if fin else 'nicht bestanden'}")
            elif count:
                print("  Endtest: nicht angesehen")

        el = tr[(tr.n >= nmin) & (tr.avg > 0) & (tr.t >= 4)].sort_values("t", ascending=False).head(3)
        print(f"\n--- Zählende Auswahl (n >= {nmin}, Ø > 0, t >= 4): {len(el)}")
        for _, row in el.iterrows():
            show(row, True)
        if el.empty:
            print("  keine -> RUNDE NICHT BESTANDEN")
        print("\n--- Nur Information: 3 beste Trainings-t")
        for _, row in tr[(tr.n >= nmin) & (tr.avg > 0)].sort_values("t", ascending=False).head(3).iterrows():
            show(row, False)
    print(f"Laufzeit {time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()

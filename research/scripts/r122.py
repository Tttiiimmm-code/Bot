"""Runde 122: 1.248 Kalender-Varianten in 24 Märkten (D1 aus Dukascopy-H1 Bid/Ask) -- Vorab: r121_prereg.md."""
from __future__ import annotations

import itertools
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from r102 import load, resample  # noqa: E402
from r105 import MARKETS  # noqa: E402

OUT = Path(__file__).with_name("r122_results.pkl")
PERIODS = {"Training": ("2012-07-01", "2017-12-31"), "Bestätigung": ("2018-01-01", "2021-12-31"),
           "Endtest": ("2022-01-01", "2026-12-31")}
TOM = ((1, 3), (2, 2), (3, 1), (1, 1), (4, 4), (0, 3))


def tstat(x):
    return float(x.mean() / x.std(ddof=1) * np.sqrt(len(x))) if len(x) > 2 and x.std() > 0 else float("nan")


def nyse_holidays():
    g = pd.read_pickle("data_cache/yahoo_long/^GSPC.pkl").index
    w = pd.DatetimeIndex(np.load(Path(__file__).with_name("r114_wide.npz"), allow_pickle=True)["dates"])
    open_days = set(pd.DatetimeIndex(g).normalize()) | set(w.normalize())
    wk = pd.bdate_range("2012-01-01", "2026-09-30")
    return set(d for d in wk if d not in open_days)


def main():
    t0 = time.time()
    hol = nyse_holidays()
    print(f"{len(hol)} US-Börsenfeiertage", flush=True)
    results = []
    for sym in MARKETS:
        bid, ask = load(sym)
        b, a = resample(bid, "1D"), resample(ask, "1D")
        idx = b.index.intersection(a.index)
        b, a = b.loc[idx], a.loc[idx]
        day = pd.DatetimeIndex(b.index.tz_convert("Europe/Athens").tz_localize(None).normalize())
        keep = day.weekday < 5
        b, a, day = b[keep], a[keep], day[keep]
        bc, ac = b["close"].to_numpy(), a["close"].to_numpy()
        n = len(day)
        per_m = day.to_period("M")
        first = np.r_[True, per_m[1:] != per_m[:-1]]
        pos_in = pd.Series(1, index=range(n)).groupby(per_m.asi8).cumsum().to_numpy()      # 1.. im Monat
        cnt_m = pd.Series(1, index=range(n)).groupby(per_m.asi8).transform("sum").to_numpy()
        from_end = cnt_m - pos_in + 1                                                         # 1 = letzter Tag

        def trade(i0, i1, side):
            """Einstieg Schluss i0, Ausstieg Schluss i1 (Indizes), in bp."""
            if side > 0:
                return (bc[i1] / ac[i0] - 1) * 1e4 - 0.5
            return (bc[i0] / ac[i1] - 1) * 1e4 - 0.5

        windows = {}
        for w in range(5):
            name = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag"][w]
            windows[name] = [(i - 1, i) for i in range(1, n) if day[i].weekday() == w]
        me = np.flatnonzero(from_end == 1)
        for m in range(1, 13):
            windows[f"Monat {m:02d}"] = [(me[k - 1], me[k]) for k in range(1, len(me)) if day[me[k]].month == m]
        fs = np.flatnonzero(first)
        for k_, j_ in TOM:
            ws = []
            for f in fs:
                i0, i1 = f - k_ - 1, f + j_ - 1
                if i0 >= 0 and i1 < n and i1 > i0:
                    ws.append((i0, i1))
            windows[f"Monatswechsel {k_}/{j_}"] = ws
        windows["Monatsmitte 10-15"] = [(f + 8, f + 14) for f in fs if f + 14 < n and pos_in[f + 14] == 15]
        hol_s = set(hol)
        pre, post = [], []
        for i in range(1, n - 1):
            nxt = day[i] + pd.Timedelta(days=1)
            while nxt.weekday() >= 5:
                nxt += pd.Timedelta(days=1)
            if nxt in hol_s:
                pre.append((i - 1, i))
            prv = day[i] - pd.Timedelta(days=1)
            while prv.weekday() >= 5:
                prv -= pd.Timedelta(days=1)
            if prv in hol_s:
                post.append((i - 1, i))
        windows["vor US-Feiertag"], windows["nach US-Feiertag"] = pre, post
        assert len(windows) == 26
        for (wn, ws), side in itertools.product(windows.items(), (1, -1)):
            if not ws:
                continue
            r = np.array([trade(i0, i1, side) for i0, i1 in ws])
            d = day[[i1 for _, i1 in ws]].to_numpy()
            ok = np.isfinite(r)
            results.append(dict(name=f"{sym} {wn} {'long' if side > 0 else 'short'}",
                                feats=dict(sym=sym, rule=wn, side=side), r=r[ok], d=d[ok]))
        print(f"{sym} ({time.time() - t0:.0f} s)", flush=True)
    pd.to_pickle(results, OUT)

    def per(x, nm):
        a, b = PERIODS[nm]
        m = (x["d"] >= np.datetime64(a)) & (x["d"] <= np.datetime64(b))
        return x["r"][m]

    def desc(r):
        return f"n {len(r):4d}  Ø {r.mean():+.1f} bp  t {tstat(r):+.2f}  Treffer {(r > 0).mean():.0%}" if len(r) > 2 else f"n {len(r)}"

    rows = []
    for i, x in enumerate(results):
        a, b = per(x, "Training"), per(x, "Bestätigung")
        rows.append(dict(i=i, n=len(a), avg=a.mean() if len(a) else np.nan, t=tstat(a), conf=b.mean() if len(b) else np.nan,
                         tc=tstat(b), **x["feats"]))
    tr = pd.DataFrame(rows)
    print(f"\nTraining: {len(tr)} | t >= 2: {(tr.t >= 2).sum()} (Zufall ~{0.023 * len(tr):.0f}) | t >= 3: {(tr.t >= 3).sum()}"
          f" | t >= 4: {(tr.t >= 4).sum()} | Ø > 0: {(tr.avg > 0).sum()}")
    print(f"  t >= 2 in Training UND Bestätigung: {((tr.t >= 2) & (tr.tc >= 2)).sum()}")
    for _, row in tr[(tr.t >= 2) & (tr.tc >= 2)].sort_values("tc", ascending=False).head(10).iterrows():
        print(f"    {results[int(row.i)]['name']}: {row.avg:+.1f} bp (t {row.t:.2f}, n {row.n}) / {row.conf:+.1f} bp (t {row.tc:.2f})")

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

    el = tr[(tr.n >= 30) & (tr.avg > 0) & (tr.t >= 4)].sort_values("t", ascending=False).head(3)
    print(f"\n--- Zählende Auswahl (n >= 30, Ø > 0, t >= 4): {len(el)}")
    for _, row in el.iterrows():
        show(row, True)
    if el.empty:
        print("  keine -> RUNDE NICHT BESTANDEN")
    print("\n--- Nur Information: 3 beste Trainings-t")
    for _, row in tr[(tr.n >= 30) & (tr.avg > 0)].sort_values("t", ascending=False).head(3).iterrows():
        show(row, False)
    print(f"Laufzeit {time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()

"""Runde 106: 1.728 Tageszeit-Konfigurationen (24 Märkte x 24 Stunden x 3 Haltedauern) -- Vorab: r106_prereg.md."""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from r102 import load  # noqa: E402
from r105 import MARKETS  # noqa: E402

OUT = Path(__file__).with_name("r106_results.pkl")
PERIODS = {"Training": ("2012-07-01", "2017-12-31"), "Bestätigung": ("2018-01-01", "2021-12-31"),
           "Endtest": ("2022-01-01", "2026-12-31")}
HOLDS = (1, 2, 4)


def tstat(r):
    return float(r.mean() / r.std(ddof=1) * np.sqrt(len(r))) if len(r) > 2 and r.std() > 0 else float("nan")


def describe(r):
    if len(r) < 3:
        return f"n {len(r)}"
    return f"n {len(r):5d}  Ø {r.mean():+.2f} bp  t {tstat(r):+.2f}  Treffer {(r > 0).mean():.0%}  Summe {r.sum():+.0f} bp"


def main():
    t0 = time.time()
    results = []
    for sym in MARKETS:
        bid, ask = load(sym)
        idx = bid.index
        bo, ao = bid["open"], ask["open"]
        mid = (bo + ao) / 2
        hour = idx.tz_convert("America/New_York").hour
        tnaive = idx.tz_convert(None).to_numpy()
        for k in HOLDS:
            later = idx + pd.Timedelta(hours=k)
            bo_x, ao_x = bo.reindex(later).to_numpy(), ao.reindex(later).to_numpy()
            mid_x = (bo_x + ao_x) / 2
            m0 = mid.to_numpy()
            long_net = (bo_x - ao.to_numpy()) / m0 * 1e4 - 0.5
            short_net = (bo.to_numpy() - ao_x) / m0 * 1e4 - 0.5
            gross = (mid_x - m0) / m0 * 1e4
            ok = ~np.isnan(mid_x)
            for h in range(24):
                m = ok & (hour == h)
                results.append(dict(sym=sym, hour=h, hold=k, t=tnaive[m], long=long_net[m], short=short_net[m],
                                    gross=gross[m]))
        print(f"{sym} fertig ({time.time() - t0:.0f} s)", flush=True)
    pd.to_pickle(results, OUT)

    def period(x, arr, nm):
        a, b = PERIODS[nm]
        m = (x["t"] >= np.datetime64(a)) & (x["t"] <= np.datetime64(b + "T23:59"))
        return arr[m]

    rows = []
    for i, x in enumerate(results):
        tl, ts_ = tstat(period(x, x["long"], "Training")), tstat(period(x, x["short"], "Training"))
        d = "long" if (np.nan_to_num(tl, nan=-99) >= np.nan_to_num(ts_, nan=-99)) else "short"
        r = period(x, x[d], "Training")
        g = period(x, x["gross"], "Training")
        rc = period(x, x[d], "Bestätigung")
        rows.append(dict(i=i, sym=x["sym"], hour=x["hour"], hold=x["hold"], dir=d, n=len(r),
                         avg=r.mean() if len(r) else np.nan, t=tstat(r), gtt=abs(tstat(g)),
                         conf=rc.mean() if len(rc) else np.nan, tc=tstat(rc)))
    tr = pd.DataFrame(rows)
    print(f"\nTraining 2012-07 bis 2017: {len(tr)} Konfigurationen (Richtung im Training gewählt)")
    print(f"  netto: t >= 2: {(tr.t >= 2).sum()} | t >= 3: {(tr.t >= 3).sum()} | t >= 4: {(tr.t >= 4).sum()} | "
          f"Ø > 0: {(tr.avg > 0).sum()} | Median Ø {tr.avg.median():+.2f} bp")
    print(f"  brutto (Mitte zu Mitte, nur Information): |t| >= 2: {(tr.gtt >= 2).sum()} | |t| >= 4: {(tr.gtt >= 4).sum()}"
          f" (Zufall |t| >= 2: ~{0.0455 * len(tr):.0f})")
    print("  Median Ø netto je Haltedauer: " + ", ".join(f"{k}h {v:+.2f}" for k, v in tr.groupby('hold').avg.median().items()))

    def show(row, count):
        x = results[int(row.i)]
        d = row.dir
        print(f"\n=== {x['sym']} {x['hour']:02d}:00 New York, {x['hold']} h, {d}")
        print(f"  Training:    {describe(period(x, x[d], 'Training'))}   brutto Ø {period(x, x['gross'], 'Training').mean():+.2f} bp")
        r = period(x, x[d], "Bestätigung")
        ok = len(r) > 2 and r.mean() > 0 and tstat(r) >= 2.4
        print(f"  Bestätigung: {describe(r)}  -> {'BESTANDEN' if ok else 'nicht bestanden'}")
        if count and ok:
            r = period(x, x[d], "Endtest")
            fin = len(r) > 2 and r.mean() > 0 and tstat(r) >= 2
            print(f"  Endtest:     {describe(r)}  -> {'BESTANDEN' if fin else 'nicht bestanden'}")
        elif count:
            print("  Endtest: nicht angesehen")

    el = tr[(tr.n >= 200) & (tr.avg > 0) & (tr.t >= 4)].sort_values("t", ascending=False).head(3)
    print(f"\n--- Zählende Auswahl (n >= 200, Ø > 0, t >= 4): {len(el)} Konfiguration(en)")
    for _, row in el.iterrows():
        show(row, True)
    if el.empty:
        print("  keine -> RUNDE NICHT BESTANDEN")
    print("\n--- Nur zur Information: 3 beste Trainings-t ohne t-4-Hürde (Endtest wird nicht angesehen)")
    for _, row in tr[(tr.n >= 200) & (tr.avg > 0)].sort_values("t", ascending=False).head(3).iterrows():
        show(row, False)
    pos = tr[tr.avg > 0]
    print(f"\nFamilie: {len(pos)} Konfigurationen netto positiv im Training; davon in der Bestätigung positiv: "
          f"{(pos.conf > 0).mean():.0%}, Median Bestätigung {pos.conf.median():+.2f} bp")
    print(f"\nLaufzeit {time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()

"""Runde 61: Gold -- Asien-Nacht long (GA) und PM-Fixing short (GF). Siehe research/PROTOCOL.md."""
from pathlib import Path

import numpy as np
import pandas as pd

from tradingbot.research import gold

COST = 1e-4
PERIODS = [("Entdeckung 2008-2014", "2008-01-01", "2014-12-31"),
           ("Bestätigung 2015-2025-09", "2015-01-01", "2025-09-19"),
           ("unberührt", "2025-09-22", "2026-09-25")]
THRESH = [2.24, 2.0, None]

m = pd.concat([gold.load_minutes(), gold.load_minutes(Path("data_cache/dukascopy/unseen_xau"), "xau_*.csv")])
m = m[~m.index.duplicated()].sort_index()
px = m["open"]
print("Minuten", len(m), m.index[0], m.index[-1])


def at(ts):
    return gold.price_at(px, ts.tz_convert("UTC"))


days = pd.date_range("2008-01-01", "2026-09-26", freq="D")
ga, gf = {}, {}
for d in days:
    wd = d.weekday()
    # GA: Nacht beginnt So-Do 18:00 NY, endet am Folgetag 08:00 London
    if wd in (6, 0, 1, 2, 3):
        t0 = pd.Timestamp(d.date()).tz_localize("America/New_York") + pd.Timedelta(hours=18)
        nxt = d + pd.Timedelta(days=1)
        t1 = pd.Timestamp(nxt.date()).tz_localize("Europe/London") + pd.Timedelta(hours=8)
        a, b = at(t0), at(t1)
        if a and b:
            ga[nxt.normalize()] = b / a - 1
    if wd < 5:
        base = pd.Timestamp(d.date()).tz_localize("Europe/London")
        a, b = at(base + pd.Timedelta(hours=14, minutes=55)), at(base + pd.Timedelta(hours=15, minutes=10))
        if a and b:
            gf[d.normalize()] = -(b / a - 1)

verdict = {}
for name, gross in (("GA Asien-Nacht long", pd.Series(ga)), ("GF Fixing short", pd.Series(gf))):
    net = gross - 2 * COST
    ok = True
    print(f"\n{name}")
    for (pname, s, e), th in zip(PERIODS, THRESH):
        g, n = gross[s:e], net[s:e]
        t = n.mean() / n.std() * np.sqrt(len(n))
        print(f"  {pname:26s} n {len(n):5d} brutto {g.mean()*1e4:6.2f} bp  netto {n.mean()*1e4:6.2f} bp  t {t:5.2f}  "
              f"Treffer {(n > 0).mean():.3f}")
        ok &= (t >= th) if th else (n.mean() > 0)
    yearly = net.groupby(net.index.year).mean() * 1e4
    print("  netto je Jahr (bp):", " ".join(f"{y}:{v:.1f}" for y, v in yearly.items()))
    verdict[name] = ok
for k, v in verdict.items():
    print(k, "->", "BESTANDEN" if v else "NICHT BESTANDEN")

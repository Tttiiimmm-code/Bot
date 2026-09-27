"""Runde 63: FX-Heimatstunden-Effekt (Breedon & Ranaldo 2013). Siehe research/PROTOCOL.md."""
from pathlib import Path

import numpy as np
import pandas as pd

from tradingbot.research import gold

COMM = 0.25e-4
PERIODS = [("Entdeckung", "2008-01-01", "2016-12-31", 2.24), ("Bestätigung", "2017-01-01", "2025-09-19", 2.0),
           ("unberührt", "2025-09-22", "2026-09-25", None)]


def load(pair):
    bid = pd.concat([gold.load_fx(pair), gold.load_fx(pair, Path("data_cache/dukascopy/unseen_fx"))])
    bid = bid[~bid.index.duplicated()].sort_index()
    ask = gold.load_fx(pair, Path("data_cache/dukascopy/fx_ask"))
    return bid, ask


def at(s, ts):
    return gold.price_at(s, ts.tz_convert("UTC"))


def run(pair):
    bid, ask = load(pair)
    net, g1, g2 = {}, {}, {}
    for d in pd.date_range("2008-01-01", "2026-09-25", freq="B"):
        t_eu = pd.Timestamp(d.date()).tz_localize("Europe/London") + pd.Timedelta(hours=7)
        ny = pd.Timestamp(d.date()).tz_localize("America/New_York")
        t_us, t_cl = ny + pd.Timedelta(hours=8), ny + pd.Timedelta(hours=16)
        b0, b1, b2 = at(bid, t_eu), at(bid, t_us), at(bid, t_cl)
        a1, a2 = at(ask, t_us), at(ask, t_cl)
        if None in (b0, b1, b2, a1) or t_eu >= t_us:
            continue
        # Short zum Bid um 07:00 London, Eindeckung zum Ask 08:00 NY; Long zum Ask 08:00 NY, Verkauf zum Bid 16:00 NY
        leg1 = b0 / a1 - 1
        leg2 = b2 / a1 - 1
        net[d] = leg1 + leg2 - 4 * COMM
        g1[d], g2[d] = -(b1 / b0 - 1), b2 / b1 - 1
    return pd.Series(net), pd.Series(g1), pd.Series(g2)


verdict = {}
for pair in ("eurusd", "gbpusd"):
    net, g1, g2 = run(pair)
    ok = True
    print(pair.upper())
    for name, s, e, th in PERIODS:
        n = net[s:e]
        t = n.mean() / n.std() * np.sqrt(len(n))
        print(f"  {name:12s} n {len(n):5d} netto {n.mean()*1e4:6.2f} bp t {t:5.2f} | brutto Bein1 {g1[s:e].mean()*1e4:5.2f} "
              f"Bein2 {g2[s:e].mean()*1e4:5.2f} bp")
        ok &= (t >= th) if th else (n.mean() > 0)
    print("  netto je Jahr (bp):", " ".join(f"{y}:{v:.1f}" for y, v in (net.groupby(net.index.year).mean() * 1e4).items()))
    verdict[pair] = ok
for k, v in verdict.items():
    print(k, "->", "BESTANDEN" if v else "NICHT BESTANDEN")

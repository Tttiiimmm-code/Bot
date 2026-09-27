"""Runde 72: S&P-500-Vortagesrendite -> Nikkei erste/letzte 30 Minuten."""
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from tradingbot.research import gold

COST = 0.75e-4
CHANGE = date(2024, 11, 5)
m = pd.concat([gold.load_minutes(Path("data_cache/dukascopy/idx"), "jpnidxjpy_*.csv"),
               gold.load_minutes(Path("data_cache/dukascopy/unseen"), "jpnidxjpy_*.csv")])
px = m[~m.index.duplicated()].sort_index()["open"]
spy = pd.read_pickle("data_cache/yahoo_unseen/SPY_full.pkl")["adjclose"].astype(float)
spy.index = pd.to_datetime(spy.index)
sret = spy.pct_change().dropna()


def at(ts):
    return gold.price_at(px, ts.tz_convert("UTC"))


ha, hb = {}, {}
for d in pd.date_range("2013-01-01", "2026-09-25", freq="B"):
    prior = sret[sret.index < d]
    if prior.empty or (d - prior.index[-1]).days > 4:
        continue
    sig = np.sign(prior.iloc[-1])
    if sig == 0:
        continue
    tk = pd.Timestamp(d.date()).tz_localize("Asia/Tokyo")
    o0, o1 = at(tk + pd.Timedelta(hours=8, minutes=45)), at(tk + pd.Timedelta(hours=9, minutes=15))
    h, mi = (15, 45) if d.date() >= CHANGE else (15, 15)
    s = tk + pd.Timedelta(hours=h, minutes=mi)
    c0, c1 = at(s - pd.Timedelta(minutes=30)), at(s)
    if o0 and o1:
        ha[d] = -sig * (o1 / o0 - 1) - 2 * COST
    if c0 and c1:
        hb[d] = sig * (c1 / c0 - 1) - 2 * COST
for name, x in (("HA Früh-Umkehr", pd.Series(ha)), ("HB Spät-Momentum", pd.Series(hb))):
    ok = True
    print(name)
    for p, s, e, th in [("Entdeckung", "2013", "2019", 2.24), ("Bestätigung", "2020", "2025-09-19", 2.0),
                        ("unberührt", "2025-09-22", "2026-09-25", None)]:
        v = x[s:e]
        t = v.mean() / v.std() * np.sqrt(len(v))
        print(f"  {p:12s} n {len(v):4d} netto {v.mean()*1e4:6.2f} bp brutto {(v.mean()+2*COST)*1e4:6.2f} t {t:5.2f}")
        ok &= (t >= th) if th else (v.mean() > 0)
    print("  ->", "BESTANDEN" if ok else "NICHT BESTANDEN")

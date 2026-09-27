"""Runde 66: USD long an US-Feiertagen (07:00 London -> 16:00 New York)."""
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from tradingbot.research import gold

COMM = 0.25e-4


def nth_weekday(y, m, wd, n):
    d = date(y, m, 1)
    d += timedelta(days=(wd - d.weekday()) % 7)
    return d + timedelta(weeks=n - 1)


def last_weekday(y, m, wd):
    d = date(y, m + 1, 1) - timedelta(days=1)
    return d - timedelta(days=(d.weekday() - wd) % 7)


def observed(d):
    return d - timedelta(days=1) if d.weekday() == 5 else d + timedelta(days=1) if d.weekday() == 6 else d


def holidays(y):
    h = {"MLK": nth_weekday(y, 1, 0, 3), "Presidents": nth_weekday(y, 2, 0, 3), "Memorial": last_weekday(y, 5, 0),
         "July4": observed(date(y, 7, 4)), "Labor": nth_weekday(y, 9, 0, 1), "Thanksgiving": nth_weekday(y, 11, 3, 4)}
    if y >= 2022:
        h["Juneteenth"] = observed(date(y, 6, 19))
    return h


spy = set(pd.read_pickle("data_cache/yahoo_unseen/SPY_full.pkl").index)
days = [(d, n) for y in range(2008, 2027) for n, d in holidays(y).items()
        if d <= date(2026, 9, 25) and d not in spy]
print("Feiertage:", len(days))


def at(s, ts):
    return gold.price_at(s, ts.tz_convert("UTC"))


verdict = {}
for pair in ("eurusd", "gbpusd"):
    bid = pd.concat([gold.load_fx(pair), gold.load_fx(pair, Path("data_cache/dukascopy/unseen_fx"))])
    bid = bid[~bid.index.duplicated()].sort_index()
    ask = gold.load_fx(pair, Path("data_cache/dukascopy/fx_ask"))
    res = {}
    for d, n in days:
        t0 = pd.Timestamp(d).tz_localize("Europe/London") + pd.Timedelta(hours=7)
        t1 = pd.Timestamp(d).tz_localize("America/New_York") + pd.Timedelta(hours=16)
        b0, a1, b1 = at(bid, t0), at(ask, t1), at(bid, t1)
        if b0 and a1:
            res[pd.Timestamp(d)] = (b0 / a1 - 1 - 2 * COMM, -(b1 / b0 - 1), n)
    r = pd.DataFrame(res, index=["net", "gross", "name"]).T
    r[["net", "gross"]] = r[["net", "gross"]].astype(float)
    r = r.sort_index()
    ok = True
    print(pair.upper())
    for name, s, e, th in [("Entdeckung", "2008", "2016", 2.24), ("Bestätigung", "2017", "2025-09-19", 2.0),
                           ("unberührt", "2025-09-22", "2026-09-25", None)]:
        v = r.loc[s:e, "net"]
        t = v.mean() / v.std() * np.sqrt(len(v)) if len(v) > 1 else float("nan")
        print(f"  {name:12s} n {len(v):3d} netto {v.mean()*1e4:6.2f} bp brutto {r.loc[s:e,'gross'].mean()*1e4:6.2f} t {t:5.2f} "
              f"Treffer {(v > 0).mean():.2f}")
        ok &= (t >= th) if th else (v.mean() > 0)
    print("  je Feiertag brutto bp:", r.groupby("name")["gross"].agg(lambda x: round(x.mean() * 1e4, 1)).to_dict())
    verdict[pair] = ok
for k, v in verdict.items():
    print(k, "->", "BESTANDEN" if v else "NICHT BESTANDEN")

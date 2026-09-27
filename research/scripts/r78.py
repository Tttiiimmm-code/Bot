"""Runde 78: FOMC-Zyklus, gerade Wochen long SPY."""
import json

import numpy as np
import pandas as pd

fomc = pd.to_datetime(json.load(open("data_cache/fomc.json")))
spy = pd.read_pickle("data_cache/yahoo_unseen/SPY_full.pkl")["adjclose"].astype(float)
spy.index = pd.to_datetime(spy.index)
r = spy.pct_change().dropna()
tb = pd.read_pickle("data_cache/fred/TB3MS.pkl") / 100
tb.index = pd.to_datetime(tb.index)
gap = r.index.to_series().diff().dt.days.fillna(1)
ex = r - tb.reindex(r.index, method="ffill").fillna(0) * gap / 360
days = r.index
pos = {d: i for i, d in enumerate(days)}
meet = [days[days.searchsorted(m)] for m in fomc if m >= days[0] and m <= days[-1]]
mi = np.array([pos[m] for m in meet])
week = pd.Series(np.nan, index=days)
for i, d in enumerate(days):
    last = mi[mi <= i]
    nxt = mi[mi > i]
    if len(nxt) and nxt[0] - i == 1:
        k = -1
    elif len(last):
        k = i - last[-1]
    else:
        continue
    week[d] = (k + 1) // 5
even = week.notna() & (week % 2 == 0)
odd = week.notna() & (week % 2 == 1)
for name, s, e, th in [("Replikation 1994-2016", "1994", "2016", None), ("Bestätigung 2017-2025-09", "2017", "2025-09-19", 2.0),
                       ("unberührt", "2025-09-22", "2026-09-25", 0)]:
    x = ex[s:e]; ev, od = x[even[s:e]], x[odd[s:e]]
    t = (ev.mean() - od.mean()) / np.sqrt(ev.var() / len(ev) + od.var() / len(od))
    strat = (1 + r[s:e].where(even[s:e], 0) - 1e-4 * even[s:e].astype(int).diff().abs().fillna(0)).prod() ** (252 / len(x)) - 1
    hold = (1 + r[s:e]).prod() ** (252 / len(x)) - 1
    print(f"{name:26s} gerade n {len(ev):4d} Ø {ev.mean()*1e4:6.2f} bp | ungerade n {len(od):4d} Ø {od.mean()*1e4:6.2f} bp | "
          f"Diff t {t:5.2f} | Strategie {strat*100:5.1f} % p.a. vs SPY {hold*100:5.1f} %")
print("Ø je Zykluswoche (gesamt, bp):", (ex.groupby(week).mean() * 1e4).round(1).to_dict())

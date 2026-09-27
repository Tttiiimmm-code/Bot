"""Runde 79: Vor-Feiertags-Effekt am Nikkei."""
import numpy as np
import pandas as pd

c = pd.read_pickle("data_cache/yahoo_unseen/^N225_full.pkl")["close"].astype(float)
c.index = pd.to_datetime(c.index) + pd.Timedelta(days=1)  # Yahoo-Cache: JST-Mitternacht als UTC-Datum gespeichert (Tag -1)
r = c.pct_change().dropna()
days = c.index
bdays = pd.bdate_range(days[0], days[-1])
missing = set(bdays.difference(days))
pre = pd.Series(False, index=r.index)
for i, d in enumerate(days[:-1]):
    nxt_b = d + pd.offsets.BDay(1)
    if nxt_b in missing and d in pre.index:
        pre[d] = True
for name, s, e, th in [("Entdeckung 1993-2008", "1993", "2008", 2.0), ("Bestätigung 2009-2025-09", "2009", "2025-09-19", 2.0),
                       ("unberührt", "2025-09-22", "2026-09-24", None)]:
    x = r[s:e]; p = x[pre[s:e]] - 2e-4; o = x[~pre[s:e]]
    t = (p.mean() - o.mean()) / np.sqrt(p.var() / len(p) + o.var() / len(o))
    print(f"{name:26s} Vor-Feiertag n {len(p):3d} Ø {p.mean()*1e4:6.2f} bp (Treffer {(p>0).mean():.2f}) | übrige Ø {o.mean()*1e4:5.2f} bp | t {t:5.2f}")

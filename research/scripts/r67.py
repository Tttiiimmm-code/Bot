"""Runde 67: Japanischer Monatswechsel (Tage -5..+2) am Nikkei."""
import numpy as np
import pandas as pd

COST_DAY = 0.25e-4
c = pd.read_pickle("data_cache/yahoo_unseen/^N225_full.pkl")["close"].astype(float)
c.index = pd.to_datetime(c.index) + pd.Timedelta(days=1)  # Yahoo-Cache: JST-Mitternacht als UTC-Datum gespeichert (Tag -1)
r = c.pct_change().dropna()
ym = r.index.to_period("M")
pos = pd.Series(0, index=r.index)
for p in ym.unique():
    idx = r.index[ym == p]
    n = len(idx)
    for k, ts in enumerate(idx):
        if k >= n - 5:
            pos[ts] = k - n          # -5..-1
        elif k < 2:
            pos[ts] = k + 1          # +1, +2
tom = pos != 0
ok = True
for name, s, e, th in [("Entdeckung", "1993", "2008", 2.0), ("Bestätigung", "2009", "2025-09-19", 2.0),
                       ("unberührt", "2025-09-22", "2026-09-24", None)]:
    rt, rr = r[s:e][tom[s:e]] - COST_DAY, r[s:e][~tom[s:e]]
    t = (rt.mean() - rr.mean()) / np.sqrt(rt.var() / len(rt) + rr.var() / len(rr))
    diff = rt.mean() - rr.mean()
    strat = (1 + rt).prod() ** (252 / len(r[s:e])) - 1
    hold = (1 + r[s:e]).prod() ** (252 / len(r[s:e])) - 1
    print(f"{name:12s} TOM n {len(rt):4d} Ø {rt.mean()*1e4:6.2f} bp | Rest n {len(rr):4d} Ø {rr.mean()*1e4:6.2f} bp | "
          f"Diff {diff*1e4:6.2f} bp t {t:5.2f} | TOM p.a. {strat*100:5.1f} % Halten {hold*100:5.1f} %")
    ok &= (t >= th) if th else (diff > 0)
print("je Tag Ø bp (gesamt):", (r.groupby(pos).mean() * 1e4).round(1).to_dict())
print("->", "BESTANDEN" if ok else "NICHT BESTANDEN")

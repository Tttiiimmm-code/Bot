"""Runde 83: GDELT-Ton (stock market) -> SPY Folgetag (short) und Umkehr (long d+1..d+5)."""
import json
from pathlib import Path

import numpy as np
import pandas as pd

src = pd.read_csv("data_cache/sffed/chart1.csv")
tone = pd.Series(src.iloc[:, 1].to_numpy(float), index=pd.to_datetime(src.iloc[:, 0], format="%m/%d/%y")).sort_index()
# zweistellige Jahre: pandas legt 00-68 auf 20xx, 69-99 auf 19xx
d = tone.diff()
print("Tage", len(tone), tone.index[0].date(), tone.index[-1].date())
z = (d - d.rolling(250).mean().shift(1)) / d.rolling(250).std().shift(1)
spy = pd.read_pickle("data_cache/yahoo_unseen/SPY_full.pkl")["adjclose"].astype(float)
spy.index = pd.to_datetime(spy.index)
days = spy.index
sig_days = sorted({days[days.searchsorted(t)] for t in z[z <= -1.5].index if days.searchsorted(t) < len(days)})
pos = {d: i for i, d in enumerate(days)}
na, nb = {}, {}
for d in sig_days:
    i = pos[d]
    if i + 5 >= len(days):
        continue
    na[d] = -(spy.iloc[i + 1] / spy.iloc[i] - 1) - 2e-4
    nb[d] = spy.iloc[i + 5] / spy.iloc[i + 1] - 1 - 2e-4
all1 = spy.pct_change().shift(-1).dropna()
all4 = (spy.shift(-5) / spy.shift(-1) - 1).dropna()
for name, x, ctrl in (("NA Folgetag short", pd.Series(na), -all1), ("NB Umkehr long d+1..d+5", pd.Series(nb), all4)):
    ok = True
    print(name)
    for p, a, b, th in [("Entdeckung 1993-2008", "1993", "2008", 2.24), ("Bestätigung 2009-2025-09", "2009", "2025-09-19", 2.0),
                        ("unberührt", "2025-09-22", "2026-08-09", None)]:
        v = x[a:b]
        t = v.mean() / v.std() * np.sqrt(len(v)) if len(v) > 1 else float("nan")
        print(f"  {p:26s} Signale {len(v):3d} Ø {v.mean()*1e4:6.1f} bp t {t:5.2f} Treffer {(v>0).mean():.2f} | "
              f"Kontrolle alle Tage Ø {ctrl[a:b].mean()*1e4:5.1f} bp")
        ok &= (t >= th) if th else (v.mean() > 0)
    print("  ->", "BESTANDEN" if ok else "NICHT BESTANDEN")

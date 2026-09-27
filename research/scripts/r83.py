"""Runde 83: GDELT-Ton (stock market) -> SPY Folgetag (short) und Umkehr (long d+1..d+5)."""
import json
from pathlib import Path

import numpy as np
import pandas as pd

vals = {}
for p in sorted(Path("data_cache/gdelt").glob("tone_*.json")):
    j = json.loads(p.read_text())
    for series in j.get("timeline", []):
        for pt in series.get("data", []):
            vals[pd.Timestamp(pt["date"][:8])] = float(pt["value"])
tone = pd.Series(vals).sort_index()
tone = tone.groupby(tone.index.normalize()).mean()
print("Tontage", len(tone), tone.index[0].date(), tone.index[-1].date())
z = (tone - tone.rolling(60).mean().shift(1)) / tone.rolling(60).std().shift(1)
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
    for p, a, b, th in [("Entdeckung 2017-2021", "2017", "2021", 2.24), ("Bestätigung 2022-2025-09", "2022", "2025-09-19", 2.0),
                        ("unberührt", "2025-09-22", "2026-09-25", None)]:
        v = x[a:b]
        t = v.mean() / v.std() * np.sqrt(len(v)) if len(v) > 1 else float("nan")
        print(f"  {p:26s} Signale {len(v):3d} Ø {v.mean()*1e4:6.1f} bp t {t:5.2f} Treffer {(v>0).mean():.2f} | "
              f"Kontrolle alle Tage Ø {ctrl[a:b].mean()*1e4:5.1f} bp")
        ok &= (t >= th) if th else (v.mean() > 0)
    print("  ->", "BESTANDEN" if ok else "NICHT BESTANDEN")

"""Runde 81: COT-Extreme (Nicht-Kommerzielle) als Umkehrsignal, wöchentlich."""
from pathlib import Path

import numpy as np
import pandas as pd

from tradingbot.research import gold

frames = []
for p in sorted(Path("data_cache/cot").glob("annual_*.txt")):
    d = pd.read_csv(p, usecols=[0, 2, 7, 8, 9], low_memory=False)
    d.columns = ["market", "date", "oi", "nc_long", "nc_short"]
    frames.append(d)
cot = pd.concat(frames)
cot["market"] = cot["market"].str.strip().str.replace("BRITISH POUND STERLING -", "BRITISH POUND -", regex=False)
cot["date"] = pd.to_datetime(cot["date"].astype(str).str.strip())
M = {"EURO FX - CHICAGO MERCANTILE EXCHANGE": ("eurusd", 1, 1e-4), "JAPANESE YEN - CHICAGO MERCANTILE EXCHANGE": ("usdjpy", -1, 1e-4),
     "BRITISH POUND - CHICAGO MERCANTILE EXCHANGE": ("gbpusd", 1, 1e-4), "GOLD - COMMODITY EXCHANGE INC.": ("xau", 1, 2e-4)}
cot = cot[cot["market"].isin(M)].drop_duplicates(["market", "date"])
print(cot.groupby("market")["date"].agg(["count", "min", "max"]))


def prices(key):
    if key == "xau":
        s = pd.concat([gold.load_minutes()["open"], gold.load_minutes(Path("data_cache/dukascopy/unseen_xau"), "xau_*.csv")["open"]])
    else:
        s = pd.concat([gold.load_fx(key), gold.load_fx(key, Path("data_cache/dukascopy/unseen_fx"))])
    return s[~s.index.duplicated()].sort_index()


weekly = {}
for mkt, (key, direction, cost) in M.items():
    c = cot[cot["market"] == mkt].set_index("date").sort_index()
    net = (c["nc_long"] - c["nc_short"]) / c["oi"]
    pct = net.rolling(157).apply(lambda x: (x[:-1] < x[-1]).mean(), raw=True)
    pos_ccy = np.where(pct >= 0.9, -1, np.where(pct <= 0.1, 1, 0))  # Position in der Fremdwährung/Gold
    pos = pd.Series(pos_ccy * direction, index=net.index)       # Position im Kursinstrument
    px = prices(key)
    rows = {}
    prev = 0
    for t, p in pos.items():
        mon = (t + pd.Timedelta(days=6)).normalize() + pd.Timedelta(hours=7)  # Montag nach Freitags-Veröffentlichung
        a = gold.price_at(px, mon.tz_localize("UTC"), 60)
        b = gold.price_at(px, (mon + pd.Timedelta(days=7)).tz_localize("UTC"), 60)
        if a is None or b is None or np.isnan(pct.get(t, np.nan)):
            continue
        rows[mon] = (p * (b / a - 1) - cost * abs(p - prev), p)
        prev = p
    weekly[key] = pd.DataFrame(rows, index=["ret", "pos"]).T
W = pd.concat({k: v["ret"] for k, v in weekly.items()}, axis=1)
A = pd.concat({k: v["pos"].abs() for k, v in weekly.items()}, axis=1)
port = (W.sum(axis=1) / A.sum(axis=1).replace(0, np.nan)).fillna(0)
print("aktive Positionen Ø:", round(A.sum(axis=1).mean(), 2))
for name, s, e, th in [("Entdeckung 2009-2016", "2009", "2016", 2.0), ("Bestätigung 2017-2025-09", "2017", "2025-09-19", 2.0),
                       ("unberührt", "2025-09-22", "2026-09-25", None)]:
    x = port[s:e]; act = A.sum(axis=1)[s:e] > 0
    t = x.mean() / x.std() * np.sqrt(len(x))
    print(f"{name:26s} Wochen {len(x):3d} (aktiv {act.mean()*100:3.0f} %) Ø {x.mean()*1e4:6.2f} bp/Woche "
          f"(~{x.mean()*52*100:5.1f} % p.a.) t {t:5.2f}")
    for k in W:
        y = W[k][s:e].dropna(); yy = y[weekly[k]['pos'][s:e] != 0]
        print(f"    {k}: aktive Wochen {len(yy):3d} Ø {yy.mean()*1e4 if len(yy) else float('nan'):6.1f} bp")

"""Runde 54: tägliche Fixing-Umkehr (Krohn, Mueller & Whelan 2024)."""
import sys
from datetime import date, timedelta
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, "research/scripts")
from gotobi import gotobi_days
from tradingbot.research import gold

PAIRS = {"eurusd": True, "gbpusd": True, "usdjpy": False}  # True: USD ist Kurswährung
COST = 0.00005


def load(pair):
    a = gold.load_fx(pair)
    b = gold.load_fx(pair, Path("data_cache/dukascopy/unseen_fx"))
    s = pd.concat([a, b])
    return s[~s.index.duplicated()].sort_index()


def ts(d, hh, mm, tz):
    return pd.Timestamp(f"{d} {hh:02d}:{mm:02d}", tz=tz)


def usd_ret(s, t0, t1, usd_quote):
    p0, p1 = gold.price_at(s, t0), gold.price_at(s, t1)
    if p0 is None or p1 is None:
        return None
    r = p1 / p0 - 1
    return -r if usd_quote else r


rows = []
data = {p: load(p) for p in PAIRS}
start, end = date(2008, 1, 2), date(2026, 9, 25)
d = start
while d <= end:
    if d.weekday() < 5:
        prev = d - timedelta(days=3 if d.weekday() == 0 else 1)
        for pair, uq in PAIRS.items():
            s = data[pair]
            w = {
                "preT": usd_ret(s, ts(prev, 17, 0, "America/New_York"), ts(d, 9, 55, "Asia/Tokyo"), uq),
                "postT": usd_ret(s, ts(d, 9, 55, "Asia/Tokyo"), ts(d, 8, 0, "Europe/Berlin"), uq),
                "preE": usd_ret(s, ts(d, 8, 0, "Europe/Berlin"), ts(d, 14, 15, "Europe/Berlin"), uq),
                "postL": usd_ret(s, ts(d, 16, 0, "Europe/London"), ts(d, 17, 0, "America/New_York"), uq),
            }
            rows.append({"date": d, "pair": pair, **w})
    d += timedelta(days=1)
df = pd.DataFrame(rows)
df.to_pickle("data_cache/dukascopy/r54_windows.pkl")
G = gotobi_days(2007, 2026)


def family(x, legs, cost):
    # USD long in "pre", short in "post"
    r = 0.0
    for leg, sign in legs:
        r = r + sign * x[leg] - 2 * cost
    return r


fams = {"CB Europa": [("preE", 1), ("postL", -1)], "CC Tokio": [("preT", 1), ("postT", -1)]}
P = {"2008-2018 (Paper-Zeitraum)": (date(2008, 1, 1), date(2018, 12, 31)),
     "2019-2025 (nach Paper)": (date(2019, 1, 1), date(2025, 9, 19)),
     "unberührt": (date(2025, 9, 22), date(2026, 9, 25))}
for fam, legs in fams.items():
    for cost in (COST, 0.0001):
        x = df.dropna(subset=[l for l, _ in legs]).copy()
        x["r"] = family(x, legs, cost)
        port = x.groupby("date")["r"].mean()
        for name, (a, b) in P.items():
            p = port[(port.index >= a) & (port.index <= b)]
            t = p.mean() / p.std() * np.sqrt(len(p))
            print(f"{fam:10s} Kosten {cost*1e4:.1f} bp {name:26s} Tage {len(p):4d} Ø {p.mean()*1e4:6.2f} bp/Tag "
                  f"{p.mean()*252:6.1%} p.a. Sharpe {p.mean()/p.std()*np.sqrt(252):5.2f} t {t:5.2f}")
        if fam.startswith("CC") and cost == COST:
            q = port[[dd not in G for dd in port.index]]
            for name, (a, b) in P.items():
                p = q[(q.index >= a) & (q.index <= b)]
                print(f"   CC ohne Gotobi-Tage {name:26s} Ø {p.mean()*1e4:6.2f} bp t {p.mean()/p.std()*np.sqrt(len(p)):5.2f}")
    # je Fenster brutto (Diagnose)
    for leg, sign in legs:
        for name, (a, b) in P.items():
            v = df[(df["date"] >= a) & (df["date"] <= b)].groupby("date")[leg].mean().dropna() * sign
            print(f"   Fenster {leg:5s} brutto {name:26s} Ø {v.mean()*1e4:6.2f} bp t {v.mean()/v.std()*np.sqrt(len(v)):5.2f}")

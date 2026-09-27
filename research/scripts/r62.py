"""Runde 62: Robustheit Gold-Asien-Nacht (R1 echte Bid/Ask, R2 Nacht minus Tag, R3 9 Zeitvarianten)."""
from pathlib import Path

import numpy as np
import pandas as pd

from tradingbot.research import gold

EXTRA = 0.5e-4
PERIODS = [("Entdeckung", "2008-01-01", "2014-12-31"), ("Bestätigung", "2015-01-01", "2025-09-19"),
           ("unberührt", "2025-09-22", "2026-09-25")]


def series(base, pattern):
    return gold.load_minutes(Path(base), pattern)["open"]


bid = pd.concat([series("data_cache/dukascopy/xau", "xau_*.csv"), series("data_cache/dukascopy/unseen_xau", "xau_*.csv")])
bid = bid[~bid.index.duplicated()].sort_index()
ask = series("data_cache/dukascopy/xau_ask", "xau_*.csv")
print("Bid", len(bid), "Ask", len(ask), ask.index[0], ask.index[-1])


def at(s, ts):
    return gold.price_at(s, ts.tz_convert("UTC"))


def nights(entry_ny: int, exit_ldn: int, real: bool):
    out = {}
    for d in pd.date_range("2008-01-01", "2026-09-26", freq="D"):
        if d.weekday() not in (6, 0, 1, 2, 3):
            continue
        nxt = d + pd.Timedelta(days=1)
        t0 = pd.Timestamp(d.date()).tz_localize("America/New_York") + pd.Timedelta(hours=entry_ny)
        t1 = pd.Timestamp(nxt.date()).tz_localize("Europe/London") + pd.Timedelta(hours=exit_ldn)
        a = at(ask if real else bid, t0)
        b = at(bid, t1)
        if a and b:
            out[nxt.normalize()] = b / a - 1 - (2 * EXTRA if real else 0)
    return pd.Series(out)


def days():
    out = {}
    for d in pd.date_range("2008-01-01", "2026-09-26", freq="D"):
        if d.weekday() >= 5:
            continue
        t0 = pd.Timestamp(d.date()).tz_localize("Europe/London") + pd.Timedelta(hours=8)
        t1 = pd.Timestamp(d.date()).tz_localize("America/New_York") + pd.Timedelta(hours=17)
        a, b = at(bid, t0), at(bid, t1)
        if a and b:
            out[d.normalize()] = b / a - 1
    return pd.Series(out)


def tstat(x):
    return x.mean() / x.std() * np.sqrt(len(x))


def report(name, x, gates):
    ok = True
    print(name)
    for (p, s, e), g in zip(PERIODS, gates):
        v = x[s:e]
        print(f"  {p:12s} n {len(v):5d} Ø {v.mean()*1e4:6.2f} bp t {tstat(v):5.2f}")
        ok &= (tstat(v) >= g) if g else (v.mean() > 0)
    return ok


r1 = nights(18, 8, real=True)
spread = {}
ok1 = report("R1 echte Kosten (Ask->Bid + 0,5 bp/Seite)", r1, [2, 2, None])
gross = nights(18, 8, real=False)
diff = (gross - days()).dropna()
ok2 = report("R2 Nacht minus Tag (brutto)", diff, [2, 2, None])
print("  zum Vergleich Tag allein:", {p: round(days()[s:e].mean() * 1e4, 2) for p, s, e in PERIODS})
ok3 = True
print("R3 Varianten (Bestätigung, netto real):")
for en in (18, 19, 20):
    row = []
    for ex in (7, 8, 9):
        v = nights(en, ex, real=True)["2015-01-01":"2025-09-19"]
        row.append(f"{en}NY->{ex:02d}L {v.mean()*1e4:5.2f}bp t{tstat(v):5.2f}")
        ok3 &= v.mean() > 0
    print("  " + " | ".join(row))
print("R1", ok1, "R2", ok2, "R3", ok3, "->", "BESTANDEN" if ok1 and ok2 and ok3 else "NICHT BESTANDEN")

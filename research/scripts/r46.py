"""Runde 46: Gotobi-Effekt USD/JPY."""
import calendar
from datetime import date, timedelta
from pathlib import Path
import numpy as np, pandas as pd
from tradingbot.research import gold
from tradingbot.research.__main__ import _log_trial
from tradingbot.research.engine import CostModel, BacktestResult


def gotobi_days(y0, y1):
    out = set()
    for y in range(y0, y1 + 1):
        for m in range(1, 13):
            last = calendar.monthrange(y, m)[1]
            for d in (5, 10, 15, 20, 25, last):
                x = date(y, m, d)
                while x.weekday() >= 5:
                    x -= timedelta(days=1)
                out.add(x)
    return out


def run(series):
    s = series.copy()
    s.index = s.index.tz_convert("Asia/Tokyo")
    G = gotobi_days(2007, 2026)
    days = sorted({d for d in s.index.date if d.weekday() < 5})
    rows = {}
    for d in days:
        p0 = gold.price_at(s, pd.Timestamp(f"{d} 05:00", tz="Asia/Tokyo"))
        p1 = gold.price_at(s, pd.Timestamp(f"{d} 09:55", tz="Asia/Tokyo"))
        if p0 is None or p1 is None:
            continue
        rows[d] = (p1 / p0 - 1 - 2 * 0.00005, d in G)
    return pd.DataFrame(rows, index=["r", "gotobi"]).T.astype({"r": float, "gotobi": bool})


hist = run(gold.load_fx("usdjpy"))
new = run(gold.load_fx("usdjpy", Path("data_cache/dukascopy/unseen_fx")))
new = new[new.index >= date(2025, 9, 22)]
P = {"Entdeckung": (date(2008, 1, 1), date(2016, 12, 31)), "Bestätigung": (date(2017, 1, 1), date(2025, 9, 19))}
for fam, flag in (("BX Gotobi", True), ("BY andere Tage", False)):
    row = {}
    for name, (a, b) in P.items():
        x = hist[(hist.index >= a) & (hist.index <= b)]
        r = x["r"].where(x["gotobi"] == flag, 0.0)
        tr = r[x["gotobi"] == flag]
        t = r.mean() / r.std() * np.sqrt(len(r))
        row[name] = t
        print(f"{fam:15s} {name:11s} Trades {len(tr):4d} Ø {tr.mean() * 1e4:5.2f} bp/Trade Treffer {(tr > 0).mean():.0%} "
              f"{(1 + r).prod() ** (252 / len(r)) - 1:6.1%} p.a. t {t:5.2f}")
        if name == "Entdeckung":
            _log_trial("gotobi", "USDJPY", {"variant": fam}, CostModel(slippage_bps=0.5), 1.0, BacktestResult(fam, r))
    tr = new["r"][new["gotobi"] == flag]
    print(f"{fam:15s} unberührt   Trades {len(tr):4d} Ø {tr.mean() * 1e4:5.2f} bp/Trade, Summe {tr.sum():6.2%}")
    ok = row["Entdeckung"] >= 2.24 and row["Bestätigung"] >= 2 and tr.mean() > 0
    print(f"  -> {'BESTANDEN' if ok else 'NICHT BESTANDEN'}")

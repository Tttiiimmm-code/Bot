"""Gotobi-Hilfsfunktionen (Runden 46/47)."""
import calendar
from datetime import date, timedelta
import pandas as pd
from tradingbot.research import gold


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


def trades(series, entry=(5, 0), exit_=(9, 55), cost_per_side=0.00005):
    s = series.copy()
    s.index = s.index.tz_convert("Asia/Tokyo")
    G = gotobi_days(2007, 2026)
    rows = {}
    for d in sorted({d for d in s.index.date if d.weekday() < 5}):
        if d not in G:
            continue
        p0 = gold.price_at(s, pd.Timestamp(f"{d} {entry[0]:02d}:{entry[1]:02d}", tz="Asia/Tokyo"))
        p1 = gold.price_at(s, pd.Timestamp(f"{d} {exit_[0]:02d}:{exit_[1]:02d}", tz="Asia/Tokyo"))
        if p0 is None or p1 is None:
            continue
        rows[d] = p1 / p0 - 1 - 2 * cost_per_side
    return pd.Series(rows, dtype=float).sort_index()

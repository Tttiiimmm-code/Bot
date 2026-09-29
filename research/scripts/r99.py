"""Runde 99: Intraday-Momentum bei Rohöl an EIA-Tagen (Vorab-Registrierung in PROTOCOL.md)."""
from pathlib import Path

import numpy as np
import pandas as pd
from pandas.tseries.holiday import USFederalHolidayCalendar

from tradingbot.research import gold
from tradingbot.research import ml_rank as ml

COST = 3e-4
PERIODS = {"P1 2012-2019": ("2012-01-01", "2019-12-31"), "P2 2020-2025-09": ("2020-01-01", "2025-09-19"),
           "unberührt 2025-09..": ("2025-09-22", "2026-12-31")}

m = gold.load_minutes(Path("data_cache/dukascopy/oil/download"), "wti_*.csv")
px = m["open"].tz_convert("America/New_York")
print(f"Minuten: {len(px)}, {px.index[0]} .. {px.index[-1]}", flush=True)
holidays = set(USFederalHolidayCalendar().holidays(px.index[0].tz_localize(None), px.index[-1].tz_localize(None)).date)


def at(day, hh, mm):
    return gold.price_at(px, pd.Timestamp(day).tz_localize("America/New_York") + pd.Timedelta(hours=hh, minutes=mm), 3)


rows = []
for day in pd.bdate_range(px.index[0].date(), px.index[-1].date()):
    week_mon = day - pd.Timedelta(days=day.weekday())
    holiday_week = any((week_mon + pd.Timedelta(days=k)).date() in holidays for k in range(3))
    eia = day.weekday() == 2 and not holiday_week
    p1030, p1100, p1400, p1430 = at(day, 10, 30), at(day, 11, 0), at(day, 14, 0), at(day, 14, 30)
    if None in (p1030, p1100, p1400, p1430):
        continue
    sig = np.sign(p1100 / p1030 - 1)
    last = p1430 / p1400 - 1
    if sig == 0:
        continue
    rows.append({"day": day, "eia": eia, "sig": sig, "last": last, "ret": sig * last - COST})
df = pd.DataFrame(rows).set_index("day")
print(f"Tage mit Kursen: {len(df)}, davon EIA-Tage {int(df['eia'].sum())}", flush=True)


def report(label, x):
    parts = [f"{label:32s}"]
    for pname, (a, b) in PERIODS.items():
        y = x[(x.index >= a) & (x.index <= b)]
        parts.append(f"{pname}: n {len(y)}, Ø {y.mean() * 1e4:+.1f} bp (t {ml.t_stat(y):+.2f}, Treffer {(y > 0).mean():.0%})")
    print(" | ".join(parts), flush=True)


e = df[df["eia"]]
report("PRIMÄR EIA-Tage long+short", e["ret"])
report("EIA nur long (Signal +)", e.loc[e["sig"] > 0, "ret"])
report("EIA nur short (Signal -)", e.loc[e["sig"] < 0, "ret"])
report("Nicht-EIA-Tage (Info)", df.loc[~df["eia"], "ret"])
yr = e["ret"].groupby(e.index.year).mean() * 1e4
print("PRIMÄR Ø bp je Jahr:", " ".join(f"{k}: {v:+.1f}" for k, v in yr.items()))
p1, p2, u = (e["ret"][(e.index >= a) & (e.index <= b)] for a, b in PERIODS.values())
ok = ml.t_stat(p1) >= 2 and ml.t_stat(p2) >= 2 and u.mean() > 0
print(f"Kriterien: t P1 {ml.t_stat(p1):+.2f}, t P2 {ml.t_stat(p2):+.2f}, unberührt {u.mean() * 1e4:+.1f} bp -> "
      f"{'BESTANDEN' if ok else 'NICHT BESTANDEN'}")

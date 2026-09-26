"""Kontrolle Runde 41: DAX-Nacht mit Dukascopy-CFD-Kursen."""
from datetime import date
from pathlib import Path
import numpy as np, pandas as pd
from tradingbot.research import anomalies, gold

m = gold.load_minutes(Path("data_cache/dukascopy/dax"), "dax_*.csv")
m.index = m.index.tz_convert("Europe/Berlin")
m = m[m.index.date <= date(2025, 9, 19)]
o = m["open"]


def at(d, hh, mm):
    ts = pd.Timestamp(f"{d} {hh:02d}:{mm:02d}", tz="Europe/Berlin")
    p = o.index.searchsorted(ts)
    if p >= len(o) or o.index[p] - ts > pd.Timedelta(minutes=5):
        return None
    return float(o.iloc[p])


days = sorted({d for d in m.index.date if pd.Timestamp(d).weekday() < 5})
rate = anomalies.fetch_fred("IR3TIB01EZM156N") / 100
rows = []
for a, b in zip(days[:-1], days[1:]):
    c, e, n = at(a, 17, 30), at(a, 22, 0), at(b, 9, 0)
    if None in (c, n):
        continue
    rf = float(rate[rate.index <= pd.Timestamp(a)].iloc[-1])
    fin = max(rf, 0) / 360 * (b - a).days
    rows.append((b, n / c - 1, (e / c - 1) if e else np.nan, (n / e - 1) if e else np.nan, fin))
df = pd.DataFrame(rows, columns=["d", "night", "evening", "late", "fin"]).set_index("d")
df["net"] = df["night"] - 2 * 0.00005 - df["fin"]
for name, (a, b) in (("2013-2018", (date(2013, 1, 1), date(2018, 12, 31))), ("2019-2025", (date(2019, 1, 1), date(2025, 9, 19))), ("gesamt", (date(2013, 1, 1), date(2025, 9, 19)))):
    x = df[(df.index >= a) & (df.index <= b)]
    t = x["net"].mean() / x["net"].std() * np.sqrt(len(x))
    print(f"{name:10s} Nächte {len(x):4d} brutto Ø {x['night'].mean() * 1e4:5.2f} bp (17:30-22 {x['evening'].mean() * 1e4:5.2f}, "
          f"22-9 {x['late'].mean() * 1e4:5.2f}) netto Ø {x['net'].mean() * 1e4:5.2f} bp, {(1 + x['net']).prod() ** (252 / len(x)) - 1:6.1%} p.a., t {t:5.2f}")

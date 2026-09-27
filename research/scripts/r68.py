"""Runde 68: Pre-EZB-Drift am DAX (CFD-Minuten, Dukascopy)."""
from pathlib import Path

import numpy as np
import pandas as pd

from tradingbot.research import gold

ECB = """2013: 5 December 2013, 7 November 2013, 2 October 2013
2014: 4 December 2014, 6 November 2014, 2 October 2014, 4 September 2014, 7 August 2014, 3 July 2014, 5 June 2014, 8 May 2014, 3 April 2014, 6 March 2014, 6 February 2014, 9 January 2014
2015: 3 December 2015, 22 October 2015, 3 September 2015, 16 July 2015, 3 June 2015, 15 April 2015, 5 March 2015, 22 January 2015
2016: 8 December 2016, 20 October 2016, 8 September 2016, 21 July 2016, 2 June 2016, 21 April 2016, 10 March 2016, 21 January 2016
2017: 14 December 2017, 26 October 2017, 7 September 2017, 20 July 2017, 8 June 2017, 27 April 2017, 9 March 2017, 19 January 2017
2018: 13 December 2018, 25 October 2018, 13 September 2018, 26 July 2018, 14 June 2018, 26 April 2018, 8 March 2018, 25 January 2018
2019: 12 December 2019, 24 October 2019, 12 September 2019, 25 July 2019, 6 June 2019, 10 April 2019, 7 March 2019, 24 January 2019
2020: 10 December 2020, 29 October 2020, 10 September 2020, 16 July 2020, 4 June 2020, 30 April 2020, 12 March 2020, 23 January 2020
2021: 16 December 2021, 28 October 2021, 9 September 2021, 22 July 2021, 10 June 2021, 22 April 2021, 11 March 2021, 21 January 2021
2022: 15 December 2022, 27 October 2022, 8 September 2022, 21 July 2022, 9 June 2022, 14 April 2022, 10 March 2022, 3 February 2022
2023: 14 December 2023, 26 October 2023, 14 September 2023, 27 July 2023, 15 June 2023, 4 May 2023, 16 March 2023, 2 February 2023
2024: 12 December 2024, 17 October 2024, 12 September 2024, 18 July 2024, 6 June 2024, 11 April 2024, 7 March 2024, 25 January 2024
2025: 18 December 2025, 30 October 2025, 11 September 2025, 24 July 2025, 5 June 2025, 17 April 2025, 6 March 2025, 30 January 2025
2026: 10 September 2026, 23 July 2026, 11 June 2026, 30 April 2026, 19 March 2026, 5 February 2026"""
dates = sorted(pd.Timestamp(x.strip()) for line in ECB.splitlines() for x in line.split(":")[1].split(","))
dates = set(d for d in dates if d >= pd.Timestamp("2013-10-01"))
COST = 1.5  # Punkte Round-Trip
FIN = 1e-4

m = pd.concat([gold.load_minutes(Path("data_cache/dukascopy/dax"), "dax_*.csv"),
               gold.load_minutes(Path("data_cache/dukascopy/unseen"), "deuidxeur_*.csv")])
px = m[~m.index.duplicated()].sort_index()["open"]


def at(ts):
    return gold.price_at(px, ts.tz_convert("UTC"))


def trade(d, prev):
    ber = pd.Timestamp(d.date()).tz_localize("Europe/Berlin")
    exit_ts = ber + (pd.Timedelta(hours=14, minutes=10) if d.year >= 2022 else pd.Timedelta(hours=13, minutes=40))
    a = at(pd.Timestamp(prev.date()).tz_localize("Europe/Berlin") + pd.Timedelta(hours=17, minutes=30))
    b = at(exit_ts)
    if not (a and b):
        return None
    return b / a - 1 - COST / a - FIN


bdays = pd.date_range("2013-10-01", "2026-09-25", freq="B")
ecb, ctrl = {}, {}
for prev, d in zip(bdays[:-1], bdays[1:]):
    r = trade(d, prev)
    if r is None:
        continue
    (ecb if d in dates else ctrl)[d] = r
e, c = pd.Series(ecb), pd.Series(ctrl)
print("EZB-Tage mit Kursen:", len(e), "von", len(dates))
ok = True
for name, s, en, th in [("Entdeckung", "2013-10-01", "2019-12-31", 2.0), ("Bestätigung", "2020-01-01", "2025-09-19", 2.0),
                        ("unberührt", "2025-09-22", "2026-09-25", None)]:
    v, k = e[s:en], c[s:en]
    t = v.mean() / v.std() * np.sqrt(len(v))
    print(f"{name:12s} EZB n {len(v):3d} netto {v.mean()*1e4:6.2f} bp t {t:5.2f} Treffer {(v>0).mean():.2f} | "
          f"Kontrolle n {len(k):4d} netto {k.mean()*1e4:6.2f} bp")
    ok &= (t >= th) if th else (v.mean() > 0)
print("->", "BESTANDEN" if ok else "NICHT BESTANDEN")

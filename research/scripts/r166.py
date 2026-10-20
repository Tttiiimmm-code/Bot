"""Runde 166: Mondzyklus (Dichev & Janes 2003) auf SPY, Info BTC -- Vorab: PROTOCOL.md Runde 166.

Aufruf aus dem Haupt-Repo: PYTHONPATH=<worktree> python <worktree>/research/scripts/r166.py
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from r153 import spy_daily, tstat
from r158 import fred, pa

SYN = 29.530589
REF = pd.Timestamp("2000-01-06 18:14")
MAIN, CLASS = ("2016-01-01", "2026-08-31"), ("1994-01-01", "2015-12-31")


def new_moon_window(days: pd.DatetimeIndex, close_hour: float) -> pd.Series:
    age = ((days + pd.Timedelta(hours=close_hour) - REF) / pd.Timedelta(days=1)) % SYN
    return pd.Series((age < 7.38) | (age > SYN - 7.38), index=days)


def welch(a: pd.Series, b: pd.Series) -> float:
    return float((a.mean() - b.mean()) / np.sqrt(a.var() / len(a) + b.var() / len(b)))


def main():
    spy = spy_daily()
    tb = (fred("DTB3") / 100 / 252).reindex(spy.index).ffill().fillna(0.0)
    nm = new_moon_window(spy.index, 21.0)                                  # Schluss 16:00 New York ~ 21:00 UTC
    pos = nm.astype(float)
    r = pos * spy + (1 - pos) * tb - pos.diff().abs().fillna(0.0) * 2e-4
    print("Runde 166 -- Mondzyklus\n\nHauptkriterium (SPY im Neumond-Fenster ±7 Tage, sonst T-Bills):")
    ok = True
    for name, (a, b) in (("Haupt 2016-01..2026-08", MAIN), ("Einordnung 1994-2015", CLASS)):
        rr, ss = r[a:b], spy[a:b]
        ex = (1 + rr).groupby(rr.index.to_period("M")).prod() - (1 + ss).groupby(ss.index.to_period("M")).prod()
        t = tstat(ex)
        print(f"  {name}: {pa(rr):+6.1%} p.a. vs SPY {pa(ss):+6.1%}, t {t:+.2f}, in SPY {pos[a:b].mean():.0%}")
        ok &= (pa(rr) > pa(ss) and t >= 2.0) if name.startswith("Haupt") else ex.mean() > 0
    print(f"  -> {'BESTANDEN' if ok else 'NICHT BESTANDEN'}\n\nInfo (nicht gewertet): Ø Tagesrendite Neumond- vs Vollmond-Fenster")
    for name, (a, b) in (("SPY 1994-2015", CLASS), ("SPY 2016-2026", MAIN)):
        s, w = spy[a:b], nm[a:b]
        print(f"  {name}: Neumond {s[w].mean() * 1e4:+.2f} bp, Vollmond {s[~w].mean() * 1e4:+.2f} bp, t {welch(s[w], s[~w]):+.2f}")
    btc = pd.read_pickle("data_cache/crypto/BTCUSDT.pkl")["close"]
    btc.index = pd.DatetimeIndex(btc.index)
    br = btc.pct_change().dropna()
    br = br[br.index >= "2018-01-01"]
    w = new_moon_window(br.index, 24.0)                                     # Tagesschluss 00:00 UTC
    print(f"  BTC 2018-2026: Neumond {br[w].mean() * 1e4:+.2f} bp, Vollmond {br[~w].mean() * 1e4:+.2f} bp, "
          f"t {welch(br[w], br[~w]):+.2f}")


if __name__ == "__main__":
    main()

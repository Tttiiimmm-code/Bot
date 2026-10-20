"""Runde 167: BTC-Zyklusindikatoren (Mayer Multiple, Pi-Cycle-Top, Hash Ribbons) gegen BTC halten.

Vorab: PROTOCOL.md Runde 167. Aufruf aus dem Haupt-Repo: PYTHONPATH=<worktree> python <worktree>/research/scripts/r167.py
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from r153 import spy_daily, tstat
from r158 import fred
from r165 import ohlc

COST = 10e-4
A, B = "2016-01-01", "2026-08-31"
T_PASS = 2.13


def machine(n: int, start: float, enter, leave) -> np.ndarray:
    pos, out = start, np.zeros(n)
    for i in range(n):
        if pos == 0 and enter[i]:
            pos = 1.0
        elif pos == 1 and leave[i]:
            pos = 0.0
        out[i] = pos
    return out


def pa_m(x):
    return float((1 + x).prod() ** (12 / len(x)) - 1)


def main():
    px = ohlc("BTC-USD")["close"]
    hr = pd.Series({pd.Timestamp(v["x"], unit="s").normalize(): v["y"]
                    for v in json.load(open("data_cache/r167/hashrate.json"))["values"]})
    hr = hr.groupby(level=0).last().reindex(px.index).ffill()
    mm = px / px.rolling(200).mean()
    pi = px.rolling(111).mean() > 2 * px.rolling(350).mean()
    pi_cross = pi & ~pi.shift(1, fill_value=False)
    below_200w = px < px.rolling(1400, min_periods=1000).mean()
    h30, h60 = hr.rolling(30).mean(), hr.rolling(60).mean()
    capit = h30 < h60
    buy = (h30 > h60) & (h30.shift(1) <= h60.shift(1)) & (px.rolling(10).mean() > px.rolling(20).mean())
    n = len(px)
    pos = {
        "A Mayer Multiple (<1 kaufen, >2,4 verkaufen)": machine(n, 0.0, (mm < 1.0).to_numpy(), (mm > 2.4).to_numpy()),
        "B Pi-Cycle-Top (raus), unter 200-Wochen-Linie (rein)": machine(n, 1.0, below_200w.to_numpy(), pi_cross.to_numpy()),
        "C Hash Ribbons (raus bei Kapitulation, rein beim Kaufsignal)": machine(n, 1.0, buy.to_numpy(), capit.to_numpy()),
    }
    ret = px.pct_change().fillna(0.0)
    tb = (fred("DTB3") / 100 / 365).reindex(px.index).ffill().fillna(0.0)
    spy = spy_daily()
    sm = (1 + spy).groupby(spy.index.to_period("M")).prod() - 1
    bm = (1 + ret[A:B]).groupby(ret[A:B].index.to_period("M")).prod() - 1
    eqb = (1 + bm).cumprod()
    print(f"Runde 167 -- BTC-Zyklusindikatoren, BTC-USD ab {px.index[0]:%Y-%m-%d}; BTC halten 2016-01..2026-08 "
          f"{pa_m(bm):+.1%} p.a. (Max-DD {float((eqb / eqb.cummax() - 1).min()):.1%}), SPY {pa_m(sm.reindex(bm.index)):+.1%}\n")
    print("Hauptkriterium je Regel (Maßstab BTC halten, Hürde t >= 2,13):")
    for label, p in pos.items():
        p = pd.Series(p, index=px.index)
        r = p.shift(1).fillna(0) * ret + (1 - p.shift(1).fillna(0)) * tb - p.diff().abs().fillna(0.0) * COST
        m = (1 + r[A:B]).groupby(r[A:B].index.to_period("M")).prod() - 1
        ex = m - bm
        t = tstat(ex)
        h1 = m.index.year <= 2020
        e1, e2 = pa_m(m[h1]) - pa_m(bm[h1]), pa_m(m[~h1]) - pa_m(bm[~h1])
        s = sm.reindex(m.index).fillna(0.0)
        ok = pa_m(m) > pa_m(bm) and pa_m(m) > pa_m(s) and t >= T_PASS and e1 > 0 and e2 > 0
        eq = (1 + m).cumprod()
        print(f"  {label}: {pa_m(m):+6.1%} p.a. vs BTC {pa_m(bm):+6.1%}, t ggü. BTC {t:+.2f}, Hälften {e1:+6.1%} / "
              f"{e2:+6.1%}, Max-DD {float((eq / eq.cummax() - 1).min()):.1%}, investiert {p[A:B].mean():.0%}, Wechsel "
              f"{int(p[A:B].diff().abs().sum())} -> {'BESTANDEN' if ok else 'NICHT BESTANDEN'}")


if __name__ == "__main__":
    main()

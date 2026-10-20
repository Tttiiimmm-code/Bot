"""Runde 161: DCA-Bot mit Safety Orders (3Commas-Standard) auf BTC/USDT -- Vorab: PROTOCOL.md Runde 161.

Aufruf aus dem Haupt-Repo: PYTHONPATH=<worktree> python <worktree>/research/scripts/r161.py
"""
from __future__ import annotations

import numba
import numpy as np
import pandas as pd

from r153 import spy_daily, tstat
from r159 import A, B, HALF, load, pa_m

FEE = 0.001
BASE = 10.0
SO = np.array([20.0, 40.0, 80.0, 160.0, 320.0])
DEV = np.array([0.01, 0.02, 0.03, 0.04, 0.05])
CAPITAL = BASE + SO.sum()


@numba.njit(cache=True)
def dca(o, h, l, c, tp):
    m = len(c)
    cash = CAPITAL
    btc = 0.0; cost = 0.0; entry = 0.0; k = 0          # k = Zahl gefüllter Safety Orders
    eq = np.zeros(m)
    deals = 0; open_since = 0; longest = 0; worst = 0.0
    active = False
    for j in range(m):
        if not active:
            entry = o[j]
            btc = BASE / entry * (1 - FEE); cash -= BASE; cost = BASE; k = 0
            active = True; open_since = j
        if c[j] >= o[j]:
            path = (o[j], l[j], h[j], c[j])
        else:
            path = (o[j], h[j], l[j], c[j])
        for s in range(3):
            a, b = path[s], path[s + 1]
            if not active:
                break
            if b < a:
                while k < len(SO) and b <= entry * (1 - DEV[k]):
                    px = entry * (1 - DEV[k])
                    btc += SO[k] / px * (1 - FEE); cash -= SO[k]; cost += SO[k]; k += 1
            elif b > a:
                target = cost / btc * (1 + tp)
                if b >= target and a < target:
                    cash += btc * target * (1 - FEE)
                    btc = 0.0; cost = 0.0; active = False; deals += 1
                    longest = max(longest, j - open_since)
        v = cash + btc * c[j]
        eq[j] = v
        worst = min(worst, v / CAPITAL - 1)
    return eq, deals, longest, worst


def main():
    df = load()
    df = df[(df.index >= A) & (df.index < "2026-09-01")]
    o, h, l_, c = (df[k].to_numpy() for k in "ohlc")
    spy = spy_daily()
    spy_m = (1 + spy).groupby(spy.index.to_period("M")).prod() - 1
    print(f"Runde 161 -- DCA-Bot (3Commas-Standard) BTC/USDT, Kapital {CAPITAL:.0f} USDT je Deal\n")

    def report(label, tp, binding):
        eq, deals, longest, worst = dca(o, h, l_, c, tp)
        e = pd.Series(eq / CAPITAL, index=df.index).resample("ME").last()
        r = e.pct_change()
        r.iloc[0] = e.iloc[0] - 1
        r.index = r.index.to_period("M")
        s = spy_m.reindex(r.index).fillna(0.0)
        t = tstat(r - s)
        h1, h2 = r.index <= HALF, r.index > HALF
        e1, e2 = pa_m(r[h1]) - pa_m(s[h1]), pa_m(r[h2]) - pa_m(s[h2])
        ok = pa_m(r) > pa_m(s) and t >= 2.0 and e1 > 0 and e2 > 0
        print(f"  {label}: {pa_m(r):+6.1%} p.a. vs SPY {pa_m(s):+6.1%}, t {t:+.2f}, Hälften {e1:+6.1%} / {e2:+6.1%}, "
              f"Max-DD (Monat) {float((e / e.cummax() - 1).min()):.1%}, Deals {deals:,}, längster Deal "
              f"{longest / 1440:.0f} Tage, größter Buchverlust {worst:.1%}"
              + (f" -> {'BESTANDEN' if ok else 'NICHT BESTANDEN'}" if binding else " (Info)"))

    print("Hauptkriterium (TP 1 %, 5 Safety Orders 1-5 %, Volumenfaktor 2, 0,1 % Gebühr):")
    report("TP 1 %", 0.01, True)
    print("\nInfo (nicht gewertet):")
    report("TP 2 %", 0.02, False)


if __name__ == "__main__":
    main()

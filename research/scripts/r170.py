"""Runde 170: Marktweite Insiderkäufe als SPY-Hebelsignal -- Vorab: PROTOCOL.md Runde 170.

Aufruf aus dem Haupt-Repo: PYTHONPATH=<worktree> python <worktree>/research/scripts/r170.py
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from r153 import spy_daily, tstat
from r158 import fred, pa

A, B = "2016-10-01", "2025-09-30"


def main():
    spy = spy_daily()
    days = spy.index
    tb = (fred("DTB3") / 100 / 252).reindex(days).ffill().fillna(0.0)
    ins = pd.read_pickle("data_cache/edgar/insider_purchases.pkl")
    ins["d"] = pd.to_datetime(ins["filing_date"])
    ins["k"] = days.searchsorted(ins["d"])
    ins = ins[ins["k"] < len(days)]
    breadth = np.zeros(len(days))
    by_day = ins.groupby("k")["issuer_cik"].apply(set)
    for k in range(len(days)):
        firms = set()
        for q in range(max(0, k - 20), k):                              # letzte 20 Handelstage bis Vortag
            firms |= by_day.get(q, set())
        breadth[k] = len(firms)
    br = pd.Series(breadth, index=days)
    br[days < ins["d"].min() + pd.Timedelta(days=30)] = np.nan
    z = (br - br.rolling(252).mean()) / br.rolling(252).std()
    print(f"Runde 170 -- marktweite Insiderkäufe, {len(ins):,} Käufe, Breite Ø {br[A:B].mean():.0f} Firmen/20 Tage\n")

    def report(label, thr, binding):
        sig = (z > thr).to_numpy()
        lev = np.ones(len(days))
        until, n_sig = -1, 0
        for k in range(len(days)):
            if sig[k] and k > until:
                until = k + 19
                n_sig += 1
            if k <= until:
                lev[k] = 1.5
        lev = pd.Series(lev, index=days)
        r = lev * spy - (lev - 1) * (tb + 0.005 / 252) - lev.diff().abs().fillna(0.0) * 2e-4
        rr, ss = r[A:B], spy[A:B]
        ex = (1 + rr).groupby(rr.index.to_period("M")).prod() - (1 + ss).groupby(ss.index.to_period("M")).prod()
        t = tstat(ex)
        h1 = rr.index.year <= 2020
        e1, e2 = pa(rr[h1]) - pa(ss[h1]), pa(rr[~h1]) - pa(ss[~h1])
        ok = pa(rr) > pa(ss) and t >= 2.0 and e1 > 0 and e2 > 0
        on = lev[A:B] > 1
        print(f"  {label}: {pa(rr):+6.1%} p.a. vs SPY {pa(ss):+6.1%}, t {t:+.2f}, Hälften {e1:+6.1%} / {e2:+6.1%}, "
              f"Signale {n_sig}, Tage mit Hebel {on.mean():.0%}, SPY je Tag mit Hebel {ss[on].mean() * 1e4:+.1f} bp vs "
              f"sonst {ss[~on].mean() * 1e4:+.1f} bp" + (f" -> {'BESTANDEN' if ok else 'NICHT BESTANDEN'}" if binding else " (Info)"))

    print("Hauptkriterium (z > 1,5 -> 20 Tage 1,5x SPY):")
    report("z > 1,5", 1.5, True)
    print("\nInfo (nicht gewertet):")
    report("z > 1,0", 1.0, False)


if __name__ == "__main__":
    main()

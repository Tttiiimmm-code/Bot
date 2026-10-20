"""Runde 163: "Growth-Trend Timing" (Philosophical Economics 2016) -- Vorab: PROTOCOL.md Runde 163.

Aufruf aus dem Haupt-Repo: PYTHONPATH=<worktree> python <worktree>/research/scripts/r163.py
"""
from __future__ import annotations

import pandas as pd

from r153 import spy_daily, tstat
from r158 import fred

MAIN, CLASS = (pd.Period("2016-01", "M"), pd.Period("2026-08", "M")), (pd.Period("1994-01", "M"), pd.Period("2015-12", "M"))
COST = 2e-4


def pa_m(x):
    return float((1 + x).prod() ** (12 / len(x)) - 1)


def main():
    spy = spy_daily()
    sm = (1 + spy).groupby(spy.index.to_period("M")).prod() - 1
    level = (1 + sm).cumprod()
    tb = fred("DTB3") / 100
    tbm = ((1 + tb / 252) ** 21 - 1).groupby(tb.index.to_period("M")).last().reindex(sm.index).ffill().fillna(0.0)
    ur = fred("UNRATE")
    ur.index = ur.index.to_period("M")
    known = ur.shift(1).reindex(sm.index)                              # am Ende von m bekannt: Wert für m-1
    trend_bad = level < level.rolling(10).mean()
    growth_bad = known > known.rolling(12).mean()
    print(f"Runde 163 -- Growth-Trend Timing, SPY-Monate {sm.index[0]} bis {sm.index[-1]}\n")

    def report(label, out_signal, binding):
        pos = (~out_signal).astype(float).shift(1).fillna(1.0)       # Signal am Monatsende gilt im Folgemonat
        r = pos * sm + (1 - pos) * tbm - pos.diff().abs().fillna(0.0) * COST
        lines, ok = [], True
        for name, (a, b) in (("Haupt 2016-01..2026-08", MAIN), ("Einordnung 1994-2015", CLASS)):
            rr, ss, pp = r[a:b], sm[a:b], pos[a:b]
            ex = rr - ss
            t = tstat(ex)
            eq, eqs = (1 + rr).cumprod(), (1 + ss).cumprod()
            lines.append(f"    {name}: {pa_m(rr):+6.1%} p.a. vs SPY {pa_m(ss):+6.1%}, t {t:+.2f}, in SPY {pp.mean():.0%}, "
                         f"Wechsel {int(pp.diff().abs().sum())}, Max-DD (Monat) {float((eq / eq.cummax() - 1).min()):.1%} "
                         f"(SPY {float((eqs / eqs.cummax() - 1).min()):.1%})")
            ok &= (pa_m(rr) > pa_m(ss) and t >= 2.0) if name.startswith("Haupt") else ex.mean() > 0
        print(f"  {label}:" + (f" -> {'BESTANDEN' if ok else 'NICHT BESTANDEN'}" if binding else " (Info)"))
        print("\n".join(lines))

    print("Hauptkriterium (raus, wenn Trend UND Arbeitsmarkt schwach):")
    report("Growth-Trend", trend_bad & growth_bad, True)
    print("\nInfo (nicht gewertet):")
    report("nur Trend (10 Monate)", trend_bad, False)


if __name__ == "__main__":
    main()

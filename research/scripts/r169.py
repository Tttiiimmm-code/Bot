"""Runde 169: Put/Call-Verhältnis als Kontra-Signal für SPY -- Vorab: PROTOCOL.md Runde 169.

Aufruf aus dem Haupt-Repo: PYTHONPATH=<worktree> python <worktree>/research/scripts/r169.py
"""
from __future__ import annotations

import pandas as pd

from r153 import spy_daily, tstat
from r158 import fred, pa

A, B, MID = "2008-01-01", "2019-09-30", 2013


def pc(name: str) -> pd.Series:
    d = pd.read_csv(f"data_cache/r169/{name}.csv", skiprows=2)
    d.columns = [c.strip() for c in d.columns]
    s = pd.Series(pd.to_numeric(d["P/C Ratio"], errors="coerce").to_numpy(),
                  index=pd.to_datetime(d["DATE"].str.strip(), format="mixed"))
    return s.dropna().sort_index()


def main():
    spy = spy_daily()
    tb = (fred("DTB3") / 100 / 252).reindex(spy.index).ffill().fillna(0.0)
    print("Runde 169 -- Put/Call als Kontra-Signal (CBOE, 2006-11..2019-10)\n")

    def report(label, name, lo, hi, binding):
        s = pc(name).rolling(10).mean()
        z = ((s - s.rolling(252).mean()) / s.rolling(252).std()).reindex(spy.index).ffill().shift(1)
        w = pd.Series(1.0, index=spy.index).where(~(z < lo), 0.0)
        if hi is not None:
            w = w.where(~(z > hi), 1.5)
        r = w * spy + (1 - w) * tb - w.diff().abs().fillna(0.0) * 2e-4
        rr, ss = r[A:B], spy[A:B]
        ex = (1 + rr).groupby(rr.index.to_period("M")).prod() - (1 + ss).groupby(ss.index.to_period("M")).prod()
        t = tstat(ex)
        h1 = rr.index.year <= MID
        e1, e2 = pa(rr[h1]) - pa(ss[h1]), pa(rr[~h1]) - pa(ss[~h1])
        ok = pa(rr) > pa(ss) and t >= 2.0 and e1 > 0 and e2 > 0
        print(f"  {label}: {pa(rr):+6.1%} p.a. vs SPY {pa(ss):+6.1%}, t {t:+.2f}, Hälften {e1:+6.1%} / {e2:+6.1%}, "
              f"außerhalb SPY {(w[A:B] == 0).mean():.0%}" + (f" -> {'BESTANDEN' if ok else 'NICHT BESTANDEN'}" if binding else " (Info)"))

    print("Hauptkriterium (Aktien-Put/Call, z < -1 -> T-Bills):")
    report("equity z<-1", "equitypc", -1.0, None, True)
    print("\nInfo (nicht gewertet):")
    report("total z<-1", "totalpc", -1.0, None, False)
    report("equity z<-1,5", "equitypc", -1.5, None, False)
    report("equity z<-1, z>+1,5 -> 1,5x", "equitypc", -1.0, 1.5, False)


if __name__ == "__main__":
    main()

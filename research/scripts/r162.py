"""Runde 162: VIX-Terminstruktur (VIX < VIX3M) als SPY-Zeitsignal -- Vorab: PROTOCOL.md Runde 162.

Aufruf aus dem Haupt-Repo: PYTHONPATH=<worktree> python <worktree>/research/scripts/r162.py
"""
from __future__ import annotations

from datetime import date

import pandas as pd

from r153 import spy_daily, tstat
from r158 import fred, pa
MAIN, CLASS = ("2016-01-01", "2026-08-31"), ("2008-01-01", "2015-12-31")
COST = 2e-4


def yahoo(sym: str) -> pd.Series:
    """Tagesschlüsse von Yahoo (chart-API), Index = New-York-Datum."""
    import json
    import urllib.parse
    import urllib.request
    from datetime import datetime, timezone

    p1, p2 = (int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp())
              for d in (date(2007, 1, 1), date(2026, 10, 10)))
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(sym)}?period1={p1}&period2={p2}"
           "&interval=1d")
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=60) as r:
        res = json.load(r)["chart"]["result"][0]
    idx = pd.to_datetime(res["timestamp"], unit="s", utc=True).tz_convert("America/New_York").tz_localize(None).normalize()
    s = pd.Series(res["indicators"]["quote"][0]["close"], index=idx, dtype=float).dropna()
    return s[~s.index.duplicated(keep="last")].sort_index()


def main():
    spy = spy_daily()
    vix, v3 = yahoo("^VIX"), yahoo("^VIX3M")
    ratio = (vix / v3).dropna()
    spy = spy[spy.index >= ratio.index[0] + pd.Timedelta(days=5)]
    tb = (fred("DTB3") / 100 / 252).reindex(spy.index).ffill().fillna(0.0)
    rt = ratio.reindex(spy.index).ffill().shift(1)                     # Vortagesschluss
    print(f"Runde 162 -- VIX/VIX3M ab {ratio.index[0]:%Y-%m-%d}, Backwardation an {(ratio > 1).mean():.1%} der Tage\n")

    def report(label, thr, lev, binding):
        pos = (rt < thr).astype(float)
        risk = lev * spy - (lev - 1) * (tb + 0.005 / 252)
        r = pos * risk + (1 - pos) * tb - pos.diff().abs().fillna(0.0) * COST * lev
        lines, ok = [], True
        for name, (a, b) in (("Haupt 2016-01..2026-08", MAIN), ("Einordnung 2008-2015", CLASS)):
            rr, ss, pp = r[a:b], spy[a:b], pos[a:b]
            ex = (1 + rr).groupby(rr.index.to_period("M")).prod() - (1 + ss).groupby(ss.index.to_period("M")).prod()
            t = tstat(ex)
            eq, eqs = (1 + rr).cumprod(), (1 + ss).cumprod()
            lines.append(f"    {name}: {pa(rr):+6.1%} p.a. vs SPY {pa(ss):+6.1%}, t {t:+.2f}, in SPY {pp.mean():.0%}, "
                         f"Wechsel {int(pp.diff().abs().sum())}, Max-DD {float((eq / eq.cummax() - 1).min()):.1%} "
                         f"(SPY {float((eqs / eqs.cummax() - 1).min()):.1%})")
            ok &= (pa(rr) > pa(ss) and t >= 2.0) if name.startswith("Haupt") else ex.mean() > 0
        print(f"  {label}:" + (f" -> {'BESTANDEN' if ok else 'NICHT BESTANDEN'}" if binding else " (Info)"))
        print("\n".join(lines))

    print("Hauptkriterium (VIX < VIX3M am Vortag -> SPY, sonst T-Bills):")
    report("Contango", 1.0, 1, True)
    print("\nInfo (nicht gewertet):")
    report("VIX/VIX3M < 0,95", 0.95, 1, False)
    report("2x SPY bei Contango", 1.0, 2, False)


if __name__ == "__main__":
    main()

"""Runde 158: "Fed Net Liquidity" (WALCL - TGA - RRP) als SPY-Zeitsignal -- Vorab: PROTOCOL.md Runde 158.

Braucht data_cache/fred_liq/{WALCL,WTREGEN,RRPONTSYD,DTB3}.csv (FRED). Aufruf aus dem Haupt-Repo:
PYTHONPATH=<worktree> python <worktree>/research/scripts/r158.py
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from r153 import spy_daily, tstat

F = "data_cache/fred_liq"
MAIN, CLASS = ("2016-01-01", "2026-08-31"), ("2003-01-01", "2015-12-31")
COST = 2e-4


def fred(sid: str) -> pd.Series:
    d = pd.read_csv(f"{F}/{sid}.csv")
    return pd.Series(pd.to_numeric(d.iloc[:, 1], errors="coerce").to_numpy(), index=pd.to_datetime(d.iloc[:, 0])).dropna()


def net_liquidity() -> pd.Series:
    walcl, tga = fred("WALCL"), fred("WTREGEN")                       # Mio. $, Mittwoch
    rrp = fred("RRPONTSYD") * 1000                                    # Mrd. $ -> Mio. $
    rrp = rrp.reindex(rrp.index.union(walcl.index)).ffill().reindex(walcl.index).fillna(0.0)
    return (walcl - tga.reindex(walcl.index) - rrp).dropna()


def signal_daily(nl: pd.Series, days: pd.DatetimeIndex, rule: str) -> pd.Series:
    """Position (1 = SPY) je Handelstag; Stand Mittwoch, veröffentlicht Donnerstag, umgeschichtet Freitagsschluss ->
    gilt ab dem nächsten Handelstag nach diesem Freitag."""
    if rule.startswith("chg"):
        k = int(rule[3:])
        sig = (nl.diff(k) > 0).astype(float)
    else:                                                             # über dem 13-Wochen-Schnitt
        sig = (nl > nl.rolling(13).mean()).astype(float)
    sig = sig[nl.diff(13).notna()]
    eff = sig.copy()
    eff.index = sig.index + pd.Timedelta(days=2)                      # Freitag nach dem Mittwoch
    pos = eff.reindex(days.union(eff.index)).ffill().reindex(days)
    return pos.shift(1).fillna(0.0)                                   # Freitagsschluss -> ab nächstem Handelstag


def pa(r: pd.Series) -> float:
    return float((1 + r).prod() ** (252 / len(r)) - 1)


def run(rule: str, spy: pd.Series, tb: pd.Series, nl: pd.Series) -> pd.Series:
    pos = signal_daily(nl, spy.index, rule)
    switch = pos.diff().abs().fillna(0.0)
    return pos * spy + (1 - pos) * tb - switch * COST, pos


def main():
    spy = spy_daily()
    spy = spy[spy.index >= "2003-01-01"]
    tb = (fred("DTB3") / 100 / 252).reindex(spy.index).ffill().fillna(0.0)
    nl = net_liquidity()
    print(f"Runde 158 -- Fed Net Liquidity, {nl.index[0]:%Y-%m-%d} bis {nl.index[-1]:%Y-%m-%d}, zuletzt "
          f"{nl.iloc[-1] / 1e6:.2f} Bio. $\n")

    def report(rule, binding):
        r, pos = run(rule, spy, tb, nl)
        lines, ok = [], True
        for name, (a, b) in (("Haupt 2016-01..2026-08", MAIN), ("Einordnung 2003-2015", CLASS)):
            rr, ss, pp = r[a:b], spy[a:b], pos[a:b]
            ex = (1 + rr).groupby(rr.index.to_period("M")).prod() - (1 + ss).groupby(ss.index.to_period("M")).prod()
            t = tstat(ex)
            eq = (1 + rr).cumprod()
            lines.append(f"    {name}: {pa(rr):+6.1%} p.a. vs SPY {pa(ss):+6.1%}, t {t:+.2f}, in SPY {pp.mean():.0%}, "
                         f"Wechsel {int(pp.diff().abs().sum())}, Max-DD {float((eq / eq.cummax() - 1).min()):.1%} "
                         f"(SPY {float(((1 + ss).cumprod() / (1 + ss).cumprod().cummax() - 1).min()):.1%})")
            ok &= (pa(rr) > pa(ss) and t >= 2.0) if name.startswith("Haupt") else ex.mean() > 0
        print(f"  {rule}:" + (f" -> {'BESTANDEN' if ok else 'NICHT BESTANDEN'}" if binding else " (Info)"))
        print("\n".join(lines))

    print("Hauptkriterium (Veränderung über 4 Wochen > 0 -> SPY, sonst T-Bills):")
    report("chg4", True)
    print("\nInfo (nicht gewertet):")
    for rule in ("chg1", "chg13", "ma13"):
        report(rule, False)


if __name__ == "__main__":
    main()

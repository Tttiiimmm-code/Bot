"""Runde 145: Schedule-13D-Meldungen nachhandeln -- Vorab: PROTOCOL.md."""
import math
import re
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import r141 as R  # noqa: E402

D = Path(r"C:\Users\Nutzer\Bot\data_cache\sec13d")
ACT = ["Icahn", "Elliott", "Starboard", "Trian", "Pershing Square", "Third Point", "ValueAct", "JANA", "Engaged Capital",
       "Land & Buildings", "Ancora", "Legion Partners", "Sachem Head", "Corvex", "Cevian", "Mantle Ridge", "Politan",
       "Irenic", "Blackwells", "Carl C", "Barington", "Saba", "Stilwell", "Driver Management", "Engine Capital",
       "Macellum", "Inclusive Capital", "D. E. Shaw", "Anson", "22NW"]
ACT_RE = re.compile("|".join(re.escape(a) for a in ACT), re.I)


def backtest(sig, spy, hold=252, min_px=5.0):
    """Wie R.backtest, aber Einstieg 1. Handelstag nach Meldung und Mindestkurs."""
    d = spy.index
    num = pd.Series(0.0, index=d)
    den = pd.Series(0.0, index=d)
    used = miss = cheap = 0
    for r in sig.itertuples():
        i = d.searchsorted(pd.Timestamp(r.date), side="right")
        if i >= len(d) - 1:
            continue
        p = R.price(r.ticker)
        if p is None or p.index[0] > d[i] or p.index[-1] < d[i]:
            miss += 1
            continue
        p = p.reindex(d[i:min(i + hold, len(d) - 1) + 1]).ffill()
        if p.isna().iloc[0]:
            miss += 1
            continue
        if p.iloc[0] < min_px:
            cheap += 1
            continue
        ret = p.pct_change().iloc[1:].fillna(0.0).clip(-0.9, 3.0)
        ret.iloc[0] -= R.COST
        ret.iloc[-1] -= R.COST
        num[ret.index] += ret.values
        den[ret.index] += 1
        used += 1
    port = (num / den.replace(0, np.nan)).fillna(spy.pct_change().fillna(0.0))
    return (1 + port).cumprod(), used, miss, cheap, (den > 0).mean()


def report(name, sig, spy, hold=252):
    eq, used, miss, cheap, inv = backtest(sig, spy, hold)
    out = []
    for lab, (a, b) in (("2015-21", R.PRE), ("2022-26", R.MAIN)):
        c, cs, dd, t = R.stats(eq, spy, a, b)
        out.append((c, cs, t))
        print(f"  {name:34s} {lab}: {c:+6.1%} vs SPY {cs:+6.1%}  MaxDD {dd:6.1%}  t {t:+.2f}")
    print(f"  {'':34s} genutzt {used}, ohne Kurs {miss}, unter 5 $ {cheap}, investiert {inv:.0%}")
    return out


def main():
    f = pd.read_csv(D / "filings.csv", parse_dates=["date"])
    f = f[f.ticker.notna() & (f.subject_cik != f.filer_cik)].sort_values("date")
    f["ticker"] = f.ticker.str.upper().str.replace(".", "-", regex=False)
    keep, last = [], {}
    for r in f.itertuples():                                   # je Zielfirma erste 13D in 365 Tagen
        if r.subject_cik in last and (r.date - last[r.subject_cik]).days < 365:
            continue
        last[r.subject_cik] = r.date
        keep.append(r.Index)
    s = f.loc[keep].copy()
    s["date"] = s.date.dt.date
    s = s[(s.date >= date(2014, 10, 1)) & (s.date <= date(2026, 9, 30))]
    act = s[s.filer.fillna("").str.contains(ACT_RE)]
    spy = R.fetch_daily_yahoo("SPY", date(2014, 6, 1), date(2026, 10, 3))
    spy.index = pd.to_datetime(spy.index)
    spy = spy[spy.index <= "2026-09-30"]
    print(f"13D-Meldungen mit Ticker: {len(f)}, erste je Ziel/365 Tage: {len(s)}, bekannte Aktivisten: {len(act)}")
    print("Aktivisten je Melder:", act.filer.str.slice(0, 25).value_counts().head(12).to_dict(), "\n")
    print("HAUPTERGEBNIS (K=2: 2022-26 > SPY, t >= 2,3; 2015-21 > 0)")
    for name, sig in (("A alle 13D", s), ("B bekannte Aktivisten", act)):
        (c0, s0, _), (c1, s1, t1) = report(name, sig, spy)
        print(f"  -> {name}: {'BESTANDEN' if c1 > s1 and t1 >= 2.3 and c0 > s0 else 'nicht bestanden'}")
    print("\nNUR INFO (Haltedauer)")
    for h in (21, 63, 126):
        report(f"A alle, {h} Tage", s, spy, h)
        report(f"B Aktivisten, {h} Tage", act, spy, h)


if __name__ == "__main__":
    main()

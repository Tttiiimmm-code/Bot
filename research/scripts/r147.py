"""Runde 147: Kursdrift nach Aktiensplits -- Vorab: PROTOCOL.md."""
import math
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, r"C:\Users\Nutzer\Bot")
from tradingbot.orb_scanner import NOT_COMMON  # noqa: E402

B = Path(r"C:\Users\Nutzer\Bot\data_cache")
COST = 0.001
PRE, MAIN = ("2016-01-01", "2020-12-31"), ("2021-01-01", "2026-09-30")


def panel(symbols):
    close, dv = {}, {}
    for f in sorted((B / "universe" / "daily").glob("batch_*.pkl")):
        b = pd.read_pickle(f)
        have = [s for s in b.index.get_level_values(0).unique() if s in symbols]
        for s in have:
            x = b.loc[s]
            idx = pd.to_datetime(x.index).tz_convert("America/New_York").tz_localize(None).normalize()
            close[s] = pd.Series(x["close"].to_numpy(float), index=idx)
            dv[s] = pd.Series((x["close"] * x["volume"]).to_numpy(float), index=idx)
        del b
    return close, dv


def run(sig, close, dv, spy, hold=252, min_pre_px=0.0):
    d = spy.index
    num = pd.Series(0.0, index=d)
    den = pd.Series(0.0, index=d)
    used = skipped = 0
    for r in sig.itertuples():
        p = close.get(r.symbol)
        if p is None:
            skipped += 1
            continue
        p = p[~p.index.duplicated()]
        i = d.searchsorted(r.ex_date)
        if i >= len(d) - 1 or d[i] not in p.index:
            skipped += 1
            continue
        px = p.loc[d[i]]
        liq = dv[r.symbol][~dv[r.symbol].index.duplicated()].loc[:d[i]].tail(20).mean()
        if px < 5 or liq < 1e6 or px * r.ratio < min_pre_px:
            skipped += 1
            continue
        seg = p.reindex(d[i:min(i + hold, len(d) - 1) + 1])
        last = seg.last_valid_index()
        seg = seg.loc[:last].ffill()
        ret = seg.pct_change().iloc[1:].fillna(0.0).clip(-0.9, 3.0)
        if ret.empty:
            continue
        ret.iloc[0] -= COST
        ret.iloc[-1] -= COST
        num[ret.index] += ret.values
        den[ret.index] += 1
        used += 1
    port = (num / den.replace(0, np.nan)).fillna(spy.pct_change().fillna(0.0))
    return (1 + port).cumprod(), used, skipped, (den > 0).mean()


def stats(eq, spy, a, b):
    e, s = eq[a:b], spy[a:b]
    yrs = (e.index[-1] - e.index[0]).days / 365.25
    c, cs = (e.iloc[-1] / e.iloc[0]) ** (1 / yrs) - 1, (s.iloc[-1] / s.iloc[0]) ** (1 / yrs) - 1
    ex = (e.resample("ME").last().pct_change() - s.resample("ME").last().pct_change()).dropna()
    return c, cs, (e / e.cummax() - 1).min(), ex.mean() / ex.std(ddof=1) * math.sqrt(len(ex))


def report(name, sig, close, dv, spy, **kw):
    eq, used, skipped, inv = run(sig, close, dv, spy, **kw)
    out = []
    for lab, (a, b) in (("2016-20", PRE), ("2021-26", MAIN)):
        c, cs, dd, t = stats(eq, spy, a, b)
        out.append((c, cs, t))
        print(f"  {name:30s} {lab}: {c:+6.1%} vs SPY {cs:+6.1%}  MaxDD {dd:6.1%}  t {t:+.2f}")
    print(f"  {'':30s} genutzt {used}, übersprungen {skipped}, investiert {inv:.0%}")
    return out


def main():
    s = pd.read_pickle(B / "splits.pkl")
    s = s[s.kind == "forward_splits"].copy()
    s["ex_date"] = pd.to_datetime(s.ex_date)
    s["ratio"] = s.new_rate / s.old_rate
    s = s[(s.ratio >= 1.25) & (s.ex_date <= "2026-09-30")]
    a = pd.read_pickle(B / "universe" / "assets.pkl").drop_duplicates("symbol").set_index("symbol")
    names = a["name"].reindex(s.symbol).fillna("").to_numpy()
    s = s[[not re.search(NOT_COMMON, n) for n in names]]
    close, dv = panel(set(s.symbol) | {"SPY"})
    spy = close["SPY"][~close["SPY"].index.duplicated()]
    spy = spy[(spy.index >= "2016-01-01") & (spy.index <= "2026-09-30")]
    print(f"Vorwärtssplits (Verhältnis >= 1,25, Stammaktien): {len(s)}, mit Kursen {s.symbol.isin(close.keys()).sum()}\n")
    print("HAUPTERGEBNIS (2021-26 > SPY, t >= 2,0; 2016-20 > 0)")
    (c0, s0, _), (c1, s1, t1) = report("A alle Splits, 252 Tage", s, close, dv, spy)
    print(f"  -> {'BESTANDEN' if c1 > s1 and t1 >= 2.0 and c0 > s0 else 'nicht bestanden'}\n\nNUR INFO")
    for h in (21, 63, 126):
        report(f"A alle Splits, {h} Tage", s, close, dv, spy, hold=h)
    report("B Kurs vor Split >= 100 $", s, close, dv, spy, min_pre_px=100)


if __name__ == "__main__":
    main()

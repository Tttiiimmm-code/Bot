"""Runde 140: gehebelte Misch-Portfolios (90/60, Gold, HFEA) vs S&P 500 -- Vorab: PROTOCOL.md."""
import io
import math
import sys
import urllib.request
from datetime import date

import numpy as np
import pandas as pd

sys.path.insert(0, r"C:\Users\Nutzer\Bot")
from tradingbot.forward_test import fetch_daily_yahoo  # noqa: E402

SUB = {"1993-2007": ("1993-01-01", "2007-12-31"), "2008-2021": ("2008-01-01", "2021-12-31"),
       "2022-2026": ("2022-01-01", "2026-09-30")}


def fred(sid):
    req = urllib.request.Request(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}",
                                 headers={"User-Agent": "Mozilla/5.0"})
    d = pd.read_csv(io.BytesIO(urllib.request.urlopen(req, timeout=60).read()))
    s = pd.Series(pd.to_numeric(d.iloc[:, 1], errors="coerce").to_numpy(), index=pd.to_datetime(d.iloc[:, 0]))
    return s.dropna() / 100


def portfolio(rets, weights, tbill, period="M", fee=0.002, cost=0.0005):
    """Täglich mit Drift; Rebalancing am letzten Handelstag der Periode; geliehener Anteil kostet T-Bill + 0,5 %."""
    cols = list(weights)
    target = np.array([weights[c] for c in cols], float)
    r = rets[cols].to_numpy()
    tb = tbill.reindex(rets.index, method="ffill").fillna(0).to_numpy()
    last = rets.index.to_series().groupby(rets.index.to_period(period)).transform("max").to_numpy() == rets.index
    eq, out, w = 1.0, np.empty(len(r)), target.copy()
    for i in range(len(r)):
        borrow = w.sum() - 1
        day = float(w @ r[i]) - borrow * (tb[i] + 0.005) / 252 - w.sum() * fee / 252
        eq *= 1 + day
        w = w * (1 + r[i]) / (1 + day)
        if last[i]:
            eq *= 1 - cost * float(np.abs(w - target).sum())
            w = target.copy()
        out[i] = eq
    return pd.Series(out, index=rets.index)


def stats(eq, a=None, b=None):
    e = eq[a:b] if a else eq
    yrs = (e.index[-1] - e.index[0]).days / 365.25
    cagr = (e.iloc[-1] / e.iloc[0]) ** (1 / yrs) - 1
    m = e.resample("ME").last().pct_change().dropna()
    return cagr, (e / e.cummax() - 1).min(), m.mean() / m.std() * math.sqrt(12)


def row(name, eq, bench):
    c, d, s = stats(eq)
    parts, wins = [], 0
    for a, b in SUB.values():
        if eq[a:b].empty or eq[a:b].index[0] > pd.Timestamp(a) + pd.Timedelta(days=400):
            parts.append(f"{'-':>17s}")
            continue
        cc, cb = stats(eq, a, b)[0], stats(bench, a, b)[0]
        wins += cc > cb
        parts.append(f"{cc:+6.1%} vs {cb:+6.1%}")
    ex = (eq.resample("ME").last().pct_change() - bench.resample("ME").last().pct_change()).dropna()
    t = ex.mean() / ex.std(ddof=1) * math.sqrt(len(ex))
    print(f"{name:26s} {c:+8.1%} {d:7.1%} {s:6.2f} | " + " | ".join(parts) + f" | t {t:+.2f}")
    return c, d, wins, t


def verdict(res, bench):
    c, d, w, t = res
    cb, db = stats(bench)[:2]
    print(f"{'':26s} -> (a) {'ja' if c > cb and w >= 2 else 'nein'} ({w}/3 Teilzeiträume)  "
          f"(b) {'ja' if d >= db else 'nein'}  (c) {'ja' if t >= 2.5 else 'nein'}")


def main():
    df = pd.DataFrame({k: fetch_daily_yahoo(k, date(1992, 12, 1), date(2026, 10, 1))
                       for k in ("SPY", "VFITX", "VUSTX", "GC=F")})
    df.index = pd.to_datetime(df.index)
    df = df[df.index <= "2026-09-30"]
    rets = df.pct_change()
    tbill = fred("DTB3")
    base = rets[["SPY", "VFITX", "VUSTX"]].dropna()
    gold = rets[["SPY", "VFITX", "GC=F"]].dropna()
    gold = gold[gold.index >= "2000-09-01"]
    spy = portfolio(base, {"SPY": 1.0}, tbill, fee=0.0)
    p1 = portfolio(base, {"SPY": 0.9, "VFITX": 0.6}, tbill)
    p2 = portfolio(base, {"SPY": 0.9, "VUSTX": 0.6}, tbill)
    spy_g = portfolio(gold, {"SPY": 1.0}, tbill, fee=0.0)
    p3 = portfolio(gold, {"SPY": 0.9, "VFITX": 0.375, "GC=F": 0.225}, tbill)
    tb = tbill.reindex(base.index, method="ffill").fillna(0)
    l3 = pd.DataFrame({"U": 3 * base["SPY"] - 2 * (tb + 0.005) / 252 - 0.009 / 252,
                       "T": 3 * base["VUSTX"] - 2 * (tb + 0.005) / 252 - 0.009 / 252})
    p4 = portfolio(l3, {"U": 0.55, "T": 0.45}, tbill * 0, period="Q", fee=0.0)
    print(f"Daten {base.index[0].date()} bis {base.index[-1].date()}; P3 ab {gold.index[0].date()}\n")
    print(f"{'Portfolio':26s} {'p.a.':>8s} {'MaxDD':>7s} {'Sharpe':>6s} | "
          + " | ".join(f"{k:>17s}" for k in SUB) + " | Überrendite/Monat")
    row("P0 SPY", spy, spy)
    verdict(row("P1 90/60 mittlere Anl.", p1, spy), spy)
    verdict(row("P2 90/60 lange Anl.", p2, spy), spy)
    row("P0 SPY (ab 2000-09)", spy_g, spy_g)
    verdict(row("P3 90/37,5/22,5 Gold", p3, spy_g), spy_g)
    row("P4 HFEA 3x (nur Info)", p4, spy)
    print("\nKalenderjahre  SPY / P1 / P2 / P3 / P4:")
    yr = pd.DataFrame({k: e.resample("YE").last().pct_change() for k, e in
                       {"SPY": spy, "P1": p1, "P2": p2, "P3": p3, "P4": p4}.items()})
    for y, v in yr.iloc[1:].iterrows():
        print(f"  {y.year}: " + " / ".join(f"{x:+6.1%}" for x in v))


if __name__ == "__main__":
    main()

"""Runde 150: Nacht/Tag bei den Magnificent 7 -- Vorab: PROTOCOL.md Runde 150.

Aufruf aus dem Haupt-Repo (Daten relativ): PYTHONPATH=<worktree> python <worktree>/research/scripts/r150.py
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from tradingbot.research import history

STOCKS = ("AAPL", "MSFT", "AMZN", "GOOGL", "META", "NVDA", "TSLA")
UNTIL = date(2026, 10, 9)                # exklusiv -> bis 2026-10-08
CACHE = Path("data_cache/yahoo_r150")
C_SIDE, SEC = 1e-4, 0.28e-4
T_A, T_B = 2.69, 2.82                    # Bonferroni 14 (Teil A) bzw. 21 (Teil B), einseitig
PERIODS = [("bis 2007", "1900-01-01", "2007-12-31"), ("2008-2015", "2008-01-01", "2015-12-31"),
           ("2016-2026", "2016-01-01", "2026-12-31")]


def tstat(x) -> float:
    x = pd.Series(x).dropna()
    return float(x.mean() / x.std(ddof=1) * np.sqrt(len(x))) if len(x) > 2 and x.std() > 0 else float("nan")


def load(sym: str) -> pd.DataFrame:
    df = history.fetch_yahoo(sym, base=CACHE, until=UNTIL).copy()
    df.index = pd.DatetimeIndex([pd.Timestamp(d) for d in df.index])
    pc = df["close"].shift(1)
    df["night"] = (df["open"] + df["dividend"]) / pc - 1
    df["day"] = df["close"] / df["open"] - 1
    df["hold"] = df["adjclose"].pct_change()
    df["stale"] = (df["open"] - pc).abs() < 1e-9
    return df.dropna(subset=["night", "day"])


def describe(name: str, df: pd.DataFrame) -> str:
    lines, signs = [], []
    for label, a, b in PERIODS:
        x = df[(df.index >= a) & (df.index <= b)]
        if len(x) < 60:
            continue
        signs.append((x["night"].mean() > 0, x["day"].mean() < 0))
        lines.append(f"  {label:10s} {len(x):5d} Tage  Nacht Ø {x['night'].mean() * 1e4:+6.2f} bp (t {tstat(x['night']):+5.2f})"
                     f"  Tag Ø {x['day'].mean() * 1e4:+6.2f} bp (t {tstat(x['day']):+5.2f})")
    tn, td = tstat(df["night"]), tstat(df["day"])
    lines.append(f"  {'gesamt':10s} {len(df):5d} Tage  Nacht Ø {df['night'].mean() * 1e4:+6.2f} bp (t {tn:+5.2f})"
                 f"  Tag Ø {df['day'].mean() * 1e4:+6.2f} bp (t {td:+5.2f})")
    night_ok = df["night"].mean() > 0 and tn >= T_A and all(s[0] for s in signs)
    day_ok = df["day"].mean() < 0 and td <= -T_A and all(s[1] for s in signs)
    verdict = "BESTÄTIGT" if night_ok and day_ok else "TEILWEISE" if night_ok or day_ok else "WIDERLEGT"
    return (f"{name} (ab {df.index[0].date()}, Eröffnung = Vortagesschluss an {df['stale'].mean():.1%} der Tage): "
            f"{verdict} (Nacht {'erfüllt' if night_ok else 'nicht erfüllt'}, Tag {'erfüllt' if day_ok else 'nicht erfüllt'})\n"
            + "\n".join(lines))


def strategies(df: pd.DataFrame) -> pd.DataFrame:
    rt = 2 * C_SIDE + SEC
    return pd.DataFrame({
        "S1 Nacht long": df["night"] - rt,
        "S2 Nacht long + Tag short": (1 + df["night"]) * (1 - df["day"]) - 1 - 2 * rt,
        "S3 Tag short": -df["day"] - rt,
    }, index=df.index)


def pa(r: pd.Series) -> float:
    r = r.dropna()
    return float((1 + r).prod() ** (252 / len(r)) - 1) if len(r) else float("nan")


def monthly(r: pd.Series) -> pd.Series:
    return (1 + r).groupby(r.index.to_period("M")).prod() - 1


def main():
    spy = load("SPY")["hold"]
    data = {s: load(s) for s in STOCKS}
    print("Runde 150 -- Nacht/Tag bei den Magnificent 7 (Rückschaufehler: Auswahl nach späterem Erfolg)\n")
    print("Teil A -- bestätigt: gesamt Nacht t >= 2,69 und Tag t <= -2,69, Vorzeichen in jedem Teilzeitraum")
    for s, df in data.items():
        print(describe(s, df))

    print("\nTeil B -- gegen SPY halten (bestanden: Haupt 2008/Börsengang-2026 > SPY, t >= 2,82, Einordnung bis 2007 > 0)")
    for s, df in data.items():
        st = strategies(df)
        main_mask = df.index >= "2008-01-01"
        hold_main = pa(df["hold"][main_mask])
        print(f"{s} (Halten {s} im Hauptzeitraum {hold_main:+.1%} p.a.):")
        for col in st:
            m = st[col][main_mask]
            spy_m = spy.reindex(m.index).fillna(0)
            t = tstat(monthly(m) - monthly(spy_m))
            pre = st[col][~main_mask]
            if len(pre) > 250:
                pre_ex = pa(pre) - pa(spy.reindex(pre.index).fillna(0))
                pre_txt, pre_ok = f"{pre_ex:+7.1%} p.a.", pre_ex > 0
            else:
                pre_txt, pre_ok = "entfällt", True
            passed = pa(m) > pa(spy_m) and t >= T_B and pre_ok
            print(f"  {col:28s} {pa(m):+7.1%} p.a. (SPY {pa(spy_m):+6.1%}, Halten {hold_main:+6.1%}), t ggü. SPY {t:+5.2f}, "
                  f"Einordnung bis 2007 {pre_txt} -> {'BESTANDEN' if passed else 'nicht bestanden'}")

    print("\nJahre (Ø bp je Tag, Nacht / Tag)")
    print("  Jahr " + "".join(f"{s:>15s}" for s in STOCKS))
    for y in range(1993, 2027):
        cells = []
        for s in STOCKS:
            x = data[s][data[s].index.year == y]
            cells.append(f"{x['night'].mean() * 1e4:+6.1f}/{x['day'].mean() * 1e4:+6.1f}" if len(x) else "")
        if any(cells):
            print(f"  {y} " + "".join(f"{c:>15s}" for c in cells))


if __name__ == "__main__":
    main()

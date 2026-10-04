"""Runde 142: erfolgreichste Abgeordnete (rollierendes 3-Jahres-Fenster) kopieren -- Vorab: PROTOCOL.md."""
import math
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import r141 as R  # noqa: E402

PRE, MAIN = ("2019-01-01", "2021-12-31"), ("2022-01-01", "2026-09-30")


def signal_excess(buys, spy):
    """12-Monats-Überrendite je Signal und Enddatum der Haltedauer (NaN, wenn nicht abgeschlossen/kein Kurs)."""
    d = spy.index
    ex, end = [], []
    for r in buys.itertuples():
        i = d.searchsorted(pd.Timestamp(r.filing_date), side="right") + 1
        p = R.price(r.ticker)
        if i + 252 >= len(d) or p is None or p.index[0] > d[i] or p.index[-1] < d[i + 252]:
            ex.append(np.nan)
            end.append(pd.NaT)
            continue
        p = p.reindex(d[i:i + 253]).ffill()
        ex.append(p.iloc[-1] / p.iloc[0] * (1 - R.COST) ** 2 - 1 - (spy.iloc[i + 252] / spy.iloc[i] - 1))
        end.append(d[i + 252])
    return buys.assign(ex=ex, end=end)


def select(sig, year, top, metric):
    start = pd.Timestamp(f"{year}-01-01")
    w = sig[(sig.fy >= year - 3) & (sig.fy <= year - 1) & sig.ex.notna() & (sig.end < start)]
    g = w.groupby("member").ex.agg(["mean", "std", "count"])
    g = g[g["count"] >= 5]
    g["t"] = g["mean"] / g["std"] * np.sqrt(g["count"])
    return list(g.sort_values(metric, ascending=False).head(top).index), g


def run(sig, spy, top=5, metric="mean", verbose=False):
    parts = []
    for y in range(2019, 2027):
        chosen, g = select(sig, y, top, metric)
        parts.append(sig[(sig.fy == y) & sig.member.isin(chosen)])
        if verbose:
            print(f"  {y}: " + "; ".join(f"{m} ({g.loc[m, 'mean']:+.0%}, n={int(g.loc[m, 'count'])}, "
                                         f"{int((sig[(sig.fy == y) & (sig.member == m)]).shape[0])} Käufe)"
                                         for m in chosen))
    s = pd.concat(parts)
    eq, used, miss, inv = R.backtest(s, spy)
    out = []
    for lab, (a, b) in (("2019-21", PRE), ("2022-26", MAIN)):
        c, cs, dd, t = R.stats(eq, spy, a, b)
        out.append((c, cs, t))
        print(f"  Top {top} nach {metric:4s} {lab}: {c:+6.1%} vs SPY {cs:+6.1%}  MaxDD {dd:6.1%}  t {t:+.2f}")
    print(f"  {'':20s} Signale {used}, ohne Kurs {miss}, investiert {inv:.0%}")
    return out


def main():
    tr = pd.read_csv(R.D / "trades.csv", parse_dates=["filing_date"])
    tr["ticker"] = tr.ticker.replace({"FB": "META", "SQ": "XYZ"})
    buys = tr[tr.type == "P"].drop_duplicates(["doc", "ticker"]).copy()
    buys["member"] = buys["first"].astype(str) + " " + buys["last"].astype(str)
    buys["fy"] = buys.filing_date.dt.year
    buys["filing_date"] = buys.filing_date.dt.date
    spy = R.fetch_daily_yahoo("SPY", date(2014, 6, 1), date(2026, 10, 3))
    spy.index = pd.to_datetime(spy.index)
    spy = spy[spy.index <= "2026-09-30"]
    sig = signal_excess(buys, spy)
    print(f"{len(sig)} Kaufsignale, {sig.member.nunique()} Mitglieder, {sig.ex.notna().sum()} mit 12-M-Ergebnis\n")
    print("HAUPTREGEL (Kriterium: 2022-26 > SPY und t >= 2,0; 2019-21 Überrendite > 0); Auswahl je Jahr:")
    (c0, s0, t0), (c1, s1, t1) = run(sig, spy, verbose=True)
    print(f"  -> {'BESTANDEN' if c1 > s1 and t1 >= 2.0 and c0 > s0 else 'nicht bestanden'}\n\nNUR INFO")
    run(sig, spy, top=10)
    run(sig, spy, top=3)
    run(sig, spy, top=5, metric="t")
    # Beständigkeit: Rangkorrelation Fenster-Kennzahl vs Folgejahr-Ergebnis je Mitglied
    rows = []
    for y in range(2019, 2026):
        _, g = select(sig, y, 10 ** 6, "mean")
        nxt = sig[(sig.fy == y) & sig.ex.notna()].groupby("member").ex.mean()
        j = g.join(nxt.rename("next"), how="inner")
        if len(j) > 5:
            rows.append((y, len(j), j["mean"].corr(j["next"], method="spearman")))
    print("\nRangkorrelation (Fenster -> Folgejahr):", ", ".join(f"{y}: {r:+.2f} (n={n})" for y, n, r in rows))


if __name__ == "__main__":
    main()

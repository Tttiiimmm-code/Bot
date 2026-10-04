"""Runde 144: Momentum großer Aktien long-only (French BIG HiPRIOR) vs Markt -- Vorab: PROTOCOL.md."""
import io
import math
from pathlib import Path

import numpy as np
import pandas as pd

F = Path(r"C:\Users\Nutzer\Bot\data_cache\french")
COST = 0.010 / 12


def monthly_block(path, header_startswith):
    lines = path.read_text(encoding="latin-1").splitlines()
    start = next(i for i, l in enumerate(lines) if l.startswith(header_startswith))
    rows = [lines[start]]
    for l in lines[start + 1:]:
        if not l.strip() or not l.strip()[:6].isdigit() or len(l.split(",")[0].strip()) != 6:
            break
        rows.append(l)
    d = pd.read_csv(io.StringIO("\n".join(rows)), index_col=0)
    d.index = pd.to_datetime(d.index.astype(str).str.strip(), format="%Y%m") + pd.offsets.MonthEnd(0)
    return d.apply(pd.to_numeric) / 100


def stats(ex, mom, mkt):
    t = ex.mean() / ex.std(ddof=1) * math.sqrt(len(ex))
    yrs = len(mom) / 12
    cm, ck = (1 + mom).prod() ** (1 / yrs) - 1, (1 + mkt).prod() ** (1 / yrs) - 1
    dd = lambda r: ((1 + r).cumprod() / (1 + r).cumprod().cummax() - 1).min()
    return f"{cm:+6.1%} vs Markt {ck:+6.1%} p.a. (Diff {cm - ck:+5.1%}), t {t:+.2f}, MaxDD {dd(mom):6.1%} vs {dd(mkt):6.1%}"


def main():
    p = monthly_block(F / "6_Portfolios_ME_Prior_12_2.csv", ",SMALL LoPRIOR")
    ff = monthly_block(F / "F-F_Research_Data_Factors.csv", ",Mkt-RF")
    df = pd.DataFrame({"mom": p["BIG HiPRIOR"] - COST, "mkt": ff["Mkt-RF"] + ff["RF"]}).dropna()
    df["ex"] = df.mom - df.mkt
    print(f"Daten {df.index[0]:%Y-%m} bis {df.index[-1]:%Y-%m}, Kosten 1,0 % p.a.\n")
    for lab, a, b in (("HAUPT 1994-heute", "1994-01", None), ("Zusatz 2010-heute", "2010-01", None),
                      ("Info 1927-1993", "1927-01", "1993-12"), ("Info gesamt", "1927-01", None)):
        x = df.loc[a:b]
        print(f"{lab:18s}: {stats(x.ex, x.mom, x.mkt)}")
    h, z = df.loc["1994-01":], df.loc["2010-01":]
    th = h.ex.mean() / h.ex.std(ddof=1) * math.sqrt(len(h))
    print(f"\n-> {'BESTANDEN' if th >= 2.0 and h.ex.mean() > 0 and z.ex.mean() > 0 else 'nicht bestanden'}")
    print("\nJahrzehnte (Überrendite p.a.):", ", ".join(
        f"{d}er {((1 + g.mom).prod() ** (12 / len(g)) - (1 + g.mkt).prod() ** (12 / len(g))):+.1%}"
        for d, g in df.groupby(df.index.year // 10 * 10)))
    roll = (1 + df.ex).rolling(36).apply(np.prod, raw=True) - 1
    print("Schlechteste 3-Jahres-Phasen (Überrendite):",
          ", ".join(f"bis {i:%Y-%m} {v:+.0%}" for i, v in roll.nsmallest(40).groupby(roll.nsmallest(40).index.year).head(1).head(5).items()))
    print("Anteil 3-Jahres-Phasen mit Momentum > Markt (seit 1994):", f"{(roll.loc['1996-12':] > 0).mean():.0%}")
    print("Kalenderjahre seit 2015:", ", ".join(
        f"{y}: {(1 + g.mom).prod() - (1 + g.mkt).prod():+.0%}" for y, g in df.loc["2015":].groupby(df.loc["2015":].index.year)))


if __name__ == "__main__":
    main()

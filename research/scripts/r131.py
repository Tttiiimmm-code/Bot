"""Runde 131: Geopolitical Risk Index (Caldara & Iacoviello, täglich) als Handelssignal -- Vorab: PROTOCOL.md."""
import itertools
import math
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path.cwd()))
from tradingbot.forward_test import fetch_daily_yahoo  # noqa: E402

COOLDOWN = 60
PERIODS = {"Entdeckung": ("1985-01-01", "2009-12-31"), "Bestätigung": ("2010-01-01", "2026-09-30")}
ASSETS = {"S&P 500": ("^GSPC", date(1985, 1, 1)), "Gold": ("GC=F", date(2000, 1, 1)),
          "Rohöl": ("CL=F", date(2000, 1, 1)), "Rüstung ITA": ("ITA", date(2006, 5, 1))}


def tstat(x):
    x = np.asarray(x, float)
    return float(x.mean() / x.std(ddof=1) * math.sqrt(len(x))) if len(x) > 2 and x.std() > 0 else float("nan")


def events(s: pd.Series, q: float) -> list[pd.Timestamp]:
    s = s[s.index.dayofweek < 5]
    thr = s.shift(1).rolling(252).quantile(q)
    out, block = [], -1
    for i, (t, v) in enumerate(s.items()):
        if i > block and not np.isnan(thr.iloc[i]) and v > thr.iloc[i]:
            out.append(t)
            block = i + COOLDOWN
    return out


def main():
    g = pd.read_excel("data_cache/gpr/data_gpr_daily_recent.xls")
    g.index = pd.to_datetime(g["date"])
    prices = {}
    for name, (sym, start) in ASSETS.items():
        p = fetch_daily_yahoo(sym, start, date(2026, 10, 2))
        p.index = pd.to_datetime(p.index)
        prices[name] = p[p > 0]
    rows = []
    for sig, q, h, asset in itertools.product(("GPRD", "GPRD_ACT"), (0.95, 0.99), (5, 20, 60), ASSETS):
        p = prices[asset]
        fwd = p.shift(-h) / p - 1
        for per, (a, b) in PERIODS.items():
            # nur Ereignisse ab Datenbeginn des Markts (Korrektur: vorher wurden frühere Ereignisse auf die
            # ersten Handelstage gelegt)
            ev = [t for t in events(g[sig].dropna(), q) if max(pd.Timestamp(a), p.index[0]) <= t <= pd.Timestamp(b)]
            base = fwd[a:b].dropna().mean()
            ex = []
            for t in ev:
                pos = p.index.searchsorted(t, side="right")          # erster Handelstag NACH dem Indextag
                if pos + h < len(p) and p.index[pos] <= pd.Timestamp(b) + pd.Timedelta(days=10):
                    ex.append(p.iloc[pos + h] / p.iloc[pos] - 1 - base)
            rows.append(dict(sig=sig, q=q, h=h, asset=asset, per=per, n=len(ex),
                             avg=np.mean(ex) if ex else np.nan, t=tstat(ex), pos=np.mean(np.array(ex) > 0) if ex else np.nan))
    df = pd.DataFrame(rows)
    df.to_csv(Path(__file__).with_name("r131_results.csv"), index=False)
    d = df[df.per == "Entdeckung"].copy()
    print(f"Entdeckung: {len(d)} Tests | Ø > 0: {(d.avg > 0).sum()} | t >= 2: {(d.t >= 2).sum()} | t >= 3: {(d.t >= 3).sum()}")
    show = df.pivot_table(index=["sig", "q", "h", "asset"], columns="per", values=["n", "avg", "t"])
    pd.set_option("display.width", 200)
    fmt = show.copy()
    for per in PERIODS:
        fmt[("avg", per)] = (show[("avg", per)] * 100).round(2)
        fmt[("t", per)] = show[("t", per)].round(2)
    print(fmt.to_string())
    elig = d[(d.n >= 15) & (d.avg > 0) & (d.t >= 3)].sort_values("t", ascending=False).head(3)
    print(f"\n--- Zählende Auswahl (n >= 15, Ø > 0, t >= 3): {len(elig)}")
    for _, r in elig.iterrows():
        c = df[(df.sig == r.sig) & (df.q == r.q) & (df.h == r.h) & (df.asset == r.asset) & (df.per == "Bestätigung")].iloc[0]
        ok = c.avg > 0 and c.t >= 2
        print(f"  {r.sig} {r.q} {r.h} T {r.asset}: Entdeckung {r.avg:+.2%} (t {r.t:.2f}, n {r.n}) -> Bestätigung "
              f"{c.avg:+.2%} (t {c.t:.2f}, n {c.n}) -> {'BESTANDEN' if ok else 'nicht bestanden'}")
    if elig.empty:
        print("  keine -> RUNDE NICHT BESTANDEN")


if __name__ == "__main__":
    main()

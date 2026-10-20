"""Runde 159: Spot-Grid-Bot (Pionex/Binance-Stil) auf BTC/USDT -- Vorab: PROTOCOL.md Runde 159.

Aufruf aus dem Haupt-Repo: PYTHONPATH=<worktree> python <worktree>/research/scripts/r159.py
"""
from __future__ import annotations

from pathlib import Path

import numba
import numpy as np
import pandas as pd

from r153 import spy_daily, tstat

FEE = 0.0005
A, B = "2020-01-01", "2026-08-31"
HALF = pd.Period("2022-12", "M")


def load() -> pd.DataFrame:
    parts = []
    for f in sorted(Path("data_cache/btc_1m").glob("BTCUSDT-1m-*.csv")):
        d = pd.read_csv(f, header=None, usecols=[0, 1, 2, 3, 4])
        if not str(d.iloc[0, 0]).isdigit():
            d = d.iloc[1:]
        parts.append(d.astype(float))
    df = pd.concat(parts, ignore_index=True)
    ts = df[0].to_numpy()
    ts = np.where(ts > 1e14, ts / 1000, ts)                       # Binance ab 2025: Mikrosekunden
    df.index = pd.to_datetime(ts, unit="ms")
    df = df[~df.index.duplicated()].sort_index()
    df.columns = ["t", "o", "h", "l", "c"]
    return df[["o", "h", "l", "c"]]


@numba.njit(cache=True)
def grid(o, h, l, c, block, n, lo_m, hi_m, restart):
    m = len(c)
    lower = np.zeros(n); upper = np.zeros(n); hold = np.zeros(n, np.bool_); qty = np.zeros(n); quote = np.zeros(n)
    eq_out = np.zeros(m)
    cash = 1.0
    sells = 0

    def init(p, cash, lower, upper, hold, qty, quote):
        r = (hi_m / lo_m) ** (1.0 / n)
        q = cash / n
        for i in range(n):
            lower[i] = lo_m * p * r ** i
            upper[i] = lower[i] * r
            quote[i] = q
            if lower[i] >= p:
                hold[i] = True
                qty[i] = q / p * (1 - FEE)
                cash -= q
            else:
                hold[i] = False
                qty[i] = 0.0
        return cash

    cash = init(o[0], cash, lower, upper, hold, qty, quote)
    for j in range(m):
        if restart and j > 0 and block[j] != block[j - 1]:
            p = c[j - 1]
            for i in range(n):
                if hold[i]:
                    cash += qty[i] * p * (1 - FEE)
                    hold[i] = False
                    qty[i] = 0.0
            cash = init(p, cash, lower, upper, hold, qty, quote)
        if c[j] >= o[j]:
            path = (o[j], l[j], h[j], c[j])
        else:
            path = (o[j], h[j], l[j], c[j])
        for s in range(3):
            a, b = path[s], path[s + 1]
            if b < a:
                for i in range(n):
                    if not hold[i] and b <= lower[i] < a and cash >= quote[i] * 0.999:
                        qty[i] = quote[i] / lower[i] * (1 - FEE)
                        cash -= quote[i]
                        hold[i] = True
            elif b > a:
                for i in range(n):
                    if hold[i] and a < upper[i] <= b:
                        cash += qty[i] * upper[i] * (1 - FEE)
                        qty[i] = 0.0
                        hold[i] = False
                        sells += 1
        v = cash
        for i in range(n):
            v += qty[i] * c[j]
        eq_out[j] = v
    return eq_out, sells


def pa_m(x):
    return float((1 + x).prod() ** (12 / len(x)) - 1)


def main():
    df = load()
    df = df[(df.index >= A) & (df.index < "2026-09-01")]
    o, h, l_, c = (df[k].to_numpy() for k in "ohlc")
    mins = (df.index.as_unit("ns").asi8 // 60_000_000_000)        # to_datetime(unit="ms") behält ms-Auflösung
    block = (mins - mins[0]) // (30 * 1440)
    spy = spy_daily()
    spy_m = (1 + spy).groupby(spy.index.to_period("M")).prod() - 1
    btc_m = df["c"].resample("ME").last().pct_change()
    btc_m.index = btc_m.index.to_period("M")
    print(f"Runde 159 -- Spot-Grid BTC/USDT, {len(df):,} Minuten {df.index[0]:%Y-%m-%d} bis {df.index[-1]:%Y-%m-%d}\n")

    def report(label, n, lo, hi, restart, binding):
        eq, sells = grid(o, h, l_, c, block, n, lo, hi, restart)
        e = pd.Series(eq, index=df.index).resample("ME").last()
        r = e.pct_change()
        r.iloc[0] = e.iloc[0] - 1
        r.index = r.index.to_period("M")
        s = spy_m.reindex(r.index).fillna(0.0)
        ex = r - s
        t = tstat(ex)
        h1, h2 = r.index <= HALF, r.index > HALF
        e1, e2 = pa_m(r[h1]) - pa_m(s[h1]), pa_m(r[h2]) - pa_m(s[h2])
        dd = float((e / e.cummax() - 1).min())
        ok = pa_m(r) > pa_m(s) and t >= 2.0 and e1 > 0 and e2 > 0
        print(f"  {label}: {pa_m(r):+6.1%} p.a. vs SPY {pa_m(s):+6.1%}, t {t:+.2f}, Hälften {e1:+6.1%} / {e2:+6.1%}, "
              f"Max-DD (Monat) {dd:.1%}, Grid-Verkäufe {sells:,}"
              + (f" -> {'BESTANDEN' if ok else 'NICHT BESTANDEN'}" if binding else " (Info)"))

    print("Hauptkriterium (50 Intervalle, 0,80-1,25 x Kurs, Neustart alle 30 Tage, 0,05 % je Füllung):")
    report("Grid 50", 50, 0.80, 1.25, True, True)
    print("\nInfo (nicht gewertet):")
    b = btc_m.reindex(spy_m.index).dropna()
    b = b[(b.index >= pd.Period(A[:7], "M")) & (b.index <= pd.Period(B[:7], "M"))]
    print(f"  BTC halten: {pa_m(b):+6.1%} p.a., Max-DD {float((((1 + b).cumprod()) / ((1 + b).cumprod()).cummax() - 1).min()):.1%}")
    report("Grid 50 ohne Neustart", 50, 0.80, 1.25, False, False)
    report("Grid 20", 20, 0.80, 1.25, True, False)
    report("Grid 100", 100, 0.80, 1.25, True, False)
    report("Grid 50, Spanne 0,90-1,11", 50, 0.90, 1.11, True, False)


if __name__ == "__main__":
    main()

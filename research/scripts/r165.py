"""Runde 165: TradingView-Klassiker (MACD+EMA200, Heikin-Ashi, Stochastik, TTM Squeeze) auf 15 ETFs.

Vorab: PROTOCOL.md Runde 165. Aufruf aus dem Haupt-Repo: PYTHONPATH=<worktree> python <worktree>/research/scripts/r165.py
"""
from __future__ import annotations

import json
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

from r153 import spy_daily, tstat
from r158 import fred

ETFS = "SPY QQQ IWM DIA EFA EEM TLT IEF GLD SLV XLE XLF XLK VNQ DBC".split()
CACHE = Path("data_cache/r165")
COST = 2e-4
MAIN, CLASS = (pd.Period("2016-01", "M"), pd.Period("2026-08", "M")), (pd.Period("2006-01", "M"), pd.Period("2015-12", "M"))
T_PASS = 2.24


def ohlc(sym: str) -> pd.DataFrame:
    CACHE.mkdir(parents=True, exist_ok=True)
    f = CACHE / f"{sym}.json"
    if not f.exists():
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?period1=946684800&period2=1790000000&interval=1d"
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=60) as r:
            f.write_bytes(r.read())
    res = json.loads(f.read_text())["chart"]["result"][0]
    q = res["indicators"]["quote"][0]
    idx = pd.to_datetime(res["timestamp"], unit="s", utc=True).tz_convert("America/New_York").tz_localize(None).normalize()
    df = pd.DataFrame({k: q[k] for k in ("open", "high", "low", "close")}, index=idx, dtype=float)
    df["adj"] = res["indicators"]["adjclose"][0]["adjclose"]
    df = df[~df.index.duplicated(keep="last")].dropna()
    k = df["adj"] / df["close"]
    for c in ("open", "high", "low", "close"):
        df[c] = df[c] * k
    return df[df.index <= "2026-08-31"]


def ema(x, n):
    return x.ewm(span=n, adjust=False).mean()


def cross_up(a, b):
    return (a > b) & (a.shift(1) <= b.shift(1))


def state(enter: pd.Series, leave: pd.Series) -> pd.Series:
    pos, out = 0.0, np.zeros(len(enter))
    for i, (e, x) in enumerate(zip(enter.to_numpy(), leave.to_numpy())):
        if pos == 0 and e:
            pos = 1.0
        elif pos == 1 and x:
            pos = 0.0
        out[i] = pos
    return pd.Series(out, index=enter.index)


def linreg_end(y: pd.Series, n: int = 20) -> pd.Series:
    x = np.arange(n)
    xm = x.mean()
    w = (x - xm) / ((x - xm) ** 2).sum()
    slope = y.rolling(n).apply(lambda v: float(np.dot(w, v)), raw=True)
    return y.rolling(n).mean() + slope * (n - 1 - xm)


def signals(d: pd.DataFrame) -> dict[str, pd.Series]:
    o, h, l, c = d["open"], d["high"], d["low"], d["close"]
    e200 = ema(c, 200)
    macd = ema(c, 12) - ema(c, 26)
    sig = ema(macd, 9)
    m = state(cross_up(macd, sig) & (c > e200), cross_up(sig, macd))
    hac = (o + h + l + c) / 4
    hao = np.zeros(len(c))
    hao[0] = (o.iloc[0] + c.iloc[0]) / 2
    hv = hac.to_numpy()
    for i in range(1, len(c)):
        hao[i] = (hao[i - 1] + hv[i - 1]) / 2
    ha = (hac > pd.Series(hao, index=c.index)).astype(float)
    ll, hh = l.rolling(14).min(), h.rolling(14).max()
    k = (100 * (c - ll) / (hh - ll)).rolling(3).mean()
    dd = k.rolling(3).mean()
    s = state(cross_up(k, dd) & (k < 20) & (c > e200), cross_up(dd, k) & (k > 80))
    sma = c.rolling(20).mean()
    sd = c.rolling(20).std(ddof=0)
    tr = pd.concat([h - l, (h - c.shift(1)).abs(), (l - c.shift(1)).abs()], axis=1).max(axis=1)
    rng = tr.rolling(20).mean()
    sq_on = (sma - 2 * sd > sma - 1.5 * rng) & (sma + 2 * sd < sma + 1.5 * rng)
    mom = linreg_end(c - ((h.rolling(20).max() + l.rolling(20).min()) / 2 + sma) / 2)
    fire = (~sq_on) & sq_on.shift(1, fill_value=False) & (mom > 0)
    t = state(fire, mom < mom.shift(1))
    valid = pd.Series(np.arange(len(c)) >= 200, index=c.index)
    return {k_: v.where(valid, np.nan) for k_, v in (("M", m), ("H", ha), ("S", s), ("T", t))}


def sleeve(d: pd.DataFrame, pos: pd.Series, tb: pd.Series) -> pd.Series:
    ret = d["adj"].pct_change()
    p = pos.shift(1)
    r = p * ret + (1 - p) * tb.reindex(ret.index).ffill().fillna(0.0) - pos.diff().abs().shift(1).fillna(0.0) * COST
    r = r[p.notna()]
    return (1 + r).groupby(r.index.to_period("M")).prod() - 1


def pa_m(x):
    return float((1 + x).prod() ** (12 / len(x)) - 1)


def main():
    tb = fred("DTB3") / 100 / 252
    data = {s: ohlc(s) for s in ETFS}
    sigs = {s: signals(d) for s, d in data.items()}
    spy = spy_daily()
    sm = (1 + spy).groupby(spy.index.to_period("M")).prod() - 1
    print("Runde 165 -- TradingView-Klassiker auf 15 ETFs (" + ", ".join(f"{s} ab {d.index[0]:%Y}" for s, d in data.items()) + ")\n")

    def judge(label, m, binding):
        lines, ok = [], True
        for name, (a, b) in (("Haupt 2016-01..2026-08", MAIN), ("Einordnung 2006-2015", CLASS)):
            r, s = m[a:b], sm.reindex(m[a:b].index).fillna(0.0)
            t = tstat(r - s)
            eq = (1 + r).cumprod()
            lines.append(f"    {name}: {pa_m(r):+6.1%} p.a. vs SPY {pa_m(s):+6.1%}, t {t:+.2f}, Max-DD (Monat) "
                         f"{float((eq / eq.cummax() - 1).min()):.1%}")
            ok &= (pa_m(r) > pa_m(s) and t >= T_PASS) if name.startswith("Haupt") else (r - s).mean() > 0
        print(f"  {label}:" + (f" -> {'BESTANDEN' if ok else 'NICHT BESTANDEN'}" if binding else " (Info)"))
        print("\n".join(lines))

    names = {"M": "MACD(12,26,9) + EMA200", "H": "Heikin-Ashi grün", "S": "Stochastik(14,3,3) + EMA200",
             "T": "TTM Squeeze"}
    print("Hauptkriterium je Regel (15 ETFs gleich gewichtet, flach = T-Bills, Hürde t >= 2,24):")
    for key, label in names.items():
        sl = pd.concat({s: sleeve(data[s], sigs[s][key], tb) for s in ETFS}, axis=1)
        invested = np.mean([sigs[s][key].mean() for s in ETFS])
        judge(f"{key} {label} (Ø investiert {invested:.0%})", sl.mean(axis=1), True)
    print("\nInfo (nicht gewertet):")
    bh = pd.concat({s: (1 + data[s]["adj"].pct_change().dropna()).groupby(
        data[s]["adj"].pct_change().dropna().index.to_period("M")).prod() - 1 for s in ETFS}, axis=1)
    judge("15 ETFs gleich gewichtet halten", bh.mean(axis=1), False)
    for key, label in names.items():
        judge(f"nur SPY, {label}", sleeve(data["SPY"], sigs["SPY"][key], tb), False)


if __name__ == "__main__":
    main()

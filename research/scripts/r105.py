"""Runde 105: 1.296 Konfigurationen Rückkehr zum Mittelwert (D1, 24 Märkte) -- Vorab: r105_prereg.md."""
from __future__ import annotations

import itertools
import sys
import time
from pathlib import Path

import numba
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from r102 import load, resample  # noqa: E402

OUT = Path(__file__).with_name("r105_results.pkl")
MARKETS = ("xauusd", "xagusd", "eurusd", "gbpusd", "usdjpy", "usdchf", "usdcnh", "audusd", "nzdusd", "usdsek",
           "gbpjpy", "eurjpy", "chfjpy", "usatechidxusd", "usa500idxusd", "usa30idxusd", "deuidxeur", "gbridxgbp",
           "fraidxeur", "eusidxeur", "jpnidxjpy", "hkgidxhkd", "ausidxaud", "lightcmdusd")
PERIODS = {"Training": ("2012-07-01", "2017-12-31"), "Bestätigung": ("2018-01-01", "2021-12-31"),
           "Endtest": ("2022-01-01", "2026-12-31")}
ENTRIES = [("RSI2", x) for x in (5, 10, 20)] + [("BB", x) for x in (1.5, 2.0, 2.5)] + \
          [("IBS", x) for x in (0.1, 0.2, 0.3)] + [("Tief", x) for x in (5, 10, 20)] + \
          [("Folge", x) for x in (2, 3, 4)] + [("SMA10-ATR", x) for x in (1.0, 1.5, 2.0)]
TRENDS = ("kein", "SMA100", "SMA200")
EXITS = (("Schluss>SMA5", 10), ("RSI2>70", 10), ("erster höherer Schluss", 10), ("nach 5 Tagen", 5))
STOPS = (0.0, 2.0, 3.0)
DIRS = ("nur long", "beide")


def wilder(s, n):
    return s.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def rsi(c, n):
    d = c.diff()
    g, l_ = wilder(d.clip(lower=0), n), wilder((-d).clip(lower=0), n)
    return 100 - 100 / (1 + g / l_.replace(0, np.nan))


def streak(cond):
    grp = (~cond).cumsum()
    return cond.astype(int).groupby(grp).cumsum()


def indicators(d1):
    c, h, l_ = d1["close"], d1["high"], d1["low"]
    pc = c.shift(1)
    tr = pd.concat([h - l_, (h - pc).abs(), (l_ - pc).abs()], axis=1).max(axis=1)
    x = pd.DataFrame(index=d1.index)
    x["atr"] = wilder(tr, 20)
    x["rsi2"] = rsi(c, 2)
    m20, s20 = c.rolling(20).mean(), c.rolling(20).std()
    x["z"] = (c - m20) / s20
    x["ibs"] = ((c - l_) / (h - l_)).where(h > l_)
    for n in (5, 10, 20):
        x[f"low{n}"] = c <= c.rolling(n).min()
        x[f"high{n}"] = c >= c.rolling(n).max()
    x["down"], x["up"] = streak(c < pc), streak(c > pc)
    x["dist"] = (c - c.rolling(10).mean()) / x["atr"]
    x["sma5"], x["sma100"], x["sma200"] = c.rolling(5).mean(), c.rolling(100).mean(), c.rolling(200).mean()
    x["c"], x["pc"] = c, pc
    return x


def entry_signal(x, kind, v):
    if kind == "RSI2":
        return x.rsi2 < v, x.rsi2 > 100 - v
    if kind == "BB":
        return x.z < -v, x.z > v
    if kind == "IBS":
        return x.ibs < v, x.ibs > 1 - v
    if kind == "Tief":
        return x[f"low{int(v)}"], x[f"high{int(v)}"]
    if kind == "Folge":
        return x.down >= v, x.up >= v
    return x.dist < -v, x.dist > v


def exit_flags(x, i):
    if i == 0:
        return (x.c > x.sma5).to_numpy(), (x.c < x.sma5).to_numpy()
    if i == 1:
        return (x.rsi2 > 70).to_numpy(), (x.rsi2 < 30).to_numpy()
    if i == 2:
        return (x.c > x.pc).to_numpy(), (x.c < x.pc).to_numpy()
    z = np.zeros(len(x), dtype=np.bool_)
    return z, z


@numba.njit(cache=True)
def run(sig_day, sig_side, sig_atr, dep, ex_l, ex_s, maxhold, mult, bo, bh, bl, bc, ao, ah, al, ac):
    n, nd = len(bo), len(dep)
    out_p = np.empty(len(sig_day), np.int64)
    out_r = np.empty(len(sig_day), np.float64)
    k, busy = 0, -1
    for s in range(len(sig_day)):
        d0, side, a = sig_day[s], sig_side[s], sig_atr[s]
        if d0 <= busy or not (a > 0):
            continue
        p = dep[d0]
        if p >= n:
            continue
        entry = ao[p] if side > 0 else bo[p]
        stop = entry - side * mult * a
        ex, exit_day = np.nan, nd
        dd = d0 + 1
        while True:
            if dd >= nd:
                ex = bc[n - 1] if side > 0 else ac[n - 1]
                break
            lo_i, hi_i = dep[dd - 1], min(dep[dd], n)
            hit = False
            if mult > 0:
                for i in range(lo_i, hi_i):
                    if side > 0:
                        if i > p and bo[i] <= stop:
                            ex, hit = bo[i], True
                        elif bl[i] <= stop:
                            ex, hit = stop, True
                    else:
                        if i > p and ao[i] >= stop:
                            ex, hit = ao[i], True
                        elif ah[i] >= stop:
                            ex, hit = stop, True
                    if hit:
                        break
            if hit:
                exit_day = dd
                break
            flag = ex_l[dd] if side > 0 else ex_s[dd]
            if flag or dd - d0 >= maxhold:
                q = dep[dd]
                if q >= n:
                    ex = bc[n - 1] if side > 0 else ac[n - 1]
                else:
                    ex = bo[q] if side > 0 else ao[q]
                exit_day = dd
                break
            dd += 1
        out_p[k] = p
        out_r[k] = side * (ex - entry) / a - 0.5e-4 * entry / a
        k += 1
        busy = exit_day
    return out_p[:k], out_r[:k]


def tstat(r):
    return float(r.mean() / r.std(ddof=1) * np.sqrt(len(r))) if len(r) > 2 and r.std() > 0 else float("nan")


def describe(r):
    if len(r) < 3:
        return f"n {len(r)}"
    w, l_ = r[r > 0].sum(), -r[r < 0].sum()
    return (f"n {len(r):5d}  Ø R {r.mean():+.3f}  t {tstat(r):+.2f}  Treffer {(r > 0).mean():.0%}  "
            f"PF {w / l_ if l_ > 0 else float('inf'):.2f}  Summe {r.sum():+.0f} R")


def name(key):
    (kind, v), trend, d, ex, stop = key
    return f"{kind} {v} Trend {trend} {d} Ausstieg {ex[0]} Stop {'kein' if stop == 0 else f'{stop}x ATR'}"


def main():
    t0 = time.time()
    grid = list(itertools.product(ENTRIES, TRENDS, DIRS, EXITS, STOPS))
    acc = {g: ([], []) for g in grid}
    for mi, sym in enumerate(MARKETS):
        bid, ask = load(sym)
        h1 = bid.index
        arrs = [bid[c].to_numpy() for c in ("open", "high", "low", "close")] + \
               [ask[c].to_numpy() for c in ("open", "high", "low", "close")]
        d1 = resample(bid, "1D")
        dep = h1.searchsorted(d1.index + pd.Timedelta(days=1)).astype(np.int64)
        x = indicators(d1)
        atr = x["atr"].to_numpy()
        flags = [exit_flags(x, i) for i in range(4)]
        for (kind, v), trend in itertools.product(ENTRIES, TRENDS):
            lg, sh = entry_signal(x, kind, v)
            if trend != "kein":
                lg, sh = lg & (x.c > x[trend.lower()]), sh & (x.c < x[trend.lower()])
            ok = x["atr"].notna() & x["sma5"].notna()
            lg, sh = (lg & ok).to_numpy(), (sh & ok).to_numpy()
            for d in DIRS:
                side = np.where(lg, 1, np.where(sh & (d == "beide"), -1, 0))
                days = np.flatnonzero(side != 0).astype(np.int64)
                sd = side[days].astype(np.int64)
                for ei, ex in enumerate(EXITS):
                    for stop in STOPS:
                        p, r = run(days, sd, atr[days], dep, flags[ei][0], flags[ei][1], ex[1], stop, *arrs)
                        key = ((kind, v), trend, d, ex, stop)
                        acc[key][0].append(h1[p].tz_convert(None).to_numpy())
                        acc[key][1].append(r)
        print(f"{sym} fertig ({mi + 1}/{len(MARKETS)}, {time.time() - t0:.0f} s)", flush=True)

    results = []
    for key, (ts, rs) in acc.items():
        t = np.concatenate(ts)
        r = np.concatenate(rs)
        o = np.argsort(t)
        results.append({"key": key, "t": t[o], "r": r[o]})
    pd.to_pickle(results, OUT)

    def period(res, nm):
        a, b = PERIODS[nm]
        m = (res["t"] >= np.datetime64(a)) & (res["t"] <= np.datetime64(b + "T23:59"))
        return res["r"][m]

    rows = []
    for i, x in enumerate(results):
        r = period(x, "Training")
        (kind, v), trend, d, ex, stop = x["key"]
        rows.append(dict(i=i, n=len(r), avg=r.mean() if len(r) else np.nan, t=tstat(r), entry=kind, trend=trend,
                         dir=d, exit=ex[0], stop=stop))
    tr = pd.DataFrame(rows)
    print(f"\nTraining 2012-07 bis 2017: {len(tr)} Konfigurationen | t >= 2: {(tr.t >= 2).sum()} | t >= 3: "
          f"{(tr.t >= 3).sum()} | t >= 4: {(tr.t >= 4).sum()} | Ø R > 0: {(tr.avg > 0).sum()} | "
          f"Median Ø R {tr.avg.median():+.3f}")
    for col in ("entry", "trend", "dir", "exit", "stop"):
        print(f"  Median Ø R je {col}: " + ", ".join(f"{k} {v:+.3f}" for k, v in tr.groupby(col).avg.median().items()))

    def show(row, count):
        res = results[int(row.i)]
        print(f"\n=== {name(res['key'])}")
        print(f"  Training:    {describe(period(res, 'Training'))}")
        r = period(res, "Bestätigung")
        ok = len(r) > 2 and r.mean() > 0 and tstat(r) >= 2.4
        print(f"  Bestätigung: {describe(r)}  -> {'BESTANDEN' if ok else 'nicht bestanden'}")
        if count and ok:
            r = period(res, "Endtest")
            fin = len(r) > 2 and r.mean() > 0 and tstat(r) >= 2
            print(f"  Endtest:     {describe(r)}  -> {'BESTANDEN' if fin else 'nicht bestanden'}")
        elif count:
            print("  Endtest: nicht angesehen")

    el = tr[(tr.n >= 200) & (tr.avg > 0) & (tr.t >= 4)].sort_values("t", ascending=False).head(3)
    print(f"\n--- Zählende Auswahl (n >= 200, Ø R > 0, t >= 4): {len(el)} Konfiguration(en)")
    for _, row in el.iterrows():
        show(row, True)
    if el.empty:
        print("  keine -> RUNDE NICHT BESTANDEN")
    print("\n--- Nur zur Information: 3 beste Trainings-t ohne t-4-Hürde (Endtest wird nicht angesehen)")
    for _, row in tr[(tr.n >= 200) & (tr.avg > 0)].sort_values("t", ascending=False).head(3).iterrows():
        show(row, False)
    conf = np.array([period(x, "Bestätigung").mean() if len(period(x, "Bestätigung")) else np.nan for x in results])
    print(f"\nFamilie in der Bestätigung (nur Information): Median Ø R {np.nanmedian(conf):+.3f}, "
          f"Anteil > 0: {np.mean(conf > 0):.0%}")
    tr["conf"] = conf
    for col in ("entry", "trend", "dir"):
        print(f"  Bestätigung Median je {col}: " +
              ", ".join(f"{k} {v:+.3f}" for k, v in tr.groupby(col).conf.median().items()))
    print(f"\nLaufzeit {time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()

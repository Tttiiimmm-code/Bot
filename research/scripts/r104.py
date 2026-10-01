"""Runde 104: 1.152 Konfigurationen eines langsamen Trend-Bots (H4/D1, 14 Märkte) -- Vorab: r104_prereg.md."""
from __future__ import annotations

import itertools
import sys
import time
from pathlib import Path

import numba
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from r102 import load, resample  # noqa: E402  (H1-Bid/Ask laden, H4/D1 in Broker-Zeit)

OUT = Path(__file__).with_name("r104_results.pkl")
MARKETS = ("xauusd", "xagusd", "eurusd", "gbpusd", "usdjpy", "usdchf", "usdcnh", "audusd", "nzdusd", "usdsek",
           "gbpjpy", "eurjpy", "chfjpy", "usatechidxusd")
PERIODS = {"Training": ("2012-07-01", "2017-12-31"), "Bestätigung": ("2018-01-01", "2021-12-31"),
           "Endtest": ("2022-01-01", "2026-12-31")}
MAX_HOLD_H1 = 2880
EXITS = ((0, 2.0, "Ziel 2R"), (0, 3.0, "Ziel 3R"), (1, 0.0, "Nachzieh-Stop"), (2, 2.0, "Einstand+2R"))


def ema(s, n):
    return s.ewm(span=n, adjust=False, min_periods=n).mean()


def atr(df, n):
    pc = df["close"].shift(1)
    tr = pd.concat([df["high"] - df["low"], (df["high"] - pc).abs(), (df["low"] - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def rsi(s, n=14):
    d = s.diff()
    g = d.clip(lower=0).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    l_ = (-d).clip(lower=0).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    return 100 - 100 / (1 + g / l_.replace(0, np.nan))


def signals(bars, entry, ema_len):
    c = bars["close"]
    e = ema(c, ema_len)
    up, dn = c > e, c < e
    if entry.startswith("RSI"):
        lvl = int(entry[3:])
        r = rsi(c)
        long = up & (r.shift(1) <= lvl) & (r > lvl)
        short = dn & (r.shift(1) >= 100 - lvl) & (r < 100 - lvl)
    else:
        n = int(entry[3:])
        long = up & (c > bars["high"].shift(1).rolling(n).max())
        short = dn & (c < bars["low"].shift(1).rolling(n).min())
    return pd.Series(np.where(long, 1, np.where(short, -1, 0)), index=bars.index)


@numba.njit(cache=True)
def run(sig_pos, sig_side, sig_sd, bo, bh, bl, bc, ao, ah, al, ac, atr_h1, tf_close, mode, tp_mult, mult):
    n_sig, n = len(sig_pos), len(bo)
    out_entry = np.empty(n_sig, np.int64)
    out_r = np.empty(n_sig, np.float64)
    k, busy_until = 0, -1
    for s in range(n_sig):
        p = sig_pos[s]
        if p <= busy_until or p >= n:
            continue
        side, sd = sig_side[s], sig_sd[s]
        if not (sd > 0):
            continue
        entry = ao[p] if side > 0 else bo[p]
        sl = entry - side * sd
        tp = entry + side * tp_mult * sd
        use_tp = mode != 1
        be_done = False
        ext = entry
        exit_pos, r = -1, 0.0
        last = min(n - 1, p + MAX_HOLD_H1)
        for i in range(p, last + 1):
            if side > 0:
                o, h, l_, c = bo[i], bh[i], bl[i], bc[i]
                if i > p and (o <= sl or (use_tp and o >= tp)):
                    exit_pos, r = i, (o - entry) / sd
                    break
                if l_ <= sl:
                    exit_pos, r = i, (sl - entry) / sd
                    break
                if use_tp and h >= tp:
                    exit_pos, r = i, (tp - entry) / sd
                    break
                if h > ext:
                    ext = h
                if mode == 2 and not be_done and h >= entry + sd:
                    sl, be_done = max(sl, entry), True
                if mode == 1 and tf_close[i]:
                    cand = ext - mult * atr_h1[i]
                    if cand > sl:
                        sl = cand
                if i == last:
                    exit_pos, r = i, (c - entry) / sd
            else:
                o, h, l_, c = ao[i], ah[i], al[i], ac[i]
                if i > p and (o >= sl or (use_tp and o <= tp)):
                    exit_pos, r = i, (entry - o) / sd
                    break
                if h >= sl:
                    exit_pos, r = i, (entry - sl) / sd
                    break
                if use_tp and l_ <= tp:
                    exit_pos, r = i, (entry - tp) / sd
                    break
                if l_ < ext:
                    ext = l_
                if mode == 2 and not be_done and l_ <= entry - sd:
                    sl, be_done = min(sl, entry), True
                if mode == 1 and tf_close[i]:
                    cand = ext + mult * atr_h1[i]
                    if cand < sl:
                        sl = cand
                if i == last:
                    exit_pos, r = i, (entry - c) / sd
        if exit_pos < 0:
            continue
        out_entry[k] = p
        out_r[k] = r - 0.5e-4 * entry / sd
        k += 1
        busy_until = exit_pos
    return out_entry[:k], out_r[:k]


def tstat(r):
    return float(r.mean() / r.std(ddof=1) * np.sqrt(len(r))) if len(r) > 2 and r.std() > 0 else float("nan")


def describe(r):
    if len(r) < 3:
        return f"n {len(r)}"
    w, l_ = r[r > 0].sum(), -r[r < 0].sum()
    return (f"n {len(r):5d}  Ø R {r.mean():+.3f}  t {tstat(r):+.2f}  Treffer {(r > 0).mean():.0%}  "
            f"PF {w / l_ if l_ > 0 else float('inf'):.2f}  Summe {r.sum():+.0f} R")


def main():
    t0 = time.time()
    grid = list(itertools.product(("H4", "D1"), (10, 20), (50, 100, 200), ("RSI30", "RSI40", "DON20", "DON55"),
                                  ("beide", "nur long"), (1.5, 2.0, 3.0), EXITS))
    acc = {g: ([], []) for g in grid}          # Konfiguration -> (Einstiegszeiten, R)
    for mi, sym in enumerate(MARKETS):
        bid, ask = load(sym)
        h1 = bid.index
        arrs = [bid[c].to_numpy() for c in ("open", "high", "low", "close")] + \
               [ask[c].to_numpy() for c in ("open", "high", "low", "close")]
        for tf_name in ("H4", "D1"):
            bars = resample(bid, {"H4": "4h", "D1": "1D"}[tf_name])
            step = pd.Timedelta(hours=4) if tf_name == "H4" else pd.Timedelta(days=1)
            end_pos = h1.searchsorted(bars.index + step) - 1
            tf_close = np.zeros(len(h1), dtype=np.bool_)
            tf_close[end_pos[(end_pos >= 0) & (end_pos < len(h1))]] = True
            for atr_len in (10, 20):
                a = atr(bars, atr_len)
                a_closed = a.copy()
                a_closed.index = a_closed.index + step
                atr_h1 = np.nan_to_num(a_closed[~a_closed.index.duplicated()].reindex(h1, method="ffill").to_numpy())
                for ema_len, entry in itertools.product((50, 100, 200), ("RSI30", "RSI40", "DON20", "DON55")):
                    sig_all = signals(bars, entry, ema_len)
                    sig_all = sig_all[(sig_all != 0) & a.notna()]
                    for direction in ("beide", "nur long"):
                        sig = sig_all if direction == "beide" else sig_all[sig_all > 0]
                        pos = h1.searchsorted(sig.index + step).astype(np.int64)
                        side = sig.to_numpy().astype(np.int64)
                        for stop in (1.5, 2.0, 3.0):
                            sd = (a.reindex(sig.index) * stop).to_numpy()
                            for ex in EXITS:
                                e_pos, r = run(pos, side, sd, *arrs, atr_h1, tf_close, ex[0], ex[1], stop)
                                key = (tf_name, atr_len, ema_len, entry, direction, stop, ex)
                                acc[key][0].append(h1[e_pos].tz_convert(None).to_numpy())
                                acc[key][1].append(r)
        print(f"{sym} fertig ({mi + 1}/{len(MARKETS)}, {time.time() - t0:.0f} s)", flush=True)

    results = []
    for key, (times, rs) in acc.items():
        t = np.concatenate(times) if times else np.array([], dtype="datetime64[ns]")
        r = np.concatenate(rs) if rs else np.array([])
        order = np.argsort(t)
        results.append({"key": key, "t": t[order], "r": r[order]})
    pd.to_pickle(results, OUT)

    def period(res, name):
        a, b = PERIODS[name]
        m = (res["t"] >= np.datetime64(a)) & (res["t"] <= np.datetime64(b + "T23:59"))
        return res["r"][m]

    rows = []
    for i, x in enumerate(results):
        r = period(x, "Training")
        rows.append((i, len(r), r.mean() if len(r) else np.nan, tstat(r)))
    tr = pd.DataFrame(rows, columns=["i", "n", "avg", "t"])
    print(f"\nTraining 2012-07 bis 2017: {len(tr)} Konfigurationen | t >= 2: {(tr.t >= 2).sum()} | t >= 3: "
          f"{(tr.t >= 3).sum()} | t >= 4: {(tr.t >= 4).sum()} | Ø R > 0: {(tr.avg > 0).sum()} | "
          f"Median Ø R {tr.avg.median():+.3f}")
    keys = pd.DataFrame([x["key"] for x in results], columns=["tf", "atr", "ema", "entry", "dir", "stop", "exit"])
    keys["exit"] = keys["exit"].map(lambda e: e[2])
    tr = pd.concat([tr, keys], axis=1)
    for col in ("tf", "entry", "dir", "exit", "stop", "ema"):
        print(f"  Median Ø R je {col}: " + ", ".join(f"{k} {v:+.3f}" for k, v in tr.groupby(col).avg.median().items()))

    def show(row, count: bool):
        res = results[int(row.i)]
        tf_, atr_, ema_, entry_, dir_, stop_, ex_ = res["key"]
        print(f"\n=== {tf_} ATR{atr_} EMA{ema_} {entry_} {dir_} Stop {stop_}x {ex_[2]}")
        r = period(res, "Training")
        print(f"  Training:    {describe(r)}")
        r = period(res, "Bestätigung")
        ok = len(r) > 2 and r.mean() > 0 and tstat(r) >= 2.4
        print(f"  Bestätigung: {describe(r)}  -> {'BESTANDEN' if ok else 'nicht bestanden'}")
        if count and ok:
            r = period(res, "Endtest")
            fin = len(r) > 2 and r.mean() > 0 and tstat(r) >= 2
            print(f"  Endtest:     {describe(r)}  -> {'BESTANDEN' if fin else 'nicht bestanden'}")
        elif count:
            print("  Endtest: nicht angesehen")

    eligible = tr[(tr.n >= 200) & (tr.avg > 0) & (tr.t >= 4)].sort_values("t", ascending=False).head(3)
    print(f"\n--- Zählende Auswahl (n >= 200, Ø R > 0, t >= 4): {len(eligible)} Konfiguration(en)")
    for _, row in eligible.iterrows():
        show(row, count=True)
    if eligible.empty:
        print("  keine -> RUNDE NICHT BESTANDEN")
    print("\n--- Nur zur Information: 3 beste Trainings-t ohne t-4-Hürde (Endtest wird nicht angesehen)")
    for _, row in tr[(tr.n >= 200) & (tr.avg > 0)].sort_values("t", ascending=False).head(3).iterrows():
        show(row, count=False)
    print(f"\nLaufzeit {time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()

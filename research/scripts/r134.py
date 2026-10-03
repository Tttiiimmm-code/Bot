"""Runde 134: Nachbau "The Gold Reaper" als Breakout-Familie auf XAUUSD M1 Bid/Ask -- Vorab: PROTOCOL.md."""
from __future__ import annotations

import gc
import itertools
import math
import time
from pathlib import Path

import numba
import numpy as np
import pandas as pd

D = Path(r"C:\Users\Nutzer\Bot\data_cache\dukascopy")
PERIODS = {"Training": ("2008-01-01", "2016-12-31"), "Bestätigung": ("2017-01-01", "2022-12-31"),
           "Endtest": ("2023-01-01", "2026-12-31")}
SIGNAL = ("2024-10-22", "2026-09-25")
DT = {"timestamp": "int64", "open": "float32", "high": "float32", "low": "float32", "close": "float32"}


def load():
    bid_files = sorted((D / "xau").glob("xau_20*.csv")) + [D / "unseen_xau" / "xau_2026.csv"]
    ask_files = sorted((D / "xau_ask").glob("xau_20*.csv"))
    bid = pd.concat(pd.read_csv(f, dtype=DT) for f in bid_files).drop_duplicates("timestamp").set_index("timestamp")
    ask = pd.concat(pd.read_csv(f, dtype=DT) for f in ask_files).drop_duplicates("timestamp").set_index("timestamp")
    idx = bid.index.intersection(ask.index)
    bid, ask = bid.loc[idx].sort_index(), ask.loc[idx].sort_index()
    t = pd.to_datetime(bid.index.to_numpy(), unit="ms", utc=True)
    keep = (ask["close"].to_numpy() >= bid["close"].to_numpy()) & ~((t.weekday == 5) | ((t.weekday == 6) & (t.hour < 22)))
    flat = (bid["high"] == bid["low"]).to_numpy() & (bid["open"] == bid["close"]).to_numpy()
    keep &= ~flat                                            # Wochenend-/Pausen-Flachminuten raus
    return t[keep], bid[keep], ask[keep]


def h1_features(t, bid):
    """Je Minute: Index der Stunde; je Stunde: Hoch, Tief (Geld) und ATR14."""
    hk = t.as_unit("ns").asi8 // 3_600_000_000_000         # Zeitindex kommt in ms -> erst auf ns bringen
    _, h_of_m = np.unique(hk, return_inverse=True)
    hb = pd.DataFrame({"h": bid["high"].to_numpy(), "l": bid["low"].to_numpy(), "c": bid["close"].to_numpy(),
                       "k": h_of_m}).groupby("k").agg(h=("h", "max"), l=("l", "min"), c=("c", "last"))
    pc = hb["c"].shift(1)
    tr = np.maximum(hb["h"] - hb["l"], np.maximum((hb["h"] - pc).abs(), (hb["l"] - pc).abs()))
    atr = tr.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    return h_of_m.astype(np.int64), hb["h"].to_numpy(np.float64), hb["l"].to_numpy(np.float64), atr.to_numpy(np.float64)


@numba.njit(cache=True)
def sim(h_of_m, hh, hl, atr, bo, bh, bl, bc, ao, ah, al, ac, fri_stop, fri_cancel,
        n_lvl, exp_h, sl_x, tp_y, trail, long_only):
    n = len(bo)
    out_i = np.empty(n // 30 + 10, np.int64)
    out_r = np.empty(n // 30 + 10, np.float64)
    out_x = np.empty(n // 30 + 10, np.int64)       # Ausstiegsminute (für Haltedauer/Swap)
    out_q = np.empty(n // 30 + 10, np.float64)     # Risiko / Einstiegskurs (für Positionsgröße)
    k = 0
    pos = 0                    # 0 flach, 1 long, -1 short
    pend = False
    buy_lvl = sell_lvl = pend_atr = 0.0
    pend_until = -1
    entry = sl = tp = risk = best = 0.0
    e_idx = 0
    for i in range(1, n):
        new_hour = h_of_m[i] != h_of_m[i - 1]
        if new_hour and pos == 0 and not pend and not fri_stop[i]:
            kk = h_of_m[i]                                   # abgeschlossene Stunden kk-n_lvl .. kk-1
            if kk - n_lvl >= 15 and not np.isnan(atr[kk - 1]):
                a = atr[kk - 1]
                hi = -1e18
                lo = 1e18
                for j in range(kk - n_lvl, kk):
                    if hh[j] > hi:
                        hi = hh[j]
                    if hl[j] < lo:
                        lo = hl[j]
                buy_lvl, sell_lvl, pend_atr = hi + 0.1 * a, lo - 0.1 * a, a
                pend, pend_until = True, kk + exp_h
        if pend:
            if h_of_m[i] >= pend_until or fri_cancel[i]:
                pend = False
            else:
                hit_b = ah[i] >= buy_lvl
                hit_s = (not long_only) and bl[i] <= sell_lvl
                if hit_b and hit_s:
                    hit_s = False                             # beide in einer Minute: nur long, danach Stop-Prüfung
                if hit_b:
                    entry = max(ao[i], buy_lvl)
                    pos, pend = 1, False
                elif hit_s:
                    entry = min(bo[i], sell_lvl)
                    pos, pend = -1, False
                if pos != 0:
                    risk = sl_x * pend_atr
                    sl = entry - pos * risk
                    tp = entry + pos * tp_y * pend_atr
                    best = entry
                    e_idx = i
                    if pos == 1 and bl[i] <= sl:              # Einstiegsminute: nur Stop prüfen
                        out_i[k], out_r[k], out_x[k], out_q[k] = e_idx, (sl - entry) / risk, i, risk / entry
                        k += 1
                        pos = 0
                    elif pos == -1 and ah[i] >= sl:
                        out_i[k], out_r[k], out_x[k], out_q[k] = e_idx, (entry - sl) / risk, i, risk / entry
                        k += 1
                        pos = 0
                    continue
        if pos == 1:
            ex = -1.0
            if bo[i] <= sl or bo[i] >= tp:
                ex = bo[i]
            elif bl[i] <= sl:
                ex = sl
            elif bh[i] >= tp:
                ex = tp
            if ex > 0:
                out_i[k], out_r[k], out_x[k], out_q[k] = e_idx, (ex - entry) / risk, i, risk / entry
                k += 1
                pos = 0
            elif trail:
                if bh[i] > best:
                    best = bh[i]
                if best - entry >= pend_atr and best - pend_atr > sl:
                    sl = best - pend_atr
        elif pos == -1:
            ex = -1.0
            if ao[i] >= sl or ao[i] <= tp:
                ex = ao[i]
            elif ah[i] >= sl:
                ex = sl
            elif al[i] <= tp:
                ex = tp
            if ex > 0:
                out_i[k], out_r[k], out_x[k], out_q[k] = e_idx, (entry - ex) / risk, i, risk / entry
                k += 1
                pos = 0
            elif trail:
                if al[i] < best:
                    best = al[i]
                if entry - best >= pend_atr and best + pend_atr < sl:
                    sl = best + pend_atr
        if k >= len(out_i) - 1:
            break
    return out_i[:k], out_r[:k], out_x[:k], out_q[:k]


def tstat(x):
    x = np.asarray(x, float)
    return float(x.mean() / x.std(ddof=1) * math.sqrt(len(x))) if len(x) > 2 and x.std() > 0 else float("nan")


def cagr_at_risk(r, t, risk=0.01):
    if len(r) < 2:
        return float("nan")
    eq = np.cumprod(1 + risk * r)
    yrs = max((t[-1] - t[0]) / np.timedelta64(365, "D"), 1e-9)
    return float(eq[-1] ** (1 / yrs) - 1)


def main():
    t0 = time.time()
    t, bid, ask = load()
    print(f"{len(t):,} Minuten {t[0]:%Y-%m-%d} bis {t[-1]:%Y-%m-%d} ({time.time() - t0:.0f} s)", flush=True)
    h_of_m, hh, hl, atr = h1_features(t, bid)
    arrs = [bid[c].to_numpy(np.float64) for c in ("open", "high", "low", "close")] + \
           [ask[c].to_numpy(np.float64) for c in ("open", "high", "low", "close")]
    wd, hr, mi = t.weekday.to_numpy(), t.hour.to_numpy(), t.minute.to_numpy()
    fri_stop = (wd == 4) & (hr >= 20)
    fri_cancel = (wd == 4) & ((hr > 20) | ((hr == 20) & (mi >= 55)))
    del bid, ask
    gc.collect()
    tt = t.tz_convert(None).to_numpy()
    res = []
    for n_lvl, e, x, y, tr, lo in itertools.product((12, 24, 48), (4, 12), (1.0, 2.0), (2.0, 4.0), (False, True),
                                                    (False, True)):
        ei, r, xi, q = sim(h_of_m, hh, hl, atr, *arrs, fri_stop, fri_cancel, n_lvl, e, x, y, tr, lo)
        res.append(dict(key=(n_lvl, e, x, y, tr, lo), t=tt[ei], r=r, t_exit=tt[xi], risk_rel=q))
    print(f"96 Varianten simuliert ({time.time() - t0:.0f} s)", flush=True)
    pd.to_pickle(res, Path(__file__).with_name("r134_results.pkl"))

    def part(x, a, b):
        m = (x["t"] >= np.datetime64(a)) & (x["t"] <= np.datetime64(b + "T23:59"))
        return x["r"][m], x["t"][m]

    def name(k):
        n_lvl, e, x, y, tr, lo = k
        return (f"N{n_lvl} Ablauf {e}h SL {x:g}ATR TP {y:g}ATR {'Trail' if tr else 'ohne Trail'} "
                f"{'nur long' if lo else 'beide'}")

    rows = []
    for x in res:
        r, _ = part(x, *PERIODS["Training"])
        rows.append((len(r), r.mean() if len(r) else np.nan, tstat(r)))
    tr_df = pd.DataFrame(rows, columns=["n", "avg", "t"])
    print(f"\nTraining 2008-2016: Ø > 0: {(tr_df.avg > 0).sum()} von 96 | t >= 2: {(tr_df.t >= 2).sum()} | "
          f"t >= 3,5: {(tr_df.t >= 3.5).sum()} | Median Ø R {tr_df.avg.median():+.3f}")
    for per in ("Bestätigung", "Endtest"):
        a = [part(x, *PERIODS[per])[0] for x in res]
        print(f"{per}: Ø > 0: {sum(len(v) > 0 and v.mean() > 0 for v in a)} von 96 | Median Ø R "
              f"{np.median([v.mean() for v in a if len(v)]):+.3f}")
    sig = [part(x, *SIGNAL) for x in res]
    print(f"Signal-Zeitraum 2024-10..2026-09: Ø > 0 bei {sum(len(v) > 0 and v.mean() > 0 for v, _ in sig)} von 96 | "
          f"Median Ø R {np.median([v.mean() for v, _ in sig if len(v)]):+.3f}")
    order = np.argsort([-(np.nan_to_num(v.mean(), nan=-9)) for v, _ in sig])[:5]
    for i in order:
        v, tt_ = sig[i]
        print(f"  bester im Signal-Zeitraum: {name(res[i]['key'])}: n {len(v)}, Ø {v.mean():+.3f} R, t {tstat(v):.2f}, "
              f"p.a. bei 1 % Risiko {cagr_at_risk(v, tt_):+.1%} | Training Ø {tr_df.avg[i]:+.3f} R (t {tr_df.t[i]:.2f})")
    elig = tr_df[(tr_df.n >= 200) & (tr_df.avg > 0) & (tr_df.t >= 3.5)].sort_values("t", ascending=False).head(3)
    print(f"\n--- Zählende Auswahl (n >= 200, Ø > 0, t >= 3,5): {len(elig)}")
    for i, row in elig.iterrows():
        b, _ = part(res[i], *PERIODS["Bestätigung"])
        ok = len(b) > 2 and b.mean() > 0 and tstat(b) >= 2.4
        print(f"  {name(res[i]['key'])}: Training Ø {row.avg:+.3f} (t {row.t:.2f}) -> Bestätigung Ø {b.mean():+.3f} "
              f"(t {tstat(b):.2f}) -> {'BESTANDEN' if ok else 'nicht bestanden'}")
        if ok:
            e_, _ = part(res[i], *PERIODS["Endtest"])
            print(f"     Endtest Ø {e_.mean():+.3f} (t {tstat(e_):.2f}) -> "
                  f"{'BESTANDEN' if e_.mean() > 0 and tstat(e_) >= 2 else 'nicht bestanden'}")
    if elig.empty:
        print("  keine -> RUNDE NICHT BESTANDEN")
    print("\nNur Information -- 3 beste Trainings-t:")
    for i in tr_df[tr_df.n >= 200].sort_values("t", ascending=False).head(3).index:
        vals = [part(res[i], *PERIODS[p])[0] for p in PERIODS]
        print(f"  {name(res[i]['key'])}: " + " | ".join(f"{p} Ø {v.mean():+.3f} (t {tstat(v):.2f}, n {len(v)})"
                                                      for p, v in zip(PERIODS, vals)))
    print(f"Laufzeit {time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()

"""Runde 136: Nachbau "Luna AI Pro" -- Nacht-Scalper (Bollinger-Rückkehr, M5) -- Vorab: PROTOCOL.md."""
from __future__ import annotations

import gc
import itertools
import math
import time
from pathlib import Path

import numba
import numpy as np
import pandas as pd

D = Path(r"C:\Users\Nutzer\Bot\data_cache\dukascopy\luna")
PAIRS = ("euraud", "gbpaud", "audcad", "audusd")
PERIODS = {"Training": ("2012-01-01", "2017-12-31"), "Bestätigung": ("2018-01-01", "2021-12-31"),
           "Endtest": ("2022-01-01", "2026-12-31")}
DT = {"timestamp": "int64", "open": "float32", "high": "float32", "low": "float32", "close": "float32"}
COMM = 0.35e-4
WINDOWS = {"A": (18 * 60 + 15, 22 * 60), "B": (19 * 60, 24 * 60)}   # Nachtminuten ET (B bis 24:00)
EXIT_ET = 25 * 60                                                   # 01:00 ET (Nachtzeit)


def load(pair):
    def side(s):
        fs = sorted(D.glob(f"{pair}_{s}_20*.csv"))
        return pd.concat(pd.read_csv(f, dtype=DT) for f in fs).drop_duplicates("timestamp").set_index("timestamp")
    bid, ask = side("bid"), side("ask")
    idx = bid.index.intersection(ask.index)
    bid, ask = bid.loc[idx].sort_index(), ask.loc[idx].sort_index()
    keep = (ask["close"].to_numpy() >= bid["close"].to_numpy())
    keep &= ~((bid["high"] == bid["low"]).to_numpy() & (bid["open"] == bid["close"]).to_numpy())
    bid, ask = bid[keep], ask[keep]
    t = pd.to_datetime(bid.index.to_numpy(), unit="ms", utc=True).as_unit("ns")
    return t, bid, ask


def night_minutes(t):
    """ET-Uhrzeit als Nachtminuten (18:00 -> 1080, 00:30 -> 1470), Nachtschlüssel (Datum des Abends), Wochentag."""
    et = t.tz_convert("America/New_York")
    mins = np.asarray(et.hour * 60 + et.minute)
    shifted = et - pd.Timedelta(hours=12)                 # 00:30 gehört zur Nacht des Vortags
    night = shifted.normalize().tz_localize(None)
    nm = np.where(mins < 12 * 60, mins + 24 * 60, mins)
    return nm.astype(np.int64), night, np.asarray(shifted.weekday)


@numba.njit(cache=True)
def sim(sig_m1, sig_dir, sig_tp, sig_sd, sig_exit_m1, bo, bh, bl, ao, ah, al):
    n = len(sig_m1)
    out_e = np.empty(n, np.int64)
    out_r = np.empty(n, np.float64)
    k, busy = 0, -1
    for s in range(n):
        i0 = sig_m1[s]
        if i0 <= busy or i0 >= len(bo):
            continue
        d, sd, tp = sig_dir[s], sig_sd[s], sig_tp[s]
        entry = ao[i0] if d > 0 else bo[i0]
        if (d > 0 and tp <= entry) or (d < 0 and tp >= entry) or not sd > 0:
            continue
        sl = entry - d * sd
        last = min(sig_exit_m1[s], len(bo) - 1)
        if last <= i0:
            continue
        r, j_end, done = 0.0, last, False
        for j in range(i0, last + 1):
            if j == last:
                x = bo[j] if d > 0 else ao[j]              # Zeitausstieg zur Eröffnung
                r, j_end, done = (x - entry) * d / sd, j, True
                break
            if d > 0:
                if j > i0 and (bo[j] <= sl or bo[j] >= tp):
                    r, j_end, done = (bo[j] - entry) / sd, j, True
                    break
                if bl[j] <= sl:
                    r, j_end, done = (sl - entry) / sd, j, True
                    break
                if j > i0 and bh[j] >= tp:
                    r, j_end, done = (tp - entry) / sd, j, True
                    break
            else:
                if j > i0 and (ao[j] >= sl or ao[j] <= tp):
                    r, j_end, done = (entry - ao[j]) / sd, j, True
                    break
                if ah[j] >= sl:
                    r, j_end, done = (entry - sl) / sd, j, True
                    break
                if j > i0 and al[j] <= tp:
                    r, j_end, done = (entry - tp) / sd, j, True
                    break
        if not done:
            continue
        out_e[k] = i0
        out_r[k] = r - 2 * COMM * entry / sd
        k += 1
        busy = j_end
    return out_e[:k], out_r[:k]


def tstat(x):
    x = np.asarray(x, float)
    return float(x.mean() / x.std(ddof=1) * math.sqrt(len(x))) if len(x) > 2 and x.std() > 0 else float("nan")


def pair_trades(pair):
    t, bid, ask = load(pair)
    nm, night, wd_night = night_minutes(t)
    m1 = {k: bid[k].to_numpy(np.float64) for k in ("open", "high", "low", "close")}
    a1 = {k: ask[k].to_numpy(np.float64) for k in ("open", "high", "low")}
    key = t.asi8 // 300_000_000_000
    g = pd.DataFrame({"h": m1["high"], "l": m1["low"], "c": m1["close"], "k": key, "i": np.arange(len(t))})
    m5 = g.groupby("k").agg(h=("h", "max"), l=("l", "min"), c=("c", "last"), first=("i", "first"), last=("i", "last"))
    c5 = m5["c"]
    pc = c5.shift(1)
    tr = np.maximum(m5["h"] - m5["l"], np.maximum((m5["h"] - pc).abs(), (m5["l"] - pc).abs()))
    atr = tr.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean().to_numpy()
    mid = c5.rolling(20).mean().to_numpy()
    sdv = c5.rolling(20).std(ddof=0).to_numpy()
    first_next = m5["first"].shift(-1).to_numpy()
    last_i = m5["last"].to_numpy()
    nm5, night5, wd5 = nm[last_i], night[last_i], wd_night[last_i]
    in_any = (nm5 >= WINDOWS["A"][0]) & (nm5 < WINDOWS["B"][1])
    night_atr = pd.Series(atr[in_any], index=night5[in_any]).groupby(level=0).mean()
    ref = night_atr.shift(1).rolling(20, min_periods=10).median()
    quiet = atr < ref.reindex(night5).to_numpy()
    night_codes, night_idx = np.unique(night.to_numpy(), return_inverse=True)
    exit_m1 = np.full(len(night_codes), len(t) - 1, np.int64)
    after = np.flatnonzero(nm >= EXIT_ET)
    first_after = pd.Series(after).groupby(night_idx[after]).min()
    exit_m1[first_after.index.to_numpy()] = first_after.to_numpy()
    night5_idx = night_idx[last_i]
    cv = c5.to_numpy()
    res = {}
    for wname, k_bb, tp_mode, sl_x, filt in itertools.product(WINDOWS, (2.0, 2.5), ("mid", "0.5atr"), (1.5, 3.0),
                                                              (False, True)):
        lo_w, hi_w = WINDOWS[wname]
        ok = (nm5 >= lo_w) & (nm5 < hi_w) & (wd5 != 4) & ~np.isnan(first_next) & ~np.isnan(atr) & ~np.isnan(mid)
        if filt:
            ok &= quiet
        up, lo = mid + k_bb * sdv, mid - k_bb * sdv
        d = np.where(ok & (cv < lo), 1, np.where(ok & (cv > up), -1, 0))
        idx = np.flatnonzero(d != 0)
        a_ = atr[idx]
        tp = np.where(tp_mode == "mid", mid[idx], cv[idx] + d[idx] * 0.5 * a_)
        e, r = sim(first_next[idx].astype(np.int64), d[idx].astype(np.int64), tp.astype(np.float64),
                   (sl_x * a_).astype(np.float64), exit_m1[night5_idx[idx]], m1["open"], m1["high"], m1["low"],
                   a1["open"], a1["high"], a1["low"])
        res[(wname, k_bb, tp_mode, sl_x, filt)] = (night[e].to_numpy(), r)
    del t, bid, ask, m1, a1
    gc.collect()
    return res


def main():
    t0 = time.time()
    per_pair = {}
    for p in PAIRS:
        per_pair[p] = pair_trades(p)
        print(f"{p} fertig ({time.time() - t0:.0f} s)", flush=True)
    keys = list(per_pair[PAIRS[0]].keys())
    pooled = {k: (np.concatenate([per_pair[p][k][0] for p in PAIRS]), np.concatenate([per_pair[p][k][1] for p in PAIRS]))
              for k in keys}
    pd.to_pickle(pooled, Path(__file__).with_name("r136_results.pkl"))

    def part(k, a, b):
        nt, r = pooled[k]
        m = (nt >= np.datetime64(a)) & (nt <= np.datetime64(b))
        s = pd.Series(r[m], index=nt[m])
        return s, s.groupby(level=0).sum()

    rows = []
    for k in keys:
        s, nights = part(k, *PERIODS["Training"])
        rows.append(dict(k=k, n=len(s), avg=s.mean() if len(s) else np.nan, t=tstat(nights), win=(s > 0).mean()))
    tr = pd.DataFrame(rows)
    print(f"\nTraining 2012-2017: Ø > 0 bei {(tr.avg > 0).sum()} von {len(tr)} | t >= 2: {(tr.t >= 2).sum()} | "
          f"t >= 3: {(tr.t >= 3).sum()}")
    for _, r_ in tr.sort_values("t", ascending=False).iterrows():
        print(f"  {r_.k}: n {r_.n}, Ø {r_.avg:+.3f} R, Treffer {r_.win:.0%}, t(Nächte) {r_.t:+.2f}")
    el = tr[(tr.n >= 300) & (tr.avg > 0) & (tr.t >= 3)].sort_values("t", ascending=False).head(3)
    print(f"\n--- Zählende Auswahl (n >= 300, Ø > 0, t >= 3): {len(el)}")
    for _, r_ in el.iterrows():
        s, nights = part(r_.k, *PERIODS["Bestätigung"])
        ok = s.mean() > 0 and tstat(nights) >= 2.4
        print(f"  {r_.k}: Bestätigung n {len(s)}, Ø {s.mean():+.3f} R, t {tstat(nights):.2f} -> "
              f"{'BESTANDEN' if ok else 'nicht bestanden'}")
        if ok:
            s2, n2 = part(r_.k, *PERIODS["Endtest"])
            print(f"    Endtest n {len(s2)}, Ø {s2.mean():+.3f} R, t {tstat(n2):.2f} -> "
                  f"{'BESTANDEN' if s2.mean() > 0 and tstat(n2) >= 2 else 'nicht bestanden'}")
    if el.empty:
        print("  keine -> RUNDE NICHT BESTANDEN")
    print(f"Laufzeit {time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()

"""Runde 137: Rückkehr zum Mittelwert auf AUD/NZD/CAD-Kreuzkursen (M15/H1, Bollinger) -- Vorab: PROTOCOL.md."""
from __future__ import annotations

import gc
import itertools
import math
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from r136 import load, sim  # noqa: E402  (gleicher M1-Simulator: Ziel/Stop/Zeitausstieg, Kurslücken, Kosten)

PAIRS = ("audcad", "nzdcad", "audnzd")
PERIODS = {"Training": ("2012-01-01", "2017-12-31"), "Bestätigung": ("2018-01-01", "2021-12-31"),
           "Endtest": ("2022-01-01", "2026-12-31")}
NIGHT = (18 * 60 + 15, 24 * 60)


def tstat(x):
    x = np.asarray(x, float)
    return float(x.mean() / x.std(ddof=1) * math.sqrt(len(x))) if len(x) > 2 and x.std() > 0 else float("nan")


def pair_trades(pair):
    t, bid, ask = load(pair)
    et = t.tz_convert("America/New_York")
    et_min = np.asarray(et.hour * 60 + et.minute)
    et_wd = np.asarray(et.weekday)
    day = t.tz_localize(None).normalize().to_numpy()
    bo, bh, bl, bc = (bid[k].to_numpy(np.float64) for k in ("open", "high", "low", "close"))
    ao, ah, al = (ask[k].to_numpy(np.float64) for k in ("open", "high", "low"))
    tns = t.asi8
    res = {}
    for tf in (15, 60):
        key = tns // (tf * 60_000_000_000)
        g = pd.DataFrame({"h": bh, "l": bl, "c": bc, "k": key, "i": np.arange(len(t))})
        b = g.groupby("k").agg(h=("h", "max"), l=("l", "min"), c=("c", "last"), first=("i", "first"),
                               last=("i", "last"))
        c = b["c"]
        pc = c.shift(1)
        tr = np.maximum(b["h"] - b["l"], np.maximum((b["h"] - pc).abs(), (b["l"] - pc).abs()))
        atr = tr.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean().to_numpy()
        mid = c.rolling(20).mean().to_numpy()
        sdv = c.rolling(20).std(ddof=0).to_numpy()
        first_next = b["first"].shift(-1).to_numpy()
        last_i = b["last"].to_numpy()
        bar_start = b.index.to_numpy().astype(np.int64) * tf * 60_000_000_000      # ns
        cv = c.to_numpy()
        m_et, wd_et, d_bar = et_min[last_i], et_wd[last_i], day[last_i]
        daily_atr = pd.Series(atr, index=d_bar).groupby(level=0).mean()
        ref = daily_atr.shift(1).rolling(20, min_periods=10).median()
        quiet = atr < ref.reindex(d_bar).to_numpy()
        for k_bb, sl_x, hold, sess, filt in itertools.product((2.0, 2.5), (2.0, 4.0), (12, 48), ("ganztags", "nachts"),
                                                              (False, True)):
            ok = ~np.isnan(first_next) & ~np.isnan(atr) & ~np.isnan(mid) & ~((wd_et == 4) & (m_et >= 12 * 60)) & \
                 (wd_et != 5)
            if sess == "nachts":
                ok &= (m_et >= NIGHT[0]) & (m_et < NIGHT[1])
            if filt:
                ok &= quiet
            d = np.where(ok & (cv < mid - k_bb * sdv), 1, np.where(ok & (cv > mid + k_bb * sdv), -1, 0))
            idx = np.flatnonzero(d != 0)
            entry_m1 = first_next[idx].astype(np.int64)
            exit_ns = bar_start[idx] + (hold + 1) * tf * 60_000_000_000      # Ende der hold-ten Kerze nach Einstieg
            exit_m1 = np.minimum(np.searchsorted(tns, exit_ns), len(t) - 1).astype(np.int64)
            e, r = sim(entry_m1, d[idx].astype(np.int64), mid[idx].astype(np.float64),
                       (sl_x * atr[idx]).astype(np.float64), exit_m1, bo, bh, bl, ao, ah, al)
            res[(tf, k_bb, sl_x, hold, sess, filt)] = (day[e], r)
    del t, bid, ask
    gc.collect()
    return res


def main():
    t0 = time.time()
    per = {}
    for p in PAIRS:
        per[p] = pair_trades(p)
        print(f"{p} fertig ({time.time() - t0:.0f} s)", flush=True)
    keys = list(per[PAIRS[0]].keys())
    pooled = {k: (np.concatenate([per[p][k][0] for p in PAIRS]), np.concatenate([per[p][k][1] for p in PAIRS]))
              for k in keys}
    pd.to_pickle(pooled, Path(__file__).with_name("r137_results.pkl"))

    def part(k, a, b):
        dd, r = pooled[k]
        m = (dd >= np.datetime64(a)) & (dd <= np.datetime64(b))
        s = pd.Series(r[m], index=dd[m])
        return s, s.groupby(level=0).sum()

    rows = []
    for k in keys:
        s, days = part(k, *PERIODS["Training"])
        rows.append(dict(k=k, n=len(s), avg=s.mean() if len(s) else np.nan, t=tstat(days), win=(s > 0).mean()))
    tr = pd.DataFrame(rows)
    print(f"\nTraining 2012-2017: Ø > 0 bei {(tr.avg > 0).sum()} von {len(tr)} | t >= 2: {(tr.t >= 2).sum()} | "
          f"t >= 3,2: {(tr.t >= 3.2).sum()} | Median Ø R {tr.avg.median():+.3f}")
    for _, r_ in tr.sort_values("t", ascending=False).head(12).iterrows():
        print(f"  {r_.k}: n {r_.n}, Ø {r_.avg:+.3f} R, Treffer {r_.win:.0%}, t(Tage) {r_.t:+.2f}")
    el = tr[(tr.n >= 300) & (tr.avg > 0) & (tr.t >= 3.2)].sort_values("t", ascending=False).head(3)
    print(f"\n--- Zählende Auswahl (n >= 300, Ø > 0, t >= 3,2): {len(el)}")
    for _, r_ in el.iterrows():
        s, days = part(r_.k, *PERIODS["Bestätigung"])
        ok = s.mean() > 0 and tstat(days) >= 2.4
        print(f"  {r_.k}: Bestätigung n {len(s)}, Ø {s.mean():+.3f} R, t {tstat(days):.2f} -> "
              f"{'BESTANDEN' if ok else 'nicht bestanden'}")
        if ok:
            s2, d2 = part(r_.k, *PERIODS["Endtest"])
            print(f"    Endtest n {len(s2)}, Ø {s2.mean():+.3f} R, t {tstat(d2):.2f} -> "
                  f"{'BESTANDEN' if s2.mean() > 0 and tstat(d2) >= 2 else 'nicht bestanden'}")
    if el.empty:
        print("  keine -> RUNDE NICHT BESTANDEN")
    print(f"Laufzeit {time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()

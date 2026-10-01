"""Kontrollen zu Runde 110 (NY 09-10 Ausbruch, Stop Range, Ziel 1R): andere Märkte, Jahre, doppelte Kosten,
unabhängige Nachrechnung mit Dukascopy-Minuten (Bid/Ask)."""
from __future__ import annotations

import sys
from pathlib import Path

import numba
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from r102 import load  # noqa: E402
from r110 import OUT, PERIODS, describe, run, tstat  # noqa: E402

M1 = Path("data_cache/dukascopy")


def period(t, r, nm):
    a, b = PERIODS[nm]
    m = (t >= np.datetime64(a)) & (t <= np.datetime64(b))
    return r[m]


def h1_arrays(sym, spread_mult=1.0):
    bid, ask = load(sym)
    ny = bid.index.tz_convert("America/New_York")
    shifted = ny + pd.Timedelta(hours=5)
    sh = np.asarray(shifted.hour, dtype=np.int64)
    day = np.asarray((shifted.tz_localize(None).normalize() - pd.Timestamp("2000-01-01")).days)
    dstart = np.concatenate([[0], np.flatnonzero(np.diff(day)) + 1, [len(day)]]).astype(np.int64)
    dlabel = shifted.tz_localize(None).normalize()[dstart[:-1]].to_numpy()
    b = [bid[c].to_numpy() for c in ("open", "high", "low", "close")]
    a = [bid[c].to_numpy() + spread_mult * (ask[c].to_numpy() - bid[c].to_numpy()) for c in ("open", "high", "low", "close")]
    return dstart, sh, b + a, dlabel


@numba.njit(cache=True)
def run_m1(dstart, mins, bo, bh, bl, bc, ao, ah, al, ac):
    """Minuten (NY-Minute des Tages): Range 9:00-9:59, Einstieg 10:00-13:59, Ausstieg spätestens 16:00."""
    nd = len(dstart) - 1
    out = np.full(nd, np.nan)
    for d in range(nd):
        s, e_ = dstart[d], dstart[d + 1]
        rh, rl, cnt = -1e30, 1e30, 0
        for i in range(s, e_):
            if 540 <= mins[i] < 600:
                rh, rl, cnt = max(rh, bh[i]), min(rl, bl[i]), cnt + 1
        if cnt < 30 or not rh > rl:
            continue
        e, side, entry = -1, 0, 0.0
        for i in range(s, e_):
            if mins[i] < 600:
                continue
            if mins[i] >= 840:
                break
            up, dn = bh[i] > rh, bl[i] < rl
            if up and dn:
                break
            if up:
                e, side, entry = i, 1, max(ao[i], rh + (ao[i] - bo[i]))
                break
            if dn:
                e, side, entry = i, -1, min(bo[i], rl)
                break
        if e < 0:
            continue
        sd = rh - rl
        stop, tp = entry - side * sd, entry + side * sd
        ex = bc[e_ - 1] if side > 0 else ac[e_ - 1]
        for i in range(e, e_):
            if i > e and mins[i] >= 960:
                ex = bo[i] if side > 0 else ao[i]
                break
            if side > 0:
                if i > e and (bo[i] <= stop or bo[i] >= tp):
                    ex = bo[i]
                    break
                if bl[i] <= stop:
                    ex = stop
                    break
                if i > e and bh[i] >= tp:
                    ex = tp
                    break
            else:
                if i > e and (ao[i] >= stop or ao[i] <= tp):
                    ex = ao[i]
                    break
                if ah[i] >= stop:
                    ex = stop
                    break
                if i > e and al[i] <= tp:
                    ex = tp
                    break
        out[d] = side * (ex - entry) / sd - 0.5e-4 * entry / sd
    return out


def m1(sym):
    def rd(folder):
        fs = sorted((M1 / folder).glob(f"{sym}_*.csv"))
        df = pd.concat([pd.read_csv(f) for f in fs]).drop_duplicates("timestamp").sort_values("timestamp")
        df.index = pd.to_datetime(df.pop("timestamp"), unit="ms", utc=True)
        return df
    b, a = rd("fx"), rd("fx_ask")
    idx = b.index.intersection(a.index)
    b, a = b.loc[idx], a.loc[idx]
    keep = (b["high"] > b["low"]) | (b["close"] != b["open"])
    b, a = b[keep], a[keep]
    ny = b.index.tz_convert("America/New_York")
    mins = np.asarray(ny.hour * 60 + ny.minute, dtype=np.int64)
    day = np.asarray((ny.tz_localize(None).normalize() - pd.Timestamp("2000-01-01")).days)
    dstart = np.concatenate([[0], np.flatnonzero(np.diff(day)) + 1, [len(day)]]).astype(np.int64)
    dlabel = ny.tz_localize(None).normalize()[dstart[:-1]].to_numpy()
    arrs = [b[c].to_numpy() for c in ("open", "high", "low", "close")] + [a[c].to_numpy() for c in ("open", "high", "low", "close")]
    return dstart, mins, arrs, dlabel


def main():
    res = pd.read_pickle(OUT)
    print("1) Dieselbe Regel (NY 09-10, Ausbruch, Stop Range, Ziel 1R) in allen 24 Märkten: Training / Bestätigung")
    for x in res:
        if x["key"][1:] == ("NY 09-10", "Ausbruch", "Range", "Ziel 1R"):
            a, b = period(x["t"], x["r"], "Training"), period(x["t"], x["r"], "Bestätigung")
            print(f"  {x['key'][0]:14s} {a.mean():+.3f} (t {tstat(a):+.2f}) / {b.mean():+.3f} (t {tstat(b):+.2f})")
    for sym in ("eurusd", "usdjpy"):
        print(f"\n2) {sym} je Jahr (H1):")
        x = [y for y in res if y["key"] == (sym, "NY 09-10", "Ausbruch", "Range", "Ziel 1R")][0]
        ys = pd.Series(x["r"], index=pd.DatetimeIndex(x["t"])).groupby(lambda d: d.year)
        print("  " + ", ".join(f"{k} {v.mean():+.2f}" for k, v in ys))
        ds, sh, arrs, lab = h1_arrays(sym, 2.0)
        r = run(ds, sh, *arrs, 14, 15, 19, 0, 1.0, 1.0)
        m = ~np.isnan(r)
        print(f"3) doppelter Spread: " + " | ".join(f"{nm} {describe(period(lab[m], r[m], nm))}" for nm in PERIODS))
        ds, mins, arrs, lab = m1(sym)
        r = run_m1(ds, mins, *arrs)
        m = ~np.isnan(r)
        print(f"4) Minuten-Nachrechnung (2008-2025, Bid/Ask):")
        for nm, (a, b) in {"vor Training 2008-2012/06": ("2008-01-01", "2012-06-30"), **PERIODS}.items():
            mm = (lab[m] >= np.datetime64(a)) & (lab[m] <= np.datetime64(b))
            print(f"   {nm:26s} {describe(r[m][mm])}")


if __name__ == "__main__":
    main()

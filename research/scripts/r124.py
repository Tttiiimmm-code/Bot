"""Runde 124: 1.872 Sitzungs-Range-Varianten auf Dukascopy-Minuten (13 Märkte) -- Vorab: r124_prereg.md."""
from __future__ import annotations

import itertools
import sys
import time
from pathlib import Path

import numba
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from r102 import load  # noqa: E402

D = Path("data_cache/dukascopy")
OUT = Path(__file__).with_name("r124_results.pkl")
PERIODS = {"Training": ("2008-01-01", "2017-12-31"), "Bestätigung": ("2018-01-01", "2021-12-31"),
           "Endtest": ("2022-01-01", "2025-12-31")}
# Markt: (Bid-Muster, Ask-Muster oder None, H1-Symbol für den Spread)
MARKETS = {"EURUSD": ("fx/eurusd", "fx_ask/eurusd", "eurusd"), "GBPUSD": ("fx/gbpusd", "fx_ask/gbpusd", "gbpusd"),
           "XAUUSD": ("xau/xau", "xau_ask/xau", "xauusd"), "USDJPY": ("fx/usdjpy", "fx_ask/usdjpy", "usdjpy"),
           "DAX": ("dax/dax", None, "deuidxeur"), "CAC": ("idx/fraidxeur", None, "fraidxeur"),
           "FTSE": ("idx/gbridxgbp", None, "gbridxgbp"), "Nikkei": ("idx/jpnidxjpy", None, "jpnidxjpy"),
           "HangSeng": ("idx/hkgidxhkd", None, "hkgidxhkd"), "ASX": ("idx/ausidxaud", None, "ausidxaud"),
           "US500": ("idx/usa500idxusd", None, "usa500idxusd"), "USTEC": ("idx/usatechidxusd", None, "usatechidxusd"),
           "WTI": ("oil/download/wti", None, "lightcmdusd")}
RANGES = (("Asien 19-02", 0, 420, 960), ("Vor-London 00-03", 300, 480, 960), ("London 03-04", 480, 540, 960),
          ("Europa 03:00-03:30", 480, 510, 960), ("NY 09:30-10:00", 870, 900, 1200), ("NY 09:30-09:45", 870, 885, 1200))
EXIT_MIN = 1260


def read(pattern):
    folder, name = pattern.rsplit("/", 1)
    fs = sorted((D / folder).glob(f"{name}_*.csv"))
    df = pd.concat([pd.read_csv(f) for f in fs if f.stat().st_size > 0])
    df = df.drop_duplicates("timestamp").sort_values("timestamp")
    df.index = pd.to_datetime(df.pop("timestamp"), unit="ms", utc=True)
    return df[["open", "high", "low", "close"]].astype(float)


@numba.njit(cache=True)
def run(dstart, smin, bo, bh, bl, bc, ao, ah, al, ac, ra, rb, tend, mode, sfrac, tpr, narrow):
    nd = len(dstart) - 1
    out = np.full(nd, np.nan)
    hist = np.full(nd, np.nan)
    nh = 0
    for d in range(nd):
        s, e_ = dstart[d], dstart[d + 1]
        rh, rl, cnt = -1e30, 1e30, 0
        for i in range(s, e_):
            if ra <= smin[i] < rb:
                rh, rl, cnt = max(rh, bh[i]), min(rl, bl[i]), cnt + 1
        if cnt < 0.5 * (rb - ra) or not rh > rl:
            continue
        rs = rh - rl
        okn = True
        if narrow:
            if nh < 20:
                okn = False
            else:
                okn = rs < np.median(hist[nh - 20:nh])
        hist[nh] = rs
        nh += 1
        if not okn:
            continue
        e, side, entry = -1, 0, 0.0
        for i in range(s, e_):
            if smin[i] < rb:
                continue
            if smin[i] >= tend:
                break
            up, dn = bh[i] > rh, bl[i] < rl
            if up and dn:
                e = -2
                break
            spr = ao[i] - bo[i]
            if up:
                e = i
                if mode == 0:
                    side, entry = 1, max(ao[i], rh + spr)
                else:
                    side, entry = -1, max(bo[i], rh)
                break
            if dn:
                e = i
                if mode == 0:
                    side, entry = -1, min(bo[i], rl)
                else:
                    side, entry = 1, min(ao[i], rl + spr)
                break
        if e == -2:
            out[d] = -1.0
            continue
        if e < 0:
            continue
        sd = sfrac * rs
        stop = entry - side * sd
        use_tp = tpr > 0
        tp = entry + side * tpr * sd
        ex = bc[e_ - 1] if side > 0 else ac[e_ - 1]
        for i in range(e, e_):
            if i > e and smin[i] >= EXIT_MIN:
                ex = bo[i] if side > 0 else ao[i]
                break
            if side > 0:
                if i > e and (bo[i] <= stop or (use_tp and bo[i] >= tp)):
                    ex = bo[i]
                    break
                if bl[i] <= stop:
                    ex = stop
                    break
                if i > e and use_tp and bh[i] >= tp:
                    ex = tp
                    break
            else:
                if i > e and (ao[i] >= stop or (use_tp and ao[i] <= tp)):
                    ex = ao[i]
                    break
                if ah[i] >= stop:
                    ex = stop
                    break
                if i > e and use_tp and al[i] <= tp:
                    ex = tp
                    break
        out[d] = side * (ex - entry) / sd - 0.5e-4 * entry / sd
    return out


def tstat(r):
    return float(r.mean() / r.std(ddof=1) * np.sqrt(len(r))) if len(r) > 2 and r.std() > 0 else float("nan")


def describe(r):
    if len(r) < 3:
        return f"n {len(r)}"
    w, l_ = r[r > 0].sum(), -r[r < 0].sum()
    return (f"n {len(r):5d}  Ø R {r.mean():+.3f}  t {tstat(r):+.2f}  Treffer {(r > 0).mean():.0%}  "
            f"PF {w / l_ if l_ > 0 else float('inf'):.2f}")


def main():
    t0 = time.time()
    results = []
    for mk, (bp, ap, h1) in MARKETS.items():
        bid = read(bp)
        hb, ha = load(h1)
        spr = float((ha["close"] - hb["close"]).median()) * 1.5
        ask = bid + spr
        if ap is not None:
            real = read(ap).reindex(bid.index)
            ok = real.notna().all(axis=1)
            ask.loc[ok] = real.loc[ok]
        ny = bid.index.tz_convert("America/New_York")
        shifted = ny + pd.Timedelta(hours=5)
        smin = np.asarray(shifted.hour * 60 + shifted.minute, dtype=np.int64)
        day = np.asarray((shifted.tz_localize(None).normalize() - pd.Timestamp("2000-01-01")).days)
        dstart = np.concatenate([[0], np.flatnonzero(np.diff(day)) + 1, [len(day)]]).astype(np.int64)
        dlabel = shifted.tz_localize(None).normalize()[dstart[:-1]].to_numpy()
        arrs = [bid[c].to_numpy() for c in ("open", "high", "low", "close")] + \
               [ask[c].to_numpy() for c in ("open", "high", "low", "close")]
        for (rn, ra, rb, te), mi, (sn, sf), (en, tp), nf in itertools.product(
                RANGES, range(2), (("Range", 1.0), ("halbe Range", 0.5)),
                (("Ziel 1R", 1.0), ("Ziel 2R", 2.0), ("16:00 NY", 0.0)), (False, True)):
            r = run(dstart, smin, *arrs, ra, rb, te, mi, sf, tp, nf)
            m = ~np.isnan(r)
            results.append(dict(key=(mk, rn, ("Ausbruch", "Fehlausbruch")[mi], sn, en, "eng" if nf else "alle"),
                                t=dlabel[m], r=r[m]))
        print(f"{mk}: {len(bid)} Minuten, Spread-Zuschlag {spr:.5g} ({time.time() - t0:.0f} s)", flush=True)
        del bid, ask, arrs
    pd.to_pickle(results, OUT)

    def period(x, nm):
        a, b = PERIODS[nm]
        m = (x["t"] >= np.datetime64(a)) & (x["t"] <= np.datetime64(b))
        return x["r"][m]

    rows = []
    for i, x in enumerate(results):
        a, b = period(x, "Training"), period(x, "Bestätigung")
        mk, rn, mo, sn, en, nf = x["key"]
        rows.append(dict(i=i, n=len(a), avg=a.mean() if len(a) else np.nan, t=tstat(a),
                         conf=b.mean() if len(b) else np.nan, tc=tstat(b), mk=mk, rng=rn, mode=mo, stop=sn, exit=en, filt=nf))
    tr = pd.DataFrame(rows)
    print(f"\nTraining: {len(tr)} | t >= 2: {(tr.t >= 2).sum()} | t >= 3: {(tr.t >= 3).sum()} | t >= 4: {(tr.t >= 4).sum()}"
          f" | Ø > 0: {(tr.avg > 0).sum()} | Median {tr.avg.median():+.3f} R")
    for c_ in ("mk", "rng", "mode", "stop", "exit", "filt"):
        g = tr.groupby(c_)
        print(f"  {c_}: " + ", ".join(f"{k} {a:+.3f}->{b:+.3f}" for k, a, b in
                                      zip(g.groups.keys(), g.avg.median(), g.conf.median())))
    print(f"  t >= 2 in beiden: {((tr.t >= 2) & (tr.tc >= 2)).sum()}")
    for _, row in tr[(tr.t >= 2) & (tr.tc >= 2)].sort_values("tc", ascending=False).head(8).iterrows():
        print(f"    {' '.join(results[int(row.i)]['key'])}: {row.avg:+.3f} (t {row.t:.2f}) / {row.conf:+.3f} (t {row.tc:.2f})")

    def show(row, count):
        x = results[int(row.i)]
        print(f"\n=== {' '.join(x['key'])}")
        print(f"  Training:    {describe(period(x, 'Training'))}")
        r = period(x, "Bestätigung")
        ok = len(r) > 2 and r.mean() > 0 and tstat(r) >= 2.4
        print(f"  Bestätigung: {describe(r)}  -> {'BESTANDEN' if ok else 'nicht bestanden'}")
        if count and ok:
            r = period(x, "Endtest")
            fin = len(r) > 2 and r.mean() > 0 and tstat(r) >= 2
            print(f"  Endtest:     {describe(r)}  -> {'BESTANDEN' if fin else 'nicht bestanden'}")
        elif count:
            print("  Endtest: nicht angesehen")

    el = tr[(tr.n >= 200) & (tr.avg > 0) & (tr.t >= 4)].sort_values("t", ascending=False).head(3)
    print(f"\n--- Zählende Auswahl (n >= 200, Ø > 0, t >= 4): {len(el)}")
    for _, row in el.iterrows():
        show(row, True)
    if el.empty:
        print("  keine -> RUNDE NICHT BESTANDEN")
    print("\n--- Nur Information: 3 beste Trainings-t")
    for _, row in tr[(tr.n >= 200) & (tr.avg > 0)].sort_values("t", ascending=False).head(3).iterrows():
        show(row, False)
    print(f"Laufzeit {time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()

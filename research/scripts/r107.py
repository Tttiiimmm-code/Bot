"""Runde 107: 1.440 Konfigurationen Aktien-ORB auf "Stocks in Play" -- Vorab: r107_prereg.md."""
from __future__ import annotations

import itertools
import time
from pathlib import Path

import numba
import numpy as np
import pandas as pd

U = Path("data_cache/universe")
CACHE = Path(__file__).with_name("r107_arrays.npz")
OUT = Path(__file__).with_name("r107_results.pkl")
PERIODS = {"Training": ("2016-01-01", "2019-12-31"), "Bestätigung": ("2020-01-01", "2022-12-31"),
           "Endtest": ("2023-01-01", "2026-12-31")}
OR_LEN = (5, 15, 30)
SIDES = ("beide", "nur long", "long+Lücke2%")
FILTERS = ("ohne", "VWAP")
STOPS = (("OR-Gegenseite", 0.0), ("10% ATR", 0.10), ("25% ATR", 0.25), ("50% ATR", 0.50))
EXITS = (("Ziel 1R", 1.0), ("Ziel 2R", 2.0), ("Ziel 3R", 3.0), ("Tagesschluss", 0.0), ("Einstand+Schluss", 0.0))
TOPN = (5, 20)
CUTOFF = (("bis 10:30", 60), ("bis 15:00", 330))


def build():
    cand = pd.read_pickle(U / "candidates.pkl")
    cand = cand.sort_values("relvol", ascending=False)
    cand["rank"] = cand.groupby(level="date").cumcount()
    feats = pd.read_pickle(U / "features.pkl")["prev_close"]
    cand = cand.join(feats.swaplevel().rename("prev_close"), how="left").sort_index()
    cand["gap"] = cand["open"] / cand["prev_close"] - 1
    cand = cand.reset_index()
    cand["date"] = pd.to_datetime(cand["date"]).astype("datetime64[s]")
    cand = cand.set_index(["date", "symbol"])
    parts = []
    for f in sorted((U / "intraday").glob("*.pkl")):
        x = pd.read_pickle(f)
        ts = x.index.get_level_values("timestamp").tz_convert("America/New_York")
        m = np.asarray(ts.hour * 60 + ts.minute - 570)
        keep = (m >= 0) & (m < 390)
        df = pd.DataFrame({"symbol": np.asarray(x.index.get_level_values("symbol"))[keep],
                           "date": pd.DatetimeIndex(ts.date)[keep], "mi": m[keep].astype(np.int16)})
        for col in ("open", "high", "low", "close", "volume"):
            df[col] = x[col].to_numpy()[keep].astype(np.float32)
        parts.append(df)
        print(f.name, len(df), flush=True)
    bars = pd.concat(parts, ignore_index=True)
    bars = bars.sort_values(["date", "symbol", "mi"], kind="stable").reset_index(drop=True)
    meta = bars.groupby(["date", "symbol"], sort=False).size().rename("n").reset_index()
    meta["start"] = np.concatenate([[0], np.cumsum(meta["n"].to_numpy())[:-1]])
    meta = meta.join(cand[["rank", "atr", "gap"]], on=["date", "symbol"], how="inner")
    np.savez(CACHE, o=bars.open.to_numpy(), h=bars.high.to_numpy(), l=bars.low.to_numpy(), c=bars.close.to_numpy(),
             v=bars.volume.to_numpy(), mi=bars.mi.to_numpy(), start=meta.start.to_numpy(np.int64),
             n=meta.n.to_numpy(np.int64), rank=meta["rank"].to_numpy(np.int64), atr=meta.atr.to_numpy(np.float64),
             gap=meta.gap.fillna(-1).to_numpy(np.float64), date=meta.date.to_numpy().astype("datetime64[D]"))


@numba.njit(parallel=True, cache=True)
def sim(o, h, l, c, v, mi, start, n, rank, atr, gap, orlen, side_mode, vwap_f, stop_mode, frac, exit_mode, tp_r,
        topn, cutoff):
    nd = len(start)
    out = np.full(nd, np.nan)
    for d in numba.prange(nd):
        if rank[d] >= topn:
            continue
        s, L = start[d], n[d]
        if mi[s] != 0:
            continue
        oro = o[s]
        orh, orl, orc = -1e30, 1e30, 0.0
        k = s
        while k < s + L and mi[k] < orlen:
            if h[k] > orh:
                orh = h[k]
            if l[k] < orl:
                orl = l[k]
            orc = c[k]
            k += 1
        if k >= s + L:
            continue
        if orc > oro:
            side = 1
        elif orc < oro and side_mode == 0:
            side = -1
        else:
            continue
        if side_mode == 2 and gap[d] < 0.02:
            continue
        level = orh if side > 0 else orl
        cpv, cv = 0.0, 0.0
        e = -1
        entry = 0.0
        for j in range(s, s + L):
            if mi[j] > cutoff:
                break
            if mi[j] >= orlen and j > s:
                ok = True
                if vwap_f == 1:
                    if cv <= 0:
                        ok = False
                    else:
                        vw = cpv / cv
                        ok = (c[j - 1] > vw) if side > 0 else (c[j - 1] < vw)
                if ok:
                    if side > 0 and h[j] > level:
                        e, entry = j, max(o[j], level)
                        break
                    if side < 0 and l[j] < level:
                        e, entry = j, min(o[j], level)
                        break
            cpv += (h[j] + l[j] + c[j]) / 3.0 * v[j]
            cv += v[j]
        if e < 0:
            continue
        if stop_mode == 0:
            stop = orl if side > 0 else orh
        else:
            stop = entry - side * frac * atr[d]
        sd = (entry - stop) * side
        if not sd > 0:
            continue
        use_tp = exit_mode <= 2
        tp = entry + side * tp_r * sd
        ex = c[s + L - 1]
        for j in range(e, s + L):
            if side > 0:
                if j > e:
                    if o[j] <= stop or (use_tp and o[j] >= tp):
                        ex = o[j]
                        break
                if l[j] <= stop:
                    ex = stop
                    break
                if j > e and use_tp and h[j] >= tp:
                    ex = tp
                    break
                if exit_mode == 4 and h[j] >= entry + sd and stop < entry:
                    stop = entry
            else:
                if j > e:
                    if o[j] >= stop or (use_tp and o[j] <= tp):
                        ex = o[j]
                        break
                if h[j] >= stop:
                    ex = stop
                    break
                if j > e and use_tp and l[j] <= tp:
                    ex = tp
                    break
                if exit_mode == 4 and l[j] <= entry - sd and stop > entry:
                    stop = entry
        cost = 2.0 * (0.0001 * entry + 0.01) / sd
        out[d] = side * (ex - entry) / sd - cost
    return out


def tstat(x):
    return float(x.mean() / x.std(ddof=1) * np.sqrt(len(x))) if len(x) > 2 and x.std() > 0 else float("nan")


def stats(r, dates, a, b):
    m = (dates >= np.datetime64(a)) & (dates <= np.datetime64(b)) & ~np.isnan(r)
    rr, dd = r[m], dates[m]
    if len(rr) < 3:
        return dict(n=len(rr), avg=np.nan, t=np.nan, desc=f"n {len(rr)}")
    daily = pd.Series(rr).groupby(dd).sum().to_numpy()
    w, lo = rr[rr > 0].sum(), -rr[rr < 0].sum()
    t = tstat(daily)
    desc = (f"n {len(rr):6d}  Ø R {rr.mean():+.3f}  t(Tage) {t:+.2f}  Treffer {(rr > 0).mean():.0%}  "
            f"PF {w / lo if lo > 0 else float('inf'):.2f}  Summe {rr.sum():+.0f} R")
    return dict(n=len(rr), avg=rr.mean(), t=t, desc=desc)


def main():
    t0 = time.time()
    if not CACHE.exists():
        build()
    z = np.load(CACHE)
    arrs = [z[k] for k in ("o", "h", "l", "c", "v", "mi", "start", "n", "rank", "atr", "gap")]
    dates = z["date"]
    print(f"Kandidaten-Tage: {len(dates)} ({time.time() - t0:.0f} s)", flush=True)
    grid = list(itertools.product(OR_LEN, range(3), range(2), range(4), range(5), TOPN, CUTOFF))
    results = []
    for gi, (orl, sm, vf, st, exm, tn, cut) in enumerate(grid):
        r = sim(*arrs, orl, sm, vf, 0 if st == 0 else 1, STOPS[st][1], exm, EXITS[exm][1], tn, cut[1])
        name = f"OR{orl} {SIDES[sm]} {FILTERS[vf]} Stop {STOPS[st][0]} {EXITS[exm][0]} Top{tn} {cut[0]}"
        feats = dict(orl=orl, side=SIDES[sm], filt=FILTERS[vf], stop=STOPS[st][0], exit=EXITS[exm][0], top=tn,
                     cut=cut[0])
        results.append(dict(name=name, feats=feats, r=r.astype(np.float32)))
        if gi % 120 == 0:
            print(f"{gi}/{len(grid)} ({time.time() - t0:.0f} s)", flush=True)
    pd.to_pickle(dict(dates=dates, results=results), OUT)

    rows = []
    for i, x in enumerate(results):
        s = stats(x["r"].astype(float), dates, *PERIODS["Training"])
        rows.append(dict(i=i, n=s["n"], avg=s["avg"], t=s["t"], **x["feats"]))
    tr = pd.DataFrame(rows)
    print(f"\nTraining 2016-2019: {len(tr)} Konfigurationen | t >= 2: {(tr.t >= 2).sum()} | t >= 3: {(tr.t >= 3).sum()} "
          f"| t >= 4: {(tr.t >= 4).sum()} | Ø R > 0: {(tr.avg > 0).sum()} | Median Ø R {tr.avg.median():+.3f}")
    for col in ("orl", "side", "filt", "stop", "exit", "top", "cut"):
        print(f"  Median Ø R je {col}: " + ", ".join(f"{k} {v:+.3f}" for k, v in tr.groupby(col).avg.median().items()))

    def show(row, count):
        x = results[int(row.i)]
        r = x["r"].astype(float)
        print(f"\n=== {x['name']}")
        print(f"  Training:    {stats(r, dates, *PERIODS['Training'])['desc']}")
        s = stats(r, dates, *PERIODS["Bestätigung"])
        ok = s["n"] > 2 and s["avg"] > 0 and s["t"] >= 2.4
        print(f"  Bestätigung: {s['desc']}  -> {'BESTANDEN' if ok else 'nicht bestanden'}")
        if count and ok:
            s = stats(r, dates, *PERIODS["Endtest"])
            fin = s["n"] > 2 and s["avg"] > 0 and s["t"] >= 2
            print(f"  Endtest:     {s['desc']}  -> {'BESTANDEN' if fin else 'nicht bestanden'}")
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
    conf = np.array([stats(x["r"].astype(float), dates, *PERIODS["Bestätigung"])["avg"] for x in results])
    print(f"\nFamilie in der Bestätigung (nur Information): Median Ø R {np.nanmedian(conf):+.3f}, "
          f"Anteil > 0: {(conf > 0).mean():.0%}")
    print(f"\nLaufzeit {time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()

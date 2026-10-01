"""Runde 123: 1.152 Varianten taktische Vermögensaufteilung -- Vorab: r123_prereg.md."""
from __future__ import annotations

import itertools
import time
from pathlib import Path

import numpy as np
import pandas as pd

OUT = Path(__file__).with_name("r123_results.pkl")
UNIVERSES = {"GEM": ["SPY", "EFA"], "GTAA5": ["SPY", "EFA", "IEF", "VNQ", "DBC"],
             "10 ETFs": ["SPY", "QQQ", "IWM", "EFA", "EEM", "IEF", "TLT", "GLD", "VNQ", "DBC"],
             "11 ETFs": ["SPY", "IWM", "EFA", "EEM", "VNQ", "DBC", "IEF", "TLT", "GLD", "TIP", "LQD"]}
SIGNALS = ["SMA6", "SMA8", "SMA10", "SMA12", "R1", "R3", "R6", "R12", "Keller"]
PERIODS = {"Training": ("2007-03-01", "2013-12-31"), "Bestätigung": ("2014-01-01", "2019-12-31"),
           "Endtest": ("2020-01-01", "2025-12-31")}


def tstat(x):
    return float(x.mean() / x.std(ddof=1) * np.sqrt(len(x))) if len(x) > 2 and x.std() > 0 else float("nan")


def main():
    t0 = time.time()
    tick = sorted(set(sum(UNIVERSES.values(), [])) | {"SHY", "IEF"})
    P = pd.DataFrame({t: pd.read_pickle(f"data_cache/yahoo/{t}_full.pkl")["adjclose"] for t in tick})
    P.index = pd.DatetimeIndex(P.index)
    P = P.sort_index().ffill()
    dr = P.pct_change(fill_method=None)
    per = P.index.to_period("M")
    me = np.flatnonzero(np.r_[per[1:] != per[:-1], False])           # letzter Handelstag je Monat (ohne letzten)
    ex = me + 1                                                          # erster Handelstag des Folgemonats
    Pm = P.iloc[me]
    sig = {}
    for n in (6, 8, 10, 12):
        sig[f"SMA{n}"] = Pm / Pm.rolling(n).mean() - 1
    for L in (1, 3, 6, 12):
        sig[f"R{L}"] = Pm / Pm.shift(L) - 1
    sig["Keller"] = 12 * sig["R1"] + 4 * sig["R3"] + 2 * sig["R6"] + sig["R12"]
    vol = dr.rolling(63).std().iloc[me] * np.sqrt(252)
    K = len(me) - 1
    Rh = pd.DataFrame(P.iloc[ex[1:]].to_numpy() / P.iloc[ex[:-1]].to_numpy() - 1, columns=P.columns)   # Halten k
    end_dates = P.index[ex[1:]]
    cov_cache = {}

    def cov(k, cols):
        key = (k, tuple(cols))
        if key not in cov_cache:
            cov_cache[key] = dr.iloc[me[k] - 62:me[k] + 1][list(cols)].cov().to_numpy() * 252
        return cov_cache[key]

    results = []
    for (un, assets), sn, sel, wt, safe, vt in itertools.product(UNIVERSES.items(), SIGNALS, ("alle", 1, 2, 3),
                                                                 ("gleich", "invers Vola"), ("SHY", "IEF"),
                                                                 (False, True)):
        S = sig[sn][assets]
        cols = list(dict.fromkeys(assets + [safe, "SHY"]))
        ci = {c: i for i, c in enumerate(cols)}
        prev = np.zeros(len(cols))
        out, idx, bench = [], [], []
        for k in range(K):
            s = S.iloc[k]
            if s.isna().any() or Rh.iloc[k][cols].isna().any() or me[k] < 63:
                continue
            pos = s[s > 0]
            nslots = len(assets) if sel == "alle" else sel
            chosen = list(pos.index) if sel == "alle" else list(pos.sort_values(ascending=False).index[:sel])
            w = np.zeros(len(cols))
            if chosen:
                if wt == "gleich":
                    ww = np.ones(len(chosen))
                else:
                    ww = 1 / vol.iloc[k][chosen].to_numpy()
                ww = ww / ww.sum() * len(chosen) / nslots
                for c, v in zip(chosen, ww):
                    w[ci[c]] += v
            w[ci[safe]] += 1 - w.sum()
            if vt:
                pv = np.sqrt(max(w @ cov(k, cols) @ w, 1e-12))
                scale = min(1.0, 0.10 / pv)
                w = w * scale
                w[ci["SHY"]] += 1 - scale
            r = Rh.iloc[k][cols].to_numpy()
            out.append(w @ r - 0.001 * np.abs(w - prev).sum())
            bench.append(Rh.iloc[k][assets].mean())
            idx.append(end_dates[k])
            prev = w
        s_ = pd.Series(out, index=pd.DatetimeIndex(idx))
        b_ = pd.Series(bench, index=pd.DatetimeIndex(idx))
        results.append(dict(name=f"{un}, Signal {sn}, Auswahl {sel}, Gewichtung {wt}, Hafen {safe}"
                                 f"{', Vola-Ziel 10 %' if vt else ''}",
                            feats=dict(univ=un, sig=sn, sel=str(sel), wt=wt, safe=safe, vt=vt), strat=s_, bench=b_))
    print(f"{len(results)} Varianten ({time.time() - t0:.0f} s)", flush=True)
    pd.to_pickle(results, OUT)

    def cut(s_, nm):
        a, b = PERIODS[nm]
        return s_[(s_.index >= a) & (s_.index <= b)]

    def stats(x, nm):
        s_, b_ = cut(x["strat"], nm), cut(x["bench"], nm)
        ex_ = (s_ - b_).to_numpy()
        sh = s_.mean() / s_.std() * np.sqrt(12) if s_.std() > 0 else np.nan
        shb = b_.mean() / b_.std() * np.sqrt(12) if b_.std() > 0 else np.nan
        dd = ((1 + s_).cumprod() / (1 + s_).cumprod().cummax() - 1).min()
        ddb = ((1 + b_).cumprod() / (1 + b_).cumprod().cummax() - 1).min()
        return ex_, sh, shb, dd, ddb

    def desc(x, nm):
        ex_, sh, shb, dd, ddb = stats(x, nm)
        return (f"Monate {len(ex_)}  Überschuss {ex_.mean() * 1200:+.1f} % p.a.  t {tstat(ex_):+.2f}  |  Sharpe {sh:.2f} "
                f"(Halten {shb:.2f})  MaxDD {dd:.0%} (Halten {ddb:.0%})")

    rows = []
    for i, x in enumerate(results):
        a = stats(x, "Training")
        b = stats(x, "Bestätigung")
        rows.append(dict(i=i, avg=a[0].mean(), t=tstat(a[0]), conf=b[0].mean(), tc=tstat(b[0]), dsh=a[1] - a[2],
                         dshc=b[1] - b[2], **x["feats"]))
    tr = pd.DataFrame(rows)
    print(f"Training: t >= 2: {(tr.t >= 2).sum()} | t >= 3: {(tr.t >= 3).sum()} | t >= 4: {(tr.t >= 4).sum()} | "
          f"Ø > 0: {(tr.avg > 0).sum()} von {len(tr)}")
    print(f"Information Sharpe besser als Halten: Training {(tr.dsh > 0).mean():.0%}, Bestätigung {(tr.dshc > 0).mean():.0%}")
    for c_ in ("univ", "sig", "sel", "wt", "safe", "vt"):
        g = tr.groupby(c_)
        print(f"  {c_}: " + ", ".join(f"{k} {a * 1200:+.1f}->{b * 1200:+.1f}" for k, a, b in
                                      zip(g.groups.keys(), g.avg.median(), g.conf.median())))

    def show(row, count):
        x = results[int(row.i)]
        print(f"\n=== {x['name']}")
        print(f"  Training:    {desc(x, 'Training')}")
        ex_ = stats(x, "Bestätigung")[0]
        ok = ex_.mean() > 0 and tstat(ex_) >= 2.4
        print(f"  Bestätigung: {desc(x, 'Bestätigung')}  -> {'BESTANDEN' if ok else 'nicht bestanden'}")
        if count and ok:
            e_ = stats(x, "Endtest")[0]
            fin = e_.mean() > 0 and tstat(e_) >= 2
            print(f"  Endtest:     {desc(x, 'Endtest')}  -> {'BESTANDEN' if fin else 'nicht bestanden'}")
        elif count:
            print("  Endtest: nicht angesehen")

    el = tr[(tr.avg > 0) & (tr.t >= 4)].sort_values("t", ascending=False).head(3)
    print(f"\n--- Zählende Auswahl (Ø > 0, t >= 4): {len(el)}")
    for _, row in el.iterrows():
        show(row, True)
    if el.empty:
        print("  keine -> RUNDE NICHT BESTANDEN")
    print("\n--- Nur Information: 3 beste Trainings-t")
    for _, row in tr[tr.avg > 0].sort_values("t", ascending=False).head(3).iterrows():
        show(row, False)
    print(f"Laufzeit {time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()

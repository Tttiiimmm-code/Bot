"""Runde 109: 1.152 Varianten Lücken-Handel mit 9:30-Universum -- Vorab: r109_prereg.md."""
from __future__ import annotations

import itertools
import time
from pathlib import Path

import numpy as np
import pandas as pd

U = Path("data_cache/universe")
TABLE = Path(__file__).with_name("r109_table.pkl")
OUT = Path(__file__).with_name("r109_results.pkl")
PERIODS = {"Training": ("2016-01-01", "2019-12-31"), "Bestätigung": ("2020-01-01", "2022-12-31"),
           "Endtest": ("2023-01-01", "2026-12-31")}


def build():
    f = pd.read_pickle(U / "features.pkl")
    f = f[f["eligible"]].copy()
    f["gap"] = f["open"] / f["prev_close"] - 1
    f = f[f["gap"].abs() >= 0.02].reset_index()
    f["date"] = pd.to_datetime(f["date"])
    op = pd.concat([pd.read_pickle(p) for p in sorted((U / "opening").glob("*.pkl"))], ignore_index=True)
    op["date"] = pd.to_datetime(op["date"])
    op = op.rename(columns={"open": "o5_open", "close": "o5_close"})[["date", "symbol", "o5_open", "o5_close"]]
    t = f.merge(op, on=["date", "symbol"], how="inner")
    need = set(zip(t["symbol"], t["date"]))
    closes = []
    for p in sorted((U / "daily").glob("batch_*.pkl")):
        x = pd.read_pickle(p)
        if not len(x):
            continue
        d = pd.DataFrame({"symbol": x.index.get_level_values("symbol"),
                          "date": pd.to_datetime(x.index.get_level_values("timestamp").tz_convert("America/New_York")
                                                 .date), "close": x["close"].to_numpy()})
        d = d[[k in need for k in zip(d["symbol"], d["date"])]]
        closes.append(d)
    cl = pd.concat(closes).drop_duplicates(["symbol", "date"])
    t = t.merge(cl, on=["symbol", "date"], how="inner")
    t = t[(t.o5_close > 0) & (t.close > 0)]
    t.to_pickle(TABLE)
    print(f"Tabelle: {len(t)} Zeilen", flush=True)


def tstat(x):
    return float(x.mean() / x.std(ddof=1) * np.sqrt(len(x))) if len(x) > 2 and x.std() > 0 else float("nan")


def main():
    t0 = time.time()
    if not TABLE.exists():
        build()
    t = pd.read_pickle(TABLE)
    t["absgap"] = t["gap"].abs()
    t = t.sort_values(["date", "absgap"], ascending=[True, False]).reset_index(drop=True)
    gs = np.sign(t["gap"].to_numpy())
    ret = (t["close"] / t["o5_close"] - 1).to_numpy() * 1e4
    cost = 2 * (1.0 + 0.01 / t["o5_close"].to_numpy() * 1e4)
    confirm = np.sign(t["o5_close"] - t["o5_open"]).to_numpy() == gs
    dates = t["date"].to_numpy()
    grid = list(itertools.product((0.02, 0.04, 0.06, 0.10), (5, 10, 20, 100000), ("beide", "auf", "ab"), (5, 10, 20),
                                  (1e6, 3e6), ("mit", "gegen"), (False, True)))
    results = []
    for gi, (gth, top, dr, pmin, vmin, wa, conf) in enumerate(grid):
        m = (t["absgap"].to_numpy() >= gth) & (t["open"].to_numpy() >= pmin) & (t["avg_volume"].to_numpy() >= vmin)
        if dr == "auf":
            m &= gs > 0
        elif dr == "ab":
            m &= gs < 0
        if conf:
            m &= confirm
        idx = np.flatnonzero(m)
        rank = pd.Series(dates[idx]).groupby(dates[idx]).cumcount().to_numpy()
        idx = idx[rank < top]
        side = gs[idx] * (1 if wa == "mit" else -1)
        r = side * ret[idx] - cost[idx]
        daily = pd.Series(r).groupby(dates[idx]).mean()
        name = (f"Lücke >= {gth:.0%} Top{top if top < 1000 else ' alle'} {dr} Kurs >= {pmin} Vol >= {vmin / 1e6:.0f} Mio "
                f"{wa} {'mit 5-Min-Bestätigung' if conf else 'ohne Bestätigung'}")
        results.append(dict(name=name, feats=dict(gap=gth, top=top, dir=dr, price=pmin, vol=vmin, wa=wa, conf=conf),
                            daily=daily))
    pd.to_pickle(results, OUT)

    def per(daily, nm):
        a, b = PERIODS[nm]
        return daily[(daily.index >= a) & (daily.index <= b)].to_numpy()

    def desc(x):
        return f"Tage {len(x):4d}  Ø {x.mean():+.1f} bp/Tag  t {tstat(x):+.2f}  Tage positiv {(x > 0).mean():.0%}" if len(x) > 2 else f"Tage {len(x)}"

    rows = []
    for i, x in enumerate(results):
        a, b = per(x["daily"], "Training"), per(x["daily"], "Bestätigung")
        rows.append(dict(i=i, n=len(a), avg=a.mean() if len(a) else np.nan, t=tstat(a),
                         conf_avg=b.mean() if len(b) else np.nan, tc=tstat(b), **x["feats"]))
    tr = pd.DataFrame(rows)
    print(f"Training 2016-2019: {len(tr)} | t >= 2: {(tr.t >= 2).sum()} | t >= 3: {(tr.t >= 3).sum()} | t >= 4: "
          f"{(tr.t >= 4).sum()} | Ø > 0: {(tr.avg > 0).sum()} | Median {tr.avg.median():+.1f} bp")
    for col in ("gap", "top", "dir", "price", "vol", "wa", "conf"):
        g = tr.groupby(col)
        print(f"  {col}: " + ", ".join(f"{k} {a:+.1f}->{b:+.1f}" for k, a, b in
                                       zip(g.groups.keys(), g.avg.median(), g.conf_avg.median())))

    def show(row, count):
        x = results[int(row.i)]
        print(f"\n=== {x['name']}")
        print(f"  Training:    {desc(per(x['daily'], 'Training'))}")
        b = per(x["daily"], "Bestätigung")
        ok = len(b) > 2 and b.mean() > 0 and tstat(b) >= 2.4
        print(f"  Bestätigung: {desc(b)}  -> {'BESTANDEN' if ok else 'nicht bestanden'}")
        if count and ok:
            e = per(x["daily"], "Endtest")
            fin = len(e) > 2 and e.mean() > 0 and tstat(e) >= 2
            print(f"  Endtest:     {desc(e)}  -> {'BESTANDEN' if fin else 'nicht bestanden'}")
        elif count:
            print("  Endtest: nicht angesehen")

    el = tr[(tr.n >= 200) & (tr.avg > 0) & (tr.t >= 4)].sort_values("t", ascending=False).head(3)
    print(f"\n--- Zählende Auswahl (>= 200 Tage, Ø > 0, t >= 4): {len(el)}")
    for _, row in el.iterrows():
        show(row, True)
    if el.empty:
        print("  keine -> RUNDE NICHT BESTANDEN")
    print("\n--- Nur Information: 3 beste Trainings-t ohne Hürde")
    for _, row in tr[(tr.n >= 200) & (tr.avg > 0)].sort_values("t", ascending=False).head(3).iterrows():
        show(row, False)
    print(f"\nFamilie Bestätigung: Median {tr.conf_avg.median():+.1f} bp, positiv {(tr.conf_avg > 0).mean():.0%}")
    print(f"Laufzeit {time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()

"""Runde 135: Gold-Ausbruch, 12.000 Varianten + Bündel -- Vorab: PROTOCOL.md."""
import gc
import itertools
import math
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, r"C:\Users\Nutzer\Bot")
from r134 import h1_features, load  # noqa: E402
from r135_sim import sim2  # noqa: E402

TRAIN = ("2008-01-01", "2016-12-31")
CONF = ("2017-01-01", "2022-12-31")
END = ("2023-01-01", "2026-12-31")


def tstat(x):
    x = np.asarray(x, float)
    return float(x.mean() / x.std(ddof=1) * math.sqrt(len(x))) if len(x) > 2 and x.std() > 0 else float("nan")


def main():
    t0 = time.time()
    t, bid, ask = load()
    h_of_m, hh, hl, atr = h1_features(t, bid)
    arrs = [bid[c].to_numpy(np.float64) for c in ("open", "high", "low", "close")] + \
           [ask[c].to_numpy(np.float64) for c in ("open", "high", "low", "close")]
    wd, hr, mi = t.weekday.to_numpy(), t.hour.to_numpy(), t.minute.to_numpy()
    fri_stop = (wd == 4) & (hr >= 20)
    fri_cancel = (wd == 4) & ((hr > 20) | ((hr == 20) & (mi >= 55)))
    del bid, ask
    gc.collect()
    tt = t.tz_convert(None).to_numpy()
    rate = pd.read_pickle(r"C:\Users\Nutzer\Bot\data_cache\fred\IR3TIB01USM156N.pkl")
    rate = (rate.iloc[:, 0] if hasattr(rate, "columns") else rate) / 100
    rate.index = pd.to_datetime(rate.index)
    rate = rate.sort_index()
    lims = {k: (np.datetime64(a), np.datetime64(b + "T23:59")) for k, (a, b) in
            {"tr": TRAIN, "co": CONF, "en": END}.items()}
    grid = list(itertools.product((6, 12, 24, 48, 96), (0.0, 0.1, 0.25), (2, 4, 12, 24), (0.5, 1.0, 1.5, 2.0, 3.0),
                                  (1.0, 2.0, 3.0, 4.0, 6.0), (False, True), (False, True), (0.0, 3.0)))
    rows, keep = [], {}
    for gi, (n_lvl, buf, e, x, y, tr, lo, rng) in enumerate(grid):
        ei, r, xi, q = sim2(h_of_m, hh, hl, atr, *arrs, fri_stop, fri_cancel, n_lvl, e, x, y, tr, lo, buf, rng)
        tin, tout = tt[ei], tt[xi]
        hold = (tout - tin) / np.timedelta64(1, "D")
        side_long = True if lo else None
        rr = rate.reindex(pd.DatetimeIndex(tin), method="ffill").fillna(rate.iloc[-1]).to_numpy()
        # Richtung je Trade: Swap long (Zins + 2,5 %), short 1 % -- Richtung steckt im Vorzeichen nicht; Sim gibt sie
        # nicht aus, daher konservativ: alle Trades mit Long-Swap (für "beide" leicht zu streng)
        _ = side_long
        net = r - (rr + 0.025) * hold / 365 / q
        row = {"i": gi}
        for k, (a, b) in lims.items():
            m = (tin >= a) & (tin <= b)
            v = net[m]
            row[f"n_{k}"], row[f"m_{k}"], row[f"t_{k}"] = len(v), (v.mean() if len(v) else np.nan), tstat(v)
        rows.append(row)
        if row["n_tr"] >= 200 and row["t_tr"] >= 3:
            keep[gi] = (tout, net)
        if gi % 1000 == 999:
            print(f"{gi + 1} Varianten ({time.time() - t0:.0f} s)", flush=True)
    df = pd.DataFrame(rows)
    df.to_pickle(Path(__file__).with_name("r135_stats.pkl"))
    name = lambda g: (f"N{g[0]} Puffer {g[1]:g} Ablauf {g[2]}h SL {g[3]:g} TP {g[4]:g} {'Trail' if g[5] else '-'} "
                      f"{'long' if g[6] else 'beide'} {'eng' if g[7] else '-'}")
    print(f"\nTraining: Ø > 0 bei {(df.m_tr > 0).sum()} von {len(df)} | t >= 3: {(df.t_tr >= 3).sum()} | t >= 4: "
          f"{(df.t_tr >= 4).sum()} | Median Ø R {df.m_tr.median():+.3f}")
    print(f"Bestätigung: Ø > 0 bei {(df.m_co > 0).sum()} | Korrelation Training->Bestätigung (Ø R) "
          f"{df[['m_tr', 'm_co']].corr().iloc[0, 1]:+.2f}")
    for col, lab in ((6, "nur long"), (7, "Enge-Filter"), (5, "Trail")):
        g = df.assign(f=[grid[i][col] for i in df.i]).groupby("f")
        print(f"  Median Ø R je {lab}: " + ", ".join(f"{k}: Tr {v.m_tr.median():+.3f} / Best {v.m_co.median():+.3f}"
                                                  for k, v in g))
    el = df[(df.n_tr >= 200) & (df.m_tr > 0) & (df.t_tr >= 4)].sort_values("t_tr", ascending=False).head(3)
    print(f"\n--- A) Einzelauswahl (t >= 4): {len(el)}")
    for _, r_ in el.iterrows():
        ok = r_.m_co > 0 and r_.t_co >= 2.4
        print(f"  {name(grid[int(r_.i)])}: Training {r_.m_tr:+.3f} (t {r_.t_tr:.2f}, n {r_.n_tr}) -> Bestätigung "
              f"{r_.m_co:+.3f} (t {r_.t_co:.2f}) -> {'BESTANDEN' if ok else 'nicht bestanden'} | Endtest (berührt) "
              f"{r_.m_en:+.3f} (t {r_.t_en:.2f})")
    if el.empty:
        print("  keine")
    # B) Bündel
    k = len(keep)
    print(f"\n--- B) Bündel: {k} Varianten mit Training t >= 3")
    if k:
        allp = pd.concat([pd.Series(net * 0.01 / k, index=pd.DatetimeIndex(tout)) for tout, net in keep.values()])
        daily = allp.groupby(allp.index.normalize()).sum()
        days = pd.bdate_range("2008-01-01", "2026-09-25")
        daily = daily.reindex(days, fill_value=0.0)
        from tradingbot.forward_test import fetch_daily_yahoo
        from datetime import date
        spy = fetch_daily_yahoo("SPY", date(2007, 12, 1), date(2026, 9, 30))
        spy.index = pd.to_datetime(spy.index)
        for lab, (a, b) in (("Training", TRAIN), ("Bestätigung", CONF), ("Endtest (berührt)", END)):
            d = daily[a:b]
            yrs = len(d) / 252
            cagr = (1 + d).prod() ** (1 / yrs) - 1
            s = spy[a:b]
            spy_cagr = (s.iloc[-1] / s.iloc[0]) ** (1 / ((s.index[-1] - s.index[0]).days / 365.25)) - 1
            eq = (1 + d).cumprod()
            print(f"  {lab}: Bündel {cagr:+.1%} p.a. (t Tage {tstat(d):.2f}, MaxDD {(eq / eq.cummax() - 1).min():.1%})"
                  f" | S&P 500 {spy_cagr:+.1%} p.a.")
    best_ret = df.sort_values("m_tr", ascending=False).iloc[0]
    print(f"\nWarnbeispiel höchste Trainingsrendite: {name(grid[int(best_ret.i)])}: Training {best_ret.m_tr:+.3f} R "
          f"(n {best_ret.n_tr}) -> Bestätigung {best_ret.m_co:+.3f} R (t {best_ret.t_co:.2f})")
    print(f"Laufzeit {time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()

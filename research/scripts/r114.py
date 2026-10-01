"""Runden 114 (Quartalszahlen, 1.536) und 115 (Insiderkäufe, 576) -- Vorab: r114_prereg.md."""
from __future__ import annotations

import itertools
import json
import time
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

U = Path("data_cache/universe/daily")
E = Path("data_cache/edgar")
WIDE = Path(__file__).with_name("r114_wide.npz")
OUT = Path(__file__).with_name("r114_results.pkl")
PERIODS = {"Training": ("2016-01-01", "2019-12-31"), "Bestätigung": ("2020-01-01", "2022-12-31"),
           "Endtest": ("2023-01-01", "2026-12-31")}


def build_wide():
    Os, Cs, Vs = [], [], []
    for p in sorted(U.glob("batch_*.pkl")):
        x = pd.read_pickle(p)
        if not len(x):
            continue
        d = pd.to_datetime(x.index.get_level_values("timestamp").tz_convert("America/New_York").date)
        df = pd.DataFrame({"symbol": x.index.get_level_values("symbol"), "date": d, "open": x["open"].to_numpy(),
                           "close": x["close"].to_numpy(), "volume": x["volume"].to_numpy()})
        df = df.drop_duplicates(["date", "symbol"])
        for col, acc in (("open", Os), ("close", Cs), ("volume", Vs)):
            acc.append(df.pivot(index="date", columns="symbol", values=col).astype(np.float32))
    O, C, V = (pd.concat(a, axis=1).sort_index() for a in (Os, Cs, Vs))
    keep = ~O.columns.duplicated()
    O, C, V = O.loc[:, keep], C.loc[:, ~C.columns.duplicated()][O.columns], V.loc[:, ~V.columns.duplicated()][O.columns]
    np.savez(WIDE, O=O.to_numpy(np.float32), C=C.to_numpy(np.float32), V=V.to_numpy(np.float32),
             dates=O.index.to_numpy(), syms=np.array(O.columns, dtype=str))


def tstat(x):
    return float(x.mean() / x.std(ddof=1) * np.sqrt(len(x))) if len(x) > 2 and x.std() > 0 else float("nan")


def main():
    t0 = time.time()
    if not WIDE.exists():
        build_wide()
    z = np.load(WIDE, allow_pickle=True)
    O, C, V = z["O"].astype(np.float64), z["C"].astype(np.float64), z["V"].astype(np.float64)
    dates, syms = pd.DatetimeIndex(z["dates"]), list(z["syms"])
    T, M = C.shape
    col = {s: j for j, s in enumerate(syms)}
    print(f"{M} Symbole, {T} Tage ({time.time() - t0:.0f} s)", flush=True)
    # Kennzahlen
    Cf = pd.DataFrame(C).ffill().to_numpy()                       # letzter bekannter Schluss (Delisting)
    pc = np.vstack([np.full((1, M), np.nan), C[:-1]])
    dv = pd.DataFrame(C * V).rolling(20, min_periods=15).mean().shift(1).to_numpy()
    rank = pd.DataFrame(np.where((C > 0) & np.isfinite(dv), dv, np.nan)).rank(axis=1, ascending=False).to_numpy()
    mkt_u = (rank <= 1500) & (pc > 5)
    cc = np.where(mkt_u, C / pc - 1, np.nan)
    on = np.where(mkt_u, O / pc - 1, np.nan)
    ew_cc = np.nan_to_num(np.nanmean(np.clip(cc, -0.9, 5), axis=1))
    ew_on = np.nan_to_num(np.nanmean(np.clip(on, -0.9, 5), axis=1))
    lvl_c = np.cumprod(1 + ew_cc)                                 # Markt-Index zum Schluss
    lvl_o = np.concatenate([[1.0], lvl_c[:-1]]) * (1 + ew_on)     # Markt-Index zur Eröffnung
    vavg = pd.DataFrame(V).rolling(20, min_periods=15).mean().shift(1).to_numpy()
    sma200 = pd.DataFrame(C).rolling(200, min_periods=150).mean().to_numpy()
    print(f"Kennzahlen ({time.time() - t0:.0f} s)", flush=True)

    def trades(j, e, at_open, hold):
        """Vektorisiert: Einstieg Tag e (Open oder Schluss), Ausstieg Schluss nach hold Tagen; Überschuss ggü. Markt."""
        ok = (e >= 1) & (e < T)
        x = e + hold - 1 if at_open else e + hold
        ok &= x < T
        j, e, x = j[ok], e[ok], x[ok]
        pin = O[e, j] if at_open else C[e, j]
        pout = Cf[x, j]
        m_in = lvl_o[e] if at_open else lvl_c[e]
        r = pout / pin - 1 - (lvl_c[x] / m_in - 1)
        good = np.isfinite(r) & (pin > 0)
        return ok.nonzero()[0][good], r[good], e[good]

    # ---------------- Runde 114: Quartalszahlen
    tick = json.loads(urllib.request.urlopen(urllib.request.Request(
        "https://www.sec.gov/files/company_tickers.json", headers={"User-Agent": "tradingbot-research-script"}),
        timeout=60).read())
    cik2sym = {}
    for v in tick.values():
        cik2sym.setdefault(str(v["cik_str"]).zfill(10), set()).add(v["ticker"].upper())
    ins = pd.read_pickle(E / "insider_purchases.pkl")
    for s, c in ins[["symbol", "issuer_cik"]].itertuples(index=False):
        cik2sym.setdefault(str(c).zfill(10), set()).add(s)
    ev = []
    days = dates
    for f in (E / "8k").glob("*.pkl"):
        acc = pd.read_pickle(f)["accepted"]
        js = [col[s] for s in cik2sym.get(f.stem, ()) if s in col]
        if not js or not len(acc):
            continue
        acc = pd.DatetimeIndex(acc)
        d = pd.DatetimeIndex(acc.tz_localize(None).normalize())
        after = np.asarray(acc.hour * 60 + acc.minute) >= 570
        pos = np.where(after, days.searchsorted(d, side="right"), days.searchsorted(d, side="left"))
        for j in js:
            for p in pos:
                if 1 <= p < T:
                    ev.append((j, p))
    ev = np.array(sorted(set(ev)), dtype=np.int64)
    j0, d0 = ev[:, 0], ev[:, 1]
    react_day = C[d0, j0] / C[d0 - 1, j0] - 1 - ew_cc[d0]
    react_gap = O[d0, j0] / C[d0 - 1, j0] - 1 - ew_on[d0]
    volok = V[d0, j0] >= 3 * vavg[d0, j0]
    trend = C[d0 - 1, j0] > sma200[d0 - 1, j0]
    rk = rank[d0, j0]
    price_ok = C[d0 - 1, j0] > 5
    print(f"R114: {len(ev)} Ergebnis-Ereignisse ({time.time() - t0:.0f} s)", flush=True)
    results = []
    for kind, th, dr, hold, un, vf, tf, delay in itertools.product(("Tag", "Lücke"), (0.03, 0.05, 0.10, 0.20),
                                                                   ("Gewinner", "Verlierer"), (1, 5, 20, 60),
                                                                   (500, 1500, 3000), (False, True), (False, True),
                                                                   (0, 2)):
        rx = react_day if kind == "Tag" else react_gap
        m = price_ok & (rk <= un) & np.isfinite(rx)
        m &= (rx >= th) if dr == "Gewinner" else (rx <= -th)
        if vf:
            m &= volok
        if tf:
            m &= trend
        idx = np.flatnonzero(m)
        e = d0[idx] + (1 if kind == "Tag" else 0) + delay
        sel, r, ee = trades(j0[idx], e, kind == "Tag", hold)
        cost = np.where(rk[idx][sel] <= 1500, 0.002, 0.005)
        r = r - cost
        results.append(dict(rnd=114, name=f"Quartalszahlen {kind}-Reaktion {dr} >= {th:.0%}, {hold} Tage, Top{un}"
                                          f"{', Volumen x3' if vf else ''}{', über SMA200' if tf else ''}"
                                          f"{f', Einstieg +{delay} Tage' if delay else ''}",
                            feats=dict(kind=kind, th=th, dir=dr, hold=hold, univ=un, vol=vf, trend=tf, delay=delay),
                            r=r, edate=dates[ee].to_numpy()))
    print(f"R114 fertig ({time.time() - t0:.0f} s)", flush=True)

    # ---------------- Runde 115: Insiderkäufe
    ins = ins.copy()
    ins["fd"] = pd.to_datetime(ins["filing_date"])
    ins = ins[ins["symbol"].isin(col)]
    ins["j"] = ins["symbol"].map(col)
    ins = ins.sort_values(["j", "fd"])
    for vmin, clus, un, hold, delay, down in itertools.product((25e3, 1e5, 5e5, 1e6), (1, 2, 3),
                                                               ("Top500", "501-3000", "alle"), (5, 20, 60, 120),
                                                               (1, 5), (False, True)):
        sub = ins[ins["value"] >= vmin]
        evs = []
        for j, g in sub.groupby("j"):
            fd = g["fd"].to_numpy()
            own = g["owner_cik"].to_numpy()
            last = None
            for k in range(len(g)):
                lo = fd[k] - np.timedelta64(30, "D")
                n_own = len(set(own[(fd >= lo) & (fd <= fd[k])]))
                if n_own >= clus and (last is None or fd[k] - last > np.timedelta64(30, "D")):
                    evs.append((j, fd[k]))
                    last = fd[k]
        if not evs:
            results.append(dict(rnd=115, name="leer", feats={}, r=np.array([]), edate=np.array([], "datetime64[ns]")))
            continue
        jj = np.array([a for a, _ in evs], dtype=np.int64)
        fdd = pd.DatetimeIndex([b for _, b in evs])
        e = days.searchsorted(fdd, side="right") + (delay - 1)
        ok = (e >= 21) & (e < T)
        jj, e = jj[ok], e[ok]
        rkk = rank[e, jj]
        pr = C[e - 1, jj]
        if un == "Top500":
            m = rkk <= 500
        elif un == "501-3000":
            m = (rkk > 500) & (rkk <= 3000)
        else:
            m = (pr > 2) & (dv[e, jj] > 1e5)
        m &= pr > 2
        if down:
            m &= (C[e - 1, jj] / C[e - 21, jj] - 1) <= -0.10
        jj, e, rkk = jj[m], e[m], rkk[m]
        sel, r, ee = trades(jj, e, True, hold)
        r = r - np.where(rkk[sel] <= 1500, 0.002, 0.005)
        results.append(dict(rnd=115, name=f"Insiderkauf >= {vmin / 1e3:.0f} Tsd. $, >= {clus} Insider, {un}, {hold} Tage, "
                                          f"Einstieg Tag {delay}{', nach -10 %' if down else ''}",
                            feats=dict(vmin=vmin, clus=clus, univ=un, hold=hold, delay=delay, down=down),
                            r=r, edate=dates[ee].to_numpy()))
    print(f"R115 fertig ({time.time() - t0:.0f} s)", flush=True)
    pd.to_pickle(results, OUT)

    def monthly(x, nm):
        a, b = PERIODS[nm]
        m = (x["edate"] >= np.datetime64(a)) & (x["edate"] <= np.datetime64(b))
        r, d = x["r"][m], x["edate"][m]
        if len(r) < 3:
            return np.array([]), 0
        s = pd.Series(r).groupby(pd.DatetimeIndex(d).to_period("M"))
        g = s.mean()[s.size() >= 3]
        return g.to_numpy(), len(r)

    def desc(x, nm):
        g, n = monthly(x, nm)
        return f"Trades {n:5d}  Monate {len(g):3d}  Ø {g.mean() * 100 if len(g) else 0:+.2f} %/Trade  t(Monate) {tstat(g):+.2f}"

    for rnd in (114, 115):
        rows = []
        for i, x in enumerate(results):
            if x["rnd"] != rnd or x["name"] == "leer":
                continue
            g, n = monthly(x, "Training")
            h, _ = monthly(x, "Bestätigung")
            rows.append(dict(i=i, n=n, months=len(g), avg=g.mean() if len(g) else np.nan, t=tstat(g),
                             conf=h.mean() if len(h) else np.nan, tc=tstat(h), **x["feats"]))
        tr = pd.DataFrame(rows)
        print(f"\n######## Runde {rnd}: {len(tr)} Varianten | Training t >= 2: {(tr.t >= 2).sum()} | t >= 3: "
              f"{(tr.t >= 3).sum()} | t >= 4: {(tr.t >= 4).sum()} | Ø > 0: {(tr.avg > 0).sum()}")
        for c_ in [c for c in tr.columns if c not in ("i", "n", "months", "avg", "t", "conf", "tc")]:
            g = tr.groupby(c_)
            print(f"  {c_}: " + ", ".join(f"{k} {a * 100:+.2f}->{b * 100:+.2f}" for k, a, b in
                                          zip(g.groups.keys(), g.avg.median(), g.conf.median())))

        def show(row, count):
            x = results[int(row.i)]
            print(f"\n=== {x['name']}")
            print(f"  Training:    {desc(x, 'Training')}")
            h, _ = monthly(x, "Bestätigung")
            ok = len(h) > 2 and h.mean() > 0 and tstat(h) >= 2.4
            print(f"  Bestätigung: {desc(x, 'Bestätigung')}  -> {'BESTANDEN' if ok else 'nicht bestanden'}")
            if count and ok:
                q, _ = monthly(x, "Endtest")
                fin = len(q) > 2 and q.mean() > 0 and tstat(q) >= 2
                print(f"  Endtest:     {desc(x, 'Endtest')}  -> {'BESTANDEN' if fin else 'nicht bestanden'}")
            elif count:
                print("  Endtest: nicht angesehen")

        el = tr[(tr.n >= 200) & (tr.months >= 24) & (tr.avg > 0) & (tr.t >= 4)].sort_values("t", ascending=False).head(3)
        print(f"\n--- Zählende Auswahl (>= 200 Trades, >= 24 Monate, Ø > 0, t >= 4): {len(el)}")
        for _, row in el.iterrows():
            show(row, True)
        if el.empty:
            print("  keine -> RUNDE NICHT BESTANDEN")
        print("\n--- Nur Information: 3 beste Trainings-t ohne Hürde (>= 200 Trades)")
        for _, row in tr[(tr.n >= 200) & (tr.avg > 0)].sort_values("t", ascending=False).head(3).iterrows():
            show(row, False)
        pos = tr[(tr.avg > 0) & (tr.n >= 200)]
        print(f"\nFamilie: {len(pos)} im Training positiv; davon Bestätigung positiv {(pos.conf > 0).mean():.0%}")
    print(f"Laufzeit {time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()

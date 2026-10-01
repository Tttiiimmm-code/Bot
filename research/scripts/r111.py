"""Runde 111: ~2.700 Krypto-Varianten (Binance Spot, täglich) -- Vorab: r111_prereg.md."""
from __future__ import annotations

import itertools
import time
from pathlib import Path

import numpy as np
import pandas as pd

D = Path("data_cache/crypto")
OUT = Path(__file__).with_name("r111_results.pkl")
PERIODS = {"Training": ("2018-01-01", "2021-12-31"), "Bestätigung": ("2022-01-01", "2023-12-31"),
           "Endtest": ("2024-01-01", "2026-12-31")}
STABLE = {"USDC", "BUSD", "TUSD", "USDP", "PAX", "DAI", "FDUSD", "USDE", "EUR", "GBP", "AEUR", "PYUSD", "USD1", "XUSD",
          "BFUSD", "EURI", "UST", "USTC", "SUSD", "USDS", "USDSB", "BKRW", "IDRT", "BIDR", "TRY", "RUB", "UAH", "NGN",
          "BRL", "AUD", "ZAR", "PAXG", "WBTC", "WBETH", "BETH", "USDJ", "RLUSD", "USD"}
COST = 0.001


def load():
    closes, qvs = {}, {}
    for f in sorted(D.glob("*USDT.pkl")):
        base = f.stem[:-4]
        if base in STABLE or (len(base) > 4 and base.endswith(("UP", "DOWN", "BULL", "BEAR"))):
            continue
        x = pd.read_pickle(f)
        if len(x) < 90:
            continue
        closes[base], qvs[base] = x["close"], x["quote_volume"]
    c = pd.DataFrame(closes).sort_index()
    q = pd.DataFrame(qvs).reindex(c.index)
    c.index = pd.to_datetime(c.index)
    q.index = c.index
    return c, q


def tstat(x):
    return float(x.mean() / x.std(ddof=1) * np.sqrt(len(x))) if len(x) > 2 and x.std() > 0 else float("nan")


def main():
    t0 = time.time()
    c, q = load()
    dates = c.index
    T, N = c.shape
    print(f"{N} Coins, {T} Tage", flush=True)
    R = c.pct_change(fill_method=None).clip(-0.95, 10).to_numpy(np.float64)
    R = np.nan_to_num(R)
    C = c.to_numpy(np.float64)
    adv = q.rolling(30, min_periods=20).mean().shift(1)
    hist = c.notna().cumsum() >= 60
    univ = {}
    for n in (20, 50):
        rk = adv.where(hist & c.notna()).rank(axis=1, ascending=False)
        univ[n] = (rk <= n).to_numpy()
    btc = c["BTC"]
    filt = {"kein": np.ones(T, bool), "BTC>SMA50": (btc > btc.rolling(50).mean()).to_numpy(),
            "BTC>SMA200": (btc > btc.rolling(200).mean()).to_numpy()}

    def evaluate(W, U, long_only):
        """W: Zielgewichte je Tag t (gelten für t+1). Rückgabe: tägliche Netto-(Über-)Rendite, Index t+1."""
        pnl = (W[:-1] * R[1:]).sum(1)
        turn = np.abs(np.diff(W, axis=0, prepend=np.zeros((1, N)))).sum(1)[:-1]
        net = pnl - COST * turn
        if long_only:
            cnt = U[:-1].sum(1)
            bench = np.where(cnt > 0, (U[:-1] * R[1:]).sum(1) / np.maximum(cnt, 1), 0.0)
            net = net - bench
        return pd.Series(net, index=dates[1:])

    results = []
    # A Querschnitt
    for L, skip, n in itertools.product((3, 7, 14, 30, 60, 90), (0, 1), (20, 50)):
        U = univ[n]
        Cs = np.roll(C, skip, axis=0)
        Cl = np.roll(C, skip + L, axis=0)
        S = Cs / Cl - 1
        S[: skip + L] = np.nan
        S = np.where(U & np.isfinite(S), S, np.nan)
        valid = np.isfinite(S).sum(1)
        order = np.argsort(np.where(np.isfinite(S), -S, np.inf), axis=1)       # absteigend, ungültig hinten
        for k, H, ls, mode, fn in itertools.product((3, 5, 10), (1, 7, 30), (False, True), ("Momentum", "Umkehr"),
                                                    filt):
            W = np.zeros((T, N))
            rows = np.arange(T)
            ok = valid >= 2 * k
            for j in range(k):
                top = order[:, j]
                bot = order[rows, np.maximum(valid - 1 - j, 0)]
                lw, sw = (top, bot) if mode == "Momentum" else (bot, top)
                W[rows[ok], lw[ok]] += 1.0 / k
                if ls:
                    W[rows[ok], sw[ok]] -= 1.0 / k
            if H > 1:
                W = W[(np.arange(T) // H) * H]
            W = W * filt[fn][:, None]
            name = (f"Querschnitt {mode} L{L}{' ohne letzten Tag' if skip else ''} Top{n} k{k} alle {H} Tage "
                    f"{'long-short' if ls else 'nur long'} Filter {fn}")
            results.append(dict(name=name, feats=dict(fam="A", mode=mode, L=L, k=k, H=H, ls=ls, filt=fn, n=n),
                                daily=evaluate(W, U, not ls)))
        print(f"A L{L} skip{skip} n{n} ({time.time() - t0:.0f} s)", flush=True)
    # B Zeitreihen-Trend
    cdf = c
    for rule, n, ls, fn in itertools.product(("SMA10", "SMA20", "SMA50", "SMA100", "SMA200", "DON20", "DON55"),
                                             (20, 50), (False, True), filt):
        U = univ[n]
        if rule.startswith("SMA"):
            m = int(rule[3:])
            sig = np.sign((cdf - cdf.rolling(m).mean()).to_numpy())
        else:
            m = int(rule[3:])
            hi, lo = cdf.rolling(m).max().shift(1), cdf.rolling(m // 2).min().shift(1)
            state = pd.DataFrame(np.where(cdf > hi, 1.0, np.where(cdf < lo, -1.0, np.nan)), index=dates,
                                 columns=cdf.columns).ffill()
            sig = state.to_numpy()
        sig = np.nan_to_num(sig)
        if not ls:
            sig = np.maximum(sig, 0)
        cnt = np.maximum(U.sum(1), 1)[:, None]
        W = np.where(U, sig, 0.0) / cnt * filt[fn][:, None]
        name = f"Trend {rule} Top{n} {'long-short' if ls else 'nur long'} Filter {fn}"
        results.append(dict(name=name, feats=dict(fam="B", mode=rule, L=0, k=0, H=1, ls=ls, filt=fn, n=n),
                            daily=evaluate(W, U, not ls)))
    pd.to_pickle(results, OUT)

    def per(s, nm):
        a, b = PERIODS[nm]
        return s[(s.index >= a) & (s.index <= b)].to_numpy()

    def desc(x):
        return f"Tage {len(x)}  Ø {x.mean() * 1e4:+.1f} bp/Tag ({x.mean() * 365:+.0%} p.a.)  t {tstat(x):+.2f}"

    rows = []
    for i, x in enumerate(results):
        a, b = per(x["daily"], "Training"), per(x["daily"], "Bestätigung")
        rows.append(dict(i=i, avg=a.mean(), t=tstat(a), conf=b.mean(), tc=tstat(b), **x["feats"]))
    tr = pd.DataFrame(rows)
    print(f"\nTraining 2018-2021: {len(tr)} | t >= 2: {(tr.t >= 2).sum()} | t >= 3: {(tr.t >= 3).sum()} | t >= 4: "
          f"{(tr.t >= 4).sum()} | Ø > 0: {(tr.avg > 0).sum()}")
    for col in ("fam", "mode", "L", "k", "H", "ls", "filt", "n"):
        g = tr.groupby(col)
        print(f"  {col}: " + ", ".join(f"{k} {a * 1e4:+.1f}->{b * 1e4:+.1f}" for k, a, b in
                                       zip(g.groups.keys(), g.avg.median(), g.conf.median())))

    def show(row, count):
        x = results[int(row.i)]
        print(f"\n=== {x['name']}")
        print(f"  Training:    {desc(per(x['daily'], 'Training'))}")
        b = per(x["daily"], "Bestätigung")
        ok = b.mean() > 0 and tstat(b) >= 2.4
        print(f"  Bestätigung: {desc(b)}  -> {'BESTANDEN' if ok else 'nicht bestanden'}")
        if count and ok:
            e = per(x["daily"], "Endtest")
            fin = e.mean() > 0 and tstat(e) >= 2
            print(f"  Endtest:     {desc(e)}  -> {'BESTANDEN' if fin else 'nicht bestanden'}")
        elif count:
            print("  Endtest: nicht angesehen")

    el = tr[(tr.avg > 0) & (tr.t >= 4)].sort_values("t", ascending=False).head(3)
    print(f"\n--- Zählende Auswahl (Ø > 0, t >= 4): {len(el)}")
    for _, row in el.iterrows():
        show(row, True)
    if el.empty:
        print("  keine -> RUNDE NICHT BESTANDEN")
    print("\n--- Nur Information: 3 beste Trainings-t ohne Hürde")
    for _, row in tr[tr.avg > 0].sort_values("t", ascending=False).head(3).iterrows():
        show(row, False)
    pos = tr[tr.avg > 0]
    print(f"\nFamilie: {len(pos)} im Training positiv; davon Bestätigung positiv {(pos.conf > 0).mean():.0%}")
    print(f"Laufzeit {time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()

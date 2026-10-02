"""Runde 127: TikTok @_tradinglab_ -- Tagesrichtung (A), Super Trend (B), Williams Fractals 1 Min (C),
Wahlzyklus (D, nur Beschreibung). Vorab-Registrierung: PROTOCOL.md, Abschnitt Runde 127."""
from __future__ import annotations

import itertools
import json
import sys
import time
import urllib.request
from pathlib import Path

import numba
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from r102 import load, resample  # noqa: E402

MARKETS = ("xauusd", "xagusd", "eurusd", "gbpusd", "usdjpy", "usdchf", "usdcnh", "audusd", "nzdusd", "usdsek",
           "gbpjpy", "eurjpy", "chfjpy", "usatechidxusd")
PERIODS = {"Training": ("2012-07-01", "2017-12-31"), "Bestätigung": ("2018-01-01", "2021-12-31"),
           "Endtest": ("2022-01-01", "2026-12-31")}
PERIODS_C = {"Training": ("2008-01-01", "2014-12-31"), "Bestätigung": ("2015-01-01", "2019-12-31"),
             "Endtest": ("2020-01-01", "2025-12-31")}
COMM = 0.5e-4
MIN_DIR = Path(r"C:\Users\Nutzer\Bot\data_cache\dukascopy")


def tstat(r):
    r = np.asarray(r, float)
    return float(r.mean() / r.std(ddof=1) * np.sqrt(len(r))) if len(r) > 2 and r.std() > 0 else float("nan")


def in_period(t, periods, name):
    a, b = periods[name]
    return (t >= np.datetime64(a)) & (t <= np.datetime64(b + "T23:59"))


# ------------------------------------------------------------ Indikatoren

def rma(x: np.ndarray, n: int) -> np.ndarray:
    return pd.Series(x).ewm(alpha=1 / n, adjust=False, min_periods=n).mean().to_numpy()


@numba.njit(cache=True)
def _supertrend(hl2, close, atr, mult):
    n = len(close)
    trend = np.zeros(n, np.int64)
    line = np.full(n, np.nan)
    up_p = dn_p = np.nan
    tr_p = 1
    for i in range(n):
        if np.isnan(atr[i]):
            continue
        up = hl2[i] - mult * atr[i]
        dn = hl2[i] + mult * atr[i]
        if not np.isnan(up_p) and close[i - 1] > up_p:
            up = max(up, up_p)
        if not np.isnan(dn_p) and close[i - 1] < dn_p:
            dn = min(dn, dn_p)
        t = tr_p
        if np.isnan(up_p):
            t = 1
        elif tr_p == -1 and close[i] > dn_p:
            t = 1
        elif tr_p == 1 and close[i] < up_p:
            t = -1
        trend[i] = t
        line[i] = up if t == 1 else dn
        up_p, dn_p, tr_p = up, dn, t
    return trend, line


def supertrend(bars: pd.DataFrame, n: int, mult: float):
    h, l, c = (bars[k].to_numpy() for k in ("high", "low", "close"))
    pc = np.r_[np.nan, c[:-1]]
    tr = np.nanmax(np.vstack([h - l, np.abs(h - pc), np.abs(l - pc)]), axis=0)
    return _supertrend((h + l) / 2, c, rma(tr, n), mult)


def ichimoku_cloud(bars: pd.DataFrame):
    h, l = bars["high"], bars["low"]
    tenkan = (h.rolling(9).max() + l.rolling(9).min()) / 2
    kijun = (h.rolling(26).max() + l.rolling(26).min()) / 2
    a = ((tenkan + kijun) / 2).shift(26)
    b = ((h.rolling(52).max() + l.rolling(52).min()) / 2).shift(26)
    return np.fmax(a, b).to_numpy(), np.fmin(a, b).to_numpy()


# ------------------------------------------------------------ Simulation (Kerzen der Zeitebene, Bid/Ask)

@numba.njit(cache=True)
def sim(sig, stop, ex_long, ex_short, use_target, tp_mult, bo, bh, bl, bc, ao, ah, al, ac, longonly):
    """sig[i] = +1/-1 am Schluss von Kerze i -> Einstieg Eröffnung i+1. Rückgabe (Einstiegsindex, R netto)."""
    n = len(sig)
    out_i = np.empty(n, np.int64)
    out_r = np.empty(n, np.float64)
    k, i = 0, 0
    while i < n - 1:
        s = sig[i]
        if s == 0 or (longonly and s < 0) or np.isnan(stop[i]):
            i += 1
            continue
        p = i + 1
        entry = ao[p] if s > 0 else bo[p]
        sd = (entry - stop[i]) * s
        if not sd > 0:
            i += 1
            continue
        sl, tp = stop[i], entry + s * tp_mult * sd
        r, j_end = np.nan, n - 1
        for j in range(p, n):
            if s > 0:
                o, h, l_, c = bo[j], bh[j], bl[j], bc[j]
                if j > p and (o <= sl or (use_target and o >= tp)):
                    r, j_end = (o - entry) / sd, j
                    break
                if l_ <= sl:
                    r, j_end = (sl - entry) / sd, j
                    break
                if use_target and h >= tp:
                    r, j_end = (tp - entry) / sd, j
                    break
                if not use_target and ex_long[j] and j + 1 < n:
                    r, j_end = (bo[j + 1] - entry) / sd, j + 1
                    break
                if j == n - 1:
                    r = (c - entry) / sd
            else:
                o, h, l_, c = ao[j], ah[j], al[j], ac[j]
                if j > p and (o >= sl or (use_target and o <= tp)):
                    r, j_end = (entry - o) / sd, j
                    break
                if h >= sl:
                    r, j_end = (entry - sl) / sd, j
                    break
                if use_target and l_ <= tp:
                    r, j_end = (entry - tp) / sd, j
                    break
                if not use_target and ex_short[j] and j + 1 < n:
                    r, j_end = (entry - ao[j + 1]) / sd, j + 1
                    break
                if j == n - 1:
                    r = (entry - c) / sd
        out_i[k] = p
        out_r[k] = r - COMM * entry / sd
        k += 1
        i = j_end           # Signale während der offenen Position verfallen
    return out_i[:k], out_r[:k]


def b_signals(bars: pd.DataFrame, rule: str):
    c = bars["close"].to_numpy()
    if rule == "B1":
        sts = [supertrend(bars, n, m) for n, m in ((12, 3.0), (10, 1.0), (11, 2.0))]
        tr = np.vstack([s[0] for s in sts])
        bull, bear = (tr == 1).all(axis=0), (tr == -1).all(axis=0)
        stop = sts[0][1]
        ex_long, ex_short = ~bull, ~bear           # eine Linie wechselt
    else:
        trend, stop = supertrend(bars, 10, 3.0)
        if rule == "B2":
            e = bars["close"].ewm(span=200, adjust=False, min_periods=200).mean().to_numpy()
            bull, bear = (trend == 1) & (c > e), (trend == -1) & (c < e)
            ex_long, ex_short = trend == -1, trend == 1
        else:
            top, bot = ichimoku_cloud(bars)
            bull, bear = (trend == 1) & (c > top), (trend == -1) & (c < bot)
            inside = (c <= top) & (c >= bot)
            ex_long, ex_short = inside | (trend == -1), inside | (trend == 1)
    prev_bull, prev_bear = np.r_[False, bull[:-1]], np.r_[False, bear[:-1]]
    sig = np.where(bull & ~prev_bull, 1, np.where(bear & ~prev_bear, -1, 0)).astype(np.int64)
    return sig, stop.astype(float), ex_long.astype(np.bool_), ex_short.astype(np.bool_)


# ------------------------------------------------------------ A: Tagesrichtung

def a_trades(bid_d: pd.DataFrame, ask_d: pd.DataFrame) -> pd.DataFrame:
    h, l, c = bid_d["high"], bid_d["low"], bid_d["close"]
    ph, pl = h.shift(1), l.shift(1)
    bear = (h > ph) & (c < ph) & (l >= pl)
    bear_s = (h > ph) & (c < pl)
    bull = (l < pl) & (c > pl) & (h <= ph)
    bull_s = (l < pl) & (c > ph)
    kind = pd.Series("", index=bid_d.index)
    kind[bear | bull] = "einfach"
    kind[bear_s | bull_s] = "stark"
    side = pd.Series(0, index=bid_d.index)
    side[bull | bull_s] = 1
    side[bear | bear_s] = -1
    nxt_bo, nxt_ao = bid_d["open"].shift(-1), ask_d["open"].shift(-1)
    nxt_bc, nxt_ac = bid_d["close"].shift(-1), ask_d["close"].shift(-1)
    ret = np.where(side > 0, nxt_bc / nxt_ao - 1, (nxt_bo - nxt_ac) / nxt_bo) * 1e4 - COMM * 1e4
    day = pd.Series(bid_d.index, index=bid_d.index).shift(-1)
    df = pd.DataFrame({"day": day, "side": side, "kind": kind, "bp": ret})
    return df[(df.side != 0) & df.bp.notna()]


# ------------------------------------------------------------ C: Williams Fractals 1 Min

@numba.njit(cache=True)
def fractal_sim(bo, bh, bl, bc, ao, ah, al, ac, s20, s50, s100, longonly, tp_mult, max_hold):
    """Technische Ergänzung: Position nach max_hold Minuten zum Schluss beendet (sonst unbegrenzt)."""
    n = len(bc)
    out_i = np.empty(n // 50 + 10, np.int64)
    out_r = np.empty(n // 50 + 10, np.float64)
    k = 0
    st = 0                          # 1 = Ordnung long, -1 = short, 0 keine
    pulled = beyond50 = beyond100 = False
    i = 0
    while i < n - 1:
        if np.isnan(s100[i]):
            i += 1
            continue
        o_now = 1 if (s20[i] > s50[i] > s100[i]) else (-1 if (s20[i] < s50[i] < s100[i]) else 0)
        if o_now != st:
            st, pulled, beyond50, beyond100 = o_now, False, False, False
        if st == 0 or (longonly and st < 0):
            i += 1
            continue
        c = bc[i]
        if st > 0:
            pulled |= c < s20[i]
            beyond50 |= c < s50[i]
            beyond100 |= c < s100[i]
        else:
            pulled |= c > s20[i]
            beyond50 |= c > s50[i]
            beyond100 |= c > s100[i]
        j = i - 2                   # Fractal an j, bestätigt mit Schluss von i = j + 2
        frac = False
        if j >= 2:
            if st > 0:
                frac = bl[j] < bl[j - 1] and bl[j] < bl[j - 2] and bl[j] < bl[j + 1] and bl[j] < bl[j + 2]
            else:
                frac = bh[j] > bh[j - 1] and bh[j] > bh[j - 2] and bh[j] > bh[j + 1] and bh[j] > bh[j + 2]
        if not (frac and pulled and not beyond100):
            i += 1
            continue
        stop = s100[i] if beyond50 else s50[i]
        p = i + 1
        entry = ao[p] if st > 0 else bo[p]
        sd = (entry - stop) * st
        pulled, beyond50 = False, False          # nächster Einstieg braucht einen neuen Rücksetzer
        if not sd > 0:
            i += 1
            continue
        tp = entry + st * tp_mult * sd
        r, j_end = np.nan, min(n - 1, p + max_hold)
        for q in range(p, min(n, p + max_hold + 1)):
            if st > 0:
                o, h, l_, cc = bo[q], bh[q], bl[q], bc[q]
                if q > p and (o <= stop or o >= tp):
                    r, j_end = (o - entry) / sd, q
                    break
                if l_ <= stop:
                    r, j_end = (stop - entry) / sd, q
                    break
                if h >= tp:
                    r, j_end = (tp - entry) / sd, q
                    break
                r = (cc - entry) / sd
            else:
                o, h, l_, cc = ao[q], ah[q], al[q], ac[q]
                if q > p and (o >= stop or o <= tp):
                    r, j_end = (entry - o) / sd, q
                    break
                if h >= stop:
                    r, j_end = (entry - stop) / sd, q
                    break
                if l_ <= tp:
                    r, j_end = (entry - tp) / sd, q
                    break
                r = (entry - cc) / sd
        if k < len(out_i):
            out_i[k] = p
            out_r[k] = r - COMM * entry / sd
            k += 1
        i = j_end + 1
    return out_i[:k], out_r[:k]


def load_minutes(sym: str):
    folder, prefix = ("xau", "xau") if sym == "xauusd" else ("fx", sym)
    """Speichersparend: Jahr für Jahr, float32, Wochenende sofort verworfen."""
    dt = {"timestamp": "int64", "open": "float32", "high": "float32", "low": "float32", "close": "float32"}
    years = sorted({p.stem.split("_")[1] for p in (MIN_DIR / folder).glob(f"{prefix}_20*.csv")}
                   & {p.stem.split("_")[1] for p in (MIN_DIR / (folder + "_ask")).glob(f"{prefix}_20*.csv")})
    ts, bids, asks = [], [], []
    for y in years:
        b = pd.read_csv(MIN_DIR / folder / f"{prefix}_{y}.csv", dtype=dt).drop_duplicates("timestamp")
        a = pd.read_csv(MIN_DIR / (folder + "_ask") / f"{prefix}_{y}.csv", dtype=dt).drop_duplicates("timestamp")
        m = b.merge(a, on="timestamp", suffixes=("", "_a")).sort_values("timestamp")
        del a, b
        t = pd.to_datetime(m["timestamp"].to_numpy(), unit="ms", utc=True)
        wd, hr = t.weekday, t.hour
        keep = ~((wd == 5) | ((wd == 6) & (hr < 21)) | ((wd == 4) & (hr >= 21)))
        keep &= m["close_a"].to_numpy() >= m["close"].to_numpy()
        m = m[keep]
        ts.append(m["timestamp"].to_numpy())
        bids.append(m[["open", "high", "low", "close"]].to_numpy())
        asks.append(m[["open_a", "high_a", "low_a", "close_a"]].to_numpy())
        del m
    t = pd.to_datetime(np.concatenate(ts), unit="ms", utc=True)
    cols = ["open", "high", "low", "close"]
    return t, pd.DataFrame(np.concatenate(bids), columns=cols), pd.DataFrame(np.concatenate(asks), columns=cols)


# ------------------------------------------------------------ D: Wahlzyklus

def election_day(y: int) -> pd.Timestamp:
    d = pd.Timestamp(year=y, month=11, day=2)
    while d.weekday() != 1:
        d += pd.Timedelta(days=1)
    return d


def part_d():
    url = ("https://query1.finance.yahoo.com/v8/finance/chart/%5EGSPC?period1=-1325635200&period2=1790000000"
           "&interval=1d")
    raw = json.load(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}),
                                           timeout=60))["chart"]["result"][0]
    s = pd.Series(raw["indicators"]["quote"][0]["close"],
                  index=pd.to_datetime(raw["timestamp"], unit="s").normalize()).dropna()
    s = s[~s.index.duplicated()]
    print("\n=== D Wahlzyklus (S&P 500 Kursindex, ohne Dividenden; nur Beschreibung) ===")
    rows = []
    for y in range(1932, 2025, 4):
        a = s[s.index >= pd.Timestamp(y - 2, 1, 1)]
        b = s[s.index <= election_day(y)]
        nxt = s[(s.index > election_day(y)) & (s.index < pd.Timestamp(y + 2, 1, 1))]
        if a.empty or b.empty or nxt.empty:
            continue
        rows.append((y, b.iloc[-1] / a.iloc[0] - 1, nxt.iloc[-1] / b.iloc[-1] - 1))
    df = pd.DataFrame(rows, columns=["Wahl", "Zwischenwahljahr->Wahl", "Wahl->Ende Folgejahr"])
    print(df.to_string(index=False, float_format=lambda v: f"{v:+.1%}"))
    ann_in = (1 + df.iloc[:, 1]) ** (1 / 2.85) - 1          # ~2 Jahre 10 Monate
    ann_out = (1 + df.iloc[:, 2]) ** (1 / 1.15) - 1         # ~1 Jahr 2 Monate
    print(f"Zyklen {len(df)}: im Fenster positiv {int((df.iloc[:, 1] > 0).sum())}/{len(df)}, Ø p.a. "
          f"{ann_in.mean():+.1%} (t {tstat(ann_in):.2f}); außerhalb Ø p.a. {ann_out.mean():+.1%} "
          f"(t {tstat(ann_out):.2f}); Differenz je Zyklus t {tstat(ann_in - ann_out):.2f}")
    for name, lo, hi in (("1932-1976", 1932, 1976), ("1980-2024", 1980, 2024)):
        m = (df.Wahl >= lo) & (df.Wahl <= hi)
        print(f"  {name}: Fenster Ø p.a. {ann_in[m].mean():+.1%}, außerhalb {ann_out[m].mean():+.1%}, "
              f"Fenster positiv {int((df.iloc[:, 1][m] > 0).sum())}/{int(m.sum())}")


# ------------------------------------------------------------ Hauptprogramm

def main():
    t0 = time.time()
    results = {}                               # key -> (Zeiten, Werte, Einheit, Perioden)
    a_all = []
    b_acc = {k: ([], []) for k in itertools.product(("B1", "B2", "B3"), ("H1", "H4", "D1"), ("beide", "nur long"),
                                                     ("Ziel 1,5R", "Signal"))}
    for mi, sym in enumerate(MARKETS):
        bid, ask = load(sym)
        dbid, dask = resample(bid, "1D"), resample(ask, "1D")
        common = dbid.index.intersection(dask.index)
        a = a_trades(dbid.loc[common], dask.loc[common])
        a["sym"] = sym
        a_all.append(a)
        for tf in ("H1", "H4", "D1"):
            if tf == "H1":
                tb, ta = bid, ask
            else:
                rule = {"H4": "4h", "D1": "1D"}[tf]
                tb, ta = resample(bid, rule), resample(ask, rule)
                ci = tb.index.intersection(ta.index)
                tb, ta = tb.loc[ci], ta.loc[ci]
            arrs = [tb[c].to_numpy() for c in ("open", "high", "low", "close")] + \
                   [ta[c].to_numpy() for c in ("open", "high", "low", "close")]
            for rule in ("B1", "B2", "B3"):
                sig, stop, exl, exs = b_signals(tb, rule)
                for d, ex in itertools.product(("beide", "nur long"), ("Ziel 1,5R", "Signal")):
                    ei, r = sim(sig, stop, exl, exs, ex == "Ziel 1,5R", 1.5, *arrs, d == "nur long")
                    b_acc[(rule, tf, d, ex)][0].append(tb.index[ei].tz_convert(None).to_numpy())
                    b_acc[(rule, tf, d, ex)][1].append(r)
        print(f"{sym} fertig ({mi + 1}/{len(MARKETS)}, {time.time() - t0:.0f} s)", flush=True)

    a_df = pd.concat(a_all)
    a_df["day"] = pd.to_datetime(a_df["day"]).dt.tz_convert(None).dt.normalize()
    for kind, d in itertools.product(("alle", "einfach", "stark"), ("beide", "nur long")):
        x = a_df if kind == "alle" else a_df[a_df.kind == kind]
        if d == "nur long":
            x = x[x.side > 0]
        per_day = x.groupby("day").bp.mean()
        results[("A", kind, d)] = (per_day.index.to_numpy(), per_day.to_numpy(), "bp/Tag", PERIODS)
    for key, (ts, rs) in b_acc.items():
        t = np.concatenate(ts)
        r = np.concatenate(rs)
        o = np.argsort(t)
        results[key] = (t[o], r[o], "R", PERIODS)

    for sym in ("eurusd", "gbpusd", "xauusd"):
        t, bid, ask = load_minutes(sym)
        c = bid["close"]
        s20, s50, s100 = (c.rolling(n).mean().to_numpy() for n in (20, 50, 100))
        arrs = [bid[k].to_numpy() for k in ("open", "high", "low", "close")] + \
               [ask[k].to_numpy() for k in ("open", "high", "low", "close")]
        for d in ("beide", "nur long"):
            ei, r = fractal_sim(*arrs, s20, s50, s100, d == "nur long", 1.5, 1440)
            key = ("C", d)
            tt = t[ei].tz_convert(None).to_numpy()
            if key in results:
                tt, r = np.concatenate([results[key][0], tt]), np.concatenate([results[key][1], r])
            o = np.argsort(tt)
            results[key] = (tt[o], r[o], "R", PERIODS_C)
        del t, bid, ask, arrs, c, s20, s50, s100
        import gc
        gc.collect()
        print(f"Minuten {sym} fertig ({time.time() - t0:.0f} s)", flush=True)

    pd.to_pickle(results, Path(__file__).with_name("r127_results.pkl"))

    def part(key, name):
        t, v, _, per = results[key]
        return v[in_period(t, per, name)]

    def desc(key, name):
        v, unit = part(key, name), results[key][2]
        if len(v) < 3:
            return f"n {len(v)}"
        return f"n {len(v):6d}  Ø {v.mean():+.3f} {unit}  t {tstat(v):+.2f}  positiv {(v > 0).mean():.0%}"

    rows = [(key, len(part(key, "Training")), np.mean(part(key, "Training")) if len(part(key, "Training")) else
             np.nan, tstat(part(key, "Training"))) for key in results]
    tr = pd.DataFrame(rows, columns=["key", "n", "avg", "t"])
    print(f"\nTraining: {len(tr)} Tests | Ø > 0: {(tr.avg > 0).sum()} | t >= 2: {(tr.t >= 2).sum()} | "
          f"t >= 3: {(tr.t >= 3).sum()}")
    for _, row in tr.sort_values("t", ascending=False).iterrows():
        print(f"  {' '.join(map(str, row.key)):34s} {desc(row.key, 'Training')}")
    elig = tr[(tr.n >= 200) & (tr.avg > 0) & (tr.t >= 3)].sort_values("t", ascending=False).head(3)
    print(f"\n--- Zählende Auswahl (n >= 200, Ø > 0, t >= 3): {len(elig)}")
    for _, row in elig.iterrows():
        b = part(row.key, "Bestätigung")
        ok = len(b) > 2 and b.mean() > 0 and tstat(b) >= 2.4
        print(f"=== {row.key}\n  Bestätigung: {desc(row.key, 'Bestätigung')} -> {'BESTANDEN' if ok else 'nicht bestanden'}")
        if ok:
            e = part(row.key, "Endtest")
            fin = len(e) > 2 and e.mean() > 0 and tstat(e) >= 2
            print(f"  Endtest: {desc(row.key, 'Endtest')} -> {'BESTANDEN' if fin else 'nicht bestanden'}")
    if elig.empty:
        print("  keine -> RUNDE NICHT BESTANDEN")
    print("\n--- Nur Information: Bestätigung der 3 besten Trainings-t (Endtest nicht angesehen)")
    for _, row in tr[(tr.n >= 200) & (tr.avg > 0)].sort_values("t", ascending=False).head(3).iterrows():
        print(f"  {row.key}: {desc(row.key, 'Bestätigung')}")
    try:
        part_d()
    except Exception as e:  # noqa: BLE001 -- Beschreibung, darf die Runde nicht abbrechen
        print(f"D nicht verfügbar: {e}")
    print(f"\nLaufzeit {time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()

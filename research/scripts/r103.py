"""Runde 103: Gold-Kurzfrist-Familie (M15/M30, ATR, Nachzieh-Stop) -- Vorab-Registrierung r103_prereg.md."""
from __future__ import annotations

import itertools
import time
from pathlib import Path

import numba
import numpy as np
import pandas as pd

D = Path(r"C:\Users\Nutzer\Bot\data_cache\dukascopy")
OUT = Path(__file__).with_name("r103_results.pkl")
PERIODS = {"Training 2008-2016": ("2008-01-01", "2016-12-31"),
           "Bestätigung 2017-2021": ("2017-01-01", "2021-12-31"),
           "Endtest 2022-2026": ("2022-01-01", "2026-12-31")}


def read_minutes(paths) -> pd.DataFrame:
    df = pd.concat([pd.read_csv(p) for p in paths])
    df = df.drop_duplicates("timestamp").sort_values("timestamp")
    df.index = pd.to_datetime(df.pop("timestamp"), unit="ms", utc=True)
    return df.astype("float64")


def load() -> tuple[pd.DataFrame, pd.DataFrame]:
    bid = read_minutes(sorted((D / "xau").glob("xau_*.csv")) + sorted((D / "unseen_xau").glob("xau_*.csv")))
    ask = read_minutes(sorted((D / "xau_ask").glob("xau_*.csv")))
    ask = ask.reindex(bid.index)
    med = float((ask["close"] - bid["close"]).where(lambda s: s > 0).median())
    for c in ask:
        ask[c] = ask[c].fillna(bid[c] + med)
    return bid, ask


def ohlc(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    out = df.resample(rule).agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    return out[out["high"] > out["low"]]          # keine Flachkerzen (Wochenende/Feiertag)


# ------------------------------------------------------------ Indikatoren

def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False, min_periods=n).mean()


def atr(df: pd.DataFrame, n: int) -> pd.Series:
    pc = df["close"].shift(1)
    tr = pd.concat([df["high"] - df["low"], (df["high"] - pc).abs(), (df["low"] - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def rsi(s: pd.Series, n: int = 14) -> pd.Series:
    d = s.diff()
    g = d.clip(lower=0).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    l_ = (-d).clip(lower=0).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    return 100 - 100 / (1 + g / l_.replace(0, np.nan))


def entries(bars: pd.DataFrame, kind: str, atr_s: pd.Series) -> pd.Series:
    """+1 long, -1 short, 0 kein Signal -- auf geschlossener Kerze."""
    c = bars["close"]
    if kind == "E1":
        hi = bars["high"].shift(1).rolling(20).max()
        lo = bars["low"].shift(1).rolling(20).min()
        long, short = c > hi, c < lo
    elif kind == "E2":
        e = ema(c, 50)
        r = rsi(c, 14)
        long = (c > e) & (e > e.shift(5)) & (r.shift(1) <= 40) & (r > 40)
        short = (c < e) & (e < e.shift(5)) & (r.shift(1) >= 60) & (r < 60)
    else:  # E3 Keltner-Ausbruch (Kreuzung)
        e = ema(c, 20)
        up, dn = e + 2 * atr_s, e - 2 * atr_s
        long = (c > up) & (c.shift(1) <= up.shift(1))
        short = (c < dn) & (c.shift(1) >= dn.shift(1))
    return pd.Series(np.where(long, 1, np.where(short, -1, 0)), index=bars.index)


# ------------------------------------------------------------ Ausführung (numba)

@numba.njit(cache=True)
def run(sig_pos, sig_side, sig_sd, bo, bh, bl, bc, ao, ah, al, ac, atr_m5, tf_close, mode, mult):
    n_sig = len(sig_pos)
    n = len(bo)
    out_entry = np.empty(n_sig, np.int64)
    out_exit = np.empty(n_sig, np.int64)
    out_r = np.empty(n_sig, np.float64)
    k = 0
    busy_until = -1
    for s in range(n_sig):
        p = sig_pos[s]
        if p <= busy_until or p >= n:
            continue
        side = sig_side[s]
        sd = sig_sd[s]
        if not (sd > 0):
            continue
        entry = ao[p] if side > 0 else bo[p]
        sl = entry - side * sd
        tp = entry + side * 2.0 * sd
        use_tp = mode != 1
        be_done = False
        ext = entry          # bestes Extrem seit Einstieg (long: Hoch auf Bid, short: Tief auf Ask)
        exit_pos = -1
        r = 0.0
        last = min(n - 1, p + 5 * 24 * 12)
        for i in range(p, last + 1):
            if side > 0:
                o, h, l_, c = bo[i], bh[i], bl[i], bc[i]
                if i > p and o <= sl:
                    exit_pos, r = i, (o - entry) / sd
                    break
                if i > p and use_tp and o >= tp:
                    exit_pos, r = i, (o - entry) / sd
                    break
                if l_ <= sl:
                    exit_pos, r = i, (sl - entry) / sd
                    break
                if use_tp and h >= tp:
                    exit_pos, r = i, (tp - entry) / sd
                    break
                if h > ext:
                    ext = h
                if mode == 2 and not be_done and h >= entry + sd:
                    sl = max(sl, entry)
                    be_done = True
                if mode == 1 and tf_close[i]:
                    cand = ext - mult * atr_m5[i]
                    if cand > sl:
                        sl = cand
                if i == last:
                    exit_pos, r = i, (c - entry) / sd
            else:
                o, h, l_, c = ao[i], ah[i], al[i], ac[i]
                if i > p and o >= sl:
                    exit_pos, r = i, (entry - o) / sd
                    break
                if i > p and use_tp and o <= tp:
                    exit_pos, r = i, (entry - o) / sd
                    break
                if h >= sl:
                    exit_pos, r = i, (entry - sl) / sd
                    break
                if use_tp and l_ <= tp:
                    exit_pos, r = i, (entry - tp) / sd
                    break
                if l_ < ext:
                    ext = l_
                if mode == 2 and not be_done and l_ <= entry - sd:
                    sl = min(sl, entry)
                    be_done = True
                if mode == 1 and tf_close[i]:
                    cand = ext + mult * atr_m5[i]
                    if cand < sl:
                        sl = cand
                if i == last:
                    exit_pos, r = i, (entry - c) / sd
        if exit_pos < 0:
            continue
        out_entry[k] = p
        out_exit[k] = exit_pos
        out_r[k] = r - 0.5e-4 * entry / sd
        k += 1
        busy_until = exit_pos
    return out_entry[:k], out_exit[:k], out_r[:k]


# ------------------------------------------------------------ Auswertung

def tstat(r: np.ndarray) -> float:
    return float(r.mean() / r.std(ddof=1) * np.sqrt(len(r))) if len(r) > 2 and r.std() > 0 else float("nan")


def describe(r: np.ndarray) -> str:
    if len(r) < 3:
        return f"n {len(r)}"
    w, l_ = r[r > 0].sum(), -r[r < 0].sum()
    return (f"n {len(r):5d}  Ø R {r.mean():+.3f}  t {tstat(r):+.2f}  Treffer {(r > 0).mean():.0%}  "
            f"PF {w / l_ if l_ > 0 else float('inf'):.2f}  Summe {r.sum():+.0f} R")


def main() -> None:
    t0 = time.time()
    bid_m1, ask_m1 = load()
    print(f"Minuten geladen: {len(bid_m1):,} ({time.time() - t0:.0f} s)", flush=True)
    bid = ohlc(bid_m1, "5min")
    ask = ohlc(ask_m1, "5min").reindex(bid.index)
    ask = ask.fillna(bid + float((ask["close"] - bid["close"]).median()))
    del bid_m1, ask_m1
    m5_idx = bid.index
    arrs = [bid[c].to_numpy() for c in ("open", "high", "low", "close")] + \
           [ask[c].to_numpy() for c in ("open", "high", "low", "close")]
    results = []
    for tf_name, rule, step in (("M15", "15min", pd.Timedelta(minutes=15)), ("M30", "30min", pd.Timedelta(minutes=30))):
        bars = ohlc(bid, rule)
        # letzte M5-Kerze jeder TF-Kerze: ab hier ist die TF-Kerze geschlossen
        end_pos = m5_idx.searchsorted(bars.index + step) - 1
        tf_close = np.zeros(len(m5_idx), dtype=np.bool_)
        tf_close[end_pos[(end_pos >= 0) & (end_pos < len(m5_idx))]] = True
        for atr_len in (7, 14, 21):
            a = atr(bars, atr_len)
            # ATR der zuletzt geschlossenen TF-Kerze auf jeder M5-Kerze
            a_closed = a.copy()
            a_closed.index = a_closed.index + step
            atr_m5 = a_closed[~a_closed.index.duplicated()].reindex(m5_idx, method="ffill").to_numpy()
            atr_m5 = np.nan_to_num(atr_m5, nan=0.0)
            for kind in ("E1", "E2", "E3"):
                sig = entries(bars, kind, a)
                sig = sig[(sig != 0) & a.notna()]
                pos = m5_idx.searchsorted(sig.index + step)      # erste M5-Kerze nach Kerzenschluss
                for stop_mult, (mode, mode_name) in itertools.product((1.5, 2.0, 3.0),
                                                                     ((0, "Ziel 2R"), (1, "Nachzieh-Stop"),
                                                                      (2, "Einstand+2R"))):
                    sd = (a.reindex(sig.index) * stop_mult).to_numpy()
                    e_pos, x_pos, r = run(pos.astype(np.int64), sig.to_numpy().astype(np.int64), sd, *arrs,
                                          atr_m5, tf_close, mode, stop_mult)
                    results.append({"tf": tf_name, "entry": kind, "atr": atr_len, "stop": stop_mult,
                                    "exit": mode_name, "t_entry": m5_idx[e_pos], "r": r})
        print(f"{tf_name} fertig ({time.time() - t0:.0f} s)", flush=True)
    pd.to_pickle(results, OUT)

    def period(res, name):
        a, b = PERIODS[name]
        m = (res["t_entry"] >= pd.Timestamp(a, tz="UTC")) & (res["t_entry"] <= pd.Timestamp(b + " 23:59", tz="UTC"))
        return res["r"][m]

    train = []
    for i, res in enumerate(results):
        r = period(res, "Training 2008-2016")
        train.append((i, len(r), r.mean() if len(r) else np.nan, tstat(r)))
    tr = pd.DataFrame(train, columns=["i", "n", "avg", "t"])
    print(f"\nTraining: {len(tr)} Varianten; t >= 2: {(tr.t >= 2).sum()}, t >= 3: {(tr.t >= 3).sum()}, "
          f"Ø R > 0: {(tr.avg > 0).sum()}; Median Ø R {tr.avg.median():+.3f}")
    fam = tr.assign(entry=[results[i]["entry"] for i in tr.i], exit=[results[i]["exit"] for i in tr.i])
    print("Median Ø R je Einstieg:", fam.groupby("entry").avg.median().round(3).to_dict(),
          "| je Ausstieg:", fam.groupby("exit").avg.median().round(3).to_dict())
    pick = tr[(tr.n >= 200) & (tr.avg > 0)].sort_values("t", ascending=False).head(3)
    if pick.empty:
        print("Keine Variante mit >= 200 Trades und Ø R > 0 im Training -> Runde NICHT BESTANDEN.")
        return
    for _, row in pick.iterrows():
        res = results[int(row.i)]
        label = f"{res['tf']} {res['entry']} ATR{res['atr']} Stop {res['stop']}x {res['exit']}"
        print(f"\n=== Ausgewählt: {label}")
        ok = True
        for name in PERIODS:
            if name.startswith("Endtest") and not ok:
                print("  Endtest: nicht angesehen (Bestätigung nicht bestanden)")
                continue
            r = period(res, name)
            print(f"  {name}: {describe(r)}")
            if name.startswith("Bestätigung"):
                ok = len(r) > 2 and r.mean() > 0 and tstat(r) >= 2.4
                print(f"    Bestätigung {'BESTANDEN' if ok else 'NICHT bestanden'}")
            if name.startswith("Endtest") and ok:
                fin = len(r) > 2 and r.mean() > 0 and tstat(r) >= 2
                print(f"    Endtest {'BESTANDEN' if fin else 'NICHT bestanden'}")
    print(f"\nLaufzeit {time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()

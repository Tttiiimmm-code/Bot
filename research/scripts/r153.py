"""Runde 153: Nachbau fremder EA "Maren asia_bruch_kontinuation_XAUUSD_15min_be_trail" -- Vorab: PROTOCOL.md Runde 153.

Aufruf aus dem Haupt-Repo (Daten relativ): PYTHONPATH=<worktree> python <worktree>/research/scripts/r153.py
Die Lade- und Bewertungsfunktionen nutzt auch Runde 154.
"""
from __future__ import annotations

import time
from datetime import date
from pathlib import Path

import numba
import numpy as np
import pandas as pd

from tradingbot.research import history

D = Path("data_cache/dukascopy")
SPY_CACHE = Path("data_cache/yahoo_r150")
COMM = 0.5e-4                     # Kommission je Runde auf den Nominalwert
MAIN = ("2016-01-01", "2025-09-30")
CLASS = ("2008-01-01", "2015-12-31")
AUTHOR = ("2023-09-01", "2026-09-30")
T_PASS = 2.0


# ------------------------------------------------------------------ Daten

def read_years(folder: str, name: str) -> pd.DataFrame:
    parts = []
    for f in sorted((D / folder).glob(f"{name}_*.csv")):
        if f.stat().st_size == 0:
            continue
        df = pd.read_csv(f, dtype={"timestamp": np.int64, "open": np.float32, "high": np.float32,
                                   "low": np.float32, "close": np.float32})
        parts.append(df)
    df = pd.concat(parts, ignore_index=True).drop_duplicates("timestamp").sort_values("timestamp")
    return df.set_index("timestamp")


def load_market(bid_dir: str, ask_dir: str, name: str) -> dict:
    """M1 Geld/Brief; fehlende Seite über den mittleren Spread, flache Kerzen (O=H=L=C, Geld) entfernt."""
    bid, ask = read_years(bid_dir, name), read_years(ask_dir, name)
    idx = bid.index.union(ask.index)
    bid, ask = bid.reindex(idx), ask.reindex(idx)
    spread = (ask["close"] - bid["close"]).where(lambda s: s > 0)
    med = float(spread.median())
    for c in ("open", "high", "low", "close"):
        bid[c] = bid[c].fillna(ask[c] - med)
        ask[c] = ask[c].fillna(bid[c] + med)
    flat = (bid["high"] == bid["low"]) & (bid["open"] == bid["close"]) & (bid["open"] == bid["high"])
    keep = ~flat & bid.notna().all(axis=1) & ask.notna().all(axis=1)
    bid, ask = bid[keep], ask[keep]
    out = {"minute": (bid.index.to_numpy() // 60000).astype(np.int64), "spread_med": med,
           "bid_only_from": None}
    for side, df in (("b", bid), ("a", ask)):
        for c in ("open", "high", "low", "close"):
            out[side + c[0]] = df[c].to_numpy(np.float64)
    return out


def coverage(m: dict) -> str:
    years = pd.to_datetime(m["minute"] * 60, unit="s").year
    s = pd.Series(1, index=years).groupby(level=0).sum()
    return " ".join(f"{y}:{n // 1000}k" for y, n in s.items())


def server_day(minute: np.ndarray) -> np.ndarray:
    """Server-Tag 17:00-17:00 New York (MT5-Serverzeit UTC+2/+3) als Tageszahl."""
    ny = pd.to_datetime(minute * 60, unit="s", utc=True).tz_convert("America/New_York")
    shifted = (ny + pd.Timedelta(hours=7)).tz_localize(None).normalize()
    return ((shifted - pd.Timestamp("2000-01-01")).days).to_numpy().astype(np.int64)


def resample(m: dict, width: int) -> dict:
    """Kerzen aus M1-Geld; Index der ersten/letzten Minute je Kerze."""
    key = m["minute"] // width
    starts = np.concatenate([[0], np.flatnonzero(np.diff(key)) + 1])
    ends = np.concatenate([starts[1:], [len(key)]]) - 1
    return {"start": key[starts] * width, "i0": starts, "i1": ends,
            "o": m["bo"][starts], "h": np.maximum.reduceat(m["bh"], starts),
            "l": np.minimum.reduceat(m["bl"], starts), "c": m["bc"][ends]}


@numba.njit(cache=True)
def atr_ea(h, l, c):
    """AtrAt(r, 14, shift) des EA: Wilder über 42 Kerzen Anlauf, endend bei der jeweiligen Kerze."""
    n = len(c)
    tr = np.empty(n)
    tr[0] = h[0] - l[0]
    for k in range(1, n):
        tr[k] = max(h[k] - l[k], max(abs(h[k] - c[k - 1]), abs(l[k] - c[k - 1])))
    out = np.full(n, np.nan)
    for k in range(43, n):
        a = 0.0
        for j in range(k - 42, k + 1):
            a = tr[j] if a == 0 else (tr[j] + 13 * a) / 14
        out[k] = a
    return out


# ------------------------------------------------------------------ Bewertung

def spy_daily() -> pd.Series:
    df = history.fetch_yahoo("SPY", base=SPY_CACHE, until=date(2026, 10, 9))
    s = df["adjclose"].copy()
    s.index = pd.DatetimeIndex([pd.Timestamp(d) for d in s.index])
    return s.pct_change().dropna()


def tstat(x) -> float:
    x = pd.Series(x).dropna()
    return float(x.mean() / x.std(ddof=1) * np.sqrt(len(x))) if len(x) > 2 and x.std() > 0 else float("nan")


def monthly_from_trades(exit_time: pd.DatetimeIndex, r: np.ndarray, risk: float, a: str, b: str) -> pd.Series:
    months = pd.period_range(a, b, freq="M")
    g = pd.Series(1 + risk * r, index=exit_time.to_period("M")).groupby(level=0).prod() - 1
    return g.reindex(months).fillna(0.0)


def pa_m(m: pd.Series) -> float:
    return float((1 + m).prod() ** (12 / len(m)) - 1)


def judge(exit_time, r, risk, spy, label) -> tuple[bool, str]:
    lines, ok = [], True
    for name, (a, b) in (("Haupt 2016-01..2025-09", MAIN), ("Einordnung 2008-2015", CLASS)):
        ms = monthly_from_trades(exit_time, r, risk, a, b)
        sp = (1 + spy[(spy.index >= a) & (spy.index <= b)]).groupby(
            spy[(spy.index >= a) & (spy.index <= b)].index.to_period("M")).prod() - 1
        sp = sp.reindex(ms.index).fillna(0.0)
        ex = ms - sp
        t = tstat(ex)
        eq = (1 + ms).cumprod()
        dd = float((eq / eq.cummax() - 1).min())
        lines.append(f"  {label} {name}: {pa_m(ms):+6.1%} p.a. vs SPY {pa_m(sp):+6.1%}, Überrendite Ø "
                     f"{ex.mean():+.2%}/Monat, t {t:+.2f}, Max-DD (Monat) {dd:.1%}")
        if name.startswith("Haupt"):
            ok &= pa_m(ms) > pa_m(sp) and t >= T_PASS
        else:
            ok &= ex.mean() > 0
    return ok, "\n".join(lines)


def trade_stats(r: np.ndarray) -> str:
    if len(r) < 3:
        return f"n {len(r)}"
    w, l_ = r[r > 0].sum(), -r[r < 0].sum()
    return (f"n {len(r):5d}  Ø R {r.mean():+.3f}  t {tstat(r):+.2f}  Treffer {(r > 0).mean():.1%}  "
            f"PF {w / l_ if l_ > 0 else float('inf'):.2f}")


# ------------------------------------------------------------------ Simulation Runde 153

@numba.njit(cache=True)
def simulate(m_min, bo, bh, bl, bc, ao, ah, al, ac, b_start, b_i1, b_h, b_l, b_c, b_day, atr15, m_bar):
    """Ein Ergebnis je Server-Tag mit Signal: R netto, Ausstiegsminute, Richtung, Teilziel ja/nein, R des Rests."""
    nb, nm = len(b_start), len(m_min)
    out_r, out_rest = np.full(nb, np.nan), np.full(nb, np.nan)
    out_exit, out_dir = np.zeros(nb, np.int64), np.zeros(nb, np.int64)
    out_tp1 = np.zeros(nb, np.bool_)
    k = 0
    while k < nb:
        k_end = k
        while k_end < nb and b_day[k_end] == b_day[k]:
            k_end += 1
        hi, lo, sig, j_sig = -1e30, 1e30, 0, -1
        for j in range(k, k_end):
            mod = b_start[j] % 1440
            if mod < 420:
                hi, lo = max(hi, b_h[j]), min(lo, b_l[j])
            elif hi > -1e29:
                if b_c[j] > hi:
                    sig, j_sig = 1, j
                elif b_c[j] < lo:
                    sig, j_sig = -1, j
                if sig != 0:
                    break
        if sig != 0:
            dow = ((b_start[j_sig] + 15) // 1440 + 4) % 7          # 0 = Sonntag
            e = b_i1[j_sig] + 1
            a_sig = atr15[j_sig]
            if dow != 0 and dow != 6 and e < nm and not np.isnan(a_sig):
                mid = (hi + lo) / 2
                sd = 2.0 * max(abs(b_c[j_sig] - mid), 0.5 * a_sig)
                entry = ao[e] if sig > 0 else bo[e]
                stop = entry - sig * sd
                e_mod = m_min[e] % 1440
                deadline = m_min[e] if e_mod >= 1260 else m_min[e] - e_mod + 1260
                tp1, r1, ex, i_ex = False, 0.0, np.nan, -1
                for i in range(e, nm):
                    if m_min[i] >= deadline:
                        if i == e:
                            ex = bc[i] if sig > 0 else ac[i]
                        else:
                            ex = bo[i] if sig > 0 else ao[i]
                        i_ex = i
                        break
                    if sig > 0:
                        if bo[i] <= stop:
                            ex, i_ex = bo[i], i
                            break
                        if bl[i] <= stop:
                            ex, i_ex = stop, i
                            break
                        fav = bh[i]
                        if not tp1 and fav >= entry + sd:
                            tp1, r1 = True, (max(bo[i], entry + sd) - entry) / sd
                            stop = max(stop, entry)
                        if fav >= entry + 2 * sd and m_bar[i] >= 1:
                            a = atr15[m_bar[i] - 1]
                            if not np.isnan(a) and fav - 2.5 * a > stop:
                                stop = fav - 2.5 * a
                    else:
                        if ao[i] >= stop:
                            ex, i_ex = ao[i], i
                            break
                        if ah[i] >= stop:
                            ex, i_ex = stop, i
                            break
                        fav = al[i]
                        if not tp1 and fav <= entry - sd:
                            tp1, r1 = True, (entry - min(ao[i], entry - sd)) / sd
                            stop = min(stop, entry)
                        if fav <= entry - 2 * sd and m_bar[i] >= 1:
                            a = atr15[m_bar[i] - 1]
                            if not np.isnan(a) and fav + 2.5 * a < stop:
                                stop = fav + 2.5 * a
                if i_ex >= 0:
                    rest = sig * (ex - entry) / sd
                    tot = 0.7 * r1 + 0.3 * rest if tp1 else rest
                    out_r[j_sig] = tot - COMM * entry / sd
                    out_rest[j_sig], out_exit[j_sig], out_dir[j_sig], out_tp1[j_sig] = rest, m_min[i_ex], sig, tp1
        k = k_end
    return out_r, out_exit, out_dir, out_tp1, out_rest


def run_maren(m: dict) -> pd.DataFrame:
    b = resample(m, 15)
    b_day = server_day(b["start"])
    atr15 = atr_ea(b["h"], b["l"], b["c"])
    m_bar = np.repeat(np.arange(len(b["start"])), b["i1"] - b["i0"] + 1)
    r, ex, d, tp1, rest = simulate(m["minute"], m["bo"], m["bh"], m["bl"], m["bc"], m["ao"], m["ah"], m["al"],
                                   m["ac"], b["start"], b["i1"], b["h"], b["l"], b["c"], b_day, atr15, m_bar)
    ok = ~np.isnan(r)
    return pd.DataFrame({"signal": pd.to_datetime(b["start"][ok] * 60, unit="s"),
                         "exit": pd.to_datetime(ex[ok] * 60, unit="s"), "dir": d[ok], "r": r[ok],
                         "tp1": tp1[ok], "rest": rest[ok]})


def deal_view(tr: pd.DataFrame) -> str:
    """Zählweise des MT5-Testers: Teilschluss = eigener Trade."""
    deals = np.concatenate([np.where(tr.tp1, 0.7, np.nan), np.where(tr.tp1, 0.3 * tr.rest, tr.r)])
    deals = deals[~np.isnan(deals)]
    w, l_ = deals[deals > 0].sum(), -deals[deals < 0].sum()
    return f"Deals {len(deals)}, Treffer {(deals > 0).mean():.1%}, PF {w / l_:.2f}"


def main():
    t0 = time.time()
    m = load_market("xau", "xau_ask", "xau")
    print(f"XAUUSD M1: {len(m['minute'])} Minuten, mittlerer Spread {m['spread_med']:.3f}; je Jahr {coverage(m)}")
    tr = run_maren(m)
    spy = spy_daily()
    print(f"Signale/Trades gesamt {len(tr)} ({time.time() - t0:.0f} s)\n")

    def per(a, b):
        return tr[(tr.exit >= a) & (tr.exit <= pd.Timestamp(b) + pd.Timedelta(days=1))]

    print("=== HAUPTERGEBNIS (1 % Risiko je Trade wie der EA)")
    ok, txt = judge(pd.DatetimeIndex(tr.exit), tr.r.to_numpy(), 0.01, spy, "Maren")
    print(txt)
    print(f"  -> {'BESTANDEN' if ok else 'NICHT BESTANDEN'}\n")

    print("=== Info: Trade-Statistik je Position (R netto)")
    for name, (a, b) in (("2008-2015", CLASS), ("2016-2025", MAIN), ("Autor 09/2023-09/2026", AUTHOR)):
        x = per(a, b)
        print(f"  {name:22s} {trade_stats(x.r.to_numpy())}  Teilziel erreicht {x.tp1.mean():.0%}  "
              f"long {(x.dir > 0).mean():.0%}  | {deal_view(x)}")
    print("\n=== Info: Autor-Zeitraum 09/2023-09/2026 (Geld ab 2025-09-20 = Brief - mittlerer Spread)")
    x = per(*AUTHOR)
    weeks = (pd.Timestamp(AUTHOR[1]) - pd.Timestamp(AUTHOR[0])).days / 7
    for risk in (0.01, 0.02):
        eq = np.cumprod(1 + risk * x.r.to_numpy())
        dd = float((eq / np.maximum.accumulate(eq) - 1).min())
        print(f"  Risiko {risk:.0%}: Endkapital x{eq[-1]:.2f}, Ø {(eq[-1] ** (1 / weeks) - 1):+.2%}/Woche, "
              f"Max-DD (Trades) {dd:.1%}")
    print("\n=== Info: andere Risikostufen (Haupt/Einordnung)")
    for risk in (0.02, 0.03):
        print(judge(pd.DatetimeIndex(tr.exit), tr.r.to_numpy(), risk, spy, f"Risiko {risk:.0%}")[1])
    gold = pd.Series(m["bc"], index=pd.to_datetime(m["minute"] * 60, unit="s")).resample("1D").last().dropna()
    for name, (a, b) in (("2008-2015", CLASS), ("2016-2025", MAIN)):
        g = gold[(gold.index >= a) & (gold.index <= b)]
        yrs = (g.index[-1] - g.index[0]).days / 365.25
        print(f"  Gold halten {name}: {(g.iloc[-1] / g.iloc[0]) ** (1 / yrs) - 1:+.1%} p.a.")
    print("\n=== Info: je Jahr (Ø R, n)")
    g = tr.groupby(tr.exit.dt.year).r
    print("  " + " | ".join(f"{y} {v.mean():+.2f} ({len(v)})" for y, v in g))
    print(f"\nLaufzeit {time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()



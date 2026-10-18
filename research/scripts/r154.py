"""Runde 154: Nachbau fremder Bot "Kerzenmuster-Jaeger" -- Vorab: PROTOCOL.md Runde 154.

Aufruf aus dem Haupt-Repo (Daten relativ): PYTHONPATH=<worktree>;<worktree>/research/scripts python r154.py
Muster-Geometrie vektorisiert nach patterns.py/config.py des Bots (gegen die Originalfunktionen geprüft).
"""
from __future__ import annotations

import gc
import time

import numba
import numpy as np
import pandas as pd

from r153 import CLASS, MAIN, D, judge, resample, server_day, spy_daily, trade_stats

MARKETS = (("EURUSD", "fx", "fx_ask", "eurusd"), ("GBPUSD", "fx", "fx_ask", "gbpusd"),
           ("USDJPY", "fx", "fx_ask", "usdjpy"), ("XAUUSD", "xau", "xau_ask", "xau"))
END_MIN = int(pd.Timestamp("2025-09-20", tz="UTC").timestamp() // 60)   # Geld-Daten enden 2025-09-19
SL_PCT, TP_PCT = 0.005, 0.010
COMM_R = 0.5e-4 / SL_PCT                  # Kommission 0,5 bp Nominal je Runde in R
FIN_R = 0.025 / 360 / SL_PCT              # Finanzierung 2,5 % p.a. Nominal je Rollover in R
RISK, MAX_OPEN = 0.01, 3
SMALL_BODY, LONG_BODY, LONG_WICK, SHORT_WICK, PIN_WICK, PIN_BODY, TREND = 0.30, 0.55, 2.0, 0.15, 2.5, 0.25, 10

# Reihenfolge und Richtung wie patterns.PATTERNS
NAMES = ("Bullish Engulfing", "Bearish Engulfing", "Morning Star", "Evening Star", "Hammer", "Hanging Man",
         "Shooting Star", "Inverted Hammer", "Bullish Pin Bar", "Bearish Pin Bar", "Piercing Line",
         "Dark Cloud Cover", "Three White Soldiers", "Three Black Crows", "Bullish Harami", "Bearish Harami")
DIRS = (1, -1, 1, -1, 1, -1, -1, 1, 1, -1, 1, -1, 1, -1, 1, -1)
ENABLED = ("Bearish Engulfing", "Piercing Line", "Shooting Star", "Inverted Hammer", "Evening Star")


# ------------------------------------------------------------------ Muster

def shift(x: np.ndarray, k: int) -> np.ndarray:
    out = np.full_like(x, np.nan)
    out[k:] = x[:-k]
    return out


def patterns(o, h, l, c) -> dict[str, np.ndarray]:
    """Je Muster eine Bool-Maske: trifft das Muster auf die (geschlossene) Kerze i zu?"""
    with np.errstate(invalid="ignore"):
        rng, body = h - l, np.abs(c - o)
        uw, lw = h - np.maximum(o, c), np.minimum(o, c) - l
        o1, h1, l1, c1 = (shift(x, 1) for x in (o, h, l, c))
        o2_, c2_ = shift(o, 2), shift(c, 2)
        r1, b1 = shift(rng, 1), shift(body, 1)
        r2_, b2_ = shift(rng, 2), shift(body, 2)
        mid1 = (o1 + c1) / 2
        trend = np.sign(c1 - shift(c, TREND))
        trend[:TREND] = 0

        def hammer_shape(mult, ratio):
            return (rng > 0) & (body > 0) & (body <= ratio * rng) & (lw >= mult * body) & (uw <= SHORT_WICK * rng)

        def star_shape(mult, ratio):
            return (rng > 0) & (body > 0) & (body <= ratio * rng) & (uw >= mult * body) & (lw <= SHORT_WICK * rng)

        # Drei-Kerzen-Muster: Kerze a = i-2, b = i-1, cc = i
        three_ok = (np.minimum(np.minimum(r2_, r1), rng) > 0)
        long_a_bear = (c2_ < o2_) & (b2_ >= LONG_BODY * r2_)
        long_a_bull = (c2_ > o2_) & (b2_ >= LONG_BODY * r2_)
        ms = (three_ok & long_a_bear & (b1 <= SMALL_BODY * r1) & (np.maximum(o1, c1) <= c2_ + 0.25 * r2_)
              & (c > o) & (body >= LONG_BODY * rng) & (c > (o2_ + c2_) / 2))
        es = (three_ok & long_a_bull & (b1 <= SMALL_BODY * r1) & (np.minimum(o1, c1) >= c2_ - 0.25 * r2_)
              & (c < o) & (body >= LONG_BODY * rng) & (c < (o2_ + c2_) / 2))

        def soldier(sign):
            if sign > 0:
                one = (rng > 0) & (c > o) & (body >= 0.5 * rng) & (uw <= 0.3 * rng)
            else:
                one = (rng > 0) & (c < o) & (body >= 0.5 * rng) & (lw <= 0.3 * rng)
            all3 = one & (shift(one.astype(float), 1) == 1) & (shift(one.astype(float), 2) == 1)
            if sign > 0:
                return all3 & (c1 > c2_) & (c > c1) & (o1 > o2_) & (o1 < c2_) & (o > o1) & (o < c1)
            return all3 & (c1 < c2_) & (c < c1) & (o1 < o2_) & (o1 > c2_) & (o < o1) & (o > c1)

        long1_bear = (r1 > 0) & (c1 < o1) & (b1 >= LONG_BODY * r1)
        long1_bull = (r1 > 0) & (c1 > o1) & (b1 >= LONG_BODY * r1)
        out = {
            "Bullish Engulfing": (c1 < o1) & (c > o) & (o <= c1) & (c >= o1) & (body > b1),
            "Bearish Engulfing": (c1 > o1) & (c < o) & (o >= c1) & (c <= o1) & (body > b1),
            "Morning Star": ms,
            "Evening Star": es,
            "Hammer": hammer_shape(LONG_WICK, SMALL_BODY) & (trend < 0),
            "Hanging Man": hammer_shape(LONG_WICK, SMALL_BODY) & (trend > 0),
            "Shooting Star": star_shape(LONG_WICK, SMALL_BODY) & (trend > 0),
            "Inverted Hammer": star_shape(LONG_WICK, SMALL_BODY) & (trend < 0),
            "Bullish Pin Bar": hammer_shape(PIN_WICK, PIN_BODY),
            "Bearish Pin Bar": star_shape(PIN_WICK, PIN_BODY),
            "Piercing Line": long1_bear & (c > o) & (o <= c1) & (c > mid1) & (c < o1),
            "Dark Cloud Cover": long1_bull & (c < o) & (o >= c1) & (c < mid1) & (c > o1),
            "Three White Soldiers": soldier(1),
            "Three Black Crows": soldier(-1),
            "Bullish Harami": long1_bear & (c > o) & (o > c1) & (o < o1) & (c > c1) & (c < o1) & (body < 0.6 * b1),
            "Bearish Harami": long1_bull & (c < o) & (o < c1) & (o > o1) & (c < c1) & (c > o1) & (body < 0.6 * b1),
        }
    valid = np.arange(len(c)) >= max(TREND, 3) + 1          # check_signal braucht >= 12 geschlossene Kerzen
    return {k: v & valid for k, v in out.items()}


def patterns_chunked(o, h, l, c, size: int = 400_000) -> dict[str, np.ndarray]:
    """Wie patterns(), blockweise mit 12 Kerzen Vorlauf (Speicher); Ergebnis identisch."""
    n, pre = len(c), max(TREND, 3) + 1
    out = {k: np.zeros(n, bool) for k in NAMES}
    for s in range(0, n, size):
        a = max(0, s - pre)
        e = s + size
        part = patterns(*(x[a:e].astype(np.float64) for x in (o, h, l, c)))
        for k in NAMES:
            out[k][s:s + size] = part[k][s - a:]
    return out


def bot_signal(masks: dict[str, np.ndarray]) -> np.ndarray:
    """Erstes passende freigegebene Muster in der Reihenfolge von patterns.py -> Richtung (+1/-1/0) und Muster-Nr."""
    n = len(next(iter(masks.values())))
    sig, pid = np.zeros(n, np.int8), np.full(n, -1, np.int16)
    for k, name in enumerate(NAMES):
        if name not in ENABLED:
            continue
        hit = masks[name] & (sig == 0)
        sig[hit], pid[hit] = DIRS[k], k
    return sig, pid


# ------------------------------------------------------------------ Trades

@numba.njit(cache=True)
def outcomes(entries, dirs, bo, bh, bl, ao, ah, al, sl_pct, tp_pct):
    """Einstieg zur Eröffnung der Minute e; Stop vor Ziel in derselben Minute; Kurslücke -> Eröffnungskurs."""
    n, nm = len(entries), len(bo)
    ex_i, r = np.full(n, -1, np.int64), np.full(n, np.nan)
    for k in range(n):
        e, d = entries[k], dirs[k]
        if d > 0:
            px = ao[e]
            sl, tp = px * (1 - sl_pct), px * (1 + tp_pct)
            for i in range(e, nm):
                if i > e and bo[i] <= sl:
                    ex_i[k], r[k] = i, (bo[i] - px) / (px * sl_pct)
                    break
                if bl[i] <= sl:
                    ex_i[k], r[k] = i, (sl - px) / (px * sl_pct)
                    break
                if i > e and bo[i] >= tp:
                    ex_i[k], r[k] = i, (bo[i] - px) / (px * sl_pct)
                    break
                if bh[i] >= tp:
                    ex_i[k], r[k] = i, (tp - px) / (px * sl_pct)
                    break
        else:
            px = bo[e]
            sl, tp = px * (1 + sl_pct), px * (1 - tp_pct)
            for i in range(e, nm):
                if i > e and ao[i] >= sl:
                    ex_i[k], r[k] = i, (px - ao[i]) / (px * sl_pct)
                    break
                if ah[i] >= sl:
                    ex_i[k], r[k] = i, (px - sl) / (px * sl_pct)
                    break
                if i > e and ao[i] <= tp:
                    ex_i[k], r[k] = i, (px - ao[i]) / (px * sl_pct)
                    break
                if al[i] <= tp:
                    ex_i[k], r[k] = i, (px - tp) / (px * sl_pct)
                    break
    return ex_i, r


def rollover_weights(day: np.ndarray) -> np.ndarray:
    """Kumulierte Rollover-Zahl je Server-Tag: Rollover 17:00 NY Mo-Fr, mittwochs dreifach (Server-Tag Do)."""
    d0 = int(day.min())
    days = np.arange(d0, int(day.max()) + 1)
    wd = (pd.Timestamp("2000-01-01") + pd.to_timedelta(days, unit="D")).weekday.to_numpy()   # 0 = Montag
    w = np.select([wd == 3, np.isin(wd, (1, 2, 4, 5))], [3, 1], 0)
    return np.cumsum(w), d0


def read_np(folder: str, name: str) -> tuple[np.ndarray, np.ndarray]:
    """Jahresdateien als (Minute, OHLC float32), bis END_MIN."""
    ts, px = [], []
    for f in sorted((D / folder).glob(f"{name}_*.csv")):
        if f.stat().st_size == 0:
            continue
        df = pd.read_csv(f, dtype={"timestamp": np.int64, "open": np.float32, "high": np.float32,
                                   "low": np.float32, "close": np.float32})
        mi = (df["timestamp"].to_numpy() // 60000).astype(np.int64)
        k = mi < END_MIN
        ts.append(mi[k]), px.append(df[["open", "high", "low", "close"]].to_numpy(np.float32)[k])
        del df
    mi, p = np.concatenate(ts), np.concatenate(px)
    mi, first = np.unique(mi, return_index=True)
    return mi, p[first]


def load_lean(bid_dir: str, ask_dir: str, name: str) -> dict:
    """Wie r153.load_market (fehlende Seite über mittleren Spread, flache Kerzen raus), speichersparend in float32."""
    bm, bp = read_np(bid_dir, name)
    am, ap = read_np(ask_dir, name)
    mi = np.union1d(bm, am)
    bid = np.full((len(mi), 4), np.nan, np.float32)
    ask = np.full((len(mi), 4), np.nan, np.float32)
    bid[np.searchsorted(mi, bm)] = bp
    ask[np.searchsorted(mi, am)] = ap
    del bm, bp, am, ap
    sp = ask[:, 3] - bid[:, 3]
    med = np.float32(np.nanmedian(sp[sp > 0]))
    nb, na = np.isnan(bid[:, 0]), np.isnan(ask[:, 0])
    bid[nb] = ask[nb] - med
    ask[na] = bid[na] + med
    flat = (bid[:, 1] == bid[:, 2]) & (bid[:, 0] == bid[:, 3]) & (bid[:, 0] == bid[:, 1])
    keep = ~flat & ~np.isnan(bid).any(axis=1) & ~np.isnan(ask).any(axis=1)
    out = {"minute": mi[keep], "spread_med": float(med)}
    for j, c in enumerate("ohlc"):
        out["b" + c] = np.ascontiguousarray(bid[keep, j])
        out["a" + c] = np.ascontiguousarray(ask[keep, j])
    return out


MAIN_MIN = int(pd.Timestamp(MAIN[0], tz="UTC").timestamp() // 60)


@numba.njit(cache=True)
def outcomes_memo(entries, dirs, bo, bh, bl, ao, ah, al, ex_mem, r_mem):
    """outcomes() mit Zwischenspeicher je (Einstiegsminute, Richtung); ex_mem -2 = noch nicht gerechnet."""
    n = len(entries)
    ex_i, r = np.empty(n, np.int64), np.empty(n)
    one_e, one_d = np.empty(1, np.int64), np.empty(1, np.int8)
    for k in range(n):
        e = entries[k]
        s = 1 if dirs[k] > 0 else 0
        if ex_mem[s, e] == -2:
            one_e[0], one_d[0] = e, dirs[k]
            x, y = outcomes(one_e, one_d, bo, bh, bl, ao, ah, al, SL_PCT, TP_PCT)
            ex_mem[s, e], r_mem[s, e] = x[0], y[0]
        ex_i[k], r[k] = ex_mem[s, e], r_mem[s, e]
    return ex_i, r


def market_trades(name, bid_dir, ask_dir, file, stats):
    """Bot-Kandidaten des Marktes (DataFrame); Einzelmuster-Kennzahlen werden in stats aufsummiert."""
    m = load_lean(bid_dir, ask_dir, file)
    nm = len(m["minute"])
    print(f"  {name}: {nm} Minuten, mittlerer Spread {m['spread_med']:.5g}", flush=True)
    day = server_day(m["minute"]).astype(np.int32)
    cw, d0 = rollover_weights(day)
    ex_mem = np.full((2, nm), -2, np.int32)
    r_mem = np.full((2, nm), np.nan, np.float32)
    px = (m["bo"], m["bh"], m["bl"], m["ao"], m["ah"], m["al"])

    def net(e, ex_i, r):
        done = ex_i >= 0
        exs = np.where(done, ex_i, 0)
        roll = np.where(done, cw[day[exs] - d0] - cw[day[e] - d0], 0)
        return done, exs, roll, r - COMM_R - FIN_R * roll

    rows_bot = []
    for tf in (1, 5):
        if tf == 1:
            o, h, l, c = m["bo"], m["bh"], m["bl"], m["bc"]
            last = np.arange(nm)
        else:
            b = resample(m, 5)
            o, h, l, c, last = b["o"], b["h"], b["l"], b["c"], b["i1"]
        masks = patterns_chunked(o, h, l, c)
        sig, pid = bot_signal(masks)
        entry = last + 1
        ok_e = entry < nm
        for k, nm_ in enumerate(NAMES):
            idx = np.flatnonzero(masks[nm_] & ok_e)
            masks[nm_] = None
            e = entry[idx]
            ex_i, r = outcomes_memo(e, np.full(len(e), DIRS[k], np.int8), *px, ex_mem, r_mem)
            done, _, _, rn = net(e, ex_i, r)
            late = m["minute"][e] >= MAIN_MIN
            for pk, sel in ((0, done & ~late), (1, done & late)):
                st = stats.setdefault((k, pk), np.zeros(4))
                st += (sel.sum(), rn[sel].sum(), (rn[sel] ** 2).sum(), r[sel].sum())
        del masks
        bidx = np.flatnonzero((sig != 0) & ok_e)
        e = entry[bidx]
        ex_i, r = outcomes_memo(e, sig[bidx], *px, ex_mem, r_mem)
        done, exs, roll, rn = net(e, ex_i, r)
        rows_bot.append(pd.DataFrame({"entry": m["minute"][e], "exit": m["minute"][exs], "r": rn, "gross": r,
                                      "hold": m["minute"][exs] - m["minute"][e], "roll": roll,
                                      "pattern": pid[bidx], "dir": sig[bidx], "tf": tf, "market": name})[done])
    return pd.concat(rows_bot, ignore_index=True)


def portfolio(cand: pd.DataFrame) -> pd.DataFrame:
    """Bot-Schleife: je Symbol höchstens 1 Position, insgesamt höchstens 3; Reihenfolge Zeit, Symbol, Zeitrahmen."""
    order = {m[0]: k for k, m in enumerate(MARKETS)}
    c = cand.assign(mo=cand.market.map(order)).sort_values(["entry", "mo", "tf"], kind="stable")
    open_until: dict[str, int] = {}
    taken = []
    for row in c.itertuples(index=False):
        open_until = {k: v for k, v in open_until.items() if v >= row.entry}
        if row.market in open_until or len(open_until) >= MAX_OPEN:
            continue
        open_until[row.market] = row.exit
        taken.append(row)
    return pd.DataFrame(taken)


def agg(st) -> tuple[int, float, float, float]:
    n, s1, s2, g = st
    if n < 3:
        return int(n), float("nan"), float("nan"), float("nan")
    mean = s1 / n
    sd = np.sqrt(max(s2 / n - mean ** 2, 0) * n / (n - 1))
    return int(n), mean, mean / sd * np.sqrt(n) if sd > 0 else float("nan"), g / n


def main():
    t0 = time.time()
    spy = spy_daily()
    bots, stats = [], {}
    for mk in MARKETS:
        bots.append(market_trades(*mk, stats))
        gc.collect()
        print(f"{mk[0]}: Bot-Kandidaten {len(bots[-1])} ({time.time() - t0:.0f} s)", flush=True)
    cand = pd.concat(bots, ignore_index=True)
    tr = portfolio(cand)
    tr["t_exit"] = pd.to_datetime(tr.exit * 60, unit="s")
    tr["t_entry"] = pd.to_datetime(tr.entry * 60, unit="s")
    print(f"\nBot-Trades nach Positionsgrenzen: {len(tr)} von {len(cand)} Kandidaten\n")

    print("=== HAUPTERGEBNIS (Bot wie geliefert, 1 % Risiko je Trade)")
    ok, txt = judge(pd.DatetimeIndex(tr.t_exit), tr.r.to_numpy(), RISK, spy, "Kerzen-Bot")
    print(txt)
    print(f"  -> {'BESTANDEN' if ok else 'NICHT BESTANDEN'}\n")

    print("=== Info: Bot-Trades (R netto; brutto = vor Kommission und Finanzierung, Spread enthalten)")
    for name, (a, b) in (("2008-2015", CLASS), ("2016-2025", MAIN)):
        x = tr[(tr.t_entry >= a) & (tr.t_entry <= pd.Timestamp(b) + pd.Timedelta(days=1))]
        print(f"  {name}: {trade_stats(x.r.to_numpy())}  | brutto Ø {x.gross.mean():+.3f} R | Haltezeit Median "
              f"{x.hold.median() / 60:.1f} h | Ø Rollover {x.roll.mean():.2f}")
        for (mk, tf), g in x.groupby(["market", "tf"]):
            print(f"      {mk} M{tf}: n {len(g):5d}  Ø R {g.r.mean():+.3f}  Treffer {(g.r > 0).mean():.0%}")
        for pid, g in x.groupby("pattern"):
            print(f"      {NAMES[int(pid)]:18s}: n {len(g):5d}  Ø R {g.r.mean():+.3f}")

    print("\n=== Info: jedes der 16 Muster einzeln (alle Signale, ohne Positionsgrenzen; Trades überlappen ->"
          " t überzeichnet; Hürde Bonferroni 16: t >= 2,73)")
    print(f"  {'Muster':20s} {'n 08-15':>8s} {'Ø R':>7s} {'t':>6s} | {'n 16-25':>8s} {'Ø R':>7s} {'t':>6s} {'brutto':>7s}")
    for k, name in enumerate(NAMES):
        na, ma, ta, _ = agg(stats.get((k, 0), np.zeros(4)))
        nb, mb, tb, gb = agg(stats.get((k, 1), np.zeros(4)))
        flag = " *" if nb > 2 and mb > 0 and tb >= 2.73 and ma > 0 else ""
        print(f"  {name:20s} {na:8d} {ma:+7.3f} {ta:+6.2f} | {nb:8d} {mb:+7.3f} {tb:+6.2f} {gb:+7.3f}{flag}")
    print(f"\nLaufzeit {time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()

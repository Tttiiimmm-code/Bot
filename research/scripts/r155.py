"""Runde 155: Nachbau "FvgGold" (GitHub foeed/FvgGold-EA v2.01, Fair Value Gap + Order Block) -- Vorab: PROTOCOL.md.

Jede M1-Kerze ist ein Tick (Geld/Brief = Schlusskurse); vorher werden Füllungen und Ausstiege der Minute aus Hoch/Tief
abgearbeitet. Aufruf aus dem Haupt-Repo: PYTHONPATH=<worktree> python <worktree>/research/scripts/r155.py
"""
from __future__ import annotations

import time

import numba
import numpy as np
import pandas as pd

from r153 import COMM, judge, load_market, resample, server_day, spy_daily, trade_stats

# FvgGold.set
MIN_GAP, MAX_AGE, MIN_AGE, BUF = 0.25, 20, 2, 3.0
MIN_SCORE, W_GAP, W_DISP, W_HTF, W_FRESH, W_PD = 50.0, 30.0, 30.0, 20.0, 10.0, 10.0
OB_IMP, OB_LOOK, OB_MIN, OB_BONUS, OB_DIST = 1.5, 50, 0.10, 20.0, 2.00
RR, DAILY_LIMIT, BE_ATR = 1.5, -5.0, 0.5
SWAP_LONG = 0.063
SL_DIST = 1.5 * BUF                      # Einstieg Unterkante + 1,5, Stop Unterkante - 3,0


@numba.njit(cache=True)
def simulate(mt, bo, bh, bl, bc, ao, ah, al, ac, k15, s15, o15, h15, l15, c15, tr15, k60, ema50c, ema200c,
             sday, hour, cancel_stale, last_px):
    """Gibt je abgeschlossenem Trade (Füllminute, Ausstiegsminute, Richtung, G/V je Unze netto) und die Zahl der Ticks mit
    hängender Limit-Order zurück."""
    n = len(mt)
    cap = 64
    ob_t = np.zeros(cap, np.int64); ob_ty = np.zeros(cap, np.int64)
    ob_top = np.zeros(cap); ob_bot = np.zeros(cap); n_ob = 0
    fv_t = np.zeros(cap, np.int64); fv_ty = np.zeros(cap, np.int64)
    fv_top = np.zeros(cap); fv_bot = np.zeros(cap); fv_mid = np.zeros(cap); fv_sc = np.zeros(cap)
    fv_pl = np.zeros(cap, np.bool_); n_fv = 0
    out_f = np.zeros(200000, np.int64); out_x = np.zeros(200000, np.int64)
    out_d = np.zeros(200000, np.int64); out_p = np.zeros(200000); n_out = 0
    pend = 0; pos = 0                     # Richtung +1/-1, 0 = keine
    p_entry = p_sl = p_tp = 0.0; p_tag = -1; p_min = 0
    e_px = 0.0; e_min = 0
    day = -1; daypl = 0.0
    pend_ticks = 0
    a50 = 2.0 / 51.0; a200 = 2.0 / 201.0
    for j in range(n):
        k = k15[j]
        # ---------- Minute j: Ausstiege und Füllungen (Stand der Vorminute)
        closed = False
        x_px = 0.0
        if pos == 1:
            if bo[j] <= p_sl or bo[j] >= p_tp:
                x_px = bo[j]; closed = True
            elif bl[j] <= p_sl:
                x_px = p_sl; closed = True
            elif bh[j] >= p_tp:
                x_px = p_tp; closed = True
        elif pos == -1:
            if ao[j] >= p_sl or ao[j] <= p_tp:
                x_px = ao[j]; closed = True
            elif ah[j] >= p_sl:
                x_px = p_sl; closed = True
            elif al[j] <= p_tp:
                x_px = p_tp; closed = True
        elif pend == 1 and al[j] <= p_entry:
            e_px = min(ao[j], p_entry); e_min = mt[j]; pos = 1; pend = 0
            if bl[j] <= p_sl:                      # Füllminute: nur Stop
                x_px = p_sl; closed = True
        elif pend == -1 and bh[j] >= p_entry:
            e_px = max(bo[j], p_entry); e_min = mt[j]; pos = -1; pend = 0
            if ah[j] >= p_sl:
                x_px = p_sl; closed = True
        if closed:
            pnl = (x_px - e_px) * pos - COMM * e_px
            if pos == 1:
                pnl -= SWAP_LONG / 365.0 * e_px * (mt[j] - e_min) / 1440.0
            out_f[n_out] = e_min; out_x[n_out] = mt[j]; out_d[n_out] = pos; out_p[n_out] = pnl; n_out += 1
            if sday[j] == day:
                daypl += pnl
            pos = 0
        # ---------- Tick am Minutenschluss
        bid, ask = bc[j], ac[j]
        now = mt[j] + 1
        if sday[j] != day:
            day = sday[j]; daypl = 0.0
            if closed and out_x[n_out - 1] == mt[j]:
                daypl = out_p[n_out - 1]
        # laufende M15-Kerze und ATR14 (einfacher Durchschnitt, laufende Kerze eingeschlossen)
        i0 = j
        while i0 > 0 and k15[i0 - 1] == k:
            i0 -= 1
        fh, fl = bh[i0], bl[i0]
        for q in range(i0 + 1, j + 1):
            fh = max(fh, bh[q]); fl = min(fl, bl[q])
        if k < 60:
            continue
        pc = c15[k - 1]
        trf = max(fh - fl, max(abs(fh - pc), abs(fl - pc)))
        atr = trf
        for q in range(k - 13, k):
            atr += tr15[q]
        atr /= 14.0
        kh = k60[j]
        e50 = a50 * bid + (1 - a50) * ema50c[kh - 1]
        e200 = a200 * bid + (1 - a200) * ema200c[kh - 1]
        bias = 1 if e50 > e200 else (-1 if e50 < e200 else 0)
        # Einstand
        if pos == 1 and bid - e_px >= BE_ATR * atr and p_sl < e_px:
            p_sl = e_px + 0.02
        elif pos == -1 and e_px - ask >= BE_ATR * atr and p_sl > e_px:
            p_sl = e_px - 0.02
        if pend != 0:
            pend_ticks += 1
        if daypl <= DAILY_LIMIT:
            continue
        # ---------- Order Blocks
        for i in range(2, OB_LOOK + 5):
            kk = k - i
            o1, c1 = o15[kk - 1], c15[kk - 1]
            o2, c2 = o15[kk], c15[kk]
            if abs(c2 - o2) < atr * OB_IMP:
                continue
            ty = 0
            if c2 > o2 and c1 < o1:
                ty = 1
            elif c2 < o2 and c1 > o1:
                ty = -1
            if ty == 0:
                continue
            top, bot = max(o1, c1), min(o1, c1)
            if top - bot < OB_MIN:
                continue
            t1 = s15[kk - 1]
            ex = False
            for q in range(n_ob):
                if ob_t[q] == t1:
                    ex = True
                    break
            if ex or n_ob >= cap:
                continue
            ob_t[n_ob] = t1; ob_ty[n_ob] = ty; ob_top[n_ob] = top; ob_bot[n_ob] = bot; n_ob += 1
        w = 0
        for q in range(n_ob):
            rem = ob_t[q] < now - OB_LOOK * 15
            if not rem:
                if ob_ty[q] == 1 and bid < ob_bot[q]:
                    rem = True
                elif ob_ty[q] == -1 and ask > ob_top[q]:
                    rem = True
            if not rem:
                ob_t[w] = ob_t[q]; ob_ty[w] = ob_ty[q]; ob_top[w] = ob_top[q]; ob_bot[w] = ob_bot[q]; w += 1
        n_ob = w
        # ---------- Fair Value Gaps
        for i in range(3, 30):
            ko, km, kn = k - i, k - i + 1, k - i + 2
            ty = 0
            if l15[kn] > h15[ko]:
                ty = 1; top = l15[kn]; bot = h15[ko]
            elif h15[kn] < l15[ko]:
                ty = -1; top = l15[ko]; bot = h15[kn]
            if ty == 0:
                continue
            if top - bot < MIN_GAP:
                continue
            age = i - 1
            if age < MIN_AGE or age > MAX_AGE:
                continue
            t1 = s15[km]
            ex = False
            for q in range(n_fv):
                if fv_t[q] == t1:
                    ex = True
                    break
            if ex:
                continue
            sc = min((top - bot) / atr, 1.0) * W_GAP
            rng = h15[km] - l15[km]
            if rng > 0:
                sc += abs(c15[km] - o15[km]) / rng * W_DISP
            if ty == bias:
                sc += W_HTF
            sc += (1.0 - age / MAX_AGE) * W_FRESH
            if (ty == 1 and bid - e50 < 0) or (ty == -1 and bid - e50 > 0):
                sc += W_PD
            for q in range(n_ob):
                if ob_ty[q] != ty:
                    continue
                if top >= ob_bot[q] and bot <= ob_top[q]:
                    sc += OB_BONUS
                    break
                dist = bot - ob_top[q] if ty == 1 else ob_bot[q] - top
                if dist >= 0 and dist <= OB_DIST:
                    sc += OB_BONUS
                    break
            sc = round(sc, 1)
            if sc < MIN_SCORE or n_fv >= cap:
                continue
            fv_t[n_fv] = t1; fv_ty[n_fv] = ty; fv_top[n_fv] = top; fv_bot[n_fv] = bot
            fv_mid[n_fv] = (top + bot) / 2; fv_sc[n_fv] = sc; fv_pl[n_fv] = False; n_fv += 1
        w = 0
        for q in range(n_fv):
            rem = fv_t[q] < now - MAX_AGE * 15
            if not rem:
                if fv_ty[q] == 1 and bid < fv_mid[q]:
                    rem = True
                elif fv_ty[q] == -1 and ask > fv_mid[q]:
                    rem = True
            if rem and cancel_stale and pend != 0 and fv_t[q] == p_tag:
                pend = 0                           # Info-Variante: Order mit der Zone löschen
            if not rem:
                fv_t[w] = fv_t[q]; fv_ty[w] = fv_ty[q]; fv_top[w] = fv_top[q]; fv_bot[w] = fv_bot[q]
                fv_mid[w] = fv_mid[q]; fv_sc[w] = fv_sc[q]; fv_pl[w] = fv_pl[q]; w += 1
        n_fv = w
        # ---------- Trend, Killzone, Orders
        if bias == 0:
            continue
        hr = hour[j]
        if not ((hr >= 7 and hr < 10) or (hr >= 12 and hr < 21)):
            continue
        for q in range(n_fv):
            if fv_pl[q] or fv_ty[q] != bias or fv_sc[q] < MIN_SCORE:
                continue
            if pos != 0 or pend != 0:
                break
            spread = ask - bid
            if bias == 1:
                entry = fv_bot[q] + BUF * 0.5; sl = fv_bot[q] - BUF
                if ask - entry < spread or sl >= entry:
                    continue
                pend = 1; p_entry = entry; p_sl = sl; p_tp = entry + (entry - sl) * RR
            else:
                entry = fv_top[q] - BUF * 0.5; sl = fv_top[q] + BUF
                if entry - bid < spread or sl <= entry:
                    continue
                pend = -1; p_entry = entry; p_sl = sl; p_tp = entry - (sl - entry) * RR
            fv_pl[q] = True; p_tag = fv_t[q]; p_min = mt[j]
    last_px[0] = pend; last_px[1] = p_entry; last_px[2] = p_min; last_px[3] = bc[n - 1]
    return out_f[:n_out], out_x[:n_out], out_d[:n_out], out_p[:n_out], pend_ticks


def ema(x: np.ndarray, span: int) -> np.ndarray:
    return pd.Series(x).ewm(span=span, adjust=False).mean().to_numpy()


def run(m: dict, cancel_stale: bool = False, info: dict | None = None) -> tuple[pd.DataFrame, float]:
    b15, b60 = resample(m, 15), resample(m, 60)
    k15 = np.repeat(np.arange(len(b15["start"])), b15["i1"] - b15["i0"] + 1)
    k60 = np.repeat(np.arange(len(b60["start"])), b60["i1"] - b60["i0"] + 1)
    pc = np.concatenate([[b15["c"][0]], b15["c"][:-1]])
    tr = np.maximum(b15["h"] - b15["l"], np.maximum(np.abs(b15["h"] - pc), np.abs(b15["l"] - pc)))
    hour = ((m["minute"] // 60) % 24).astype(np.int64)
    last = np.zeros(4)
    f, x, d, p, pend = simulate(m["minute"], m["bo"], m["bh"], m["bl"], m["bc"], m["ao"], m["ah"], m["al"], m["ac"],
                                k15, b15["start"], b15["o"], b15["h"], b15["l"], b15["c"], tr, k60,
                                ema(b60["c"], 50), ema(b60["c"], 200), server_day(m["minute"]), hour, cancel_stale, last)
    tr_ = pd.DataFrame({"fill": pd.to_datetime(f * 60, unit="s"), "exit": pd.to_datetime(x * 60, unit="s"),
                        "dir": d, "pnl": p})
    tr_["r"] = tr_["pnl"] / SL_DIST
    if info is not None:
        info.update(dir=int(last[0]), entry=last[1], placed=pd.Timestamp(int(last[2]) * 60, unit="s"), last=last[3])
    return tr_, pend / len(m["minute"])


def main():
    t0 = time.time()
    m = load_market("xau", "xau_ask", "xau")
    print(f"Runde 155 -- FvgGold (Fair Value Gap + Order Block), XAUUSD M1 {len(m['minute']):,} Minuten, "
          f"mittlerer Spread {m['spread_med']:.3f} $\n")
    info = {}
    tr, pend_share = run(m, info=info)
    spy = spy_daily()
    print(f"Trades gesamt {len(tr)}; Ticks mit hängender Limit-Order {pend_share:.1%}\n")
    print("Hauptkriterium (1 % Risiko je Trade, R = G/V / 4,50 $):")
    ok, txt = judge(pd.DatetimeIndex(tr.exit), tr.r.to_numpy(), 0.01, spy, "FvgGold")
    print(txt)
    print(f"  -> {'BESTANDEN' if ok else 'NICHT BESTANDEN'}\n")
    print("Info je Zeitraum (R netto je Trade):")
    for name, a, b in (("2008-2015", "2008-01-01", "2015-12-31"), ("2016-2025/09", "2016-01-01", "2025-09-30"),
                       ("Autor Jan-Jul 2026", "2026-01-01", "2026-07-31")):
        s = tr[(tr.exit >= a) & (tr.exit <= b)]
        print(f"  {name:20s} {trade_stats(s.r.to_numpy())}")
        for dd, lab in ((1, "long"), (-1, "short")):
            print(f"    {lab:5s} {trade_stats(s[s.dir == dd].r.to_numpy())}")
    print(f"Info: hängende Order am Datenende: Richtung {info['dir']:+d}, Limit {info['entry']:.2f} $, gesetzt "
          f"{info['placed']:%Y-%m-%d %H:%M}, letzter Kurs {info['last']:.2f} $")
    a = tr[(tr.exit >= "2026-01-01") & (tr.exit <= "2026-07-31")]
    print(f"\nInfo Autor-Zeitraum Jan-Jul 2026, 0,01 Lot (1 Unze) auf 10.000 $: {a.pnl.sum():+.2f} $ = "
          f"{a.pnl.sum() / 10000:+.2%} bei {len(a)} Trades (Autor: +48,7 % bei 64 Trades)")
    start = int(pd.Timestamp("2025-11-01").timestamp() // 60)
    sub = {k: (v[m["minute"] >= start] if isinstance(v, np.ndarray) else v) for k, v in m.items()}
    t26, _ = run(sub)                                     # frischer Start Ende 2025 (wie ein Testerlauf des Autors)
    a = t26[(t26.exit >= "2026-01-01") & (t26.exit <= "2026-07-31")]
    print(f"Info frischer Start (Tester ab ~Nov 2025), Jan-Jul 2026, 0,01 Lot: {a.pnl.sum():+.2f} $ = "
          f"{a.pnl.sum() / 10000:+.2%} bei {len(a)} Trades, Treffer {(a.pnl > 0).mean() if len(a) else 0:.0%}")
    print("\nNACHTRÄGLICHE VARIANTE (nur Info, nicht gewertet): Limit-Order wird gelöscht, sobald ihre FVG-Zone verfällt")
    tv, pv = run(m, cancel_stale=True)
    print(f"  Trades {len(tv)}, Ticks mit hängender Order {pv:.1%}")
    print(judge(pd.DatetimeIndex(tv.exit), tv.r.to_numpy(), 0.01, spy, "Variante")[1])
    for name, a_, b_ in (("2008-2015", "2008-01-01", "2015-12-31"), ("2016-2025/09", "2016-01-01", "2025-09-30"),
                         ("Jan-Jul 2026", "2026-01-01", "2026-07-31")):
        s_ = tv[(tv.exit >= a_) & (tv.exit <= b_)]
        print(f"  {name:20s} {trade_stats(s_.r.to_numpy())}")
    print(f"Info: Ø G/V je Trade {tr.pnl.mean():+.3f} $ je Unze netto; Laufzeit {time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()

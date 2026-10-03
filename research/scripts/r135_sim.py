"""Simulator Runde 135 (Runde 134 + Puffer + Enge-Filter)."""
import numba
import numpy as np


@numba.njit(cache=True)
def sim2(h_of_m, hh, hl, atr, bo, bh, bl, bc, ao, ah, al, ac, fri_stop, fri_cancel,
         n_lvl, exp_h, sl_x, tp_y, trail, long_only, buf, max_rng):
    n = len(bo)
    out_i = np.empty(n // 30 + 10, np.int64)
    out_r = np.empty(n // 30 + 10, np.float64)
    out_x = np.empty(n // 30 + 10, np.int64)       # Ausstiegsminute (für Haltedauer/Swap)
    out_q = np.empty(n // 30 + 10, np.float64)     # Risiko / Einstiegskurs (für Positionsgröße)
    k = 0
    pos = 0                    # 0 flach, 1 long, -1 short
    pend = False
    buy_lvl = sell_lvl = pend_atr = 0.0
    pend_until = -1
    entry = sl = tp = risk = best = 0.0
    e_idx = 0
    for i in range(1, n):
        new_hour = h_of_m[i] != h_of_m[i - 1]
        if new_hour and pos == 0 and not pend and not fri_stop[i]:
            kk = h_of_m[i]                                   # abgeschlossene Stunden kk-n_lvl .. kk-1
            if kk - n_lvl >= 15 and not np.isnan(atr[kk - 1]):
                a = atr[kk - 1]
                hi = -1e18
                lo = 1e18
                for j in range(kk - n_lvl, kk):
                    if hh[j] > hi:
                        hi = hh[j]
                    if hl[j] < lo:
                        lo = hl[j]
                if max_rng <= 0 or (hi - lo) <= max_rng * a:
                    buy_lvl, sell_lvl, pend_atr = hi + buf * a, lo - buf * a, a
                    pend, pend_until = True, kk + exp_h
        if pend:
            if h_of_m[i] >= pend_until or fri_cancel[i]:
                pend = False
            else:
                hit_b = ah[i] >= buy_lvl
                hit_s = (not long_only) and bl[i] <= sell_lvl
                if hit_b and hit_s:
                    hit_s = False                             # beide in einer Minute: nur long, danach Stop-Prüfung
                if hit_b:
                    entry = max(ao[i], buy_lvl)
                    pos, pend = 1, False
                elif hit_s:
                    entry = min(bo[i], sell_lvl)
                    pos, pend = -1, False
                if pos != 0:
                    risk = sl_x * pend_atr
                    sl = entry - pos * risk
                    tp = entry + pos * tp_y * pend_atr
                    best = entry
                    e_idx = i
                    if pos == 1 and bl[i] <= sl:              # Einstiegsminute: nur Stop prüfen
                        out_i[k], out_r[k], out_x[k], out_q[k] = e_idx, (sl - entry) / risk, i, risk / entry
                        k += 1
                        pos = 0
                    elif pos == -1 and ah[i] >= sl:
                        out_i[k], out_r[k], out_x[k], out_q[k] = e_idx, (entry - sl) / risk, i, risk / entry
                        k += 1
                        pos = 0
                    continue
        if pos == 1:
            ex = -1.0
            if bo[i] <= sl or bo[i] >= tp:
                ex = bo[i]
            elif bl[i] <= sl:
                ex = sl
            elif bh[i] >= tp:
                ex = tp
            if ex > 0:
                out_i[k], out_r[k], out_x[k], out_q[k] = e_idx, (ex - entry) / risk, i, risk / entry
                k += 1
                pos = 0
            elif trail:
                if bh[i] > best:
                    best = bh[i]
                if best - entry >= pend_atr and best - pend_atr > sl:
                    sl = best - pend_atr
        elif pos == -1:
            ex = -1.0
            if ao[i] >= sl or ao[i] <= tp:
                ex = ao[i]
            elif ah[i] >= sl:
                ex = sl
            elif al[i] <= tp:
                ex = tp
            if ex > 0:
                out_i[k], out_r[k], out_x[k], out_q[k] = e_idx, (entry - ex) / risk, i, risk / entry
                k += 1
                pos = 0
            elif trail:
                if al[i] < best:
                    best = al[i]
                if entry - best >= pend_atr and best + pend_atr < sl:
                    sl = best + pend_atr
        if k >= len(out_i) - 1:
            break
    return out_i[:k], out_r[:k], out_x[:k], out_q[:k]



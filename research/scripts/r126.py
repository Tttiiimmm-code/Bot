"""Runde 126 (Vorab, 2026-10-01): Bull-Flag des Momentum-Bots auf Stocks-in-Play-Minutendaten, 48 Varianten.

Flaggenstange: Schluss >= 3 % über dem tiefsten Tief seit dem letzten Rücksetzpunkt, binnen <= 15 Minuten. Flagge: danach
2-5 Minuten ohne neues Hoch, Rücksetzer höchstens 50 % der Stange. Einstieg: Schluss über dem Vorminuten-Hoch nach
>= 2 Flaggen-Minuten -> Kauf zur Eröffnung der nächsten Minute. Stop: Flaggen-Tief, mindestens 2 % bzw. 4 % unter dem
Einstieg. Ausstieg: Ziel 2R / 3R / Einstand ab +1R sonst Tagesschluss; Stop vor Ziel; Einstiegsminute nur Stop.
Varianten: Einstieg jeder Ausbruch / nur über bisherigem Tageshoch x bis 10:30 / bis 15:00 x Stop min 2 % / 4 % x
3 Ausstiege x Top 5 / Top 20 = 48. Höchstens 3 Trades je Aktie und Tag (nacheinander). Kosten je Seite 1 bp + 1 Cent.
Daten/Zeiträume/Kennzahl wie Runde 107 (Tages-Summe R, t über Tage). Hürde: t >= 3 im Training (48 Tests),
Bestätigung t >= 2,4, Endtest t >= 2. Universum nur Kurs > 5 $ (Bot handelt meist < 5 $ -- nicht nachstellbar).
"""
import itertools
import sys
import time
from pathlib import Path

import numba
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from r107 import CACHE, PERIODS  # noqa: E402


@numba.njit(parallel=True, cache=True)
def sim(o, h, l, c, mi, start, n, rank, topn, cutoff, need_hod, min_stop, exit_mode):
    nd = len(start)
    out_sum = np.zeros(nd)
    out_cnt = np.zeros(nd, np.int64)
    for d in numba.prange(nd):
        if rank[d] >= topn:
            continue
        s, L = start[d], n[d]
        end = s + L
        if L < 30 or mi[s] != 0:
            continue
        trades = 0
        swing_low, swing_i = l[s], s
        pole_peak, in_flag, flag_n, flag_low, hod = 0.0, False, 0, 0.0, h[s]
        j = s + 1
        while j < end - 1 and trades < 3:
            if mi[j] > cutoff:
                break
            if not in_flag:
                if l[j] < swing_low:
                    swing_low, swing_i = l[j], j
                if c[j] >= swing_low * 1.03 and mi[j] - mi[swing_i] <= 15 and j > swing_i:
                    in_flag, pole_peak, flag_n, flag_low = True, h[j], 0, 1e30
            else:
                if h[j] > pole_peak and flag_n == 0:
                    pole_peak = h[j]                       # Stange läuft weiter
                elif flag_n >= 2 and c[j] > h[j - 1]:
                    ok = (not need_hod) or c[j] > hod
                    e = j + 1
                    if ok and e < end:
                        entry = o[e]
                        stop = min(flag_low, entry * (1.0 - min_stop))
                        sd = entry - stop
                        if sd > 0:
                            tp = entry + (2.0 if exit_mode == 0 else 3.0) * sd
                            ex, k = c[end - 1], end - 1
                            be = False
                            for k in range(e, end):
                                if k > e and o[k] <= stop:
                                    ex = o[k]
                                    break
                                if l[k] <= stop:
                                    ex = stop
                                    break
                                if exit_mode <= 1 and k > e and h[k] >= tp:
                                    ex = tp
                                    break
                                if exit_mode == 2 and not be and h[k] >= entry + sd:
                                    stop, be = entry, True
                            out_sum[d] += (ex - entry) / sd - 2.0 * (0.0001 * entry + 0.01) / sd
                            out_cnt[d] += 1
                            trades += 1
                            j = k + 1
                            swing_low, swing_i, in_flag = l[min(j, end - 1)], min(j, end - 1), False
                            hod = max(hod, h[k])
                            continue
                    in_flag = False
                    swing_low, swing_i = l[j], j
                else:
                    flag_n += 1
                    flag_low = min(flag_low, l[j])
                    if flag_low <= pole_peak - 0.5 * (pole_peak - swing_low) or flag_n > 5:
                        in_flag = False
                        swing_low, swing_i = l[j], j
            hod = max(hod, h[j])
            j += 1
    return out_sum, out_cnt


def main():
    t0 = time.time()
    z = np.load(CACHE)
    arrs = [z[k] for k in ("o", "h", "l", "c", "mi", "start", "n", "rank")]
    dates = z["date"]
    rows, res = [], {}
    for need_hod, cut, ms, em, top in itertools.product((False, True), (60, 330), (0.02, 0.04), (0, 1, 2), (5, 20)):
        s, k = sim(*arrs, top, cut, need_hod, ms, em)
        name = (f"{'nur über Tageshoch' if need_hod else 'jeder Ausbruch'}, bis {'10:30' if cut == 60 else '15:00'}, "
                f"Stop min {ms:.0%}, {['Ziel 2R', 'Ziel 3R', 'Einstand+Schluss'][em]}, Top{top}")
        per = {}
        for nm, (a, b) in PERIODS.items():
            m = (dates >= np.datetime64(a)) & (dates <= np.datetime64(b)) & (k > 0)
            daily = pd.Series(s[m]).groupby(dates[m]).sum()
            nt = int(k[m].sum())
            tt = float(daily.mean() / daily.std(ddof=1) * np.sqrt(len(daily))) if len(daily) > 2 else np.nan
            per[nm] = (nt, s[m].sum() / max(nt, 1), tt)
        res[name] = per
        rows.append(dict(name=name, hod=need_hod, n=per["Training"][0], avg=per["Training"][1], t=per["Training"][2],
                         conf=per["Bestätigung"][1], tc=per["Bestätigung"][2]))
    tr = pd.DataFrame(rows)
    pd.to_pickle(res, Path(__file__).with_name("r126_results.pkl"))
    print(f"48 Varianten ({time.time() - t0:.0f} s). Training: t >= 2: {(tr.t >= 2).sum()}, t >= 3: {(tr.t >= 3).sum()}, "
          f"Ø > 0: {(tr.avg > 0).sum()}")
    print("Median Ø R Training -> Bestätigung: jeder Ausbruch {:+.3f} -> {:+.3f} | nur über Tageshoch {:+.3f} -> {:+.3f}".format(
        tr[~tr.hod].avg.median(), tr[~tr.hod].conf.median(), tr[tr.hod].avg.median(), tr[tr.hod].conf.median()))
    for _, r in tr.sort_values("t", ascending=False).head(5).iterrows():
        passed = r.n >= 200 and r.avg > 0 and r.t >= 3 and r.conf > 0 and r.tc >= 2.4
        line = " | ".join(f"{nm[:5]} n {v[0]} Ø {v[1]:+.3f} R t {v[2]:+.2f}" for nm, v in res[r["name"]].items()
                          if nm != "Endtest" or passed)
        print(f"  {r['name']}: {line}")
    el = tr[(tr.n >= 200) & (tr.avg > 0) & (tr.t >= 3) & (tr.conf > 0) & (tr.tc >= 2.4)]
    print(f"Bestanden Training+Bestätigung: {len(el)} (Endtest nur für diese angezeigt)")


if __name__ == "__main__":
    main()

"""Runde 160: Steuerverlust-Umkehr -- Jahresverlierer Ende Dezember kaufen, Ende Januar verkaufen.

Vorab: PROTOCOL.md Runde 160. Aufruf aus dem Haupt-Repo: PYTHONPATH=<worktree> python <worktree>/research/scripts/r160.py
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from r153 import spy_daily, tstat
from r157 import panel_cv

COST_L, COST_S = 10e-4, 2e-4
A, B = "2017-01-01", "2026-08-31"


def pa_m(x):
    return float((1 + x).prod() ** (12 / len(x)) - 1)


def main():
    idx, univ = pd.read_pickle("data_cache/r152_universe.pkl")
    spy = spy_daily()
    days = spy.index
    years = range(2016, 2026)
    plan = {}
    for y in years:
        sel = days[days <= pd.Timestamp(y, 12, 15)][-1]
        dec = days[(days.year == y) & (days.month == 12)]
        jan = days[(days.year == y + 1) & (days.month == 1)]
        plan[y] = {"sel": sel, "entry": dec[-4], "exit": jan[-1], "mid": jan[jan.day <= 15][-1]}
    members = {y: set(univ.loc[univ["date"] == p["sel"], "symbol"]) for y, p in plan.items()}
    px = {s: d["c"] for s, d in panel_cv(set().union(*members.values())).items()}

    def losers(y, frac):
        p = plan[y]
        rows = []
        for s in members[y]:
            c = px.get(s)
            if c is None:
                continue
            prev = c[c.index.year < y]
            base = prev.iloc[-1] if len(prev) else c[c.index.year == y].iloc[0]
            at = c[c.index <= p["sel"]]
            if not len(at) or at.iloc[-1] < 5:
                continue
            rows.append((s, at.iloc[-1] / base - 1))
        r = pd.Series(dict(rows)).sort_values()
        return list(r.index[: int(round(len(members[y]) * frac))])

    def path(names, a, b):
        """Täglicher Wert eines gleichgewichteten Kauf-und-Halten-Korbs von Schluss a bis Schluss b."""
        win = days[(days >= a) & (days <= b)]
        rel = []
        for s in names:
            c = px[s].reindex(win).ffill()
            if pd.isna(c.iloc[0]):
                continue
            rel.append(c / c.iloc[0])
        return pd.concat(rel, axis=1).mean(axis=1)

    def strategy(frac, entry_key, exit_key):
        r = spy.copy()
        events = []
        for y in years:
            a, b = plan[y][entry_key], plan[y][exit_key]
            v = path(losers(y, frac), a, b)
            lr = v.pct_change().dropna()
            r.loc[lr.index] = lr
            r.loc[a] -= COST_S + COST_L
            r.loc[b] -= COST_L + COST_S
            spy_win = float((1 + spy[(spy.index > a) & (spy.index <= b)]).prod() - 1)
            events.append((y + 1, float(v.iloc[-1] - 1), spy_win))
        r = r[(r.index >= A) & (r.index <= B)]
        m = (1 + r).groupby(r.index.to_period("M")).prod() - 1
        s = spy[(spy.index >= A) & (spy.index <= B)]
        sm = (1 + s).groupby(s.index.to_period("M")).prod() - 1
        return m, sm, events

    def report(label, frac, ek, xk, binding):
        m, sm, ev = strategy(frac, ek, xk)
        ex = m - sm
        t = tstat(ex)
        h1 = m.index.year <= 2021
        e1, e2 = pa_m(m[h1]) - pa_m(sm[h1]), pa_m(m[~h1]) - pa_m(sm[~h1])
        ok = pa_m(m) > pa_m(sm) and t >= 2.0 and e1 > 0 and e2 > 0
        print(f"  {label}: {pa_m(m):+6.2%} p.a. vs SPY {pa_m(sm):+6.2%}, t {t:+.2f}, Hälften {e1:+.2%} / {e2:+.2%}"
              + (f" -> {'BESTANDEN' if ok else 'NICHT BESTANDEN'}" if binding else " (Info)"))
        return ev

    print("Runde 160 -- Steuerverlust-Umkehr (Top 500, Jahresverlierer)\n")
    print("Hauptkriterium (schwächstes Zehntel, viertletzter Dezember-Tag bis Ende Januar, sonst SPY):")
    ev = report("Zehntel", 0.10, "entry", "exit", True)
    print("  je Ereignis (Januar-Jahr: Verlierer-Korb brutto / SPY gleiches Fenster):")
    print("   " + "; ".join(f"{y}: {a:+.1%}/{b:+.1%}" for y, a, b in ev))
    print(f"   Ø Differenz {np.mean([a - b for _, a, b in ev]):+.2%}, positiv in {sum(a > b for _, a, b in ev)} von {len(ev)}")
    print("\nInfo (nicht gewertet):")
    report("Zwanzigstel", 0.05, "entry", "exit", False)
    report("Zehntel, Einstieg am Auswahltag", 0.10, "sel", "exit", False)
    report("Zehntel, Ausstieg Mitte Januar", 0.10, "entry", "mid", False)


if __name__ == "__main__":
    main()

"""Runde 168: Prämie vor Quartalszahlen (8-K Item 2.02, Top 500) -- Vorab: PROTOCOL.md Runde 168.

Aufruf aus dem Haupt-Repo: PYTHONPATH=<worktree> python <worktree>/research/scripts/r168.py
"""
from __future__ import annotations

import json
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

from r153 import spy_daily, tstat
from r157 import panel_cv

E = Path("data_cache/edgar")
COST = 10e-4
A, B = "2016-07-01", "2026-08-31"


def cik_map() -> dict[str, set]:
    f = Path("data_cache/r168_company_tickers.json")
    if not f.exists():
        f.write_bytes(urllib.request.urlopen(urllib.request.Request(
            "https://www.sec.gov/files/company_tickers.json", headers={"User-Agent": "tradingbot-research-script"}),
            timeout=60).read())
    out: dict[str, set] = {}
    for v in json.loads(f.read_text()).values():
        out.setdefault(str(v["cik_str"]).zfill(10), set()).add(v["ticker"].upper())
    ins = pd.read_pickle(E / "insider_purchases.pkl")
    for s, c in ins[["symbol", "issuer_cik"]].itertuples(index=False):
        out.setdefault(str(c).zfill(10), set()).add(s)
    return out


def pa(r):
    return float((1 + r).prod() ** (252 / len(r)) - 1)


def main():
    days, univ = pd.read_pickle("data_cache/r152_universe.pkl")
    T = len(days)
    syms = sorted(set(univ["symbol"]))
    col = {s: j for j, s in enumerate(syms)}
    px = panel_cv(set(syms))
    C = np.full((T, len(syms)), np.nan, np.float32)
    for s, d in px.items():
        C[:, col[s]] = d["c"].reindex(days).to_numpy(np.float32)
    C = pd.DataFrame(C).ffill().to_numpy()
    R = np.zeros_like(C)
    R[1:] = C[1:] / C[:-1] - 1
    R[~np.isfinite(R)] = 0.0
    inU = np.zeros((T, len(syms)), bool)
    di = {d: i for i, d in enumerate(days)}
    for d, s in univ.itertuples(index=False):
        inU[di[d], col[s]] = True
    ew = np.where(inU, R, 0).sum(1) / np.maximum(inU.sum(1), 1)
    cmap = cik_map()
    events: dict[int, list] = {}
    for f in (E / "8k").glob("*.pkl"):
        js = [col[s] for s in cmap.get(f.stem, ()) if s in col]
        acc = pd.read_pickle(f)["accepted"]
        if not js or not len(acc):
            continue
        acc = pd.DatetimeIndex(acc)
        d = pd.DatetimeIndex(acc.tz_localize(None).normalize())
        after = np.asarray(acc.hour * 60 + acc.minute) >= 570
        pos = np.where(after, days.searchsorted(d, side="right"), days.searchsorted(d, side="left"))
        for j in js:
            events.setdefault(j, []).extend(int(p) for p in pos if 1 <= p < T)

    def trades(lead: int, pre_only: bool):
        out = []
        for j, ev in events.items():
            ev = sorted(set(ev))
            for k, e in enumerate(ev):
                exp = e + 63
                entry = exp - lead
                nxt = ev[k + 1] if k + 1 < len(ev) else None
                if entry >= T or (nxt is not None and nxt <= entry):
                    continue
                if not inU[entry, j] or not C[entry, j] > 5:
                    continue
                if nxt is not None and nxt <= exp + 10:
                    exit_ = nxt - 1 if pre_only else nxt
                else:
                    exit_ = exp + 10
                exit_ = min(exit_, T - 1)
                if exit_ > entry:
                    out.append((j, entry, exit_))
        return out

    spy = spy_daily().reindex(days).fillna(0.0)

    def portfolio(tr):
        s = np.zeros(T); n = np.zeros(T)
        exc = []
        for j, a, b in tr:
            r = R[a + 1:b + 1, j].copy()
            r[0] -= COST
            r[-1] -= COST
            s[a + 1:b + 1] += r
            n[a + 1:b + 1] += 1
            exc.append(float(np.prod(1 + R[a + 1:b + 1, j]) - np.prod(1 + ew[a + 1:b + 1])))
        port = np.where(n >= 10, s / np.maximum(n, 1), spy.to_numpy())
        return pd.Series(port, index=days), pd.Series(n, index=days), np.array(exc)

    def report(label, lead, pre_only, binding):
        tr = trades(lead, pre_only)
        p, n, exc = portfolio(tr)
        p, s = p[A:B], spy[A:B]
        ex = (1 + p).groupby(p.index.to_period("M")).prod() - (1 + s).groupby(s.index.to_period("M")).prod()
        t = tstat(ex)
        h1 = p.index.year <= 2020
        e1, e2 = pa(p[h1]) - pa(s[h1]), pa(p[~h1]) - pa(s[~h1])
        ok = pa(p) > pa(s) and t >= 2.0 and e1 > 0 and e2 > 0
        print(f"  {label}: {pa(p):+6.1%} p.a. vs SPY {pa(s):+6.1%}, t {t:+.2f}, Hälften {e1:+6.1%} / {e2:+6.1%}, "
              f"Trades {len(tr):,}, Ø offen {n[A:B][n[A:B] >= 10].mean():.0f}, Tage in Aktien {(n[A:B] >= 10).mean():.0%}, "
              f"Ø Überrendite je Trade ggü. Universum {exc.mean():+.2%} (t {tstat(pd.Series(exc)):+.1f})"
              + (f" -> {'BESTANDEN' if ok else 'NICHT BESTANDEN'}" if binding else " (Info)"))

    print(f"Runde 168 -- Prämie vor Quartalszahlen, {len(events)} Kürzel mit 8-K-2.02-Ereignissen im Top-500-Universum\n")
    print("Hauptkriterium (Kauf 5 Tage vor erwartetem Termin, Verkauf Schluss Ereignistag):")
    report("5 Tage, mit Reaktion", 5, False, True)
    print("\nInfo (nicht gewertet):")
    report("5 Tage, nur bis Vortag", 5, True, False)
    report("10 Tage, mit Reaktion", 10, False, False)


if __name__ == "__main__":
    main()

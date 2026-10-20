"""Runde 157: Dividenden-Erstausschüttung kaufen, 12 Monate halten -- Vorab: PROTOCOL.md Runde 157.

Aufruf aus dem Haupt-Repo: PYTHONPATH=<worktree> python <worktree>/research/scripts/r157.py
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

import r156
from r153 import spy_daily, tstat

r156.START, r156.END = pd.Period("2018-02", "M"), pd.Period("2026-08", "M")
HALF = pd.Period("2021-12", "M")


def panel_cv(symbols: set[str]) -> dict[str, pd.DataFrame]:
    out: dict[str, list] = {}
    for p in sorted(Path(r156.U).glob("batch_*.pkl")):
        x = pd.read_pickle(p)
        if not len(x):
            continue
        x = x[x.index.get_level_values("symbol").isin(symbols)]
        if not len(x):
            continue
        d = pd.to_datetime(x.index.get_level_values("timestamp").tz_convert("America/New_York").date)
        df = pd.DataFrame({"s": x.index.get_level_values("symbol"), "d": d, "c": x["close"].to_numpy(),
                           "v": x["volume"].to_numpy()})
        for s, g in df.groupby("s"):
            out.setdefault(s, []).append(g.set_index("d")[["c", "v"]])
    return {s: pd.concat(v).sort_index().loc[lambda z: ~z.index.duplicated()] for s, v in out.items()}


def events(min_px: float, min_dv: float, px: dict, first_any: pd.Series, first_reg: pd.Series) -> pd.DataFrame:
    rows = []
    for s, ex in first_reg.items():
        if ex < pd.Timestamp("2018-01-01") or first_any[s] < ex or s not in px:
            continue
        df = px[s]
        if df.index[0] > ex - pd.Timedelta(days=730):
            continue
        before = df[df.index < ex].tail(20)
        if len(before) < 15 or float((before["c"] * before["v"]).mean()) < min_dv:
            continue
        lm = ex.to_period("M")
        month = df[df.index.to_period("M") == lm]
        if not len(month) or float(month["c"].iloc[-1]) < min_px:
            continue
        rows.append({"sym": s, "ex": ex.date(), "list_month": lm})
    return pd.DataFrame(rows)


def pa(m):
    return float((1 + m).prod() ** (12 / len(m)) - 1)


def main():
    dv = pd.read_pickle("data_cache/dividends.pkl")
    dv["ex"] = pd.to_datetime(dv["ex_date"])
    first_any = dv.groupby("symbol")["ex"].min()
    reg = dv[~dv["special"].astype(bool) & ~dv["foreign"].astype(bool)]
    first_reg = reg.groupby("symbol")["ex"].min()
    cand = set(first_reg[first_reg >= "2018-01-01"].index)
    px = panel_cv(cand)
    divs = r156.dividends(set(px))
    rets = {s: r156.monthly_total(px[s]["c"], divs.get(s)) for s in px}
    spy = spy_daily()
    spy_m = (1 + spy).groupby(spy.index.to_period("M")).prod() - 1

    def report(label, ev, hold, binding):
        p, n = r156.portfolio(ev, rets, hold, False)
        s = spy_m.reindex(p.index).fillna(0.0)
        ex = p - s
        t = tstat(ex)
        h1, h2 = p.index <= HALF, p.index > HALF
        e1, e2 = pa(p[h1]) - pa(s[h1]), pa(p[h2]) - pa(s[h2])
        eq = (1 + p).cumprod()
        ok = pa(p) > pa(s) and t >= 2.0 and e1 > 0 and e2 > 0
        print(f"  {label}: {pa(p):+6.1%} p.a. vs SPY {pa(s):+6.1%}, t {t:+.2f}, Hälften {e1:+6.1%} / {e2:+6.1%}, "
              f"Max-DD {float((eq / eq.cummax() - 1).min()):.1%}, Ø {n[n > 0].mean():.0f} Titel, Cash-Monate "
              f"{int((n == 0).sum())}" + (f" -> {'BESTANDEN' if ok else 'NICHT BESTANDEN'}" if binding else " (Info)"))

    ev = events(5.0, 1e6, px, first_any, first_reg)
    print(f"Runde 157 -- Dividenden-Erstausschüttungen: {len(ev)} Fälle (Kandidaten-Kürzel {len(cand)})")
    print("Fälle je Jahr:", ev.groupby(pd.to_datetime(ev["ex"]).dt.year).size().to_dict())
    print("\nHauptkriterium (Einstieg Monatsende des Ex-Tags, 12 Monate, 10 bp je Seite):")
    report("12 Monate", ev, 12, True)
    print("\nInfo (nicht gewertet):")
    report("6 Monate", ev, 6, False)
    report("24 Monate", ev, 24, False)
    big = events(10.0, 10e6, px, first_any, first_reg)
    report(f"12 Monate, Kurs >= 10 $ und Umsatz >= 10 Mio. $ ({len(big)} Fälle)", big, 12, False)


if __name__ == "__main__":
    main()

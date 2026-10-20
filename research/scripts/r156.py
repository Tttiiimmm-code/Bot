"""Runde 156: Spin-offs (Formular 10-12B) kaufen und 24 Monate halten -- Vorab: PROTOCOL.md Runde 156.

Braucht data_cache/spinoff/candidates.csv (r156_fetch.py). Aufruf aus dem Haupt-Repo:
PYTHONPATH=<worktree> python <worktree>/research/scripts/r156.py
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from r153 import spy_daily, tstat

U = "data_cache/universe/daily"
CAND = "data_cache/spinoff/candidates.csv"
START, END = pd.Period("2016-01", "M"), pd.Period("2026-08", "M")
HALF = pd.Period("2020-12", "M")
COST = 10e-4                                      # je Seite auf den Umschlag
MIN_N, MIN_PX, T_PASS = 5, 5.0, 2.0


def candidates() -> pd.DataFrame:
    c = pd.read_csv(CAND, dtype=str).fillna("")
    rows = []
    for r in c.itertuples():
        ticks = []
        for field in (r.sec_ticker, r.sub_tickers, r.doc_prefix):
            ticks += [t.strip().replace(".", "-") for t in field.split(",") if t.strip()]
        rows.append({"cik": r.cik, "name": r.name, "filed": pd.Timestamp(r.first_10_12b),
                     "ticks": list(dict.fromkeys(ticks))})
    return pd.DataFrame(rows)


def panel(symbols: set[str]) -> dict[str, pd.Series]:
    from pathlib import Path
    out: dict[str, list] = {}
    for p in sorted(Path(U).glob("batch_*.pkl")):
        x = pd.read_pickle(p)
        if not len(x):
            continue
        sym = x.index.get_level_values("symbol")
        x = x[sym.isin(symbols)]
        if not len(x):
            continue
        d = pd.to_datetime(x.index.get_level_values("timestamp").tz_convert("America/New_York").date)
        df = pd.DataFrame({"s": x.index.get_level_values("symbol"), "d": d, "c": x["close"].to_numpy()})
        for s, g in df.groupby("s"):
            out.setdefault(s, []).append(g.set_index("d")["c"])
    return {s: pd.concat(v).sort_index().loc[lambda z: ~z.index.duplicated()] for s, v in out.items()}


def dividends(symbols: set[str]) -> dict[str, pd.Series]:
    dv = pd.read_pickle("data_cache/dividends.pkl")
    dv = dv[dv["symbol"].isin(symbols) & ~dv["foreign"].astype(bool)]
    sp = pd.read_pickle("data_cache/splits.pkl")
    sp = sp[sp["symbol"].isin(symbols)]
    out = {}
    for s, g in dv.groupby("symbol"):
        ex = pd.to_datetime(g["ex_date"])
        f = np.ones(len(g))
        for q in sp[sp["symbol"] == s].itertuples():               # Splits nach dem Ex-Tag -> Betrag umrechnen
            f = np.where(ex.to_numpy() < np.datetime64(q.ex_date), f * q.old_rate / q.new_rate, f)
        out[s] = pd.Series(g["rate"].to_numpy(float) * f, index=ex).groupby(level=0).sum()
    return out


def monthly_total(close: pd.Series, div: pd.Series | None) -> pd.Series:
    r = close.pct_change()
    if div is not None and len(div):
        d = div.reindex(close.index).fillna(0.0)
        r = (close + d) / close.shift(1) - 1
    r = r.dropna()
    return (1 + r).groupby(r.index.to_period("M")).prod() - 1


def portfolio(events: pd.DataFrame, rets: dict[str, pd.Series], hold: int, first_close: bool) -> tuple[pd.Series, pd.Series]:
    months = pd.period_range(START, END, freq="M")
    out, n_held = [], []
    w_prev: dict[str, float] = {}
    for m in months:
        names = []
        for e in events.itertuples():
            first_m = e.list_month if first_close else e.list_month + 1
            if first_m <= m <= e.list_month + hold and m in rets[e.sym].index:
                names.append(e.sym)
        names = list(dict.fromkeys(names))
        if len(names) < MIN_N:
            cost = COST * sum(w_prev.values())
            out.append(-cost); n_held.append(0); w_prev = {}
            continue
        target = {s: 1 / len(names) for s in names}
        turn = sum(abs(target.get(s, 0) - w_prev.get(s, 0)) for s in set(target) | set(w_prev))
        r = {s: rets[s].loc[m] for s in names}
        rp = sum(target[s] * r[s] for s in names)
        out.append(rp - COST * turn)
        n_held.append(len(names))
        w_prev = {s: target[s] * (1 + r[s]) / (1 + rp) for s in names}
    return pd.Series(out, index=months), pd.Series(n_held, index=months)


def pa(m: pd.Series) -> float:
    return float((1 + m).prod() ** (12 / len(m)) - 1)


def main(window: int = 365, info_only: bool = False):
    c = candidates()
    syms = {t for ts in c["ticks"] for t in ts}
    px = panel(syms)
    dv = dividends(set(px))
    events, unmatched = [], 0
    for r in c.itertuples():
        hit = None
        for t in r.ticks:
            s = px.get(t)
            if s is None or not len(s):
                continue
            first = s.index[0]
            if first > pd.Timestamp("2016-01-05") and r.filed <= first <= r.filed + pd.Timedelta(days=window):
                hit = (t, first, s)
                break
        if hit is None:
            unmatched += 1
            continue
        t, first, s = hit
        lm = first.to_period("M")
        entry_px = s[s.index.to_period("M") == lm].iloc[-1]
        if entry_px < MIN_PX:
            continue
        events.append({"sym": t, "name": r.name, "filed": r.filed.date(), "first": first.date(), "list_month": lm})
    ev = pd.DataFrame(events).drop_duplicates("sym")
    rets = {s: monthly_total(px[s], dv.get(s)) for s in ev["sym"]}
    spy = spy_daily()
    spy_m = (1 + spy).groupby(spy.index.to_period("M")).prod() - 1
    print(f"Runde 156 -- Spin-offs: {len(c)} Firmen mit 10-12B, {len(ev)} Spin-offs im Panel (>= {MIN_PX:.0f} $), "
          f"{unmatched} ohne passendes Kürzel/Notiz (nicht handelbar, kein Kürzel oder nie gelistet)\n")
    print("Erstnotizen je Jahr:", ev.groupby(pd.to_datetime(ev["first"]).dt.year).size().to_dict())

    def report(label, hold, first_close, binding):
        p, n = portfolio(ev, rets, hold, first_close)
        s = spy_m.reindex(p.index).fillna(0.0)
        ex = p - s
        t = tstat(ex)
        h1, h2 = (p.index <= HALF), (p.index > HALF)
        e1, e2 = pa(p[h1]) - pa(s[h1]), pa(p[h2]) - pa(s[h2])
        eq = (1 + p).cumprod()
        ok = pa(p) > pa(s) and t >= T_PASS and e1 > 0 and e2 > 0
        print(f"  {label}: {pa(p):+6.1%} p.a. vs SPY {pa(s):+6.1%}, t {t:+.2f}, Hälften {e1:+6.1%} / {e2:+6.1%}, "
              f"Max-DD {float((eq / eq.cummax() - 1).min()):.1%}, Ø {n[n > 0].mean():.0f} Titel, Cash-Monate "
              f"{int((n == 0).sum())}" + (f" -> {'BESTANDEN' if ok else 'NICHT BESTANDEN'}" if binding else " (Info)"))

    if info_only:
        report(f"24 Monate, Fenster {window} Tage", 24, False, False)
        return
    print("\nHauptkriterium (Einstieg Monatsende der Erstnotiz, 24 Monate, 10 bp je Seite):")
    report("24 Monate", 24, False, True)
    print("\nInfo (nicht gewertet):")
    report("12 Monate", 12, False, False)
    report("36 Monate", 36, False, False)
    report("24 Monate, Einstieg erster Schluss", 24, True, False)
    first_m = pd.Series({e.sym: rets[e.sym].get(e.list_month, np.nan) for e in ev.itertuples()}).dropna()
    print(f"  Rendite im Monat der Erstnotiz (ab erstem Schluss): Ø {first_m.mean():+.2%}, Median {first_m.median():+.2%}")


if __name__ == "__main__":
    main()
    print("\nNACHTRÄGLICH (nur Info): Erstnotiz bis 1.100 Tage nach der ersten 10-12B-Meldung")
    main(window=1100, info_only=True)

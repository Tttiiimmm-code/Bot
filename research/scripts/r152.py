"""Runde 152: dynamischer Kauf letzte Stunde x Verkauf erste Stunde -- Vorab: PROTOCOL.md Runde 152.

Braucht data_cache/r152/*.pkl (r152_fetch.py). Aufruf aus dem Haupt-Repo:
PYTHONPATH=<worktree> python <worktree>/research/scripts/r152.py
"""
from __future__ import annotations

import itertools
from pathlib import Path

import numpy as np
import pandas as pd

U = Path("data_cache/universe/daily")
BARS = Path("data_cache/r152")
SPY = Path("data_cache/yahoo_r149/SPY_full.pkl")
START, END = "2016-01-01", "2026-09-30"
SEC = 0.28e-4
T_B = 2.54                                           # Bonferroni 9, einseitig
MIN_TRADES = 5


def tstat(x) -> float:
    x = pd.Series(x).dropna()
    return float(x.mean() / x.std(ddof=1) * np.sqrt(len(x))) if len(x) > 2 and x.std() > 0 else float("nan")


def daily():
    """Offizieller Schluss/Eröffnung je (Symbol, Tag), nächster Handelstag, Top-500-Universum (Info bis t-1)."""
    rows = []
    for p in sorted(U.glob("batch_*.pkl")):
        x = pd.read_pickle(p)
        if not len(x):
            continue
        d = pd.to_datetime(x.index.get_level_values("timestamp").tz_convert("America/New_York").date)
        rows.append(pd.DataFrame({"symbol": x.index.get_level_values("symbol"), "date": d, "open": x["open"].to_numpy(),
                                  "close": x["close"].to_numpy(), "volume": x["volume"].to_numpy()}))
    df = pd.concat(rows).drop_duplicates(["date", "symbol"])
    C = df.pivot(index="date", columns="symbol", values="close").sort_index()
    V = df.pivot(index="date", columns="symbol", values="volume").reindex_like(C)
    O = df.pivot(index="date", columns="symbol", values="open").reindex_like(C)
    rank = ((C * V).rolling(20, min_periods=15).mean().where(C > 5)).rank(axis=1, ascending=False).shift(1)
    univ = (rank <= 500).stack()
    univ = univ[univ].index.to_frame(index=False, name=["date", "symbol"])
    dates = C.index
    nxt = pd.Series(list(dates[1:]) + [pd.NaT], index=dates)
    close = C.stack().rename("close_t").reset_index().rename(columns={"level_1": "symbol"})
    open_ = O.stack().rename("open_next").reset_index().rename(columns={"level_1": "symbol"})
    return univ, nxt, close, open_


def entries_exits(m: pd.DataFrame):
    m = m.sort_values(["symbol", "date", "hh", "mm"]).reset_index(drop=True)
    m["date"] = pd.to_datetime(m["date"])
    g = m.groupby(["symbol", "date"], sort=False)
    for c in ("low", "high", "close", "cum_low"):
        m["prev_" + c] = g[c].shift(1)
    t = m["hh"].astype(int) * 60 + m["mm"].astype(int)
    window = (t >= 900) & (t <= 945)                                   # Balken 15:00..15:45 (schließen 15:05..15:50)
    rng = m["cum_high"] - m["cum_low"]
    pos = np.where(rng > 0, (m["close"] - m["cum_low"]) / rng, np.nan)
    k1 = m[(t == 945) & (pos <= 0.10)][["symbol", "date"]].assign(k="K1", entry=np.nan)
    c2 = window & (m["prev_low"] <= m["prev_cum_low"] * 1.0025) & (m["close"] > m["prev_high"])
    c3 = window & (m["close"] <= m["cum_vwap"] * 0.985) & (m["close"] > m["prev_close"])
    k2 = m[c2].groupby(["symbol", "date"], as_index=False).first()[["symbol", "date", "close"]]
    k3 = m[c3].groupby(["symbol", "date"], as_index=False).first()[["symbol", "date", "close"]]
    ent = pd.concat([k1, k2.rename(columns={"close": "entry"}).assign(k="K2"),
                     k3.rename(columns={"close": "entry"}).assign(k="K3")], ignore_index=True)
    # Ausstiege am Tag selbst (werden mit den Einstiegen des Vortags verbunden)
    first = m[t == 570].set_index(["symbol", "date"])["low"].rename("l1")
    morning = m[(t >= 575) & (t <= 625)].join(first, on=["symbol", "date"])
    last = morning[morning["mm"].astype(int).eq(25) & morning["hh"].astype(int).eq(10)].set_index(["symbol", "date"])["close"]
    stop = morning[morning["close"] < morning["l1"]].groupby(["symbol", "date"])["close"].first()
    ex = pd.DataFrame({"v2": last})
    ex["v3"] = stop.reindex(ex.index).fillna(ex["v2"])
    return ent, ex.reset_index()


def main():
    univ, nxt, close, open_ = daily()
    ents, exs = [], []
    for p in sorted(BARS.glob("*.pkl")):
        m = pd.read_pickle(p)
        if len(m):
            e, x = entries_exits(m)
            ents.append(e)
            exs.append(x)
    ent = pd.concat(ents).drop_duplicates(["symbol", "date", "k"])
    ex = pd.concat(exs).drop_duplicates(["symbol", "date"])
    ent = ent.merge(univ, on=["date", "symbol"])                       # nur Top-500 des Tages
    ent = ent[(ent["date"] >= START) & (ent["date"] <= END)]
    ent["next"] = ent["date"].map(nxt)
    ent = ent.merge(close, on=["date", "symbol"], how="left")
    ent["entry"] = ent["entry"].fillna(ent["close_t"]).where(ent["k"] != "K1", ent["close_t"])
    ent = ent.merge(open_.rename(columns={"date": "next"}), on=["next", "symbol"], how="left")
    ent = ent.merge(ex.rename(columns={"date": "next"}), on=["next", "symbol"], how="left")
    print(f"Runde 152 -- {len(ent)} Einstiegssignale (K1 {int((ent['k'] == 'K1').sum())}, K2 {int((ent['k'] == 'K2').sum())}, "
          f"K3 {int((ent['k'] == 'K3').sum())}), Monate mit Balken: {len(ents)}\n")
    spy = pd.read_pickle(SPY)
    spy.index = pd.DatetimeIndex([pd.Timestamp(d) for d in spy.index])
    days = pd.DatetimeIndex(sorted(set(univ["date"]))).to_series()
    days = days[(days >= START) & (days <= END)].index
    spy_d = spy["adjclose"].pct_change().reindex(days).fillna(0)

    def pa(r):
        return float((1 + r).prod() ** (252 / len(r)) - 1)

    def monthly(r):
        return (1 + r).groupby(r.index.to_period("M")).prod() - 1

    def run(k, v, cont_cost):
        x = ent[ent["k"] == k].copy()
        exit_px = x["open_next"] if v == "V1" else x[v.lower()]
        buy_cost = 0.0 if k == "K1" else cont_cost
        sell_cost = SEC if v == "V1" else cont_cost + SEC
        x["gross"] = exit_px / x["entry"] - 1
        missing = int(x["gross"].isna().sum())
        x = x.dropna(subset=["gross"])
        x["gross"] = x["gross"].clip(-0.9, 5)
        x["net"] = x["gross"] - buy_cost - sell_cost
        by = x.groupby("date")["net"].agg(["mean", "size"])
        r = pd.Series(np.where(by["size"] >= MIN_TRADES, by["mean"], 0.0), index=by.index).reindex(days).fillna(0.0)
        return r, x, missing

    print(f"SPY halten {START[:4]}-{END[:7]}: {pa(spy_d):+.1%} p.a.\n")
    print("Hauptkriterium (laufender Handel 3 bp je Seite; bestanden: > SPY, t >= 2,54, beide Hälften > 0)")
    for k, v in itertools.product(("K1", "K2", "K3"), ("V1", "V2", "V3")):
        r, x, missing = run(k, v, 3e-4)
        t = tstat(monthly(r) - monthly(spy_d))
        h1 = pa(r[r.index < "2021-01-01"]) - pa(spy_d[spy_d.index < "2021-01-01"])
        h2 = pa(r[r.index >= "2021-01-01"]) - pa(spy_d[spy_d.index >= "2021-01-01"])
        passed = pa(r) > pa(spy_d) and t >= T_B and h1 > 0 and h2 > 0
        n_night = x.groupby("date").size()
        info = ", ".join(f"{c * 1e4:.0f} bp {pa(run(k, v, c)[0]):+6.1%}" for c in (1e-4, 5e-4))
        print(f"  {k} x {v}: {pa(r):+7.1%} p.a., t ggü. SPY {t:+5.2f}, Hälften {h1:+6.1%} / {h2:+6.1%} | "
              f"brutto Ø {x['gross'].mean() * 1e4:+6.1f} bp je Trade, Treffer {(x['gross'] > 0).mean():.0%}, "
              f"Ø {n_night.mean():5.1f} Käufe/Nacht, Nächte investiert {(n_night.reindex(days).fillna(0) >= MIN_TRADES).mean():.0%}, "
              f"ohne Ausstiegskurs {missing} [{info}] -> {'BESTANDEN' if passed else 'nicht bestanden'}")
    r, x, _ = run("K1", "V1", 0.0)
    print(f"\nInfo: K1 x V1 brutto Ø {x['gross'].mean() * 1e4:+.2f} bp je Trade (Signal 15:50 statt Schlusskurs; "
          f"Runde 151 IBS <= 0,10 Top 500 mit Schlusskurs-Signal brutto Ø +8,52 bp je Nacht)")


if __name__ == "__main__":
    main()

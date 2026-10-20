"""Runde 164: "Dogs of the Dow" -- Vorab: PROTOCOL.md Runde 164.

Aufruf aus dem Haupt-Repo: PYTHONPATH=<worktree> python <worktree>/research/scripts/r164.py
"""
from __future__ import annotations

import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from r153 import spy_daily, tstat

CACHE = Path("data_cache/r164")
COST = 5e-4
BASE = "MMM GE NKE AXP GS PFE AAPL HD PG BA INTC TRV CAT IBM UNH CVX JNJ UTX CSCO JPM VZ KO MCD V DD MRK WMT XOM MSFT DIS"
CHANGES = [("2017-09-01", {"DD": "DWDP"}), ("2018-06-26", {"GE": "WBA"}), ("2019-04-02", {"DWDP": "DOW"}),
           ("2020-04-06", {"UTX": "RTX"}), ("2020-08-31", {"XOM": "AMGN", "PFE": "HON", "RTX": "CRM"}),
           ("2024-02-26", {"WBA": "AMZN"}), ("2024-11-08", {"DOW": "SHW", "INTC": "NVDA"}),
           ("2026-06-29", {"VZ": "GOOGL"})]                     # Wikipedia, Stände 2015-03-19 .. 2026-06-29
YAHOO = {"UTX": "RTX", "DWDP": "DD"}                          # Yahoo führt die Historie unter dem heutigen Kürzel


def members(day: pd.Timestamp) -> list[str]:
    m = BASE.split()
    for d, ch in CHANGES:
        if pd.Timestamp(d) <= day:
            m = [ch.get(s, s) for s in m]
    assert len(set(m)) == 30
    return m


def yahoo(sym: str) -> dict:
    CACHE.mkdir(parents=True, exist_ok=True)
    f = CACHE / f"{sym}.json"
    if not f.exists():
        p1 = int(datetime(2015, 1, 1, tzinfo=timezone.utc).timestamp())
        url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?period1={p1}&period2=1790000000&interval=1d"
               "&events=div")
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=60) as r:
            f.write_bytes(r.read())
    res = json.loads(f.read_text())["chart"]["result"][0]
    idx = pd.to_datetime(res["timestamp"], unit="s", utc=True).tz_convert("America/New_York").tz_localize(None).normalize()
    close = pd.Series(res["indicators"]["quote"][0]["close"], index=idx, dtype=float)
    adj = pd.Series(res["indicators"]["adjclose"][0]["adjclose"], index=idx, dtype=float)
    dv = res.get("events", {}).get("dividends", {})
    div = pd.Series({pd.Timestamp(int(v["date"]), unit="s").normalize(): float(v["amount"]) for v in dv.values()}, dtype=float)
    if not len(div):
        div = pd.Series(dtype=float, index=pd.DatetimeIndex([]))
    keep = ~idx.duplicated(keep="last")
    return {"close": close[keep].dropna(), "adj": adj[keep].dropna(), "div": div.sort_index()}


def alpaca_wba() -> dict:
    f = CACHE / "WBA_alpaca.pkl"
    if not f.exists():
        from alpaca.data.enums import Adjustment
        from alpaca.data.historical import StockHistoricalDataClient
        from alpaca.data.requests import StockBarsRequest
        from alpaca.data.timeframe import TimeFrame
        from dotenv import dotenv_values

        v = dotenv_values("copilot.env")
        dc = StockHistoricalDataClient(v["ALPACA_API_KEY"], v["ALPACA_SECRET_KEY"])
        df = dc.get_stock_bars(StockBarsRequest(symbol_or_symbols="WBA", timeframe=TimeFrame.Day,
                                                start=datetime(2016, 1, 1), end=datetime(2025, 12, 31),
                                                adjustment=Adjustment.SPLIT)).df
        df.to_pickle(f)
    df = pd.read_pickle(f)
    idx = pd.to_datetime(df.index.get_level_values("timestamp").tz_convert("America/New_York").date)
    close = pd.Series(df["close"].to_numpy(), index=idx)
    dv = pd.read_pickle("data_cache/dividends.pkl")
    dv = dv[dv["symbol"] == "WBA"]
    div = pd.Series(dv["rate"].to_numpy(float), index=pd.to_datetime(dv["ex_date"])).groupby(level=0).sum()
    tr = (close + div.reindex(close.index).fillna(0.0)) / close.shift(1)
    adj = tr.fillna(1.0).cumprod() * close.iloc[0]
    return {"close": close, "adj": adj, "div": div}


def pa_m(x):
    return float((1 + x).prod() ** (12 / len(x)) - 1)


def main():
    syms = sorted({s for d in ["2015-12-31"] + [c[0] for c in CHANGES] for s in members(pd.Timestamp(d))})
    data = {s: (alpaca_wba() if s == "WBA" else yahoo(YAHOO.get(s, s))) for s in syms}
    spy = spy_daily()
    days = spy.index
    dia = yahoo("DIA")["adj"]

    def dogs(y: int, rule: str) -> list[str]:
        d = days[days.year == y][-1]
        rows = []
        for s in members(d):
            x = data[s]
            c = x["close"][x["close"].index <= d]
            if not len(c):
                continue
            dv = x["div"][(x["div"].index > d - pd.Timedelta(days=365)) & (x["div"].index <= d)].sum()
            rows.append((s, dv / c.iloc[-1], c.iloc[-1]))
        t = pd.DataFrame(rows, columns=["s", "y", "px"]).sort_values("y", ascending=False)
        top = t.head(10)
        if rule == "small":
            top = top.sort_values("px").head(5)
        elif rule == "top5":
            top = t.head(5)
        return list(top["s"])

    def run(rule: str):
        months, out, w_prev, picks = [], [], {}, {}
        for y in range(2016, 2026):
            a = days[days.year == y][-1]
            b = days[days.year == y + 1][-1] if y < 2025 else days[days <= "2026-08-31"][-1]
            names = dogs(y, rule)
            picks[y + 1] = names
            win = days[(days >= a) & (days <= b)]
            rel = pd.concat([data[s]["adj"].reindex(win).ffill() / data[s]["adj"].reindex(win).ffill().iloc[0]
                             for s in names], axis=1)
            v = rel.mean(axis=1)
            target = {s: 1 / len(names) for s in names}
            turn = sum(abs(target.get(s, 0) - w_prev.get(s, 0)) for s in set(target) | set(w_prev))
            first = v[v.index.to_period("M") > a.to_period("M")]        # Monate nach dem Einstiegsmonat
            mm = first.groupby(first.index.to_period("M")).last()
            rr = mm / pd.concat([pd.Series([v.iloc[0]]), mm.iloc[:-1]]).to_numpy() - 1
            rr.iloc[0] -= COST * turn
            months.append(rr)
            last = rel.iloc[-1]
            w_prev = {s: float(last[i]) / float(last.sum()) for i, s in enumerate(names)}
        return pd.concat(months), picks

    sm = (1 + spy).groupby(spy.index.to_period("M")).prod() - 1
    dm = dia.groupby(dia.index.to_period("M")).last().pct_change()
    print("Runde 164 -- Dogs of the Dow (Yahoo, WBA aus Alpaca)\n")

    def report(label, rule, binding):
        r, picks = run(rule)
        r = r[(r.index >= pd.Period("2017-01", "M")) & (r.index <= pd.Period("2026-08", "M"))]
        s = sm.reindex(r.index).fillna(0.0)
        t = tstat(r - s)
        h1 = r.index.year <= 2021
        e1, e2 = pa_m(r[h1]) - pa_m(s[h1]), pa_m(r[~h1]) - pa_m(s[~h1])
        eq = (1 + r).cumprod()
        ok = pa_m(r) > pa_m(s) and t >= 2.0 and e1 > 0 and e2 > 0
        d_ = dm.reindex(r.index).fillna(0.0)
        print(f"  {label}: {pa_m(r):+6.1%} p.a. vs SPY {pa_m(s):+6.1%} (DIA {pa_m(d_):+6.1%}), t {t:+.2f}, Hälften "
              f"{e1:+6.1%} / {e2:+6.1%}, Max-DD (Monat) {float((eq / eq.cummax() - 1).min()):.1%}"
              + (f" -> {'BESTANDEN' if ok else 'NICHT BESTANDEN'}" if binding else " (Info)"))
        return picks

    print("Hauptkriterium (10 höchste Dividendenrenditen, jährlich, 5 bp je Seite):")
    picks = report("Dogs 10", "dogs", True)
    for y, n in picks.items():
        print(f"    {y}: {' '.join(n)}")
    print("\nInfo (nicht gewertet):")
    report("Small Dogs (5 billigste der 10)", "small", False)
    report("Top 5 nach Rendite", "top5", False)


if __name__ == "__main__":
    main()

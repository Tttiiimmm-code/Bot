"""Runde 87: Merger-Arbitrage -- Zielaktie nach SC TO-T kaufen, bis Delisting/120 Tage halten."""
import json
import re
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

t = pd.read_pickle("data_cache/tender/sc_to_t.pkl")
ins = pd.read_pickle("data_cache/edgar/insider_purchases.pkl").sort_values("filing_date")
cik2sym = {}
cur = json.loads(urllib.request.urlopen(urllib.request.Request("https://www.sec.gov/files/company_tickers.json",
                                                               headers={"User-Agent": "tradingbot-research-script"})).read())
for v in cur.values():
    cik2sym.setdefault(str(v["cik_str"]).zfill(10), v["ticker"].upper())
for sym, cik in ins[["symbol", "issuer_cik"]].itertuples(index=False):
    cik2sym[str(cik).zfill(10)] = sym  # historisches Kürzel hat Vorrang (auch delistete Firmen)
ev = []
for _, r in t.iterrows():
    cik = r["ciks"][0]
    m = re.search(r"\(([A-Z.\-]{1,6})\)\s+\(CIK", r["names"][0])
    sym = cik2sym.get(cik) or (m.group(1) if m else None)
    ev.append((pd.Timestamp(r["date"]), cik, sym))
ev = pd.DataFrame(ev, columns=["date", "cik", "sym"])
print("Angebote", len(ev), "mit Ticker", ev["sym"].notna().sum())
syms = set(ev["sym"].dropna()) | {"SPY"}
closes = []
for p in sorted(Path("data_cache/universe/daily").glob("batch_*.pkl")):
    d = pd.read_pickle(p)
    if d.empty:
        continue
    d = d[d.index.get_level_values(0).isin(syms)]
    if d.empty:
        continue
    c = d["close"].copy()
    c.index = pd.MultiIndex.from_arrays([c.index.get_level_values(0), c.index.get_level_values(1).tz_convert("America/New_York").normalize().tz_localize(None)])
    closes.append(c.unstack(0))
C = pd.concat(closes, axis=1).sort_index()
C = C.loc[:, ~C.columns.duplicated()]
days = C.index
R = C.pct_change(fill_method=None)
pos = pd.DataFrame(0.0, index=days, columns=C.columns)
deals = []
for _, e in ev.dropna().iterrows():
    s = e["sym"]
    if s not in C.columns:
        continue
    i0 = days.searchsorted(e["date"], side="right")
    if i0 >= len(days) or pd.isna(C[s].iloc[i0]) or C[s].iloc[i0] < 1:
        continue
    avail = C[s].iloc[i0:i0 + 121].dropna()
    if len(avail) < 2:
        continue
    end = avail.index[-1]
    pos.loc[days[i0 + 1]:end, s] = 1.0
    deals.append((e["date"], s, avail.iloc[-1] / avail.iloc[0] - 1 - 0.002, len(avail) - 1))
D = pd.DataFrame(deals, columns=["date", "sym", "ret", "days"])
print("Deals mit Kursen:", len(D), "Ø Rendite je Deal", round(D["ret"].mean() * 100, 2), "% Median", round(D["ret"].median() * 100, 2),
      "% Ø Haltedauer", round(D["days"].mean()), "Tage, Verluste > 10 %:", (D["ret"] < -0.10).sum())
w = pos.div(pos.sum(axis=1).replace(0, np.nan), axis=0)
port = (w * R.fillna(0)).sum(axis=1)
active = pos.sum(axis=1) > 0
tb = pd.read_pickle("data_cache/fred/TB3MS.pkl") / 100
tb.index = pd.to_datetime(tb.index)
rf = tb.reindex(days, method="ffill").fillna(0) / 252
# Kosten 20 bp je Deal auf das Portfolio verteilen (Einstieg+Ausstieg)
cost = pd.Series(0.0, index=days)
for _, dl in D.iterrows():
    i0 = days.searchsorted(dl["date"], side="right")
    n_open = pos.iloc[min(i0 + 1, len(days) - 1)].sum()
    if n_open > 0:
        cost.iloc[min(i0 + 1, len(days) - 1)] += 0.002 / n_open
strat = port.where(active, rf) - cost
ex = strat - rf
spy = R["SPY"].fillna(0) - rf
for name, a, b in [("Entdeckung 2016-2020", "2016", "2020"), ("Bestätigung 2021-2025-09", "2021", "2025-09-19")]:
    x, m = ex[a:b], spy[a:b]
    tt = x.mean() / x.std() * np.sqrt(len(x))
    beta = np.cov(x, m)[0, 1] / m.var()
    cagr = (1 + strat[a:b]).prod() ** (252 / len(x)) - 1
    eq = (1 + strat[a:b]).cumprod()
    print(f"{name}: {cagr*100:5.1f} % p.a., Überrendite {x.mean()*252*100:5.1f} % p.a. t {tt:5.2f}, Beta {beta:.2f}, "
          f"MaxDD {(eq/eq.cummax()-1).min()*100:5.1f} %, investiert {active[a:b].mean()*100:3.0f} % | Deals {((D['date']>=a)&(D['date']<=b)).sum()}")

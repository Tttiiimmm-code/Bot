"""Runde 80: DIX hoch / GEX niedrig -> 20 Tage SPY long."""
import numpy as np
import pandas as pd

d = pd.read_csv("data_cache/squeeze/DIX.csv", parse_dates=["date"]).set_index("date")
spy = pd.read_pickle("data_cache/yahoo_unseen/SPY_full.pkl")["adjclose"].astype(float)
spy.index = pd.to_datetime(spy.index)
r = spy.pct_change().dropna()
tb = pd.read_pickle("data_cache/fred/TB3MS.pkl") / 100
tb.index = pd.to_datetime(tb.index)
gap = r.index.to_series().diff().dt.days.fillna(1)
rf = tb.reindex(r.index, method="ffill").fillna(0) * gap / 360
d = d.reindex(r.index).ffill()


def pct(s):
    return s.rolling(252).apply(lambda x: (x[:-1] < x[-1]).mean(), raw=True)


sig = {"DA DIX hoch": pct(d["dix"]) >= 0.8, "DB GEX niedrig": pct(d["gex"]) <= 0.2}
for name, s in sig.items():
    s = s.fillna(False).astype(int)
    # Signal am Tag t (nach Schluss bekannt) -> Kauf zum Schluss t+1 -> Renditen ab t+2 für 20 Tage
    active = s.shift(2).rolling(20, min_periods=1).max().fillna(0)
    strat = active * r + (1 - active) * rf - 1e-4 * active.diff().abs().fillna(0)
    ex, mk = strat - rf, r - rf
    ok = True
    print(name)
    for p, a, b, th in [("Entdeckung 2012-05..2017", "2012-05", "2017", 2.24), ("Bestätigung 2018..2025-09", "2018", "2025-09-19", 2.0),
                        ("unberührt", "2025-09-22", "2026-09-25", None)]:
        e, m = ex[a:b], mk[a:b]
        beta = np.cov(e, m)[0, 1] / m.var()
        al = e - beta * m
        t = al.mean() / al.std() * np.sqrt(len(al))
        cagr = (1 + strat[a:b]).prod() ** (252 / len(e)) - 1
        hold = (1 + r[a:b]).prod() ** (252 / len(e)) - 1
        print(f"  {p:26s} investiert {active[a:b].mean()*100:4.0f} % | {cagr*100:5.1f} % p.a. vs SPY {hold*100:5.1f} % | "
              f"Beta {beta:.2f} Alpha {al.mean()*252*100:5.1f} % p.a. t {t:5.2f}")
        ok &= (t >= th) if th else (al.mean() > 0)
    print("  ->", "BESTANDEN" if ok else "NICHT BESTANDEN")

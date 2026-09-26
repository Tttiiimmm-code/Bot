"""Runde 42: DAX-Daytrading per CFD (Dukascopy-Minutendaten)."""
from datetime import date
from pathlib import Path
import numpy as np, pandas as pd
from tradingbot.research import gold
from tradingbot.research.__main__ import _log_trial
from tradingbot.research.engine import CostModel, BacktestResult

m = gold.load_minutes(Path("data_cache/dukascopy/dax"), "dax_*.csv")
m.index = m.index.tz_convert("Europe/Berlin")
m = m[m.index.date <= date(2025, 9, 19)]
RT = 1.5  # Punkte je Round-Trip
days = {d: g for d, g in m.groupby(m.index.date) if pd.Timestamp(d).weekday() < 5}
print("Handelstage:", len(days), "erste", min(days), "letzte", max(days))

res = {}
for tp in (None, 1.0):
    out = {}
    for d, g in days.items():
        g8 = g[g.index.hour >= 8]
        if len(g8) == 0:
            continue
        cps = RT / 2 / float(g8["open"].iloc[0])
        # gold.day_trade: Spanne = Stunden < range_end_hour, Sitzung bis close_hour
        r = gold.day_trade(g8, tp, cps, range_end_hour=9, close_hour=17)
        out[d] = 0.0 if r is None else r
    res[f"BU TP={tp}"] = pd.Series(out).sort_index()


def px_at(g, hh, mm):
    t = g.index.hour * 60 + g.index.minute
    sel = g[t >= hh * 60 + mm]
    if len(sel) == 0 or (sel.index[0].hour * 60 + sel.index[0].minute) - (hh * 60 + mm) > 5:
        return None
    return float(sel["open"].iloc[0])


out, prev_close = {}, None
for d, g in days.items():
    p0930, p1700, p1730 = px_at(g, 9, 30), px_at(g, 17, 0), px_at(g, 17, 30)
    if None not in (prev_close, p0930, p1700, p1730):
        side = np.sign(p0930 / prev_close - 1)
        out[d] = side * (p1730 / p1700 - 1) - (RT / p1700 if side != 0 else 0.0)
    else:
        out[d] = 0.0
    if p1730 is not None:
        prev_close = p1730
res["BV Intraday-Momentum"] = pd.Series(out).sort_index()

table = {}
for label, r in res.items():
    row = {}
    for name, (a, b) in (("Entdeckung", (date(2013, 1, 1), date(2018, 12, 31))), ("Bestätigung", (date(2019, 1, 1), date(2025, 9, 19)))):
        x = r[(r.index >= a) & (r.index <= b)]
        t = x.mean() / x.std(ddof=1) * np.sqrt(len(x))
        eq = (1 + x).cumprod()
        row[name] = t
        print(f"{label:22s} {name:11s} Tage {len(x):4d} Trades {(x != 0).sum():4d} Ø {x.mean() * 1e4:5.2f} bp/Tag "
              f"{(1 + x).prod() ** (252 / len(x)) - 1:6.1%} p.a. Sharpe {x.mean() / x.std() * np.sqrt(252):5.2f} "
              f"MaxDD {(eq / eq.cummax() - 1).min():6.1%} t {t:5.2f}")
        if name == "Entdeckung":
            _log_trial("dax_intraday", "DEUIDXEUR", {"variant": label}, CostModel(slippage_bps=1.0), 1.0, BacktestResult(label, x))
    table[label] = row
for fam in ("BU", "BV"):
    ls = [k for k in table if k.startswith(fam)]
    best = max(ls, key=lambda k: table[k]["Entdeckung"])
    ok = table[best]["Entdeckung"] >= 2.24 and table[best]["Bestätigung"] >= 2
    print(f"Familie {fam}: {best} {table[best]} -> {'BESTANDEN' if ok else 'NICHT BESTANDEN'}")

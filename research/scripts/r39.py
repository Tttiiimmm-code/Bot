"""Runde 39: Kalendereffekte an europäischen Indizes."""
import sys
from datetime import date
import numpy as np, pandas as pd
sys.path.insert(0, "research/scripts")
from tradingbot.research import swing
from tradingbot.research.__main__ import _log_trial
from tradingbot.research.engine import CostModel, BacktestResult
from tradingbot.research.metrics import compute_metrics
exec(open("research/scripts/r38.py", encoding="utf-8").read().split("tb = anomalies")[0].split('"""', 2)[2])

idx_syms = ["^GDAXI", "^FCHI", "^FTSE", "^STOXX50E"]
px = pd.DataFrame({s: long_history(s) for s in idx_syms})
px = px[px.index <= date(2025, 9, 19)]
for s in idx_syms:
    print(s, px[s].first_valid_index())
ret = px.pct_change(fill_method=None)
days = pd.Series(px.index, index=px.index)
ym = pd.Series([(d.year, d.month) for d in px.index], index=px.index)
pos_in_month = ym.groupby(ym).cumcount()
last = (ym != ym.shift(-1))
tom = (pos_in_month <= 2) | last          # Rendite am letzten Tag und Tage 1-3
hal = pd.Series([d.month in (11, 12, 1, 2, 3, 4) for d in px.index], index=px.index)
start = date(1990, 3, 1)
P = {"Entdeckung": (start, date(2005, 12, 31)), "Bestätigung": (date(2006, 1, 1), date(2025, 9, 19))}
table = {}
for fam, held in (("BP Monatswechsel", tom), ("BQ Halloween", hal)):
    h = held.astype(float)
    switch = (h.diff().abs().fillna(0.0))
    strat = ret.mul(h, axis=0).sub(0.001 * switch, axis=0)
    s = strat.mean(axis=1, skipna=True)
    b = ret.mean(axis=1, skipna=True)
    row = {}
    for name, (a, e) in P.items():
        m_ = (s.index >= a) & (s.index <= e)
        ms, mb = compute_metrics(BacktestResult("s", s[m_].fillna(0))), compute_metrics(BacktestResult("b", b[m_].fillna(0)))
        al, t, beta = swing.alpha_vs_benchmark(s[m_].fillna(0), b[m_].fillna(0))
        row[name] = t
        print(f"{fam:17s} {name:11s} {a}..{e}: {ms.cagr:6.1%} p.a. Sharpe {ms.sharpe:4.2f} MaxDD {ms.max_drawdown:6.1%} | Halten {mb.cagr:6.1%} "
              f"{mb.sharpe:4.2f} {mb.max_drawdown:6.1%} | investiert {h[m_].mean():.0%} Alpha {al:6.1%} t {t:5.2f}")
        if name == "Entdeckung":
            _log_trial("europe_calendar", "4 indices", {"variant": fam}, CostModel(slippage_bps=10.0), 1.0, BacktestResult(fam, s[m_].fillna(0)))
    ok = row["Entdeckung"] >= 2.24 and row["Bestätigung"] >= 2
    print(f"  -> {'BESTANDEN' if ok else 'NICHT BESTANDEN'}")

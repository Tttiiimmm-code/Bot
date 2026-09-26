"""Runde 37, R2 (unberührtes Jahr) und R3 (Kostenstress)."""
from datetime import date
from pathlib import Path
import sys
sys.path.insert(0, "research/scripts")
import pandas as pd
from r37_common import load_returns, momentum_run
from tradingbot.research import swing
from tradingbot.research.engine import BacktestResult
from tradingbot.research.metrics import compute_metrics, yearly_returns

close, ret = load_returns(Path("data_cache/europe"), date(2025, 9, 20), date(2025, 9, 19))
univ = (close.notna().cumsum() >= 252) & close.notna()
P = {"Entdeckung": (date(2003, 1, 1), date(2013, 12, 31)), "Bestätigung": (date(2014, 1, 1), date(2025, 9, 19))}
def sl(x, a, b): return x[(x.index >= a) & (x.index <= b)]
for cost in (0.001, 0.0025):
    net, ew, w, to = momentum_run(close, ret, univ, cost=cost)
    for k, (a, b) in P.items():
        al, t, beta = swing.alpha_vs_benchmark(sl(net, a, b), sl(ew, a, b))
        print(f"R3 Kosten {cost*1e4:.0f} bp {k:11s} Alpha {al:6.1%} t {t:5.2f}  Umschlag p.a. {sl(to, a, b).sum() / ((b - a).days / 365.25):4.1f}x")
    if cost == 0.001:
        uk = sum(w[c].gt(0).sum() for c in w.columns if c.endswith(".L")) / w.gt(0).sum().sum()
        print(f"Anteil UK-Positionstage {uk:.0%}")
        yr = pd.DataFrame({"Momentum": yearly_returns(net[net.index >= date(2003, 1, 1)]),
                           "EW": yearly_returns(ew[ew.index >= date(2003, 1, 1)])})
        print(yr.map(lambda x: f"{x:6.1%}").to_string())

# R2: neue Daten; Signale nutzen nur Vergangenheit, Auswertung nur ab 2025-09-22
close2, ret2 = load_returns(Path("data_cache/europe_new"), date(2026, 9, 26), date(2026, 9, 25))
univ2 = (close2.notna().cumsum() >= 252) & close2.notna()
net2, ew2, w2, _ = momentum_run(close2, ret2, univ2)
a, b = date(2025, 9, 22), date(2026, 9, 25)
r, e = sl(net2, a, b), sl(ew2, a, b)
al, t, beta = swing.alpha_vs_benchmark(r, e)
m, me = compute_metrics(BacktestResult("m", r)), compute_metrics(BacktestResult("e", e))
print(f"R2 unberührtes Jahr {a}..{b}: Momentum {(1 + r).prod() - 1:6.1%} (Sharpe {m.sharpe:4.2f}, MaxDD {m.max_drawdown:6.1%}), "
      f"EW {(1 + e).prod() - 1:6.1%}, Alpha {al:6.1%} t {t:5.2f} -> {'POSITIV' if al > 0 else 'NEGATIV'}; Tage {len(r)}")
# Konsistenz: überlappender Zeitraum alt vs. neu
o_old = sl(momentum_run(close, ret, univ)[0], date(2024, 1, 1), date(2025, 9, 19))
o_new = sl(net2, date(2024, 1, 1), date(2025, 9, 19))
print("Kontrolle 2024-2025 alt vs. neu geladen, Korrelation:", round(o_old.corr(o_new.reindex(o_old.index)), 3))

"""Runde 37, R1: zeitpunktgenaues Universum aus Wikipedia-Revisionen."""
import shutil, sys, time
from datetime import date
from pathlib import Path
sys.path.insert(0, "research/scripts")
import pandas as pd
from r37_common import load_returns, momentum_run
from r37_wiki import SUFFIX, normalize, tickers
from tradingbot.research import history, swing
from tradingbot.research.engine import BacktestResult
from tradingbot.research.metrics import compute_metrics

PIT = Path("data_cache/europe_pit")
PIT.mkdir(parents=True, exist_ok=True)
members = {}  # Jahr -> Menge
for page in SUFFIX:
    last = set()
    for y in range(2004, 2026):
        tk = {normalize(page, t) for t in tickers(page, y)}
        if tk:
            last = tk
        members.setdefault(y, set()).update(last)
allsyms = set().union(*members.values())
missing = []
for s in sorted(allsyms):
    src = Path("data_cache/europe") / f"{s}_full.pkl"
    dst = PIT / f"{s}_full.pkl"
    if dst.exists():
        continue
    if src.exists():
        shutil.copy(src, dst)
        continue
    try:
        history.fetch_yahoo(s, base=PIT, until=date(2025, 9, 20))
        time.sleep(0.4)
    except Exception:
        missing.append(s)
for c in ("GBP", "CHF", "SEK"):
    f = f"{c}EUR=X_full.pkl"
    if not (PIT / f).exists():
        shutil.copy(Path("data_cache/europe") / f, PIT / f)
print(f"Symbole je Jahr: {[(y, len(m)) for y, m in members.items()]}")
print(f"Alle historischen Mitglieder {len(allsyms)}, bei Yahoo nicht gefunden {len(missing)}: {missing[:30]}")

close, ret = load_returns(PIT, date(2025, 9, 20), date(2025, 9, 19))
mem = pd.DataFrame(False, index=close.index, columns=close.columns)
years = pd.Series([d.year for d in close.index], index=close.index)
for y, m in members.items():
    cols = [c for c in close.columns if c in m]
    mem.loc[years == y, cols] = True
univ = mem & (close.notna().cumsum() >= 252) & close.notna()
cover = []
for y, m in members.items():
    if m:
        have = sum(1 for s in m if s in close.columns and close[s][[d.year == y for d in close.index]].notna().any())
        cover.append((y, len(m), have))
print("Abdeckung (Jahr, Mitglieder, mit Kursen):", cover)
net, ew, w, to = momentum_run(close, ret, univ)
first = next(y for y, m in sorted(members.items()) if m)
P = {"Entdeckung": (date(first, 1, 1), date(2013, 12, 31)), "Bestätigung": (date(2014, 1, 1), date(2025, 9, 19))}
res = {}
for k, (a, b) in P.items():
    r, e = net[(net.index >= a) & (net.index <= b)], ew[(ew.index >= a) & (ew.index <= b)]
    m, me = compute_metrics(BacktestResult("m", r)), compute_metrics(BacktestResult("e", e))
    al, t, beta = swing.alpha_vs_benchmark(r, e)
    res[k] = t
    print(f"R1 {k:11s} {a}..{b}: {m.cagr:6.1%} p.a. (EW {me.cagr:6.1%}) Sharpe {m.sharpe:4.2f} MaxDD {m.max_drawdown:6.1%} "
          f"Alpha {al:6.1%} t {t:5.2f} beta {beta:4.2f}, Ø Universum {univ.loc[r.index].sum(axis=1).mean():.0f}")
print("R1:", "BESTANDEN" if all(t >= 1.65 for t in res.values()) else "NICHT BESTANDEN")

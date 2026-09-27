"""Runde 47: Robustheit Gotobi."""
import sys
from datetime import date
import numpy as np, pandas as pd
sys.path.insert(0, "research/scripts")
from gotobi import trades
from tradingbot.research import gold

fx = gold.load_fx("usdjpy")
conf = lambda s: s[(s.index >= date(2017, 1, 1)) & (s.index <= date(2025, 9, 19))]
base = trades(fx)
# t über Handelstage wie in Runde 46 (0 an Nicht-Gotobi-Tagen) ~ t über Trades; hier Trade-t berichtet
def tstat(s): return s.mean() / s.std() * np.sqrt(len(s))
r1 = conf(trades(fx, cost_per_side=0.00015))
print(f"R1 Kosten 1,5 bp/Seite: Ø {r1.mean() * 1e4:5.2f} bp, t {tstat(r1):5.2f} -> {'ok' if tstat(r1) >= 1.65 else 'NICHT ok'}")
ok2 = True
for h in (3, 7, 8):
    x = conf(trades(fx, entry=(h, 0)))
    ok2 &= x.mean() > 0
    print(f"R2 Einstieg {h:02d}:00: Ø {x.mean() * 1e4:5.2f} bp, t {tstat(x):5.2f}")
print("R2", "ok" if ok2 else "NICHT ok")
yr = base[base.index <= date(2025, 9, 19)].groupby([d.year for d in base.index[base.index <= date(2025, 9, 19)]]).sum()
print("R3 Jahressummen:", {k: f"{v:+.2%}" for k, v in yr.items()})
share = (yr > 0).mean()
print(f"R3 positive Jahre {share:.0%} -> {'ok' if share >= 0.6 else 'NICHT ok'}")
x = conf(trades(fx, exit_=(10, 30)))
print(f"R4 Ausstieg 10:30: Ø {x.mean() * 1e4:5.2f} bp, t {tstat(x):5.2f} (09:55: Ø {conf(base).mean() * 1e4:5.2f} bp, t {tstat(conf(base)):5.2f})")

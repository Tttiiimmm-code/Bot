"""Runde 52: IBS-Band und Double 7 an DAX, CAC, Nikkei."""
from datetime import date
from pathlib import Path
import pandas as pd
from tradingbot.research import anomalies, history, swing
from tradingbot.research.__main__ import _log_trial
from tradingbot.research.engine import CostModel, BacktestResult
from tradingbot.research.metrics import compute_metrics

tb = anomalies.fetch_fred("TB3MS") / 100
out = {"Z1 IBS-Band": {}, "Z2 Double 7": {}}
bench = {}
for s in ("^GDAXI", "^FCHI", "^N225"):
    df = history.fetch_yahoo_ohlc(s, base=Path("data_cache/yahoo_unseen"), until=date(2026, 9, 26))
    df = df[df.index >= date(1994, 1, 1)]
    r = df["close"].pct_change().fillna(0.0)
    ym = pd.PeriodIndex([pd.Timestamp(d) for d in df.index], freq="M").to_timestamp()
    rf = pd.Series(tb.reindex(ym, method="ffill").to_numpy(), index=df.index).ffill().fillna(0.0) / 252
    bench[s] = r
    for fam, pos in (("Z1 IBS-Band", anomalies.ibs_band_positions(df)), ("Z2 Double 7", anomalies.double7_positions(df["close"]))):
        held = pos.shift(1).fillna(0.0)
        out[fam][s] = held * (r - rf) - 0.00005 * pos.diff().abs().fillna(0.0).shift(1).fillna(0.0)
B = pd.DataFrame(bench).mean(axis=1)
P = {"Entdeckung": (date(1994, 1, 1), date(2008, 12, 31)), "Bestätigung": (date(2009, 1, 1), date(2025, 9, 19)),
     "unberührt": (date(2025, 9, 22), date(2026, 9, 25))}
for fam, d in out.items():
    S = pd.DataFrame(d).mean(axis=1)
    row = {}
    for name, (a, b) in P.items():
        x, bb = S[(S.index >= a) & (S.index <= b)], B[(B.index >= a) & (B.index <= b)]
        m, mb = compute_metrics(BacktestResult("x", x)), compute_metrics(BacktestResult("b", bb))
        al, t, beta = swing.alpha_vs_benchmark(x, bb)
        row[name] = (t, al)
        print(f"{fam:12s} {name:11s} {m.cagr:6.1%} p.a. Sharpe {m.sharpe:4.2f} MaxDD {m.max_drawdown:6.1%} | Halten {mb.cagr:6.1%} {mb.sharpe:4.2f} "
              f"| Alpha {al:6.1%} t {t:5.2f} beta {beta:4.2f}")
        if name == "Entdeckung":
            _log_trial("eu_jp_reversion", "DAX/CAC/N225", {"variant": fam}, CostModel(slippage_bps=0.5), 1.0, BacktestResult(fam, x))
    ok = row["Entdeckung"][0] >= 2.24 and row["Bestätigung"][0] >= 2 and row["unberührt"][1] > 0
    print(f"  -> {'BESTANDEN' if ok else 'NICHT BESTANDEN'}")

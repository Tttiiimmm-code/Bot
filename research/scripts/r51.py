"""Runde 51, Schritt 3: Best-Ideas-Backtest."""
import json, re
from datetime import date
import numpy as np, pandas as pd
from tradingbot.research import crypto, swing
from tradingbot.research.universe import UNIVERSE_DIR, load_daily_panel
from tradingbot.research.__main__ import _FUND_NAME, _log_trial, HOLDOUT_START
from tradingbot.research.engine import CostModel, BacktestResult
from tradingbot.research.metrics import compute_metrics

assets = pd.read_pickle(UNIVERSE_DIR / "assets.pkl")
funds = set(assets.loc[assets["name"].fillna("").str.contains(re.compile(_FUND_NAME, re.I)), "symbol"])
panel = load_daily_panel()
panel = panel[panel.index.get_level_values("date") < HOLDOUT_START]
bench = panel.xs("SPY", level="symbol")["close"].pct_change().dropna()
stocks = panel[~panel.index.get_level_values("symbol").isin(funds)]
_, closes, mask = swing.reversal_matrices(stocks, universe_size=1000)
idx = closes.index
col = {c: i for i, c in enumerate(closes.columns)}

cand = pd.read_pickle("data_cache/sec13f/candidates.pkl")
fig = json.load(open("data_cache/sec13f/figi.json"))
cand["ticker"] = cand["CUSIP"].map(fig).fillna("").str.replace("/", ".", regex=False)
cand = cand[cand["ticker"].isin(col.keys())]
print("Kandidaten mit Ticker im Panel:", len(cand), "Meldungen:", cand["ACCESSION_NUMBER"].nunique())
month_ends = [d for d, nd in zip(idx[:-1], idx[1:]) if d.month != nd.month]
M = mask.to_numpy()
variants = {"20-200 Positionen": (20, 200), "20-50 Positionen": (20, 50)}
table = {}
for label, (lo, hi) in variants.items():
    c = cand[(cand["n"] >= lo) & (cand["n"] <= hi)].sort_values(["ACCESSION_NUMBER", "rank"])
    W = pd.DataFrame(0.0, index=idx, columns=closes.columns)
    npos = []
    for i, t in enumerate(month_ends):
        t_ts = pd.Timestamp(t)
        live = c[(c["FILING_DATE"] <= t_ts) & (c["FILING_DATE"] > t_ts - pd.Timedelta(days=92))]
        latest = live.sort_values("FILING_DATE").groupby("CIK")["ACCESSION_NUMBER"].last()
        live = live[live["ACCESSION_NUMBER"].isin(latest)]
        ti = idx.get_loc(t)
        picks = set()
        for acc, g in live.groupby("ACCESSION_NUMBER"):
            for tk in g["ticker"]:
                if M[ti, col[tk]]:
                    picks.add(tk)
                    break
        npos.append(len(picks))
        end = idx.get_loc(month_ends[i + 1]) if i + 1 < len(month_ends) else len(idx) - 1
        if picks:
            W.iloc[ti:end, [col[p] for p in picks]] = 1.0 / len(picks)
    res = crypto.run_weights(W, closes, 0.0010, label).daily_returns
    row = {}
    for name, (a, b) in (("Entdeckung", (date(2014, 1, 1), date(2019, 12, 31))), ("Bestätigung", (date(2020, 1, 1), date(2025, 9, 19)))):
        r = res[(res.index >= a) & (res.index <= b)]
        bb = bench.reindex(r.index).fillna(0.0)
        m, mb = compute_metrics(BacktestResult(label, r)), compute_metrics(BacktestResult("b", bb))
        al, t, beta = swing.alpha_vs_benchmark(r, bb)
        row[name] = t
        print(f"{label:18s} {name:11s} {m.cagr:7.1%} Sharpe {m.sharpe:4.2f} (SPY {mb.cagr:6.1%}, {mb.sharpe:4.2f}) MaxDD {m.max_drawdown:6.1%} "
              f"Alpha {al:6.1%} t {t:5.2f} beta {beta:4.2f}")
        if name == "Entdeckung":
            _log_trial("13f_best_ideas", "13F", {"variant": label}, CostModel(slippage_bps=10.0), 1.0, BacktestResult(label, r))
    print(f"   Ø Titel je Monat {np.mean(npos):.0f} (min {min(npos)}, max {max(npos)})")
    table[label] = row
best = max(table, key=lambda k: table[k]["Entdeckung"])
ok = table[best]["Entdeckung"] >= 2.24 and table[best]["Bestätigung"] >= 2
print(f"gewählt {best}: {table[best]} -> {'BESTANDEN' if ok else 'NICHT BESTANDEN'}")

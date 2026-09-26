from datetime import date as _date
import numpy as np, pandas as pd
from tradingbot.research import crypto, swing
from tradingbot.research.universe import load_daily_panel
from tradingbot.research.__main__ import _log_trial, HOLDOUT_START
from tradingbot.research.engine import CostModel, BacktestResult
from tradingbot.research.metrics import compute_metrics
disc, conf = (_date(2016,1,1), _date(2020,12,31)), (_date(2021,1,1), _date(2025,9,19))
ev = pd.read_csv('data_cache/sp500_changes.csv', parse_dates=['date']).fillna('')
ev = ev[(ev.date >= '2016-01-01') & (ev.date < str(HOLDOUT_START))]
panel = load_daily_panel(); panel = panel[panel.index.get_level_values('date') < HOLDOUT_START]
closes = panel['close'].unstack('symbol')
bench = closes['SPY'].pct_change().dropna()
idx = closes.index
bad = ev.reason.str.contains('acqui|merg|spin|spun|bankrupt|private|split|reorgan', case=False)
sets = {'BC': ev.loc[~bad & (ev.removed != ''), ['date','removed']].rename(columns={'removed':'sym'}),
        'BD': ev.loc[ev.added != '', ['date','added']].rename(columns={'added':'sym'})}
def sl(x, p): return x[(x.index >= p[0]) & (x.index <= p[1])]
table = {}
for fam, E in sets.items():
    for H in (20, 60):
        W = pd.DataFrame(0.0, index=idx, columns=closes.columns); used = 0
        for d, sym in E.itertuples(index=False):
            if sym not in closes.columns: continue
            pos = idx.searchsorted(d.date()) - 1
            if pos < 0 or pd.isna(closes[sym].iloc[pos]): continue
            used += 1
            W.iloc[pos:pos+H, W.columns.get_loc(sym)] += 0.10
        tot = W.sum(axis=1); W = W.div(tot.clip(lower=1.0), axis=0)
        label = f'{fam} H={H}'
        res = crypto.run_weights(W, closes, 0.0010, label).daily_returns
        res = res.reindex(bench.index).fillna(0.0)
        row = {}
        for name, p in (('Entdeckung', disc), ('Bestätigung', conf)):
            r, b = sl(res, p), sl(bench, p)
            m = compute_metrics(BacktestResult(label, r))
            al, t, beta = swing.alpha_vs_benchmark(r, b)
            row[name] = t
            print(f'{label:9s} {name:11s} Ereignisse {used:3d} {m.cagr:7.1%} Sharpe {m.sharpe:5.2f} MaxDD {m.max_drawdown:6.1%} Alpha {al:6.1%} t {t:5.2f} beta {beta:4.2f} investiert {sl(W.sum(axis=1),p).mean():.0%}')
            if name == 'Entdeckung':
                _log_trial('sp500_changes', 'events', {'variant': label}, CostModel(slippage_bps=10.0), 1.0, BacktestResult(label, r))
        table[label] = row
for fam in sets:
    ls = [k for k in table if k.startswith(fam)]
    best = max(ls, key=lambda k: table[k]['Entdeckung'])
    ok = table[best]['Entdeckung'] >= 2.24 and table[best]['Bestätigung'] >= 2
    print(f"Familie {fam}: {best} {table[best]} -> {'BESTANDEN' if ok else 'NICHT BESTANDEN'}")

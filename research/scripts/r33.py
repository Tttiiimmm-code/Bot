import numpy as np, pandas as pd
from tradingbot.research import crypto, swing
from tradingbot.research.__main__ import _log_trial
from tradingbot.research.engine import CostModel, BacktestResult
from tradingbot.research.metrics import compute_metrics
close, vol = crypto.load_panel()
close.index = pd.to_datetime(close.index); vol.index = close.index
periods = {'Entdeckung': ('2018-01-01', '2021-12-31'), 'Bestätigung': ('2022-01-01', '2025-09-21')}
table = {}
for top in (20, 50):
    U = crypto.universe_mask(close, vol, top)
    ret = close.pct_change()
    ew = (ret.where(U.shift(1, fill_value=False))).mean(axis=1).fillna(0.0)
    for fam, lb, hold_days in (('BE', 7, 'W'), ('BF', 1, 'D')):
        past = close / close.shift(lb) - 1
        s = past.where(U)
        rank = s.rank(axis=1, method='first')
        pick = (rank <= 5).astype(float) / 5
        if hold_days == 'W':
            is_sun = close.index.weekday == 6
            pick = pick.where(pd.Series(is_sun, index=close.index), np.nan).ffill().fillna(0.0)
        label = f'{fam} Top{top}'
        res = crypto.run_weights(pick, close, 0.001, label).daily_returns
        res.index = pd.to_datetime(res.index)
        row = {}
        for name, (a, b) in periods.items():
            r = res[(res.index >= a) & (res.index <= b)]; bb = ew.reindex(r.index).fillna(0.0)
            m = compute_metrics(BacktestResult(label, r), 365); mb = compute_metrics(BacktestResult('b', bb), 365)
            al, t, beta = swing.alpha_vs_benchmark(r, bb, 365)
            row[name] = t
            print(f'{label:9s} {name:11s} {m.cagr:8.1%} Sharpe {m.sharpe:5.2f} (EW {mb.cagr:7.1%}, {mb.sharpe:4.2f}) MaxDD {m.max_drawdown:6.1%} Alpha {al:7.1%} t {t:5.2f} beta {beta:4.2f}')
            if name == 'Entdeckung':
                _log_trial('crypto_reversal', f'top{top}', {'variant': label}, CostModel(slippage_bps=10.0), 1.0, BacktestResult(label, r), 365)
        table[label] = row
for fam in ('BE', 'BF'):
    ls = [k for k in table if k.startswith(fam)]
    best = max(ls, key=lambda k: table[k]['Entdeckung'])
    ok = table[best]['Entdeckung'] >= 2.24 and table[best]['Bestätigung'] >= 2
    print(f"Familie {fam}: {best} {table[best]} -> {'BESTANDEN' if ok else 'NICHT BESTANDEN'}")

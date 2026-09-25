"""Kennzahlen für Backtest-Ergebnisse inkl. Deflated Sharpe Ratio.

Deflated Sharpe Ratio nach Bailey & López de Prado (2014): Wahrscheinlich-
keit, dass die echte Sharpe Ratio > 0 ist, nachdem berücksichtigt wurde,
dass die beste von N getesteten Varianten ausgewählt wurde.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import NormalDist

import numpy as np
import pandas as pd

from tradingbot.research.engine import BacktestResult

TRADING_DAYS = 252
_EULER_GAMMA = 0.5772156649
_N = NormalDist()


@dataclass(frozen=True)
class Metrics:
    days: int
    total_return: float
    cagr: float
    ann_vol: float
    sharpe: float
    max_drawdown: float
    n_trades: int
    win_rate: float
    profit_factor: float
    avg_trade_bps: float


def sharpe_ratio(daily_returns: pd.Series, periods: int = TRADING_DAYS) -> float:
    """Annualisiert (`periods` Tage je Jahr, Krypto: 365), Tage ohne Trade zählen als 0 %."""
    r = np.asarray(daily_returns, dtype=float)
    if len(r) < 2 or r.std(ddof=1) == 0:
        return 0.0
    return float(r.mean() / r.std(ddof=1) * math.sqrt(periods))


def max_drawdown(daily_returns: pd.Series) -> float:
    equity = np.cumprod(1 + np.asarray(daily_returns, dtype=float))
    if len(equity) == 0:
        return 0.0
    peak = np.maximum.accumulate(np.concatenate([[1.0], equity]))[1:]
    return float((equity / peak - 1).min())


def compute_metrics(result: BacktestResult, periods: int = TRADING_DAYS) -> Metrics:
    r = result.daily_returns
    n = len(r)
    total = float(np.prod(1 + r.to_numpy()) - 1) if n else 0.0
    years = n / periods
    cagr = (1 + total) ** (1 / years) - 1 if years > 0 and total > -1 else 0.0
    tr = result.trade_net_returns
    wins, losses = tr[tr > 0].sum(), -tr[tr < 0].sum()
    return Metrics(
        days=n,
        total_return=total,
        cagr=cagr,
        ann_vol=float(r.std(ddof=1) * math.sqrt(periods)) if n > 1 else 0.0,
        sharpe=sharpe_ratio(r, periods),
        max_drawdown=max_drawdown(r),
        n_trades=len(tr),
        win_rate=float((tr > 0).mean()) if len(tr) else 0.0,
        profit_factor=float(wins / losses) if losses > 0 else math.inf if wins > 0 else 0.0,
        avg_trade_bps=float(tr.mean() * 10_000) if len(tr) else 0.0,
    )


def expected_max_sharpe(n_trials: int, sharpe_variance: float) -> float:
    """Erwartetes Maximum der (nicht annualisierten) Sharpe Ratio unter N
    Versuchen ohne echten Vorteil."""
    if n_trials <= 1:
        return 0.0
    return math.sqrt(sharpe_variance) * (
        (1 - _EULER_GAMMA) * _N.inv_cdf(1 - 1 / n_trials)
        + _EULER_GAMMA * _N.inv_cdf(1 - 1 / (n_trials * math.e))
    )


def deflated_sharpe(daily_returns: pd.Series, n_trials: int, trial_sharpe_variance: float) -> float:
    """Wahrscheinlichkeit (0..1), dass die echte Sharpe Ratio > 0 ist.
    `trial_sharpe_variance`: Varianz der NICHT annualisierten täglichen
    Sharpe Ratios aller getesteten Varianten."""
    r = np.asarray(daily_returns, dtype=float)
    t = len(r)
    if t < 3 or r.std(ddof=1) == 0:
        return 0.0
    sr = r.mean() / r.std(ddof=1)
    z = (r - r.mean()) / r.std(ddof=0)
    skew = float((z**3).mean())
    kurt = float((z**4).mean())
    sr0 = expected_max_sharpe(n_trials, trial_sharpe_variance)
    denom = 1 - skew * sr + (kurt - 1) / 4 * sr**2
    if denom <= 0:
        return 0.0
    return _N.cdf((sr - sr0) * math.sqrt(t - 1) / math.sqrt(denom))


def yearly_returns(daily_returns: pd.Series) -> pd.Series:
    r = daily_returns.copy()
    r.index = pd.to_datetime(r.index)
    return r.groupby(r.index.year).apply(lambda x: float(np.prod(1 + x) - 1))

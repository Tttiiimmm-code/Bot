"""Einfacher Vektor-Backtest für die Moving-Average-Crossover-Strategie."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from tradingbot.strategy import Signal, generate_signal_series


@dataclass
class BacktestResult:
    final_equity: float
    total_return_pct: float
    num_trades: int
    equity_curve: pd.Series


def run_backtest(
    close: pd.Series,
    short_window: int,
    long_window: int,
    starting_cash: float = 10_000.0,
) -> BacktestResult:
    signals = generate_signal_series(close, short_window, long_window)

    cash = starting_cash
    shares = 0.0
    num_trades = 0
    equity_curve = []

    for price, signal in zip(close, signals):
        if signal == Signal.BUY and shares == 0:
            shares = cash / price
            cash = 0.0
            num_trades += 1
        elif signal == Signal.SELL and shares > 0:
            cash = shares * price
            shares = 0.0
            num_trades += 1

        equity_curve.append(cash + shares * price)

    equity_series = pd.Series(equity_curve, index=close.index)
    final_equity = equity_series.iloc[-1] if not equity_series.empty else starting_cash
    total_return_pct = (final_equity / starting_cash - 1) * 100

    return BacktestResult(
        final_equity=final_equity,
        total_return_pct=total_return_pct,
        num_trades=num_trades,
        equity_curve=equity_series,
    )

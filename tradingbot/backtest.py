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
    total_costs: float
    equity_curve: pd.Series


def run_backtest(
    close: pd.Series,
    short_window: int,
    long_window: int,
    starting_cash: float = 10_000.0,
    commission_pct: float = 0.0,
    slippage_pct: float = 0.0005,
) -> BacktestResult:
    """Backtest mit Transaktionskosten.

    - `commission_pct`: Provision pro Order als Anteil des Ordervolumens
      (z.B. 0.001 = 0.1%). Alpaca ist für US-Aktien provisionsfrei, daher
      Default 0.0.
    - `slippage_pct`: Erwartete Ausführung schlechter als der Schlusskurs
      (Market-Order trifft Geld-/Briefkurs statt Mittelkurs). Default 0.05%
      pro Order als grobe Annäherung an den Bid-Ask-Spread liquider Aktien.
    """
    signals = generate_signal_series(close, short_window, long_window)

    cash = starting_cash
    shares = 0.0
    num_trades = 0
    total_costs = 0.0
    equity_curve = []

    for price, signal in zip(close, signals):
        if signal == Signal.BUY and shares == 0:
            fill_price = price * (1 + slippage_pct)
            gross_shares = cash / fill_price
            commission = cash * commission_pct
            shares = (cash - commission) / fill_price
            total_costs += commission + (fill_price - price) * gross_shares
            cash = 0.0
            num_trades += 1
        elif signal == Signal.SELL and shares > 0:
            fill_price = price * (1 - slippage_pct)
            proceeds = shares * fill_price
            commission = proceeds * commission_pct
            total_costs += commission + (price - fill_price) * shares
            cash = proceeds - commission
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
        total_costs=total_costs,
        equity_curve=equity_series,
    )

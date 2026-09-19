"""Einfacher Vektor-Backtest für die Moving-Average-Crossover-Strategie."""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from tradingbot.strategy import Signal, generate_signal_series


@dataclass
class Trade:
    date: pd.Timestamp
    side: str  # "BUY" oder "SELL"
    price: float
    shares: float
    cost: float


@dataclass
class BacktestResult:
    final_equity: float
    total_return_pct: float
    num_trades: int
    total_costs: float
    equity_curve: pd.Series
    trades: list[Trade] = field(default_factory=list)


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
    trades: list[Trade] = []

    for date, price, signal in zip(close.index, close, signals):
        if signal == Signal.BUY and shares == 0:
            fill_price = price * (1 + slippage_pct)
            gross_shares = cash / fill_price
            commission = cash * commission_pct
            shares = (cash - commission) / fill_price
            trade_cost = commission + (fill_price - price) * gross_shares
            total_costs += trade_cost
            cash = 0.0
            num_trades += 1
            trades.append(Trade(date, "BUY", fill_price, shares, trade_cost))
        elif signal == Signal.SELL and shares > 0:
            fill_price = price * (1 - slippage_pct)
            proceeds = shares * fill_price
            commission = proceeds * commission_pct
            trade_cost = commission + (price - fill_price) * shares
            total_costs += trade_cost
            cash = proceeds - commission
            sold_shares = shares
            shares = 0.0
            num_trades += 1
            trades.append(Trade(date, "SELL", fill_price, sold_shares, trade_cost))

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
        trades=trades,
    )

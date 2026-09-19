"""Einfacher Vektor-Backtest für die Moving-Average-Crossover-Strategie."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import pandas as pd

from tradingbot.strategy import Signal, generate_signal_series


@dataclass
class Trade:
    date: pd.Timestamp
    side: str  # "BUY", "SELL" oder "STOP" (durch Stop-Loss ausgelöster Verkauf)
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


def _execute_sell(
    shares: float, price: float, commission_pct: float, slippage_pct: float
) -> tuple[float, float, float]:
    """Führt einen Verkauf aus und gibt (cash_zufluss, gezahlte_kosten, fill_price) zurück."""
    fill_price = price * (1 - slippage_pct)
    proceeds = shares * fill_price
    commission = proceeds * commission_pct
    trade_cost = commission + (price - fill_price) * shares
    return proceeds - commission, trade_cost, fill_price


def run_backtest(
    close: pd.Series,
    short_window: int,
    long_window: int,
    starting_cash: float = 10_000.0,
    commission_pct: float = 0.0,
    slippage_pct: float = 0.0005,
    stop_loss_pct: float = 0.08,
) -> BacktestResult:
    """Backtest mit Transaktionskosten und Stop-Loss.

    - `commission_pct`: Provision pro Order als Anteil des Ordervolumens
      (z.B. 0.001 = 0.1%). Alpaca ist für US-Aktien provisionsfrei, daher
      Default 0.0.
    - `slippage_pct`: Erwartete Ausführung schlechter als der Schlusskurs
      (Market-Order trifft Geld-/Briefkurs statt Mittelkurs). Default 0.05%
      pro Order als grobe Annäherung an den Bid-Ask-Spread liquider Aktien.
    - `stop_loss_pct`: Fällt der Schlusskurs nach dem Einstieg um mehr als
      diesen Anteil unter den Einstiegspreis, wird die Position sofort
      verkauft -- unabhängig vom Crossover-Signal. 0 deaktiviert den Stop.
      Da nur Tagesschlusskurse vorliegen, wird der Stop nur einmal pro Tag
      auf Basis des Schlusskurses geprüft, nicht intraday.
    """
    if not (math.isfinite(starting_cash) and starting_cash > 0):
        # starting_cash ist Divisor bei der Renditeberechnung (final_equity
        # / starting_cash) -- 0 würde einen ZeroDivisionError auslösen
        # (leere close-Serie) oder still NaN/Inf erzeugen (nicht-leere).
        raise ValueError(f"starting_cash muss eine positive, endliche Zahl sein, war {starting_cash}.")

    for name, value in (
        ("commission_pct", commission_pct),
        ("slippage_pct", slippage_pct),
        ("stop_loss_pct", stop_loss_pct),
    ):
        if not 0 <= value < 1:
            # Ab 1 (100%) kippen die Vorzeichen: z.B. negative shares bei
            # commission_pct>=1 ((cash-commission) wird negativ) oder ein
            # negativer Verkaufspreis bei slippage_pct>=1 -- das würde den
            # Backtest-Zustand dauerhaft korrumpieren.
            raise ValueError(f"{name} muss zwischen 0 und kleiner 1 (100%) liegen, war {value}.")

    signals = generate_signal_series(close, short_window, long_window)

    cash = starting_cash
    shares = 0.0
    entry_price: float | None = None
    last_valid_price: float | None = None
    num_trades = 0
    total_costs = 0.0
    equity_curve = []
    trades: list[Trade] = []

    for date, price, signal in zip(close.index, close, signals):
        # Ein Kurs von NaN (Datenlücke) oder <= 0 (z.B. Delisting, defekter
        # Datenpunkt) ist nicht handelbar -- 0/negative Kurse würden bei
        # der Division für fill_price zu ZeroDivisionError/Vorzeichenfehlern
        # führen. An solchen Tagen wird nicht gehandelt und für die
        # Bewertung der letzte bekannte gültige Kurs verwendet.
        price_valid = pd.notna(price) and price > 0
        if price_valid:
            last_valid_price = price

        if (
            shares > 0
            and stop_loss_pct > 0
            and entry_price is not None
            and price_valid
            and price <= entry_price * (1 - stop_loss_pct)
        ):
            cash, trade_cost, fill_price = _execute_sell(shares, price, commission_pct, slippage_pct)
            total_costs += trade_cost
            trades.append(Trade(date, "STOP", fill_price, shares, trade_cost))
            num_trades += 1
            shares = 0.0
            entry_price = None
            equity_curve.append(cash)
            continue

        if signal == Signal.BUY and shares == 0 and price_valid:
            fill_price = price * (1 + slippage_pct)
            commission = cash * commission_pct
            shares = (cash - commission) / fill_price
            trade_cost = cash - shares * price
            total_costs += trade_cost
            cash = 0.0
            entry_price = fill_price
            num_trades += 1
            trades.append(Trade(date, "BUY", fill_price, shares, trade_cost))
        elif signal == Signal.SELL and shares > 0 and price_valid:
            sold_shares = shares
            cash, trade_cost, fill_price = _execute_sell(shares, price, commission_pct, slippage_pct)
            total_costs += trade_cost
            shares = 0.0
            entry_price = None
            num_trades += 1
            trades.append(Trade(date, "SELL", fill_price, sold_shares, trade_cost))

        if shares > 0:
            # Fehlt heute ein gültiger Kurs, auf den letzten bekannten
            # zurückfallen statt die Equity-Kurve zu vergiften (0 * NaN
            # wäre ebenfalls NaN, daher zusätzlich der shares==0-Fall
            # unten).
            mark_price = price if price_valid else last_valid_price
            equity_curve.append(cash + shares * mark_price)
        else:
            equity_curve.append(cash)

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

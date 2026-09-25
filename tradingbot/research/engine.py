"""Intraday-Backtest-Engine für Strategien auf einem einzelnen Symbol.

Eine Strategie liefert pro Handelstag eine Liste von Trades (Einstieg/
Ausstieg innerhalb desselben Tages). Die Engine wendet Kosten und die
Kapital-Obergrenze an und verkettet die Tagesrenditen.

Vertrag für Strategien (per Test gegen Look-Ahead geprüft): für Tag i
dürfen nur sessions[:i] vollständig und von sessions[i] nur Bars bis zum
jeweiligen Entscheidungszeitpunkt verwendet werden. Ein Signal am Schluss
von Bar j wird frühestens zum Open von Bar j+1 ausgeführt.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Protocol

import numpy as np
import pandas as pd

from tradingbot.research import HOLDOUT_START

Sessions = list[tuple[date, pd.DataFrame]]


@dataclass(frozen=True)
class Trade:
    day: date
    side: int  # +1 long, -1 short
    entry_time: pd.Timestamp
    entry_price: float
    exit_time: pd.Timestamp
    exit_price: float
    # Positionswert als Vielfaches des Tageskapitals (1.0 = 100 %).
    exposure: float
    reason: str = ""
    symbol: str = ""

    @property
    def gross_return(self) -> float:
        return self.side * (self.exit_price / self.entry_price - 1.0)


@dataclass(frozen=True)
class CostModel:
    # Pro Seite, inkl. halbem Spread. 1 bp ist für SPY/QQQ konservativ
    # (Spread ~0,2 bp), für Small Caps viel zu niedrig.
    slippage_bps: float = 1.0
    commission_per_share: float = 0.0
    # SEC-Gebühr auf Verkaufsvolumen (Stand 2025: 27,80 $ je 1 Mio. $).
    sec_fee_rate: float = 27.8e-6

    def round_trip_cost(self, trade: Trade) -> float:
        """Kosten als Anteil des Positionswerts (Näherung: Einstiegswert)."""
        slip = 2 * self.slippage_bps / 10_000
        commission = self.commission_per_share * (1 / trade.entry_price + 1 / trade.exit_price)
        sell_price = trade.exit_price if trade.side > 0 else trade.entry_price
        sec_fee = self.sec_fee_rate * sell_price / trade.entry_price
        return slip + commission + sec_fee


class Strategy(Protocol):
    name: str
    warmup_days: int

    def trades_for_day(self, sessions: Sessions, i: int) -> list[Trade]: ...


@dataclass
class BacktestResult:
    strategy: str
    daily_returns: pd.Series  # Index: Handelstag, auch Tage ohne Trade (0.0)
    trades: list[Trade] = field(default_factory=list)
    trade_net_returns: np.ndarray = field(default_factory=lambda: np.array([]))


def run_backtest(
    sessions: Sessions,
    strategy: Strategy,
    costs: CostModel = CostModel(),
    max_exposure: float = 1.0,
    start: date | None = None,
    end: date | None = None,
    allow_holdout: bool = False,
) -> BacktestResult:
    """`max_exposure`: Kapital-Obergrenze je Position (1.0 = ohne Hebel,
    wie im Cash-Konto). `allow_holdout` muss explizit gesetzt werden, um
    Tage ab HOLDOUT_START auszuwerten."""
    days, rets, trades, trade_rets = [], [], [], []
    for i in range(strategy.warmup_days, len(sessions)):
        day = sessions[i][0]
        if start is not None and day < start:
            continue
        if end is not None and day > end:
            break
        if day >= HOLDOUT_START and not allow_holdout:
            break
        day_ret = 0.0
        for t in strategy.trades_for_day(sessions, i):
            exposure = min(t.exposure, max_exposure)
            net = exposure * (t.gross_return - costs.round_trip_cost(t))
            day_ret += net
            trades.append(t)
            trade_rets.append(net)
        days.append(day)
        rets.append(day_ret)
    return BacktestResult(
        strategy=strategy.name,
        daily_returns=pd.Series(rets, index=pd.Index(days, name="day"), dtype=float),
        trades=trades,
        trade_net_returns=np.array(trade_rets, dtype=float),
    )

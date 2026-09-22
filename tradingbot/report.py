"""Trading-Report: aggregiert Alpacas Order-Historie zu abgeschlossenen
Trades mit P&L, getrennt nach Handelstag (America/New_York) -- damit sich
auswerten lässt, wie der Live-Bot (momentum_live.py) tatsächlich
abgeschnitten hat, ohne die Order-Historie von Hand aus dem
Alpaca-Dashboard abzutippen."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from alpaca.common.enums import Sort
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, QueryOrderStatus
from alpaca.trading.models import Order
from alpaca.trading.requests import GetOrdersRequest

_NY = ZoneInfo("America/New_York")
# Alpacas Obergrenze pro Anfrage -- bei mehr Orders im Zeitraum wird mit
# einem vorgerückten `after`-Cursor nachpaginiert (siehe fetch_closed_orders).
_PAGE_LIMIT = 500


@dataclass
class MatchedTrade:
    """Ein abgeschlossener Trade: von "flach" (keine Position) über einen
    oder mehrere Kauf-Fills bis wieder "flach" über einen oder mehrere
    Verkaufs-Fills (z.B. Ziel-Teilverkauf + Rest-Ausstieg)."""

    symbol: str
    entry_time: datetime
    exit_time: datetime
    shares: float
    entry_price: float
    exit_price: float
    pnl: float
    pnl_pct: float

    @property
    def trading_day(self) -> date:
        return self.exit_time.astimezone(_NY).date()

    @property
    def duration(self) -> timedelta:
        return self.exit_time - self.entry_time


@dataclass
class OpenPosition:
    """Eine am Ende des angefragten Zeitraums noch offene Position -- kein
    P&L, da kein Ausstiegskurs bekannt ist."""

    symbol: str
    shares: float
    entry_price: float
    entry_time: datetime


@dataclass
class DaySummary:
    day: date
    trades: list[MatchedTrade]

    @property
    def num_trades(self) -> int:
        return len(self.trades)

    @property
    def wins(self) -> int:
        return sum(1 for t in self.trades if t.pnl > 0)

    @property
    def win_rate(self) -> float:
        return self.wins / self.num_trades if self.trades else 0.0

    @property
    def net_pnl(self) -> float:
        return sum(t.pnl for t in self.trades)


def fetch_closed_orders(trading_client: TradingClient, after: datetime, until: datetime) -> list[Order]:
    """Holt alle Orders mit tatsächlicher Ausführung (filled_qty > 0) im
    Zeitraum [after, until], über alle Symbole hinweg, chronologisch
    sortiert. status=CLOSED umfasst auch stornierte/abgelehnte Orders --
    die werden über den filled_qty>0-Filter aussortiert, außer sie hatten
    (wie bei einer Teilausführung vor Stornierung) doch eine Teilmenge
    gefüllt."""
    orders: list[Order] = []
    cursor = after
    while True:
        request = GetOrdersRequest(
            status=QueryOrderStatus.CLOSED, after=cursor, until=until, direction=Sort.ASC, limit=_PAGE_LIMIT
        )
        page = trading_client.get_orders(filter=request)
        if not page:
            break
        orders.extend(page)
        if len(page) < _PAGE_LIMIT:
            break
        last_time = page[-1].submitted_at
        if last_time <= cursor:
            break  # Sicherheitsnetz gegen Endlosschleife bei identischem Zeitstempel
        cursor = last_time

    return [o for o in orders if float(o.filled_qty or 0) > 0]


@dataclass
class UnmatchedSell:
    """Verkaufte Stückzahl ohne zugehörigen Kauf im angefragten Zeitraum --
    die Position wurde VOR Zeitraumbeginn eröffnet. Kein P&L berechenbar
    (Einstiegskurs unbekannt)."""

    symbol: str
    shares: float
    price: float
    time: datetime


def match_trades(orders: list[Order]) -> tuple[list[MatchedTrade], list[OpenPosition], list[UnmatchedSell]]:
    """Fasst Kauf-/Verkaufs-Orders pro Symbol zu abgeschlossenen Trades
    zusammen (Positions-Lebensdauer von "flach" bis wieder "flach").
    Positionen, die am Ende des Zeitraums noch offen sind, werden separat
    als OpenPosition zurückgegeben.

    Verkäufe, die über die im Zeitraum gekaufte Menge hinausgehen (Position
    wurde vor Zeitraumbeginn eröffnet), werden als UnmatchedSell getrennt
    zurückgegeben -- NICHT mit einem späteren Kauf verrechnet, sonst
    entstünde ein Phantom-Trade mit erfundenem P&L und negativer Haltedauer,
    während die tatsächlich noch offene neue Position verschwände."""
    by_symbol: dict[str, list[Order]] = defaultdict(list)
    for o in orders:
        by_symbol[o.symbol].append(o)

    trades: list[MatchedTrade] = []
    open_positions: list[OpenPosition] = []
    unmatched_sells: list[UnmatchedSell] = []

    for symbol, symbol_orders in by_symbol.items():
        symbol_orders.sort(key=lambda o: o.filled_at or o.submitted_at)
        bought_qty = bought_cost = sold_qty = sold_proceeds = 0.0
        entry_time: datetime | None = None
        exit_time: datetime | None = None

        for o in symbol_orders:
            qty = float(o.filled_qty)
            price = float(o.filled_avg_price)
            filled_at = o.filled_at or o.submitted_at

            if o.side == OrderSide.BUY:
                if bought_qty <= 1e-9:
                    entry_time = filled_at
                bought_qty += qty
                bought_cost += qty * price
            else:
                open_qty = bought_qty - sold_qty
                excess = qty - max(open_qty, 0.0)
                if excess > 1e-6:
                    unmatched_sells.append(UnmatchedSell(symbol, excess, price, filled_at))
                    qty -= excess
                if qty <= 1e-9:
                    continue
                sold_qty += qty
                sold_proceeds += qty * price
                exit_time = filled_at

            if bought_qty > 1e-9 and bought_qty - sold_qty <= 1e-6:
                trades.append(
                    MatchedTrade(
                        symbol=symbol,
                        entry_time=entry_time,
                        exit_time=exit_time,
                        shares=bought_qty,
                        entry_price=bought_cost / bought_qty,
                        exit_price=sold_proceeds / sold_qty,
                        pnl=sold_proceeds - bought_cost,
                        pnl_pct=(sold_proceeds - bought_cost) / bought_cost,
                    )
                )
                bought_qty = bought_cost = sold_qty = sold_proceeds = 0.0
                entry_time = exit_time = None

        if bought_qty - sold_qty > 1e-6:
            open_positions.append(
                OpenPosition(
                    symbol=symbol,
                    shares=bought_qty - sold_qty,
                    entry_price=bought_cost / bought_qty,
                    entry_time=entry_time,
                )
            )

    trades.sort(key=lambda t: t.exit_time)
    return trades, open_positions, unmatched_sells


def group_by_trading_day(trades: list[MatchedTrade]) -> dict[date, DaySummary]:
    by_day: dict[date, list[MatchedTrade]] = defaultdict(list)
    for t in trades:
        by_day[t.trading_day].append(t)
    return {day: DaySummary(day=day, trades=by_day[day]) for day in sorted(by_day)}

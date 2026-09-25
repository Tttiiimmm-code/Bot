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


# --- Konto-Vergleich (momentum-compare) ---------------------------------------
#
# Mehrere Bots laufen je auf einem EIGENEN Paper-Konto (der Live-Bot verkauft
# fremde Aktien im Depot, siehe momentum_live._sell_unmanaged_shares) -- der
# Vergleich liest die Order-Historie jedes Kontos getrennt und stellt sie
# nebeneinander, z.B. um zwei Ausstiegsregeln unter identischen Marktbedingungen
# zu vergleichen.

_TRUE = {"true", "1", "yes"}
_FALSE = {"false", "0", "no"}


def read_account_env(path: str) -> tuple[str, str, bool]:
    """Liest ALPACA_API_KEY/ALPACA_SECRET_KEY/ALPACA_PAPER aus einer
    .env-Datei, OHNE die Umgebung des laufenden Prozesses zu verändern (jedes
    Konto braucht seine eigenen Keys)."""
    from dotenv import dotenv_values

    values = dotenv_values(path)
    api_key = (values.get("ALPACA_API_KEY") or "").strip()
    secret_key = (values.get("ALPACA_SECRET_KEY") or "").strip()
    if not api_key or not secret_key:
        raise ValueError(f"{path}: ALPACA_API_KEY und ALPACA_SECRET_KEY müssen gesetzt sein.")
    paper_raw = (values.get("ALPACA_PAPER") or "true").strip().lower()
    if paper_raw not in _TRUE | _FALSE:
        raise ValueError(f"{path}: ALPACA_PAPER muss true/false (oder 1/0, yes/no) sein, nicht {paper_raw!r}.")
    return api_key, secret_key, paper_raw in _TRUE


@dataclass
class AccountStats:
    num_trades: int
    wins: int
    net_pnl: float
    avg_win: float | None
    avg_loss: float | None
    # Summe Gewinne / |Summe Verluste|; None ohne Verlust-Trade (unendlich).
    profit_factor: float | None
    avg_duration: timedelta | None

    @property
    def win_rate(self) -> float:
        return self.wins / self.num_trades if self.num_trades else 0.0


def account_stats(trades: list[MatchedTrade]) -> AccountStats:
    wins = [t.pnl for t in trades if t.pnl > 0]
    losses = [t.pnl for t in trades if t.pnl <= 0]
    gross_loss = -sum(losses)
    return AccountStats(
        num_trades=len(trades),
        wins=len(wins),
        net_pnl=sum(t.pnl for t in trades),
        avg_win=sum(wins) / len(wins) if wins else None,
        avg_loss=sum(losses) / len(losses) if losses else None,
        profit_factor=sum(wins) / gross_loss if gross_loss > 0 else None,
        avg_duration=sum((t.duration for t in trades), timedelta()) / len(trades) if trades else None,
    )


def group_parallel_trades(
    trades_by_account: dict[str, list[MatchedTrade]], tolerance: timedelta = timedelta(minutes=3)
) -> list[dict[str, MatchedTrade]]:
    """Fasst Trades verschiedener Konten zum SELBEN Setup zusammen: gleiches
    Symbol, Einstieg höchstens `tolerance` nach dem ersten Einstieg der
    Gruppe, je Konto höchstens ein Trade. Gruppen mit nur einem Konto zeigen
    Setups, die nur ein Bot gehandelt hat (z.B. Kauf nicht gefüllt oder
    Positionslimit erreicht). Chronologisch nach erstem Einstieg sortiert."""
    entries = sorted(
        ((t.symbol, t.entry_time, account, t) for account, trades in trades_by_account.items() for t in trades),
        key=lambda e: (e[0], e[1]),
    )
    groups: list[tuple[datetime, dict[str, MatchedTrade]]] = []
    current: dict[str, MatchedTrade] | None = None
    current_symbol = current_start = None
    for symbol, entry_time, account, trade in entries:
        if (
            current is None
            or symbol != current_symbol
            or entry_time - current_start > tolerance
            or account in current
        ):
            current = {}
            current_symbol, current_start = symbol, entry_time
            groups.append((entry_time, current))
        current[account] = trade
    groups.sort(key=lambda g: g[0])
    return [g for _, g in groups]

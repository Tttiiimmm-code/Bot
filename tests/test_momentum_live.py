from __future__ import annotations

from datetime import date, datetime, time as dt_time, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest
from alpaca.common.exceptions import APIError
from alpaca.trading.enums import OrderSide, OrderStatus

from tradingbot.momentum import BreakoutEvent, ExitReason, ExitSignal, MomentumEngine
from tradingbot.momentum_live import (
    LiveMomentumBot,
    LiveMomentumConfig,
    _PendingExit,
    _SymbolState,
    _validate_live_config,
)
from tradingbot.scanner import ScanCandidate, ScanCriteria

from tests.test_momentum import DAY_MINUS_1, DAY_MINUS_2, TODAY, bull_flag_setup_bars, build_bars, flat_day, make_day
from tests.test_scanner import FakeCalendarEntry, make_config


def _et(hour: int, minute: int, day: date = TODAY) -> datetime:
    naive = datetime.combine(day, dt_time(hour, minute))
    return naive.replace(tzinfo=ZoneInfo("America/New_York")).astimezone(timezone.utc)


def _make_data_client(symbol: str = "AAPL", extra_today_bars=()) -> "FakeDataClient":
    days = {
        DAY_MINUS_2: flat_day(DAY_MINUS_2, 10, 10.00, 50),
        DAY_MINUS_1: flat_day(DAY_MINUS_1, 10, 10.00, 50),
        TODAY: make_day(TODAY, bull_flag_setup_bars() + list(extra_today_bars)),
    }
    bars_et = build_bars(days)
    return FakeDataClient({symbol: bars_et.tz_convert("UTC")})


def _live_config(**overrides) -> LiveMomentumConfig:
    defaults = dict(
        max_risk_dollars=70.0,
        reward_risk_ratio=2.0,
        min_relative_volume=2.0,
        lookback_days=2,
        daily_trend_window=2,
        flagpole_min_gain_pct=0.05,
        flagpole_max_bars=5,
        min_pullback_bars=2,
        max_pullback_bars=5,
        max_pullback_retrace_pct=0.5,
        extension_multiplier=4.0,
        max_concurrent_positions=3,
        max_tracked_symbols=20,
        daily_max_loss_pct=0.10,
        scan_interval_seconds=300,
        poll_interval_seconds=60,
        # Winzige Werte, damit _wait_for_fill()s echte time.sleep()-Aufrufe
        # bei "Order füllt nie"-Tests die Testlaufzeit nicht spürbar erhöhen.
        order_fill_timeout_seconds=0.05,
        order_poll_interval_seconds=0.01,
        flatten_minutes_before_close=5,
    )
    defaults.update(overrides)
    return LiveMomentumConfig(**defaults)


def _make_candidate(symbol: str) -> ScanCandidate:
    return ScanCandidate(
        symbol=symbol, price=10.05, percent_change=12.0, relative_volume=3.0, has_recent_news=None, sources=["mover"]
    )


class FakeOrder:
    def __init__(self, order_id: str, symbol: str, qty: float, side: OrderSide):
        self.id = order_id
        self.symbol = symbol
        self.qty = qty
        self.side = side
        self.status = OrderStatus.NEW
        self.filled_qty = 0
        self.filled_avg_price = 0.0


class FakeTradingClient:
    """Bildet nur die von LiveMomentumBot genutzten TradingClient-Methoden
    nach. `auto_fill=True` (Standard) füllt jede Order sofort bei
    submit_order() -- für Tests, die eine hängende/nie füllende Order
    simulieren wollen, `auto_fill=False` setzen (Order bleibt NEW, bis der
    Test sie manuell auf FILLED setzt oder cancel_order_by_id() sie storniert)."""

    def __init__(
        self,
        calendar_entries,
        equity: float = 100_000.0,
        cash: float = 100_000.0,
        fill_price: float | None = None,
        auto_fill: bool = True,
        race_fill_on_cancel: bool = False,
        partial_fill_qty_on_cancel: float | None = None,
        reject_immediately: bool = False,
        fail_submit_for_symbol: str | None = None,
    ):
        self._calendar_entries = calendar_entries
        self.equity = equity
        self.cash = cash
        self.fill_price = fill_price
        self.auto_fill = auto_fill
        self.race_fill_on_cancel = race_fill_on_cancel
        # Simuliert einen Order-Abbruch NACH einem Teil-Fill: cancel_order_by_id()
        # setzt Status=CANCELED, aber filled_qty bleibt auf diesem Wert stehen
        # (statt 0) -- reales Alpaca-Verhalten bei einer teilweise
        # ausgeführten, dann stornierten Order.
        self.partial_fill_qty_on_cancel = partial_fill_qty_on_cancel
        # Simuliert eine SOFORTIGE Ablehnung (z.B. Symbol ausgesetzt/nicht
        # leerverkaufbar) -- Status ist bereits beim Absenden terminal
        # (REJECTED, 0 gefüllt), kein Warten/Pollen nötig.
        self.reject_immediately = reject_immediately
        # Simuliert einen API-Fehler beim Senden einer Order für genau
        # dieses Symbol (z.B. transienter APIError).
        self.fail_submit_for_symbol = fail_submit_for_symbol
        # Wenn True, wirft der NÄCHSTE get_order_by_id()-Aufruf einen
        # simulierten APIError (und setzt sich danach selbst zurück) --
        # für Tests, die einen transienten Fehler MITTEN im Warten auf
        # eine bereits platzierte Order simulieren wollen.
        self.raise_on_next_get_order_by_id = False
        self.orders: dict[str, FakeOrder] = {}
        self.submitted_orders: list[FakeOrder] = []
        self.canceled_order_ids: list[str] = []
        self.get_account_calls = 0
        self._next_id = 1

    def get_calendar(self, request):
        return self._calendar_entries

    def get_account(self):
        self.get_account_calls += 1
        return SimpleNamespace(equity=self.equity, cash=self.cash)

    def submit_order(self, order_request):
        if order_request.symbol == self.fail_submit_for_symbol:
            raise APIError("simulierter transienter API-Fehler beim Senden der Order")
        order_id = f"order-{self._next_id}"
        self._next_id += 1
        order = FakeOrder(order_id, order_request.symbol, order_request.qty, order_request.side)
        if self.auto_fill:
            order.status = OrderStatus.FILLED
            order.filled_qty = order_request.qty
            order.filled_avg_price = self.fill_price if self.fill_price is not None else 10.0
        elif self.reject_immediately:
            order.status = OrderStatus.REJECTED
        self.orders[order_id] = order
        self.submitted_orders.append(order)
        return order

    def get_order_by_id(self, order_id):
        if self.raise_on_next_get_order_by_id:
            self.raise_on_next_get_order_by_id = False
            raise APIError("simulierter transienter API-Fehler beim Abfragen der Order")
        return self.orders[order_id]

    def cancel_order_by_id(self, order_id):
        self.canceled_order_ids.append(order_id)
        order = self.orders[order_id]
        if order.status in (OrderStatus.FILLED, OrderStatus.CANCELED, OrderStatus.REJECTED, OrderStatus.EXPIRED):
            return
        if self.race_fill_on_cancel:
            order.status = OrderStatus.FILLED
            order.filled_qty = order.qty
            order.filled_avg_price = self.fill_price if self.fill_price is not None else 10.0
        elif self.partial_fill_qty_on_cancel is not None:
            order.status = OrderStatus.CANCELED
            order.filled_qty = self.partial_fill_qty_on_cancel
            order.filled_avg_price = self.fill_price if self.fill_price is not None else 10.0
        else:
            order.status = OrderStatus.CANCELED


class FakeDataClient:
    def __init__(self, bars_by_symbol: dict[str, pd.DataFrame]):
        self._bars_by_symbol = bars_by_symbol

    def get_stock_bars(self, request):
        symbols = request.symbol_or_symbols
        if isinstance(symbols, str):
            symbols = [symbols]
        start = pd.Timestamp(request.start)
        end = pd.Timestamp(request.end)
        if start.tzinfo is None:
            start = start.tz_localize("UTC")
        if end.tzinfo is None:
            end = end.tz_localize("UTC")

        frames = []
        for symbol in symbols:
            full = self._bars_by_symbol.get(symbol)
            if full is None:
                continue
            sliced = full[(full.index >= start) & (full.index <= end)]
            if sliced.empty:
                continue
            idx = pd.MultiIndex.from_arrays([[symbol] * len(sliced), sliced.index], names=["symbol", "timestamp"])
            frames.append(pd.DataFrame(sliced.values, index=idx, columns=sliced.columns))

        if not frames:
            return SimpleNamespace(df=pd.DataFrame(columns=["open", "high", "low", "close", "volume"]))
        return SimpleNamespace(df=pd.concat(frames))


class FakeScanner:
    def __init__(self, candidates: list[ScanCandidate]):
        self.candidates = candidates
        self.scan_calls = 0

    def scan(self, criteria, reference_time=None):
        self.scan_calls += 1
        return self.candidates


def _make_engine(live_config: LiveMomentumConfig) -> MomentumEngine:
    return MomentumEngine(
        flagpole_min_gain_pct=live_config.flagpole_min_gain_pct,
        flagpole_max_bars=live_config.flagpole_max_bars,
        min_pullback_bars=live_config.min_pullback_bars,
        max_pullback_bars=live_config.max_pullback_bars,
        max_pullback_retrace_pct=live_config.max_pullback_retrace_pct,
        reward_risk_ratio=live_config.reward_risk_ratio,
        extension_multiplier=live_config.extension_multiplier,
        min_relative_volume=live_config.min_relative_volume,
    )


def _entered_engine(
    live_config: LiveMomentumConfig, shares: int = 10, entry_price: float = 10.0, stop_price: float = 9.0
) -> MomentumEngine:
    """Baut eine MomentumEngine, die direkt schon IN_POSITION ist -- über
    die öffentliche record_entry()-API statt process_bar(), für Tests, die
    nur den Order-/Zustands-Umgang um eine bereits offene Position prüfen
    wollen, ohne erst ein echtes Bull-Flag-Setup durchzuspielen."""
    engine = _make_engine(live_config)
    engine._pending_breakout = BreakoutEvent(
        "BULL_FLAG", pd.Timestamp.now(tz="UTC"), entry_price, stop_price, entry_price - stop_price
    )
    engine.record_entry(shares, entry_price, pd.Timestamp.now(tz="UTC"))
    return engine


def _make_bot(data_client, trading_client, scanner, live_config=None) -> LiveMomentumBot:
    return LiveMomentumBot(
        make_config(),
        ScanCriteria(),
        live_config or _live_config(),
        scanner=scanner,
        trading_client=trading_client,
        data_client=data_client,
    )


# ---------------------------------------------------------------------------
# _validate_live_config
# ---------------------------------------------------------------------------


def test_validate_live_config_rejects_swapped_trading_window():
    config = _live_config(trading_window_start=dt_time(11, 30), trading_window_end=dt_time(9, 30))
    with pytest.raises(ValueError, match="trading_window_start"):
        _validate_live_config(config)


def test_validate_live_config_rejects_max_tracked_below_max_concurrent():
    config = _live_config(max_concurrent_positions=5, max_tracked_symbols=3)
    with pytest.raises(ValueError, match="max_tracked_symbols"):
        _validate_live_config(config)


def test_validate_live_config_rejects_daily_max_loss_out_of_range():
    config = _live_config(daily_max_loss_pct=0.0)
    with pytest.raises(ValueError, match="daily_max_loss_pct"):
        _validate_live_config(config)


# ---------------------------------------------------------------------------
# run_once: Sitzungsgrenzen / Tageswechsel
# ---------------------------------------------------------------------------


def test_run_once_outside_session_does_nothing():
    trading_client = FakeTradingClient([FakeCalendarEntry(TODAY)])
    scanner = FakeScanner([])
    bot = _make_bot(FakeDataClient({}), trading_client, scanner)

    bot.run_once(now=_et(7, 0))  # vor Handelsbeginn (9:30 ET)

    assert scanner.scan_calls == 0
    assert trading_client.get_account_calls == 0


def test_new_trading_day_resets_state():
    trading_client = FakeTradingClient([FakeCalendarEntry(TODAY)])
    scanner = FakeScanner([])
    bot = _make_bot(FakeDataClient({}), trading_client, scanner)

    bot.run_once(now=_et(9, 31))
    assert bot._trading_day == TODAY
    assert bot._day_start_equity == pytest.approx(100_000.0)

    tomorrow = date(2024, 1, 11)
    trading_client._calendar_entries = [FakeCalendarEntry(tomorrow)]
    bot._halted = True  # simuliert Restzustand vom Vortag

    # Ein Symbol ohne offene Position/ausstehende Order wird verworfen wie
    # bisher; ein Symbol mit noch ausstehender Verkaufs-Order wird trotz
    # Tageswechsel NICHT verworfen (siehe _start_new_day).
    closed_state = _SymbolState(
        engine=_make_engine(bot.live_config), rel_vol_reference=np.array([]), daily_sma=None,
        session_open=_et(9, 30),
    )
    bot._symbols["CLOSED"] = closed_state
    stuck_state = _SymbolState(
        engine=_make_engine(bot.live_config), rel_vol_reference=np.array([]), daily_sma=None,
        session_open=_et(9, 30),
        pending_exit=_PendingExit(order_id="order-stuck", event=None),
    )
    bot._symbols["STUCK"] = stuck_state
    # Muss beim TradingClient "existieren", da _resolve_pending_exits() sie
    # bei jedem run_once()-Aufruf abfragt (Status bleibt absichtlich NEW,
    # damit der Test nur den Tageswechsel-Zustand prüft, nicht die
    # Order-Auflösung selbst).
    trading_client.orders["order-stuck"] = FakeOrder("order-stuck", "STUCK", 10, OrderSide.SELL)

    bot.run_once(now=_et(9, 31, day=tomorrow))

    assert bot._trading_day == tomorrow
    assert bot._halted is False
    assert "CLOSED" not in bot._symbols
    assert "STUCK" in bot._symbols
    assert bot._symbols["STUCK"] is stuck_state
    assert bot._day_start_equity == pytest.approx(100_000.0)


# ---------------------------------------------------------------------------
# _rescan / _build_symbol_context
# ---------------------------------------------------------------------------


def test_rescan_adds_candidate_with_valid_context():
    data_client = _make_data_client("AAPL")
    trading_client = FakeTradingClient([FakeCalendarEntry(TODAY)])
    scanner = FakeScanner([_make_candidate("AAPL")])
    bot = _make_bot(data_client, trading_client, scanner)

    bot._rescan(_et(9, 31), FakeCalendarEntry(TODAY))

    assert "AAPL" in bot._symbols
    state = bot._symbols["AAPL"]
    assert state.daily_sma == pytest.approx(10.00)
    assert len(state.rel_vol_reference) == 10


def test_rescan_skips_symbol_with_insufficient_history():
    data_client = FakeDataClient({})  # keine Daten für NOPE
    trading_client = FakeTradingClient([FakeCalendarEntry(TODAY)])
    scanner = FakeScanner([_make_candidate("NOPE")])
    bot = _make_bot(data_client, trading_client, scanner)

    bot._rescan(_et(9, 31), FakeCalendarEntry(TODAY))

    assert "NOPE" not in bot._symbols


def test_rescan_respects_max_tracked_symbols():
    bundle: dict[str, pd.DataFrame] = {}
    candidates = []
    for i in range(3):
        symbol = f"SYM{i}"
        days = {
            DAY_MINUS_2: flat_day(DAY_MINUS_2, 10, 10.00, 50),
            DAY_MINUS_1: flat_day(DAY_MINUS_1, 10, 10.00, 50),
        }
        bundle[symbol] = build_bars(days).tz_convert("UTC")
        candidates.append(_make_candidate(symbol))

    data_client = FakeDataClient(bundle)
    trading_client = FakeTradingClient([FakeCalendarEntry(TODAY)])
    scanner = FakeScanner(candidates)
    bot = _make_bot(
        data_client, trading_client, scanner, live_config=_live_config(max_tracked_symbols=2, max_concurrent_positions=2)
    )

    bot._rescan(_et(9, 31), FakeCalendarEntry(TODAY))

    assert len(bot._symbols) == 2


# ---------------------------------------------------------------------------
# Einstieg (Breakout -> Order -> Fill)
# ---------------------------------------------------------------------------


def test_full_cycle_detects_breakout_and_enters_position():
    data_client = _make_data_client("AAPL")
    trading_client = FakeTradingClient([FakeCalendarEntry(TODAY)], fill_price=12.20)
    scanner = FakeScanner([_make_candidate("AAPL")])
    bot = _make_bot(data_client, trading_client, scanner)

    bot.run_once(now=_et(9, 36))

    state = bot._symbols["AAPL"]
    assert state.engine.in_position
    # risk/share = 12.20 - 11.30 = 0.90; shares = floor(70 / 0.90) = 77
    assert state.engine.shares_open == 77
    buy_orders = [o for o in trading_client.submitted_orders if o.side == OrderSide.BUY]
    assert len(buy_orders) == 1
    assert buy_orders[0].qty == 77


def test_breakout_declined_when_max_concurrent_positions_reached():
    days_common = {
        DAY_MINUS_2: flat_day(DAY_MINUS_2, 10, 10.00, 50),
        DAY_MINUS_1: flat_day(DAY_MINUS_1, 10, 10.00, 50),
    }
    bars_a = build_bars({**days_common, TODAY: make_day(TODAY, bull_flag_setup_bars())}).tz_convert("UTC")
    bars_b = build_bars({**days_common, TODAY: make_day(TODAY, bull_flag_setup_bars())}).tz_convert("UTC")
    data_client = FakeDataClient({"AAA": bars_a, "BBB": bars_b})
    trading_client = FakeTradingClient([FakeCalendarEntry(TODAY)], fill_price=12.20)
    scanner = FakeScanner([_make_candidate("AAA"), _make_candidate("BBB")])
    bot = _make_bot(data_client, trading_client, scanner, live_config=_live_config(max_concurrent_positions=1))

    bot.run_once(now=_et(9, 36))

    assert bot._symbols["AAA"].engine.in_position
    assert not bot._symbols["BBB"].engine.in_position
    assert bot._symbols["BBB"].engine.state == "SEARCHING"
    buy_orders = [o for o in trading_client.submitted_orders if o.side == OrderSide.BUY]
    assert len(buy_orders) == 1


def test_buy_order_timeout_cancels_and_declines_entry():
    data_client = _make_data_client("AAPL")
    trading_client = FakeTradingClient([FakeCalendarEntry(TODAY)], auto_fill=False)
    scanner = FakeScanner([_make_candidate("AAPL")])
    bot = _make_bot(data_client, trading_client, scanner)

    bot.run_once(now=_et(9, 36))

    state = bot._symbols["AAPL"]
    assert not state.engine.in_position
    assert state.engine.state == "SEARCHING"
    buy_orders = [o for o in trading_client.submitted_orders if o.side == OrderSide.BUY]
    assert len(buy_orders) == 1
    assert buy_orders[0].status == OrderStatus.CANCELED
    assert trading_client.canceled_order_ids == [buy_orders[0].id]


def test_buy_order_race_fill_during_cancel_is_still_recorded():
    """Deckt die in _handle_breakout dokumentierte Race-Bedingung ab: die
    Order wird GENAU während des Stornierungsversuchs doch noch gefüllt --
    der Einstieg muss trotzdem verbucht werden, statt eine reale, aber vom
    Bot unbemerkte Position zu hinterlassen."""
    data_client = _make_data_client("AAPL")
    trading_client = FakeTradingClient(
        [FakeCalendarEntry(TODAY)], auto_fill=False, race_fill_on_cancel=True, fill_price=12.20
    )
    scanner = FakeScanner([_make_candidate("AAPL")])
    bot = _make_bot(data_client, trading_client, scanner)

    bot.run_once(now=_et(9, 36))

    state = bot._symbols["AAPL"]
    assert state.engine.in_position
    assert state.engine.shares_open == 77


# ---------------------------------------------------------------------------
# Ausstieg (Exit-Signal -> Order -> Fill)
# ---------------------------------------------------------------------------


def test_stop_loss_exit_fills_and_closes_position():
    extra_bars = [{"open": 12.20, "high": 12.20, "low": 11.20, "close": 11.25, "volume": 100}]
    data_client = _make_data_client("AAPL", extra_today_bars=extra_bars)
    trading_client = FakeTradingClient([FakeCalendarEntry(TODAY)], fill_price=12.20)
    scanner = FakeScanner([_make_candidate("AAPL")])
    bot = _make_bot(data_client, trading_client, scanner)

    # now=9:35 ET holt nur die Bars bis zum Einstieg (bar5) -- der
    # Stop-Bar (bar6, 9:36 ET) darf hier noch NICHT mit abgeholt werden,
    # sonst würde der Einstieg im selben Zyklus schon wieder geschlossen.
    bot.run_once(now=_et(9, 35))
    assert bot._symbols["AAPL"].engine.in_position

    trading_client.fill_price = 11.30
    bot.run_once(now=_et(9, 37))

    state = bot._symbols["AAPL"]
    assert not state.engine.in_position
    sell_orders = [o for o in trading_client.submitted_orders if o.side == OrderSide.SELL]
    assert len(sell_orders) == 1
    assert sell_orders[0].qty == 77


def test_sell_order_timeout_creates_pending_exit_and_resolves_next_cycle():
    extra_bars = [{"open": 12.20, "high": 12.20, "low": 11.20, "close": 11.25, "volume": 100}]
    data_client = _make_data_client("AAPL", extra_today_bars=extra_bars)
    trading_client = FakeTradingClient([FakeCalendarEntry(TODAY)], fill_price=12.20)
    scanner = FakeScanner([_make_candidate("AAPL")])
    bot = _make_bot(data_client, trading_client, scanner)

    bot.run_once(now=_et(9, 35))  # nur bis zum Einstieg (bar5), siehe oben
    assert bot._symbols["AAPL"].engine.in_position

    trading_client.auto_fill = False
    bot.run_once(now=_et(9, 37))  # Stop ausgelöst, Verkaufs-Order füllt nicht

    state = bot._symbols["AAPL"]
    assert state.pending_exit is not None
    assert state.engine.in_position  # Engine hält Position bis record_exit() für offen

    pending_order = trading_client.orders[state.pending_exit.order_id]
    pending_order.status = OrderStatus.FILLED
    pending_order.filled_qty = pending_order.qty
    pending_order.filled_avg_price = 11.30

    bot.run_once(now=_et(9, 38))  # keine neuen Balken, nur pending-exit-Auflösung

    assert state.pending_exit is None
    assert not state.engine.in_position


def test_daily_max_loss_circuit_breaker_flattens_and_halts():
    data_client = _make_data_client("AAPL")
    trading_client = FakeTradingClient([FakeCalendarEntry(TODAY)], fill_price=12.20, equity=100_000.0)
    scanner = FakeScanner([_make_candidate("AAPL")])
    bot = _make_bot(data_client, trading_client, scanner, live_config=_live_config(daily_max_loss_pct=0.05, scan_interval_seconds=1))

    bot.run_once(now=_et(9, 36))
    assert bot._symbols["AAPL"].engine.in_position

    trading_client.equity = 94_000.0  # -6% Drawdown, über dem 5%-Limit
    trading_client.fill_price = 11.00
    bot.run_once(now=_et(9, 37))

    assert bot._halted is True
    assert not bot._symbols["AAPL"].engine.in_position
    sell_orders = [o for o in trading_client.submitted_orders if o.side == OrderSide.SELL]
    assert len(sell_orders) == 1

    scan_calls_before = scanner.scan_calls
    bot.run_once(now=_et(9, 40))
    assert scanner.scan_calls == scan_calls_before  # keine neuen Scans nach Pausierung


def test_end_of_day_flatten_closes_open_positions():
    data_client = _make_data_client("AAPL")
    trading_client = FakeTradingClient([FakeCalendarEntry(TODAY)], fill_price=12.20)
    scanner = FakeScanner([_make_candidate("AAPL")])
    bot = _make_bot(data_client, trading_client, scanner, live_config=_live_config(flatten_minutes_before_close=5))

    bot.run_once(now=_et(9, 36))
    assert bot._symbols["AAPL"].engine.in_position

    trading_client.fill_price = 12.50
    bot.run_once(now=_et(15, 56))  # 4 Min vor Sitzungsende (16:00 ET)

    assert bot._flatten_triggered_today is True
    assert not bot._symbols["AAPL"].engine.in_position


# ---------------------------------------------------------------------------
# Regressionstests aus dem Code-Review-Durchlauf
# ---------------------------------------------------------------------------


def test_build_symbol_context_fetches_enough_history_for_daily_trend_window():
    """Regressionstest: calendar_days wurde früher nur aus lookback_days
    berechnet. Mit lookback_days < daily_trend_window (wie in den
    Standardwerten 20/50) wurde dadurch nie genug Historie abgefragt, um
    daily_sma überhaupt zu berechnen -- der Bot hätte lautlos NIE einen
    Trade platziert, weil daily_trend_ok für immer False geblieben wäre."""
    today = date(2024, 1, 21)
    days = {date(2024, 1, i): flat_day(date(2024, 1, i), 5, 10.00, 50) for i in range(1, 21)}
    days[today] = make_day(today, bull_flag_setup_bars())
    bars = build_bars(days).tz_convert("UTC")

    data_client = FakeDataClient({"AAPL": bars})
    trading_client = FakeTradingClient([FakeCalendarEntry(today)])
    scanner = FakeScanner([])
    bot = _make_bot(
        data_client, trading_client, scanner, live_config=_live_config(lookback_days=2, daily_trend_window=20)
    )

    session = FakeCalendarEntry(today)
    context = bot._build_symbol_context("AAPL", _et(9, 31, day=today), session)

    assert context is not None
    _, daily_sma, _ = context
    assert daily_sma == pytest.approx(10.00)


def test_buy_order_partial_fill_before_cancel_is_recorded():
    """Regressionstest: ein Order-Abbruch NACH einem Teil-Fill (Status
    CANCELED, aber filled_qty > 0) muss trotzdem als (Teil-)Einstieg
    verbucht werden -- sonst blieben real gekaufte Aktien ohne Stop/Ziel in
    der Engine unbewacht (der ursprüngliche Code prüfte nur
    `status == FILLED` und verwarf jeden anderen Endzustand komplett)."""
    data_client = _make_data_client("AAPL")
    trading_client = FakeTradingClient(
        [FakeCalendarEntry(TODAY)], auto_fill=False, partial_fill_qty_on_cancel=40, fill_price=12.20
    )
    scanner = FakeScanner([_make_candidate("AAPL")])
    bot = _make_bot(data_client, trading_client, scanner)

    bot.run_once(now=_et(9, 36))

    state = bot._symbols["AAPL"]
    assert state.engine.in_position
    assert state.engine.shares_open == 40
    buy_orders = [o for o in trading_client.submitted_orders if o.side == OrderSide.BUY]
    assert len(buy_orders) == 1
    assert buy_orders[0].status == OrderStatus.CANCELED
    assert buy_orders[0].filled_qty == 40


def test_pending_exit_partial_fill_before_cancel_resubmits_only_remainder():
    """Regressionstest: löst sich eine ausstehende Verkaufs-Order mit
    Status CANCELED/REJECTED/EXPIRED auf, aber filled_qty > 0, muss der
    bereits verkaufte Teil verbucht und NUR der tatsächliche Rest neu
    verkauft werden -- nicht die ursprüngliche volle Stückzahl noch einmal
    (der ursprüngliche Code resubmittierte immer pending.event.shares
    unverändert, was zu einer Overselling-Order geführt hätte)."""
    extra_bars = [{"open": 12.20, "high": 12.20, "low": 11.20, "close": 11.25, "volume": 100}]
    data_client = _make_data_client("AAPL", extra_today_bars=extra_bars)
    trading_client = FakeTradingClient([FakeCalendarEntry(TODAY)], fill_price=12.20)
    scanner = FakeScanner([_make_candidate("AAPL")])
    bot = _make_bot(data_client, trading_client, scanner)

    bot.run_once(now=_et(9, 35))  # Einstieg, 77 Stück
    assert bot._symbols["AAPL"].engine.shares_open == 77

    trading_client.auto_fill = False
    bot.run_once(now=_et(9, 37))  # Stop ausgelöst, Verkaufs-Order hängt

    state = bot._symbols["AAPL"]
    pending_order_id = state.pending_exit.order_id
    pending_order = trading_client.orders[pending_order_id]
    pending_order.status = OrderStatus.CANCELED
    pending_order.filled_qty = 30
    pending_order.filled_avg_price = 11.28

    trading_client.auto_fill = True  # die neu gesendete Rest-Order soll sofort füllen
    trading_client.fill_price = 11.30
    bot.run_once(now=_et(9, 38))  # keine neuen Balken, nur pending-exit-Auflösung

    assert state.engine.shares_open == 0
    assert not state.engine.in_position
    sell_orders = [o for o in trading_client.submitted_orders if o.side == OrderSide.SELL]
    assert len(sell_orders) == 2
    assert sell_orders[1].qty == 47  # 77 - 30 bereits verbucht, NICHT nochmal 77


def test_second_exit_signal_on_same_bar_is_deferred_not_dropped_when_first_is_pending():
    """Regressionstest: treffen TARGET- und EXTENSION-Ausstieg auf
    DEMSELBEN Balken zu (siehe tests/test_momentum.py::
    test_target_and_extension_can_both_fire_on_the_same_bar) und die
    TARGET-Verkaufs-Order füllt nicht sofort, darf das EXTENSION-Signal
    nicht stillschweigend verloren gehen -- es muss zurückgestellt und
    nachgeholt werden, sobald sich die TARGET-Order auflöst."""
    # avg_bar_range der 3 Pullback-Bars ist 0.5833; extension_multiplier=4.0
    # braucht Balkenspanne >= 2.333. high=14.60,low=12.20 (Spanne 2.40),
    # close=14.50 (> Einstieg 12.20) -- identisch zum Backtest-Regressionstest.
    extra_bars = [{"open": 12.20, "high": 14.60, "low": 12.20, "close": 14.50, "volume": 500}]
    data_client = _make_data_client("AAPL", extra_today_bars=extra_bars)
    trading_client = FakeTradingClient([FakeCalendarEntry(TODAY)], fill_price=12.20)
    scanner = FakeScanner([_make_candidate("AAPL")])
    bot = _make_bot(data_client, trading_client, scanner)

    bot.run_once(now=_et(9, 35))  # Einstieg, 77 Stück
    assert bot._symbols["AAPL"].engine.shares_open == 77

    trading_client.auto_fill = False  # TARGET-Verkaufs-Order fuellt nicht sofort
    bot.run_once(now=_et(9, 37))  # bar6: TARGET + EXTENSION auf demselben Balken

    state = bot._symbols["AAPL"]
    assert state.pending_exit is not None
    assert len(state.deferred_exits) == 1
    assert state.deferred_exits[0].reason == ExitReason.EXTENSION
    sell_orders_before = len([o for o in trading_client.submitted_orders if o.side == OrderSide.SELL])
    assert sell_orders_before == 1  # nur die TARGET-Order, EXTENSION noch nicht gesendet

    # TARGET-Order fuellt jetzt (halbe Position), danach soll die
    # zurückgestellte EXTENSION-Order fuer den Rest automatisch nachgeholt werden.
    pending_order = trading_client.orders[state.pending_exit.order_id]
    pending_order.status = OrderStatus.FILLED
    pending_order.filled_qty = pending_order.qty
    pending_order.filled_avg_price = 14.00

    trading_client.auto_fill = True
    trading_client.fill_price = 14.50
    bot.run_once(now=_et(9, 38))  # keine neuen Balken, nur pending-/deferred-exit-Auflösung

    assert state.pending_exit is None
    assert state.deferred_exits == []
    assert not state.engine.in_position
    sell_orders = [o for o in trading_client.submitted_orders if o.side == OrderSide.SELL]
    assert len(sell_orders) == 2
    assert sell_orders[1].qty == 77 - 77 // 2  # EXTENSION-Rest


def test_resolve_pending_exits_runs_even_after_session_close():
    """Regressionstest: _resolve_pending_exits() wurde früher erst NACH dem
    "außerhalb der Sitzung"-Check aufgerufen -- eine kurz vor Sitzungsende
    platzierte Verkaufs-Order, die beim Überschreiten von session_close
    noch nicht bestätigt war, wurde dadurch nie wieder abgefragt."""
    data_client = _make_data_client("AAPL")
    trading_client = FakeTradingClient([FakeCalendarEntry(TODAY)], fill_price=12.20)
    scanner = FakeScanner([_make_candidate("AAPL")])
    bot = _make_bot(data_client, trading_client, scanner)

    bot.run_once(now=_et(9, 35))
    state = bot._symbols["AAPL"]
    assert state.engine.in_position

    # Eine ausstehende Verkaufs-Order manuell simulieren (z.B. vom
    # EOD-Flatten kurz vor Sitzungsende ausgelöst, aber nicht bestätigt).
    order = trading_client.submit_order(
        SimpleNamespace(symbol="AAPL", qty=state.engine.shares_open, side=OrderSide.SELL)
    )
    trading_client.orders[order.id].status = OrderStatus.NEW
    trading_client.orders[order.id].filled_qty = 0
    state.pending_exit = _PendingExit(order_id=order.id, event=state.engine.force_exit(_et(9, 40), 12.50))

    # Order fuellt sich NACH Sitzungsende.
    trading_client.orders[order.id].status = OrderStatus.FILLED
    trading_client.orders[order.id].filled_qty = state.engine.shares_open
    trading_client.orders[order.id].filled_avg_price = 12.50

    bot.run_once(now=_et(16, 5))  # 5 Min NACH Sitzungsende (16:00 ET)

    assert state.pending_exit is None
    assert not state.engine.in_position


def test_reconcile_terminal_exit_order_returns_remainder_of_event_not_full_engine_position():
    """Regressionstest (2. Review-Runde): _reconcile_terminal_exit_order()
    gab für die verbleibende Stückzahl früher state.engine.shares_open
    zurück (die GESAMTE offene Restmenge) statt event.shares - filled_qty
    (nur den Rest DIESES Ereignisses). Bei zwei Ausstiegssignalen auf
    demselben Balken (z.B. TARGET-Hälfte + EXTENSION-Rest) hätte das dazu
    geführt, dass eine erneut gesendete TARGET-Order auch die für
    EXTENSION vorgesehenen Stücke mit beansprucht -- eine doppelt
    beauftragte Verkaufsmenge, sobald auch das EXTENSION-Ereignis
    verarbeitet wird."""
    data_client = _make_data_client("AAPL")
    trading_client = FakeTradingClient([FakeCalendarEntry(TODAY)], fill_price=12.20)
    scanner = FakeScanner([_make_candidate("AAPL")])
    bot = _make_bot(data_client, trading_client, scanner)
    bot.run_once(now=_et(9, 35))  # Einstieg, 77 Stück
    state = bot._symbols["AAPL"]
    assert state.engine.shares_open == 77

    # event deckt NUR die TARGET-Hälfte ab (38 von 77) -- ein
    # Geschwister-Ereignis (EXTENSION, 39 Stück) existiert unabhängig davon.
    target_event = ExitSignal(ExitReason.TARGET, pd.Timestamp.now(tz="UTC"), 14.00, 38)
    fake_order = SimpleNamespace(status=OrderStatus.CANCELED, filled_qty=20, filled_avg_price=14.00)

    retry_event = bot._reconcile_terminal_exit_order("AAPL", state, fake_order, target_event)

    assert retry_event is not None
    assert retry_event.shares == 18  # 38 - 20, NICHT engine.shares_open (77-20=57)
    assert state.engine.shares_open == 57  # nur die 20 TARGET-Stück verbucht


def test_carried_over_in_position_is_force_flattened_immediately_on_new_day():
    """Regressionstest (2. Review-Runde): eine Position OHNE pending_exit,
    die über einen Tageswechsel hinweg übernommen wird (z.B. verpasster
    Flatten-Cutoff durch einen Bot-Ausfall über Nacht), muss SOFORT
    zwangsweise glattgestellt werden -- sonst würde _process_new_bars mit
    dem session_open/rel_vol_reference des VORHERIGEN Tages weiterrechnen
    (minute_index weit außerhalb von rel_vol_reference) und das Symbol
    dauerhaft, aber lautlos untradebar machen, statt einen Platz in
    max_tracked_symbols freizugeben."""
    yesterday = date(2024, 1, 9)
    trading_client = FakeTradingClient([FakeCalendarEntry(TODAY)], fill_price=12.20)
    scanner = FakeScanner([])
    bot = _make_bot(FakeDataClient({}), trading_client, scanner)

    state = _SymbolState(
        engine=_entered_engine(bot.live_config, shares=50, entry_price=12.20, stop_price=11.30),
        rel_vol_reference=np.array([50.0, 100.0]),
        daily_sma=10.0,
        session_open=_et(9, 30, day=yesterday),
        last_close=12.50,
    )
    bot._symbols["AAPL"] = state
    bot._trading_day = yesterday

    bot.run_once(now=_et(9, 31))  # neuer Handelstag (TODAY)

    assert bot._trading_day == TODAY
    sell_orders = [o for o in trading_client.submitted_orders if o.side == OrderSide.SELL]
    assert len(sell_orders) == 1
    assert sell_orders[0].qty == 50
    assert "AAPL" not in bot._symbols  # sofort gefuellt -> Aufraeumung entfernt es wieder


def test_resolve_pending_exits_isolates_exceptions_per_symbol():
    """Regressionstest (2. Review-Runde): _resolve_pending_exits() hatte
    keine Fehlerisolierung pro Symbol -- ein Fehler bei EINEM Symbol (z.B.
    ein transienter APIError bei get_order_by_id) hätte verhindert, dass
    alle ANDEREN Symbole mit eigenen, ggf. zeitkritischen ausstehenden
    Verkaufs-Orders im selben Zyklus noch geprüft werden."""
    trading_client = FakeTradingClient([FakeCalendarEntry(TODAY)], fill_price=10.0)
    scanner = FakeScanner([])
    bot = _make_bot(FakeDataClient({}), trading_client, scanner)

    broken_state = _SymbolState(
        engine=_make_engine(bot.live_config), rel_vol_reference=np.array([]), daily_sma=None,
        session_open=_et(9, 30),
        # order_id existiert nicht im FakeTradingClient -> KeyError bei get_order_by_id.
        pending_exit=_PendingExit(order_id="does-not-exist", event=None),
    )
    bot._symbols["BROKEN"] = broken_state

    good_engine = _entered_engine(bot.live_config, shares=10, entry_price=10.0, stop_price=9.0)
    good_order = trading_client.submit_order(SimpleNamespace(symbol="GOOD", qty=10, side=OrderSide.SELL))
    good_state = _SymbolState(
        engine=good_engine, rel_vol_reference=np.array([]), daily_sma=None, session_open=_et(9, 30),
        pending_exit=_PendingExit(
            order_id=good_order.id, event=ExitSignal(ExitReason.STOP, pd.Timestamp.now(tz="UTC"), 10.0, 10)
        ),
    )
    bot._symbols["GOOD"] = good_state

    bot._resolve_pending_exits()

    assert "BROKEN" in bot._symbols
    assert broken_state.pending_exit is not None  # unveraendert, wird im naechsten Zyklus erneut versucht
    assert good_state.pending_exit is None  # GOOD wurde trotzdem erfolgreich aufgeloest
    assert not good_state.engine.in_position


def test_start_new_day_preserves_deferred_exits_when_pending_exit_survives():
    """Regressionstest (3. Review-Runde): _start_new_day() leerte
    deferred_exits früher UNBEDINGT für jedes übernommene Symbol -- auch
    wenn dessen pending_exit selbst den Tageswechsel übersteht (kein
    Zwangs-Glattstellen ausgelöst). Ein dabei zurückgestelltes
    Geschwister-Ausstiegssignal (z.B. der EXTENSION-Rest nach einem noch
    unbestätigten TARGET-Teilverkauf) ging dadurch STILLSCHWEIGEND
    verloren, statt -- wie bei jedem anderen deferred_exits-Eintrag --
    nach Auflösung des pending_exit nachgeholt zu werden."""
    yesterday = date(2024, 1, 9)
    trading_client = FakeTradingClient([FakeCalendarEntry(TODAY)])
    scanner = FakeScanner([])
    bot = _make_bot(FakeDataClient({}), trading_client, scanner)

    engine = _entered_engine(bot.live_config, shares=77, entry_price=12.20, stop_price=11.30)
    deferred_event = ExitSignal(ExitReason.EXTENSION, pd.Timestamp.now(tz="UTC"), 14.50, 39)
    pending = _PendingExit(
        order_id="order-target",
        event=ExitSignal(ExitReason.TARGET, pd.Timestamp.now(tz="UTC"), 14.00, 38),
    )
    state = _SymbolState(
        engine=engine, rel_vol_reference=np.array([50.0, 100.0]), daily_sma=10.0,
        session_open=_et(9, 30, day=yesterday), pending_exit=pending, deferred_exits=[deferred_event],
    )
    trading_client.orders["order-target"] = FakeOrder("order-target", "AAPL", 38, OrderSide.SELL)
    bot._symbols["AAPL"] = state
    bot._trading_day = yesterday

    bot._start_new_day(FakeCalendarEntry(TODAY), _et(9, 31))

    assert state.deferred_exits == [deferred_event]
    assert state.pending_exit is pending
    assert "AAPL" in bot._symbols


def test_deferred_exit_blocks_further_bars_in_same_fetch_batch():
    """Regressionstest (3. Review-Runde): _submit_exit()s 'Retries
    erschöpft'-Zweig legte eine unverkaufte Restmenge früher NUR in
    deferred_exits ab, OHNE state.pending_exit zu setzen -- der einzige
    Fortsetzungs-Wächter in _process_new_bars prüfte aber nur
    pending_exit, nicht deferred_exits. Enthielt ein einzelner Abruf
    mehrere neue Balken (z.B. nach einer Unterbrechung), wurde die Engine
    trotz eines noch unerledigten Ausstiegssignals mit dem NÄCHSTEN Balken
    weiter gefüttert -- mit einem shares_open-Stand, der den fehlgeschlagenen
    Verkauf nicht widerspiegelte, und konnte so ein zweites, sich
    überschneidendes Ausstiegssignal für dieselben Aktien erzeugen."""
    # bar6: rote Kerze VOR Zielerreichung -> RED_CANDLE-Vollausstieg (77 Stück).
    # bar7: Kurs fällt unter den Stop -> STOP-Vollausstieg (falls die Engine
    # fälschlich weiterläuft, obwohl bar6s Ausstieg nie verbucht wurde).
    extra_bars = [
        {"open": 12.20, "high": 12.22, "low": 12.05, "close": 12.10, "volume": 100},  # bar6: RED_CANDLE
        {"open": 11.20, "high": 11.25, "low": 11.00, "close": 11.05, "volume": 100},  # bar7: STOP
    ]
    data_client = _make_data_client("AAPL", extra_today_bars=extra_bars)
    trading_client = FakeTradingClient([FakeCalendarEntry(TODAY)], fill_price=12.20)
    scanner = FakeScanner([_make_candidate("AAPL")])
    bot = _make_bot(data_client, trading_client, scanner)

    bot.run_once(now=_et(9, 35))  # Einstieg, 77 Stück (Kauf-Order fuellt sofort)
    state = bot._symbols["AAPL"]
    assert state.engine.shares_open == 77

    # Erst JETZT auf "jede Verkaufs-Order wird sofort abgelehnt" umstellen --
    # der Einstieg selbst soll ungestoert gelingen.
    trading_client.auto_fill = False
    trading_client.reject_immediately = True

    # EIN Abruf holt BEIDE neuen Balken (bar6 und bar7) auf einmal.
    bot.run_once(now=_et(9, 38))

    # bar6s RED_CANDLE-Order wurde zweimal sofort abgelehnt (0 gefüllt,
    # lokaler Retry erschöpft) und landet in deferred_exits -- bar7 darf
    # dabei NICHT mehr verarbeitet worden sein.
    assert state.pending_exit is None
    assert len(state.deferred_exits) == 1
    assert state.deferred_exits[0].shares == 77
    assert state.last_bar_time.time() == dt_time(9, 36)  # nur bar6, NICHT bar7 (9:37)
    assert state.engine.in_position
    assert state.engine.shares_open == 77  # unveraendert, kein Fill verbucht
    sell_orders = [o for o in trading_client.submitted_orders if o.side == OrderSide.SELL]
    assert len(sell_orders) == 2  # bar6s Order + der eine lokale Retry, NICHTS von bar7


def test_start_new_day_force_flatten_isolates_exceptions_per_symbol():
    """Regressionstest (3. Review-Runde): der Zwangs-Glattstellungs-Loop
    in _start_new_day() hatte keine Fehlerisolierung pro Symbol -- ein
    Fehler beim Glattstellen EINES übernommenen Symbols hätte den
    gesamten Tageswechsel (inkl. des Glattstellens ALLER anderen Symbole
    und der anschließenden _resolve_pending_exits()-Prüfung in run_once)
    abgebrochen."""
    yesterday = date(2024, 1, 9)
    trading_client = FakeTradingClient([FakeCalendarEntry(TODAY)], fill_price=10.0)
    trading_client.fail_submit_for_symbol = "BAD"
    scanner = FakeScanner([])
    bot = _make_bot(FakeDataClient({}), trading_client, scanner)

    bad_state = _SymbolState(
        engine=_entered_engine(bot.live_config, shares=10, entry_price=10.0, stop_price=9.0),
        rel_vol_reference=np.array([]), daily_sma=None, session_open=_et(9, 30, day=yesterday), last_close=10.5,
    )
    good_state = _SymbolState(
        engine=_entered_engine(bot.live_config, shares=20, entry_price=20.0, stop_price=18.0),
        rel_vol_reference=np.array([]), daily_sma=None, session_open=_et(9, 30, day=yesterday), last_close=20.5,
    )
    bot._symbols["BAD"] = bad_state
    bot._symbols["GOOD"] = good_state
    bot._trading_day = yesterday

    bot._start_new_day(FakeCalendarEntry(TODAY), _et(9, 31))

    assert bot._trading_day == TODAY
    assert bad_state.engine.in_position  # Flatten fehlgeschlagen, Position bleibt vorerst offen
    assert not good_state.engine.in_position  # GOOD trotzdem erfolgreich glattgestellt
    sell_orders = [o for o in trading_client.submitted_orders if o.side == OrderSide.SELL]
    assert len(sell_orders) == 1
    assert sell_orders[0].qty == 20


def test_stale_deferred_exits_cleared_when_position_fully_closes_via_other_path():
    """Regressionstest (3. Review-Runde, selbst gefundene Folge der
    deferred_exits-Wächter-Erweiterung oben): schließt eine Position über
    einen ANDEREN Pfad vollständig (z.B. _flatten_all beim Tages-
    Maximalverlust/Sitzungsende, der die GESAMTE damals offene Restmenge
    inkl. eines noch zurückgestellten Geschwister-Ereignisses in einem
    Rutsch verkauft), muss ein dabei nun gegenstandsloser deferred_exits-
    Eintrag verworfen werden. Sonst würde die neue pending_exit-ODER-
    deferred_exits-Wächter-Logik (siehe oben) dieses Symbol PERMANENT von
    jeder weiteren Balkenverarbeitung blockieren -- der Nachhol-Mechanismus
    in _resolve_pending_exit_for_symbol setzt engine.in_position voraus,
    das nach einem Vollausstieg für immer False bleibt."""
    trading_client = FakeTradingClient([FakeCalendarEntry(TODAY)], fill_price=12.50)
    scanner = FakeScanner([])
    bot = _make_bot(FakeDataClient({}), trading_client, scanner)

    stale_event = ExitSignal(ExitReason.EXTENSION, pd.Timestamp.now(tz="UTC"), 14.50, 39)
    state = _SymbolState(
        engine=_entered_engine(bot.live_config, shares=77, entry_price=12.20, stop_price=11.30),
        rel_vol_reference=np.array([]), daily_sma=None, session_open=_et(9, 30),
        deferred_exits=[stale_event], last_close=12.50,
    )
    bot._symbols["AAPL"] = state

    bot._flatten_all(_et(9, 40))  # konsolidierter Vollausstieg ueber die GESAMTE Restmenge (77)

    assert not state.engine.in_position
    assert state.deferred_exits == []
    sell_orders = [o for o in trading_client.submitted_orders if o.side == OrderSide.SELL]
    assert len(sell_orders) == 1
    assert sell_orders[0].qty == 77  # deckt auch die 39 des veralteten deferred-Eintrags mit ab


def test_handle_breakout_exception_during_wait_declines_entry_and_unblocks_engine():
    """Regressionstest (4. Review-Runde): ein unerwarteter Fehler (z.B.
    transienter APIError) WÄHREND des Wartens auf die Kauf-Order-Füllung
    ließ die Engine mit einem unbeantworteten BreakoutEvent zurück -- JEDER
    folgende process_bar()-Aufruf für dieses Symbol hätte dann dauerhaft
    mit RuntimeError abgebrochen (siehe MomentumEngine-Nutzungsvertrag,
    process_bar() erfordert record_entry()/decline_entry() davor)."""
    data_client = _make_data_client("AAPL")
    trading_client = FakeTradingClient([FakeCalendarEntry(TODAY)], auto_fill=False)
    scanner = FakeScanner([_make_candidate("AAPL")])
    bot = _make_bot(data_client, trading_client, scanner)

    trading_client.raise_on_next_get_order_by_id = True
    bot.run_once(now=_et(9, 35))  # Breakout auf bar5, Order-Füllung schlägt mit Fehler fehl

    state = bot._symbols["AAPL"]
    assert not state.engine.in_position
    assert state.engine.state == "SEARCHING"

    # Ein weiterer process_bar()-Aufruf darf NICHT mehr mit RuntimeError
    # abbrechen (kein unbeantwortetes BreakoutEvent mehr offen).
    events = state.engine.process_bar(
        pd.Timestamp.now(tz="UTC"), 10.0, 10.0, 10.0, 10.0, 100,
        in_window=False, relative_volume=None, daily_trend_ok=False,
    )
    assert events == []


def test_submit_exit_exception_during_wait_sets_pending_exit():
    """Regressionstest (4. Review-Runde): ein unerwarteter Fehler WÄHREND
    des Wartens auf die Verkaufs-Order-Füllung ließ die Position komplett
    unverwaltet zurück (weder pending_exit noch record_exit aufgerufen) --
    jetzt wird die bereits platzierte Order stattdessen als ausstehend
    markiert und im nächsten Zyklus über _resolve_pending_exits() erneut
    geprüft, statt spurlos verloren zu gehen."""
    extra_bars = [{"open": 12.20, "high": 12.20, "low": 11.20, "close": 11.25, "volume": 100}]
    data_client = _make_data_client("AAPL", extra_today_bars=extra_bars)
    trading_client = FakeTradingClient([FakeCalendarEntry(TODAY)], fill_price=12.20)
    scanner = FakeScanner([_make_candidate("AAPL")])
    bot = _make_bot(data_client, trading_client, scanner)

    bot.run_once(now=_et(9, 35))  # Einstieg
    state = bot._symbols["AAPL"]
    assert state.engine.in_position

    trading_client.raise_on_next_get_order_by_id = True
    bot.run_once(now=_et(9, 37))  # Stop ausgelöst, Fehler während des Wartens auf die Verkaufs-Order

    assert state.pending_exit is not None
    assert state.engine.in_position  # Engine hält Position weiterhin für offen (record_exit nie aufgerufen)

    pending_order = trading_client.orders[state.pending_exit.order_id]
    pending_order.status = OrderStatus.FILLED
    pending_order.filled_qty = pending_order.qty
    pending_order.filled_avg_price = 11.30
    bot.run_once(now=_et(9, 38))

    assert state.pending_exit is None
    assert not state.engine.in_position


def test_halted_retries_flatten_all_across_cycles_for_pending_symbol():
    """Regressionstest (4. Review-Runde): _flatten_all() wurde beim
    Auslösen des Circuit-Breakers nur EINMAL aufgerufen -- ein Symbol mit
    einer zu diesem Zeitpunkt noch offenen (pending_exit) Order wird dort
    bewusst übersprungen (keine konkurrierende zweite Order). Löste sich
    diese Order SPÄTER in einen Teil-Fill auf, blieb die verbleibende
    Restmenge für den Rest des pausierten Handelstags komplett unbewacht,
    da jeder folgende Zyklus sofort 'if self._halted: return' traf, ohne
    _flatten_all() erneut aufzurufen -- der Circuit-Breaker soll aber
    AUSNAHMSLOS alle Positionen schließen."""
    data_client = _make_data_client("AAPL")
    trading_client = FakeTradingClient([FakeCalendarEntry(TODAY)], fill_price=12.20, equity=100_000.0)
    scanner = FakeScanner([_make_candidate("AAPL")])
    bot = _make_bot(data_client, trading_client, scanner, live_config=_live_config(daily_max_loss_pct=0.05))

    bot.run_once(now=_et(9, 35))  # Einstieg, 77 Stück
    state = bot._symbols["AAPL"]
    assert state.engine.in_position

    # Simuliert: ein TARGET-Teilverkauf (38 von 77) war schon VOR dem Halt
    # als pending_exit unterwegs, während der Drawdown gleichzeitig den
    # Circuit-Breaker auslöst.
    state.pending_exit = _PendingExit(
        order_id="order-target-pending",
        event=ExitSignal(ExitReason.TARGET, pd.Timestamp.now(tz="UTC"), 14.00, 38),
    )
    trading_client.orders["order-target-pending"] = FakeOrder("order-target-pending", "AAPL", 38, OrderSide.SELL)

    trading_client.equity = 94_000.0  # -6% Drawdown, über dem 5%-Limit
    bot.run_once(now=_et(9, 37))

    assert bot._halted is True
    assert state.pending_exit is not None  # von _flatten_all() bewusst übersprungen (s.o.)
    assert state.engine.in_position  # noch alle 77 Stück, nichts verbucht

    # Die hängende Order füllt sich jetzt (Teilverkauf, 38 von 77).
    pending_order = trading_client.orders["order-target-pending"]
    pending_order.status = OrderStatus.FILLED
    pending_order.filled_qty = 38
    pending_order.filled_avg_price = 14.00

    bot.run_once(now=_et(9, 38))  # weiterhin pausiert (self._halted bleibt True)

    # _resolve_pending_exits() verbucht den Teilverkauf (39 Stück offen),
    # UND _flatten_all() muss die verbleibende Restmenge SOFORT im selben,
    # weiterhin pausierten Zyklus zwangsweise glattstellen.
    assert state.pending_exit is None
    assert not state.engine.in_position
    sell_orders = [o for o in trading_client.submitted_orders if o.side == OrderSide.SELL]
    assert len(sell_orders) == 1  # nur der Flatten-Verkauf des Rests (die pending Order wurde nicht ueber submit_order() gesendet)
    assert sell_orders[0].qty == 39

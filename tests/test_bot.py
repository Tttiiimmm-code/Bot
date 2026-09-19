from __future__ import annotations

import pandas as pd

from tradingbot import bot as bot_module
from tradingbot.bot import TradingBot
from tradingbot.broker import Position
from tradingbot.config import Config
from tradingbot.strategy import Signal


class FakeBroker:
    """Minimaler Broker-Double für Bot-Tests -- kein Netzwerkzugriff."""

    def __init__(
        self,
        closes: pd.Series,
        position: Position | None,
        open_buy_order: bool = False,
        open_sell_order: bool = False,
    ):
        self._closes = closes
        self._position = position
        self._open_buy_order = open_buy_order
        self._open_sell_order = open_sell_order
        self.buy_calls: list[float] = []
        self.sell_calls: list[float] = []

    def get_recent_closes(self, limit: int) -> pd.Series:
        return self._closes.tail(limit)

    def get_position(self) -> Position | None:
        return self._position

    def has_open_buy_order(self) -> bool:
        return self._open_buy_order

    def has_open_sell_order(self) -> bool:
        return self._open_sell_order

    def buy(self, qty: float):
        self.buy_calls.append(qty)

    def sell(self, qty: float):
        self.sell_calls.append(qty)


def make_config(stop_loss_pct: float) -> Config:
    return Config(
        api_key="test",
        secret_key="test",
        paper=True,
        symbol="TEST",
        qty=1.0,
        short_window=2,
        long_window=4,
        poll_interval_seconds=60,
        stop_loss_pct=stop_loss_pct,
    )


def flat_closes(value: float, n: int = 20) -> pd.Series:
    return pd.Series([value] * n, index=pd.date_range("2024-01-01", periods=n, freq="D"))


def make_series(values: list[float]) -> pd.Series:
    return pd.Series(values, index=pd.date_range("2024-01-01", periods=len(values), freq="D"))


def test_stop_loss_triggers_sell_and_skips_signal_logic():
    config = make_config(stop_loss_pct=0.08)
    closes = flat_closes(90.0)  # aktueller Kurs 90
    position = Position(qty=10.0, avg_entry_price=100.0)  # Stop bei 92
    broker = FakeBroker(closes, position)
    bot = TradingBot(config, broker=broker)

    signal = bot.run_once()

    assert signal == Signal.SELL
    assert broker.sell_calls == [10.0]
    assert broker.buy_calls == []


def test_invalid_current_price_does_not_trigger_spurious_stop_sell():
    """Regressionstest: ein Kurs von 0 (Datenmüll/Delisting) wäre <= jede
    positive Stop-Schwelle und hätte einen spontanen Verkauf auf Basis
    kaputter Daten ausgelöst, statt den Stop-Check für diesen Zyklus
    schlicht zu überspringen."""
    config = make_config(stop_loss_pct=0.08)
    closes = flat_closes(0.0)
    position = Position(qty=10.0, avg_entry_price=100.0)
    broker = FakeBroker(closes, position)
    bot = TradingBot(config, broker=broker)

    signal = bot.run_once()

    assert signal != Signal.SELL
    assert broker.sell_calls == []


def test_price_above_stop_does_not_trigger_stop_sell():
    config = make_config(stop_loss_pct=0.08)
    closes = flat_closes(95.0)  # über dem Stop von 92
    position = Position(qty=10.0, avg_entry_price=100.0)
    broker = FakeBroker(closes, position)
    bot = TradingBot(config, broker=broker)

    bot.run_once()

    # Kein Stop-Loss-Verkauf; flache Kurse erzeugen zudem kein
    # Crossover-Signal, also auch kein regulärer Verkauf.
    assert broker.sell_calls == []


def test_disabled_stop_loss_never_triggers():
    config = make_config(stop_loss_pct=0.0)
    closes = flat_closes(10.0)  # weit unter jedem sinnvollen Stop
    position = Position(qty=10.0, avg_entry_price=100.0)
    broker = FakeBroker(closes, position)
    bot = TradingBot(config, broker=broker)

    bot.run_once()

    assert broker.sell_calls == []


def test_open_sell_order_blocks_duplicate_stop_loss_sell():
    config = make_config(stop_loss_pct=0.08)
    closes = flat_closes(90.0)  # würde ohne offene Order den Stop auslösen
    position = Position(qty=10.0, avg_entry_price=100.0)
    broker = FakeBroker(closes, position, open_sell_order=True)
    bot = TradingBot(config, broker=broker)

    signal = bot.run_once()

    assert signal == Signal.HOLD
    assert broker.sell_calls == []


def test_open_buy_order_does_not_block_stop_loss_sell():
    """Regressionstest: eine noch offene KAUF-Order (z.B. eine andere,
    unabhängige, langsam gefüllte Order) darf einen dringenden Stop-Loss-
    Verkauf nicht blockieren -- nur eine bereits offene VERKAUFS-Order
    für dasselbe Symbol darf das (um einen doppelten Stop-Verkauf zu
    verhindern)."""
    config = make_config(stop_loss_pct=0.08)
    closes = flat_closes(90.0)
    position = Position(qty=10.0, avg_entry_price=100.0)
    broker = FakeBroker(closes, position, open_buy_order=True)
    bot = TradingBot(config, broker=broker)

    signal = bot.run_once()

    assert signal == Signal.SELL
    assert broker.sell_calls == [10.0]


def test_open_buy_order_blocks_duplicate_buy_signal():
    config = make_config(stop_loss_pct=0.08)
    # Golden Cross am letzten Punkt -> würde ohne offene Order kaufen.
    closes = make_series([10, 9, 8, 7, 6, 7, 9])
    broker = FakeBroker(closes, position=None, open_buy_order=True)
    bot = TradingBot(config, broker=broker)

    signal = bot.run_once()

    assert signal == Signal.HOLD
    assert broker.buy_calls == []


def test_open_sell_order_blocks_duplicate_regular_sell_signal():
    config = make_config(stop_loss_pct=0.08)
    # Death Cross am letzten Punkt -> würde ohne offene Order verkaufen.
    closes = make_series([6, 7, 8, 9, 10, 9, 7])
    # Einstieg deutlich unter dem aktuellen Kurs (7), damit NICHT der
    # Stop-Loss, sondern der reguläre Crossover-SELL-Zweig getestet wird.
    position = Position(qty=5.0, avg_entry_price=5.0)
    broker = FakeBroker(closes, position, open_sell_order=True)
    bot = TradingBot(config, broker=broker)

    bot.run_once()

    assert broker.sell_calls == []


def test_no_position_skips_stop_check_without_error():
    config = make_config(stop_loss_pct=0.08)
    closes = flat_closes(50.0)
    broker = FakeBroker(closes, position=None)
    bot = TradingBot(config, broker=broker)

    signal = bot.run_once()

    assert signal == Signal.HOLD
    assert broker.sell_calls == []
    assert broker.buy_calls == []


class BrokenBroker(FakeBroker):
    """Broker-Double, dessen get_recent_closes immer eine Exception wirft
    -- simuliert z.B. einen Netzwerkfehler oder den in Runde 6/7 gefundenen
    OverflowError bei einer zu großen Fenstergröße."""

    def __init__(self):
        super().__init__(flat_closes(50.0), position=None)
        self.calls = 0

    def get_recent_closes(self, limit: int) -> pd.Series:
        self.calls += 1
        raise RuntimeError("boom")


def test_run_forever_catches_exceptions_and_keeps_looping(monkeypatch):
    """Regressionstest für den zentralen Sicherheitsmechanismus: eine
    Exception in run_once() darf run_forever() nicht abstürzen lassen --
    der Zyklus wird geloggt übersprungen und die Schleife läuft mit
    time.sleep(poll_interval_seconds) weiter, bis KeyboardInterrupt
    kommt."""
    config = make_config(stop_loss_pct=0.08)
    broker = BrokenBroker()
    bot = TradingBot(config, broker=broker)

    sleep_calls: list[float] = []

    def fake_sleep(seconds):
        sleep_calls.append(seconds)
        if len(sleep_calls) >= 3:
            raise KeyboardInterrupt

    monkeypatch.setattr(bot_module.time, "sleep", fake_sleep)

    bot.run_forever()  # darf nicht raisen

    assert broker.calls == 3
    assert sleep_calls == [config.poll_interval_seconds] * 3


def test_run_forever_exits_cleanly_on_keyboard_interrupt_during_run_once(monkeypatch):
    config = make_config(stop_loss_pct=0.08)
    closes = flat_closes(50.0)
    broker = FakeBroker(closes, position=None)
    bot = TradingBot(config, broker=broker)

    def raise_interrupt(limit):
        raise KeyboardInterrupt

    monkeypatch.setattr(broker, "get_recent_closes", raise_interrupt)
    monkeypatch.setattr(bot_module.time, "sleep", lambda seconds: None)

    bot.run_forever()  # darf nicht raisen

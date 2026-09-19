import pandas as pd

from tradingbot.bot import TradingBot
from tradingbot.broker import Position
from tradingbot.config import Config
from tradingbot.strategy import Signal


class FakeBroker:
    """Minimaler Broker-Double für Bot-Tests -- kein Netzwerkzugriff."""

    def __init__(self, closes: pd.Series, position: Position | None):
        self._closes = closes
        self._position = position
        self.buy_calls: list[float] = []
        self.sell_calls: list[float] = []

    def get_recent_closes(self, limit: int) -> pd.Series:
        return self._closes.tail(limit)

    def get_position(self) -> Position | None:
        return self._position

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


def test_no_position_skips_stop_check_without_error():
    config = make_config(stop_loss_pct=0.08)
    closes = flat_closes(50.0)
    broker = FakeBroker(closes, position=None)
    bot = TradingBot(config, broker=broker)

    signal = bot.run_once()

    assert signal == Signal.HOLD
    assert broker.sell_calls == []
    assert broker.buy_calls == []

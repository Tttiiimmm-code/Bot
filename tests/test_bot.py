from __future__ import annotations

import pandas as pd
import pytest

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
        equity: float = 10_000.0,
        available_cash: float | None = None,
    ):
        self._closes = closes
        self._position = position
        self._open_buy_order = open_buy_order
        self._open_sell_order = open_sell_order
        self._equity = equity
        # Standardmäßig kein zusätzlicher Cash-Engpass -- Tests, die nur
        # `equity` setzen, sollen sich weiterhin so verhalten, als sei
        # das gesamte Equity auch als freies Cash verfügbar.
        self._available_cash = equity if available_cash is None else available_cash
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

    def get_account_equity(self) -> float:
        return self._equity

    def get_available_cash(self) -> float:
        return self._available_cash

    def buy(self, qty: float):
        self.buy_calls.append(qty)

    def sell(self, qty: float):
        self.sell_calls.append(qty)


def make_config(
    stop_loss_pct: float,
    take_profit_pct: float = 0.0,
    risk_per_trade_pct: float = 0.0,
    trend_window: int = 0,
    rsi_window: int = 0,
) -> Config:
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
        take_profit_pct=take_profit_pct,
        risk_per_trade_pct=risk_per_trade_pct,
        trend_window=trend_window,
        rsi_window=rsi_window,
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


def test_invalid_current_price_also_blocks_crossover_sell():
    """Regressionstest: der erste Fix deckte nur den Stop-Loss-Zweig ab.
    Ein Kurs von 0 als letzter Datenpunkt fließt aber auch in
    generate_signal() ein und kann dort ein echtes Crossover-SELL-Signal
    aus dem Datenmüll erzeugen (verifiziert: [100,100,100,100,100,0] mit
    short=2/long=4 ergibt Signal.SELL). Der gesamte Zyklus muss bei
    ungültigem Kurs übersprungen werden, nicht nur der Stop-Loss-Zweig --
    sonst verkauft der Bot trotz erkanntem Datenmüll über den regulären
    Crossover-Pfad."""
    config = make_config(stop_loss_pct=0.08)
    closes = make_series([100, 100, 100, 100, 100, 0])
    position = Position(qty=10.0, avg_entry_price=50.0)  # kein Stop-Trigger
    broker = FakeBroker(closes, position)
    bot = TradingBot(config, broker=broker)

    signal = bot.run_once()

    assert signal == Signal.HOLD
    assert broker.sell_calls == []
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


def test_trailing_stop_uses_peak_price_across_cycles():
    """Regressionstest fürs Kernverhalten des Trailing-Stops im Live-Bot:
    steigt der Kurs über mehrere Zyklen hinweg und fällt danach nur leicht
    zurück, muss der Stop auf Basis des zwischenzeitlichen Höchststands
    auslösen -- ein rein auf den Einstiegspreis bezogener (fixer) Stop
    hätte hier nicht ausgelöst."""
    config = make_config(stop_loss_pct=0.08)
    position = Position(qty=10.0, avg_entry_price=100.0)

    # Zyklus 1: Kurs steigt auf 110 -> Peak wird 110, kein Trigger
    # (Trailing-Schwelle 110*0.92=101.2, Kurs 110 liegt darüber).
    broker = FakeBroker(flat_closes(110.0), position)
    bot = TradingBot(config, broker=broker)
    signal1 = bot.run_once()
    assert signal1 != Signal.SELL
    assert broker.sell_calls == []

    # Zyklus 2 (gleiche Bot-Instanz -> Peak bleibt im Speicher): Kurs
    # fällt auf 100 zurück. Fixer Stop (Einstieg*0.92=92) würde NICHT
    # auslösen, Trailing-Stop (Peak*0.92=101.2) hingegen schon.
    broker._closes = flat_closes(100.0)
    signal2 = bot.run_once()
    assert signal2 == Signal.SELL
    assert broker.sell_calls == [10.0]


def test_peak_price_resets_after_position_closes():
    config = make_config(stop_loss_pct=0.08)
    position = Position(qty=10.0, avg_entry_price=100.0)
    broker = FakeBroker(flat_closes(150.0), position)
    bot = TradingBot(config, broker=broker)

    bot.run_once()  # Peak wird auf 150 gesetzt
    assert bot._peak_price_by_symbol["TEST"] == 150.0

    broker._position = None  # Position extern geschlossen (z.B. Order gefüllt)
    bot.run_once()
    assert "TEST" not in bot._peak_price_by_symbol


def test_take_profit_triggers_sell():
    config = make_config(stop_loss_pct=0.0, take_profit_pct=0.15)
    position = Position(qty=10.0, avg_entry_price=100.0)
    broker = FakeBroker(flat_closes(116.0), position)  # +16%, über 15%-Ziel
    bot = TradingBot(config, broker=broker)

    signal = bot.run_once()

    assert signal == Signal.SELL
    assert broker.sell_calls == [10.0]


def test_take_profit_does_not_trigger_below_target():
    config = make_config(stop_loss_pct=0.0, take_profit_pct=0.15)
    position = Position(qty=10.0, avg_entry_price=100.0)
    broker = FakeBroker(flat_closes(110.0), position)  # +10%, unter 15%-Ziel
    bot = TradingBot(config, broker=broker)

    bot.run_once()

    assert broker.sell_calls == []


def test_take_profit_disabled_by_default():
    config = make_config(stop_loss_pct=0.0, take_profit_pct=0.0)
    position = Position(qty=10.0, avg_entry_price=100.0)
    broker = FakeBroker(flat_closes(1000.0), position)  # +900%
    bot = TradingBot(config, broker=broker)

    bot.run_once()

    assert broker.sell_calls == []


def test_take_profit_open_sell_order_blocks_duplicate():
    config = make_config(stop_loss_pct=0.0, take_profit_pct=0.15)
    position = Position(qty=10.0, avg_entry_price=100.0)
    broker = FakeBroker(flat_closes(116.0), position, open_sell_order=True)
    bot = TradingBot(config, broker=broker)

    signal = bot.run_once()

    assert signal == Signal.HOLD
    assert broker.sell_calls == []


def test_risk_based_buy_qty_uses_equity_and_stop_distance():
    """qty = (equity * risk_per_trade_pct) / (current_price * stop_loss_pct)."""
    config = make_config(stop_loss_pct=0.08, risk_per_trade_pct=0.02)
    # Golden Cross am letzten Punkt, aktueller Kurs 9.
    closes = make_series([10, 9, 8, 7, 6, 7, 9])
    broker = FakeBroker(closes, position=None, equity=10_000.0)
    bot = TradingBot(config, broker=broker)

    bot.run_once()

    assert len(broker.buy_calls) == 1
    expected_qty = (10_000.0 * 0.02) / (9 * 0.08)
    assert broker.buy_calls[0] == pytest.approx(expected_qty)


def test_risk_based_buy_qty_caps_at_available_equity():
    """Regressionstest: RISK_PER_TRADE_PCT und STOP_LOSS_PCT werden
    unabhängig voneinander im Bereich [0, 1) validiert -- ihr Verhältnis
    kann trotzdem > 1 ergeben (hier 0.10/0.08 = 1.25, also 125% des
    Kapitals). Ohne Deckelung würde das auf einem Margin-Konto weit über
    das beabsichtigte Risiko hinaus gehebelt, auf einem Cash-Konto jeden
    Zyklus als 'insufficient buying power' abgelehnt."""
    config = make_config(stop_loss_pct=0.08, risk_per_trade_pct=0.10)
    closes = make_series([10, 9, 8, 7, 6, 7, 9])  # Golden Cross, Kurs 9
    broker = FakeBroker(closes, position=None, equity=10_000.0)
    bot = TradingBot(config, broker=broker)

    bot.run_once()

    assert len(broker.buy_calls) == 1
    notional = broker.buy_calls[0] * 9  # Kurs 9
    assert notional == pytest.approx(10_000.0, rel=1e-6)


def test_risk_based_buy_qty_caps_at_available_cash_not_just_equity():
    """Regressionstest: die Risiko-Prozentsatz-Berechnung basiert korrekt
    auf dem Gesamt-Equity (Standard-Definition von 'Risiko pro Trade'),
    die tatsächliche Ordergröße darf aber nie das freie Cash übersteigen
    -- auf einem Konto mit anderen offenen Positionen kann das deutlich
    unter dem Gesamt-Equity liegen."""
    config = make_config(stop_loss_pct=0.08, risk_per_trade_pct=0.02)
    closes = make_series([10, 9, 8, 7, 6, 7, 9])  # Golden Cross, Kurs 9
    # Equity 10000 (anderswo gebunden), aber nur 500 tatsaechlich frei.
    broker = FakeBroker(closes, position=None, equity=10_000.0, available_cash=500.0)
    bot = TradingBot(config, broker=broker)

    bot.run_once()

    assert len(broker.buy_calls) == 1
    notional = broker.buy_calls[0] * 9
    # Ohne Cash-Deckelung waere notional = (10000*0.02)/0.08 = 2500 --
    # weit ueber dem verfuegbaren Cash von 500.
    assert notional == pytest.approx(500.0, rel=1e-6)


def test_risk_based_sizing_falls_back_to_fixed_qty_without_stop_loss():
    """Ohne Stop-Loss ist 'Risiko pro Trade' nicht definiert -- muss auf
    die feste QTY zurückfallen statt zu crashen oder eine bedeutungslose
    Größe zu berechnen."""
    config = make_config(stop_loss_pct=0.0, risk_per_trade_pct=0.02)
    closes = make_series([10, 9, 8, 7, 6, 7, 9])
    broker = FakeBroker(closes, position=None, equity=10_000.0)
    bot = TradingBot(config, broker=broker)

    bot.run_once()

    assert broker.buy_calls == [config.qty]


def test_trend_filter_suppresses_live_buy():
    config = make_config(stop_loss_pct=0.08, trend_window=30)
    # Golden Cross weit unter dem 30er-Trend-Durchschnitt.
    closes = make_series([50] * 30 + [10, 9, 8, 7, 6, 7, 9])
    broker = FakeBroker(closes, position=None)
    bot = TradingBot(config, broker=broker)

    signal = bot.run_once()

    assert signal == Signal.HOLD
    assert broker.buy_calls == []


def test_rsi_filter_suppresses_live_buy():
    config = make_config(stop_loss_pct=0.08, rsi_window=8)
    values = [100, 80, 60, 45, 35, 30, 28, 27, 26.5, 26, 27, 29]
    closes = make_series(values)
    broker = FakeBroker(closes, position=None)
    bot = TradingBot(config, broker=broker)

    signal = bot.run_once()

    assert signal == Signal.HOLD
    assert broker.buy_calls == []

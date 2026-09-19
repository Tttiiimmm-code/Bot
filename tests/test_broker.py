"""Unit-Tests für Broker-Logik, die ohne echten Netzwerkzugriff testbar ist.

Die Alpaca-Clients selbst validieren Zugangsdaten nicht bei der Konstruktion
(kein Netzwerkaufruf), daher können wir mit Dummy-Keys einen echten Broker
bauen und nur die eine Methode faken, deren Verhalten wir testen wollen.
"""

from __future__ import annotations

import pytest
from alpaca.common.exceptions import APIError

from tradingbot.broker import Broker, Position
from tradingbot.config import Config


def make_config() -> Config:
    return Config(
        api_key="dummy",
        secret_key="dummy",
        paper=True,
        symbol="TEST",
        qty=1.0,
        short_window=2,
        long_window=4,
        poll_interval_seconds=60,
        stop_loss_pct=0.08,
    )


def make_broker() -> Broker:
    return Broker(make_config())


class FakeAlpacaPosition:
    def __init__(self, qty, avg_entry_price):
        self.qty = qty
        self.avg_entry_price = avg_entry_price


def api_error(status_code: int) -> APIError:
    err = APIError('{"code": 1, "message": "boom"}')
    err._http_error = type("R", (), {"response": type("Resp", (), {"status_code": status_code})()})()
    return err


def test_get_position_returns_none_on_404(monkeypatch):
    broker = make_broker()
    monkeypatch.setattr(
        broker.trading_client,
        "get_open_position",
        lambda symbol: (_ for _ in ()).throw(api_error(404)),
    )

    assert broker.get_position() is None
    assert broker.get_position_qty() == 0.0


def test_get_position_reraises_non_404_api_error(monkeypatch):
    broker = make_broker()
    monkeypatch.setattr(
        broker.trading_client,
        "get_open_position",
        lambda symbol: (_ for _ in ()).throw(api_error(500)),
    )

    with pytest.raises(APIError):
        broker.get_position()


def test_get_position_does_not_swallow_non_api_errors(monkeypatch):
    """Ein Netzwerkfehler o.ä. (kein APIError) darf nicht als 'keine
    Position' fehlinterpretiert werden -- sonst könnte ein aktiver
    Stop-Loss unbemerkt ausgesetzt werden."""
    broker = make_broker()
    monkeypatch.setattr(
        broker.trading_client,
        "get_open_position",
        lambda symbol: (_ for _ in ()).throw(ConnectionError("network down")),
    )

    with pytest.raises(ConnectionError):
        broker.get_position()


def test_get_position_returns_position_on_success(monkeypatch):
    broker = make_broker()
    monkeypatch.setattr(
        broker.trading_client,
        "get_open_position",
        lambda symbol: FakeAlpacaPosition(qty="10", avg_entry_price="123.45"),
    )

    position = broker.get_position()

    assert position == Position(qty=10.0, avg_entry_price=123.45)
    assert broker.get_position_qty() == 10.0


@pytest.mark.parametrize(
    "qty,avg_entry_price",
    [("nan", "100"), ("10", "nan"), ("inf", "100"), ("10", "inf")],
)
def test_get_position_rejects_non_finite_values(monkeypatch, qty, avg_entry_price):
    """Regressionstest: NaN/Inf in den von Alpaca gelieferten Positions-
    daten dürfen nicht stillschweigend durchgereicht werden -- ein NaN
    avg_entry_price würde den Stop-Loss-Vergleich in bot.py unbemerkt
    immer False werden lassen und den Stop damit wirkungslos machen."""
    broker = make_broker()
    monkeypatch.setattr(
        broker.trading_client,
        "get_open_position",
        lambda symbol: FakeAlpacaPosition(qty=qty, avg_entry_price=avg_entry_price),
    )

    with pytest.raises(ValueError):
        broker.get_position()


def test_has_open_buy_order_true_and_false(monkeypatch):
    broker = make_broker()

    monkeypatch.setattr(broker.trading_client, "get_orders", lambda filter: [])
    assert broker.has_open_buy_order() is False

    monkeypatch.setattr(broker.trading_client, "get_orders", lambda filter: [object()])
    assert broker.has_open_buy_order() is True


def test_has_open_sell_order_true_and_false(monkeypatch):
    broker = make_broker()

    monkeypatch.setattr(broker.trading_client, "get_orders", lambda filter: [])
    assert broker.has_open_sell_order() is False

    monkeypatch.setattr(broker.trading_client, "get_orders", lambda filter: [object()])
    assert broker.has_open_sell_order() is True


def test_has_open_order_filters_by_side(monkeypatch):
    """Stellt sicher, dass has_open_buy_order/has_open_sell_order
    tatsächlich unterschiedliche side-Filter an die API übergeben --
    sonst würde eine offene Order in die eine Richtung fälschlich auch
    Entscheidungen in die andere Richtung blockieren."""
    from alpaca.trading.enums import OrderSide

    seen_sides = []

    def fake_get_orders(filter):
        seen_sides.append(filter.side)
        return []

    broker = make_broker()
    monkeypatch.setattr(broker.trading_client, "get_orders", fake_get_orders)

    broker.has_open_buy_order()
    broker.has_open_sell_order()

    assert seen_sides == [OrderSide.BUY, OrderSide.SELL]

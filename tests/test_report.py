from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from alpaca.common.enums import Sort
from alpaca.trading.enums import OrderSide, QueryOrderStatus
from alpaca.trading.requests import GetOrdersRequest

from tradingbot.report import (
    account_stats,
    fetch_closed_orders,
    group_by_trading_day,
    group_parallel_trades,
    match_trades,
    read_account_env,
)

_NY = ZoneInfo("America/New_York")


def _dt(hour: int, minute: int, day: int = 22) -> datetime:
    return datetime(2026, 9, day, hour, minute, tzinfo=timezone.utc)


class FakeOrder:
    def __init__(self, symbol: str, side: OrderSide, filled_qty: float, filled_avg_price: float, filled_at):
        self.symbol = symbol
        self.side = side
        self.filled_qty = filled_qty
        self.filled_avg_price = filled_avg_price
        self.filled_at = filled_at
        self.submitted_at = filled_at


class FakeTradingClient:
    """Bildet nur get_orders() nach -- filtert nach after/until (auf
    submitted_at) und respektiert `limit`, damit sich die Paginierung in
    fetch_closed_orders() testen lässt."""

    def __init__(self, orders: list[FakeOrder]):
        self._orders = orders
        self.requests: list[GetOrdersRequest] = []

    def get_orders(self, filter: GetOrdersRequest):
        self.requests.append(filter)
        assert filter.status == QueryOrderStatus.CLOSED
        assert filter.direction == Sort.ASC
        # Wie die echte Alpaca-API: `after` ist EXKLUSIV (Grenze zwischen
        # zwei Seiten darf nicht doppelt zurückgegeben werden), `until`
        # inklusiv.
        matching = [o for o in self._orders if filter.after < o.submitted_at <= filter.until]
        matching.sort(key=lambda o: o.submitted_at)
        return matching[: filter.limit]


def test_match_trades_single_buy_single_sell():
    orders = [
        FakeOrder("GLND", OrderSide.BUY, 100, 3.20, _dt(15, 36)),
        FakeOrder("GLND", OrderSide.SELL, 100, 3.03, _dt(15, 37)),
    ]

    trades, open_positions, unmatched_sells = match_trades(orders)

    assert open_positions == []
    assert len(trades) == 1
    t = trades[0]
    assert t.symbol == "GLND"
    assert t.shares == 100
    assert t.entry_price == 3.20
    assert t.exit_price == 3.03
    assert t.pnl == pytest.approx((3.03 - 3.20) * 100)
    assert t.pnl_pct == pytest.approx((3.03 - 3.20) / 3.20)
    assert t.duration == timedelta(minutes=1)


def test_match_trades_partial_exit_two_sells_are_one_trade():
    """Spiegelt IMCC aus dem echten Log: ein Kauf, zwei Verkaufs-Fills
    (Ziel-Teilverkauf + Rest) -- muss als EIN Trade mit gewichtetem
    Ausstiegskurs zusammengefasst werden, nicht als zwei."""
    orders = [
        FakeOrder("IMCC", OrderSide.BUY, 17597, 4.51, _dt(15, 37)),
        FakeOrder("IMCC", OrderSide.SELL, 8798, 4.62, _dt(15, 38)),
        FakeOrder("IMCC", OrderSide.SELL, 8799, 4.602386, _dt(15, 41)),
    ]

    trades, open_positions, unmatched_sells = match_trades(orders)

    assert open_positions == []
    assert len(trades) == 1
    t = trades[0]
    assert t.shares == 17597
    assert t.entry_price == 4.51
    expected_proceeds = 8798 * 4.62 + 8799 * 4.602386
    expected_cost = 17597 * 4.51
    assert t.pnl == pytest.approx(expected_proceeds - expected_cost)
    assert t.exit_time == _dt(15, 41)


def test_match_trades_two_round_trips_same_symbol_stay_separate():
    orders = [
        FakeOrder("GLND", OrderSide.BUY, 6249, 3.20, _dt(15, 36)),
        FakeOrder("GLND", OrderSide.SELL, 6249, 3.03, _dt(15, 37)),
        FakeOrder("GLND", OrderSide.BUY, 24999, 2.90, _dt(16, 45)),
        FakeOrder("GLND", OrderSide.SELL, 24999, 2.89, _dt(16, 47)),
    ]

    trades, open_positions, unmatched_sells = match_trades(orders)

    assert open_positions == []
    assert len(trades) == 2
    assert [t.shares for t in trades] == [6249, 24999]


def test_match_trades_leaves_unmatched_buy_as_open_position():
    orders = [
        FakeOrder("VEEE", OrderSide.BUY, 500, 10.00, _dt(15, 36)),
    ]

    trades, open_positions, unmatched_sells = match_trades(orders)

    assert trades == []
    assert len(open_positions) == 1
    p = open_positions[0]
    assert p.symbol == "VEEE"
    assert p.shares == 500
    assert p.entry_price == 10.00
    assert p.entry_time == _dt(15, 36)


def test_match_trades_sell_of_position_opened_before_window_is_not_merged_with_later_buy():
    """Regression: ein Verkauf ohne Kauf im Zeitraum (Position vor
    Zeitraumbeginn eröffnet) wurde mit dem NÄCHSTEN Kauf zu einem
    Phantom-Trade verrechnet (erfundenes P&L, negative Haltedauer), und die
    tatsächlich noch offene neue Position verschwand."""
    orders = [
        FakeOrder("XYZ", OrderSide.SELL, 10, 50.00, _dt(14, 0, day=21)),
        FakeOrder("XYZ", OrderSide.BUY, 10, 20.00, _dt(14, 0, day=22)),
        FakeOrder("XYZ", OrderSide.SELL, 5, 21.00, _dt(15, 0, day=22)),
    ]

    trades, open_positions, unmatched_sells = match_trades(orders)

    assert trades == []
    assert len(open_positions) == 1
    assert open_positions[0].shares == 5
    assert open_positions[0].entry_price == 20.00
    assert len(unmatched_sells) == 1
    assert unmatched_sells[0].shares == 10
    assert unmatched_sells[0].price == 50.00


def test_match_trades_sell_exceeding_bought_qty_splits_off_excess():
    """Teil der Verkaufsmenge gehört zu einer Position von VOR dem
    Zeitraum: nur die im Zeitraum gekaufte Menge fließt in den Trade ein."""
    orders = [
        FakeOrder("XYZ", OrderSide.BUY, 10, 20.00, _dt(14, 0)),
        FakeOrder("XYZ", OrderSide.SELL, 15, 22.00, _dt(15, 0)),
    ]

    trades, open_positions, unmatched_sells = match_trades(orders)

    assert len(trades) == 1
    assert trades[0].shares == 10
    assert trades[0].pnl == pytest.approx(20.0)
    assert open_positions == []
    assert len(unmatched_sells) == 1
    assert unmatched_sells[0].shares == pytest.approx(5)


def test_group_by_trading_day_uses_new_york_exit_time():
    """21:30 UTC ist an diesem Datum bereits 17:30 ET (Sommerzeit), also
    noch derselbe Handelstag -- aber 02:30 UTC am Folgetag ist 22:30 ET
    des VORTAGS. Die Gruppierung muss sich nach America/New_York richten,
    nicht nach dem UTC-Kalendertag."""
    late_exit_still_same_ny_day = datetime(2026, 9, 22, 21, 30, tzinfo=timezone.utc)
    orders = [
        FakeOrder("AAA", OrderSide.BUY, 10, 5.00, _dt(15, 0)),
        FakeOrder("AAA", OrderSide.SELL, 10, 5.10, late_exit_still_same_ny_day),
    ]

    trades, _, _ = match_trades(orders)
    by_day = group_by_trading_day(trades)

    assert list(by_day.keys()) == [datetime(2026, 9, 22, tzinfo=_NY).date()]
    assert by_day[datetime(2026, 9, 22, tzinfo=_NY).date()].num_trades == 1


def test_fetch_closed_orders_excludes_zero_fill_orders():
    orders = [
        FakeOrder("AAA", OrderSide.BUY, 0, 0.0, _dt(15, 0)),  # storniert, nichts gefüllt
        FakeOrder("AAA", OrderSide.BUY, 10, 5.00, _dt(15, 1)),
    ]
    client = FakeTradingClient(orders)

    result = fetch_closed_orders(client, _dt(9, 0), _dt(20, 0))

    assert len(result) == 1
    assert result[0].filled_qty == 10


def test_fetch_closed_orders_paginates_beyond_page_limit(monkeypatch):
    import tradingbot.report as report_module

    monkeypatch.setattr(report_module, "_PAGE_LIMIT", 2)
    orders = [FakeOrder("AAA", OrderSide.BUY, 10, 5.00, _dt(9, i)) for i in range(5)]
    client = FakeTradingClient(orders)

    result = fetch_closed_orders(client, _dt(8, 0), _dt(20, 0))

    assert len(result) == 5
    assert len(client.requests) == 3  # 2 + 2 + 1
    assert [o.submitted_at for o in result] == [o.submitted_at for o in orders]


def test_day_summary_win_rate_and_net_pnl():
    orders = [
        FakeOrder("A", OrderSide.BUY, 10, 5.00, _dt(9, 0)),
        FakeOrder("A", OrderSide.SELL, 10, 6.00, _dt(9, 1)),  # +10
        FakeOrder("B", OrderSide.BUY, 10, 5.00, _dt(9, 2)),
        FakeOrder("B", OrderSide.SELL, 10, 4.00, _dt(9, 3)),  # -10
    ]
    trades, _, _ = match_trades(orders)
    by_day = group_by_trading_day(trades)
    summary = next(iter(by_day.values()))

    assert summary.num_trades == 2
    assert summary.wins == 1
    assert summary.win_rate == 0.5
    assert summary.net_pnl == 0.0


# ---------------------------------------------------------------------------
# Konto-Vergleich
# ---------------------------------------------------------------------------


def _trades(*round_trips):
    """round_trips: (symbol, buy_minute, sell_minute, buy_price, sell_price) je 10 Stück."""
    orders = []
    for symbol, buy_min, sell_min, buy_px, sell_px in round_trips:
        orders.append(FakeOrder(symbol, OrderSide.BUY, 10, buy_px, _dt(14, buy_min)))
        orders.append(FakeOrder(symbol, OrderSide.SELL, 10, sell_px, _dt(14, sell_min)))
    trades, _, _ = match_trades(orders)
    return trades


def test_account_stats_averages_and_profit_factor():
    stats = account_stats(_trades(("A", 0, 2, 5.0, 7.0), ("B", 3, 4, 5.0, 4.0), ("C", 5, 9, 5.0, 4.5)))

    assert stats.num_trades == 3
    assert stats.wins == 1
    assert stats.net_pnl == pytest.approx(20 - 10 - 5)
    assert stats.avg_win == pytest.approx(20)
    assert stats.avg_loss == pytest.approx(-7.5)
    assert stats.profit_factor == pytest.approx(20 / 15)
    assert stats.avg_duration == timedelta(minutes=(2 + 1 + 4) / 3)


def test_account_stats_without_losses_or_trades():
    only_wins = account_stats(_trades(("A", 0, 2, 5.0, 6.0)))
    assert only_wins.profit_factor is None
    assert only_wins.avg_loss is None

    empty = account_stats([])
    assert empty.num_trades == 0
    assert empty.win_rate == 0.0
    assert empty.avg_duration is None


def test_group_parallel_trades_pairs_same_setup_across_accounts():
    red = _trades(("SECZ", 14, 16, 15.74, 15.53), ("LITS", 20, 25, 1.46, 1.41))
    none = _trades(("SECZ", 15, 40, 15.74, 16.11), ("GLND", 30, 35, 3.70, 3.94))

    groups = group_parallel_trades({"red": red, "none": none})

    assert [sorted(g) for g in groups] == [["none", "red"], ["red"], ["none"]]
    assert groups[0]["red"].symbol == groups[0]["none"].symbol == "SECZ"
    assert groups[1]["red"].symbol == "LITS"
    assert groups[2]["none"].symbol == "GLND"


def test_group_parallel_trades_splits_beyond_tolerance_and_repeated_trades():
    red = _trades(("MSS", 0, 1, 2.0, 2.1), ("MSS", 2, 3, 2.0, 1.9))  # zweiter MSS-Trade desselben Kontos
    none = _trades(("MSS", 10, 12, 2.0, 2.2))  # 10 Min später -> eigenes Setup

    groups = group_parallel_trades({"red": red, "none": none}, tolerance=timedelta(minutes=3))

    assert [sorted(g) for g in groups] == [["red"], ["red"], ["none"]]


def test_read_account_env_reads_keys_without_touching_environment(tmp_path, monkeypatch):
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    env = tmp_path / "bot2.env"
    env.write_text("ALPACA_API_KEY=key2\nALPACA_SECRET_KEY=secret2\nALPACA_PAPER=true\n")

    assert read_account_env(str(env)) == ("key2", "secret2", True)
    import os

    assert "ALPACA_API_KEY" not in os.environ


@pytest.mark.parametrize(
    "content, match",
    [
        ("ALPACA_API_KEY=k\n", "ALPACA_SECRET_KEY"),
        ("ALPACA_API_KEY=k\nALPACA_SECRET_KEY=s\nALPACA_PAPER=vielleicht\n", "ALPACA_PAPER"),
    ],
)
def test_read_account_env_rejects_incomplete_files(tmp_path, content, match):
    env = tmp_path / "bad.env"
    env.write_text(content)
    with pytest.raises(ValueError, match=match):
        read_account_env(str(env))

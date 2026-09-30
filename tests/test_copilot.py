from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from alpaca.trading.enums import OrderClass, OrderSide

from tradingbot.copilot import (
    NY,
    Copilot,
    CopilotRules,
    DayState,
    JournalEntry,
    attach_setups,
    check_entry,
    day_state,
    load_journal,
    position_size,
    setup_stats,
)

RULES = CopilotRules()


def ny(h, m, day=1):
    return datetime(2026, 10, day, h, m, tzinfo=NY)


def trade(symbol, entry, exit_, pnl):
    return SimpleNamespace(symbol=symbol, entry_time=entry, exit_time=exit_, pnl=pnl)


def test_entry_allowed_in_window_with_valid_stop():
    assert check_entry(RULES, DayState(), ny(12, 30), "XYZ", 25.0, 24.0) == []


@pytest.mark.parametrize("now,state,price,stop,fragment", [
    (ny(9, 31), DayState(), 25.0, 24.0, "Einstiege nur"),
    (ny(15, 50), DayState(), 25.0, 24.0, "Einstiege nur"),
    (ny(12, 0), DayState(realized_pnl=-150.0), 25.0, 24.0, "Tagesverlustgrenze"),
    (ny(12, 0), DayState(entries_today=6), 25.0, 24.0, "Maximal 6"),
    (ny(12, 0), DayState(open_symbols={"XYZ"}), 25.0, 24.0, "bereits offen"),
    (ny(12, 0), DayState(), 25.0, 25.5, "unter dem Kurs"),
    (ny(12, 0), DayState(), 25.0, 24.97, "zu eng"),
])
def test_rule_violations(now, state, price, stop, fragment):
    assert any(fragment in p for p in check_entry(RULES, state, now, "XYZ", price, stop))


def test_cooldown_after_loss_streak():
    st = DayState(loss_streak=2, last_loss_exit=ny(12, 0))
    assert any("Pause bis" in p for p in check_entry(RULES, st, ny(12, 10), "XYZ", 25.0, 24.0))
    assert check_entry(RULES, st, ny(12, 21), "XYZ", 25.0, 24.0) == []


def test_position_size_respects_risk_cap_and_cash():
    assert position_size(RULES, 25.0, 24.0, 100_000) == 50            # 50 $ / 1 $
    assert position_size(RULES, 25.0, 24.95, 100_000) == 400          # Positions-Obergrenze 10.000 $
    assert position_size(RULES, 25.0, 24.0, 500) == 20                # Kaufkraft
    assert position_size(RULES, 25.0, 26.0, 100_000) == 0


def test_day_state_counts_only_today_and_trailing_losses():
    trades = [trade("A", ny(10, 0, 30), ny(10, 30, 30), -80.0),   # anderer Tag
              trade("B", ny(10, 0), ny(10, 20), 40.0),
              trade("C", ny(11, 0), ny(11, 10), -50.0),
              trade("D", ny(11, 30), ny(11, 40), -30.0)]
    st = day_state(trades, {"E"}, 4, ny(12, 0))
    assert st.realized_pnl == pytest.approx(-40.0)
    assert st.loss_streak == 2 and st.last_loss_exit == ny(11, 40)
    assert st.open_symbols == {"E"} and st.entries_today == 4


def _entry(symbol, t, setup, risk=50.0):
    return JournalEntry(time=t.astimezone(timezone.utc).isoformat(), symbol=symbol, setup=setup, shares=50,
                        price=25.0, stop=24.0, target=None, risk=risk)


def test_attach_setups_and_stats_in_r_multiples():
    journal = [_entry("A", ny(10, 0), "vwap"), _entry("B", ny(11, 0), "power-hour"),
               _entry("A", ny(13, 0), "vwap")]
    trades = [trade("A", ny(10, 1), ny(10, 30), 100.0), trade("B", ny(11, 2), ny(11, 20), -50.0),
              trade("A", ny(13, 1), ny(13, 40), -25.0), trade("Z", ny(14, 0), ny(14, 5), 10.0)]
    rows = attach_setups(trades, journal)
    assert [r["setup"] for r in rows] == ["vwap", "power-hour", "vwap", "(ohne Journal)"]
    assert [r["r"] for r in rows[:3]] == [2.0, -1.0, -0.5]
    stats = {s["setup"]: s for s in setup_stats(rows)}
    assert stats["vwap"]["n"] == 2 and stats["vwap"]["avg_r"] == pytest.approx(0.75)
    assert stats["vwap"]["profit_factor"] == pytest.approx(4.0)
    assert stats["GESAMT"]["n"] == 4


class FakeTrading:
    def __init__(self, positions=None, orders=None):
        self.positions = positions or []
        self.orders = orders or []
        self.submitted, self.closed_all = [], False

    def get_orders(self, filter=None):
        return self.orders if getattr(filter, "status", None) and filter.status.value == "closed" else []

    def get_all_positions(self):
        return self.positions

    def get_account(self):
        return SimpleNamespace(buying_power="100000")

    def submit_order(self, req):
        self.submitted.append(req)
        return SimpleNamespace(id="o1")

    def close_all_positions(self, cancel_orders=True):
        self.closed_all = True


class FakeData:
    def __init__(self, price):
        self.price = price

    def get_stock_latest_trade(self, req):
        return {req.symbol_or_symbols: SimpleNamespace(price=self.price)}


def test_buy_places_market_order_with_broker_stop_and_journals(tmp_path):
    trading = FakeTrading()
    cp = Copilot(trading, FakeData(25.0), RULES, tmp_path / "j.jsonl")
    msg = cp.buy("xyz", stop=24.0, setup="vwap", now=ny(12, 0), note="test")
    assert msg.startswith("GEKAUFT")
    req = trading.submitted[0]
    assert req.symbol == "XYZ" and req.qty == 50 and req.side == OrderSide.BUY
    assert req.order_class == OrderClass.OTO and req.stop_loss.stop_price == 24.0
    [e] = load_journal(tmp_path / "j.jsonl")
    assert e.setup == "vwap" and e.risk == 50.0 and e.order_id == "o1"


def test_buy_refuses_when_rules_violated(tmp_path):
    trading = FakeTrading()
    cp = Copilot(trading, FakeData(25.0), RULES, tmp_path / "j.jsonl")
    msg = cp.buy("XYZ", stop=24.0, setup="vwap", now=ny(15, 50))
    assert msg.startswith("KEIN TRADE") and trading.submitted == []
    assert not (tmp_path / "j.jsonl").exists()


def test_watch_flattens_at_close_and_on_daily_loss(tmp_path):
    trading = FakeTrading(positions=[SimpleNamespace(symbol="XYZ", unrealized_pl="-20")])
    cp = Copilot(trading, FakeData(25.0), RULES, tmp_path / "j.jsonl")
    assert cp.watch_step(ny(12, 0)) is None and not trading.closed_all
    assert "glattgestellt" in cp.watch_step(ny(15, 55)) and trading.closed_all

    trading = FakeTrading(positions=[SimpleNamespace(symbol="XYZ", unrealized_pl="-160")])
    cp = Copilot(trading, FakeData(25.0), RULES, tmp_path / "j.jsonl")
    assert "Tagesverlust" in cp.watch_step(ny(12, 0)) and trading.closed_all

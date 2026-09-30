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
    def __init__(self, positions=None, orders=None, clock=None):
        self.positions = positions or []
        self.orders = orders or []
        self.submitted, self.closed_all = [], False
        # Standard: normaler Handelstag, Schluss 16:00 ET
        self.clock = clock or SimpleNamespace(is_open=True, next_close=ny(16, 0), next_open=ny(9, 30, day=2))

    def get_clock(self):
        return self.clock

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


class ClosingTrading(FakeTrading):
    """Stop-Order bleibt nach dem Stornieren noch 2 Abfragen offen (Alpaca storniert asynchron)."""
    def __init__(self):
        super().__init__()
        self.open_polls, self.cancelled, self.closed = 3, [], []

    def get_orders(self, filter=None):
        if filter.status.value == "open" and self.open_polls > 0:
            self.open_polls -= 1
            return [SimpleNamespace(id="stop1")]
        return []

    def cancel_order_by_id(self, order_id):
        self.cancelled.append(order_id)

    def close_position(self, symbol):
        assert self.open_polls == 0, "Verkauf gesendet, während der Stop noch offen war"
        self.closed.append(symbol)


def test_close_waits_until_stop_is_cancelled(tmp_path, monkeypatch):
    import tradingbot.copilot as copilot_mod
    monkeypatch.setattr(copilot_mod._systime, "sleep", lambda s: None)
    trading = ClosingTrading()
    cp = Copilot(trading, FakeData(25.0), RULES, tmp_path / "j.jsonl")
    assert "geschlossen" in cp.close("xyz")
    assert trading.cancelled == ["stop1"] and trading.closed == ["XYZ"]


def test_buy_rounds_stop_before_checking_rules(tmp_path):
    trading = FakeTrading()
    cp = Copilot(trading, FakeData(25.0), RULES, tmp_path / "j.jsonl")
    assert cp.buy("XYZ", stop=24.004, setup="vwap", now=ny(12, 0)).startswith("GEKAUFT")
    assert trading.submitted[0].stop_loss.stop_price == 24.0
    [e] = load_journal(tmp_path / "j.jsonl")
    assert e.stop == 24.0


def test_buy_refused_on_market_holiday(tmp_path):
    trading = FakeTrading(clock=SimpleNamespace(is_open=False, next_open=ny(9, 30, day=2), next_close=ny(16, 0, day=2)))
    cp = Copilot(trading, FakeData(25.0), RULES, tmp_path / "j.jsonl")
    msg = cp.buy("XYZ", stop=24.0, setup="vwap", now=ny(12, 0))
    assert "geschlossen" in msg and trading.submitted == []


def test_buy_refused_shortly_before_early_close(tmp_path):
    trading = FakeTrading(clock=SimpleNamespace(is_open=True, next_close=ny(13, 0), next_open=ny(9, 30, day=2)))
    cp = Copilot(trading, FakeData(25.0), RULES, tmp_path / "j.jsonl")
    assert cp.buy("XYZ", stop=24.0, setup="vwap", now=ny(12, 50)).startswith("KEIN TRADE")
    assert trading.submitted == []
    assert cp.buy("XYZ", stop=24.0, setup="vwap", now=ny(12, 30)).startswith("GEKAUFT")


def test_watch_flattens_before_early_close(tmp_path):
    trading = FakeTrading(positions=[SimpleNamespace(symbol="XYZ", unrealized_pl="5")],
                          clock=SimpleNamespace(is_open=True, next_close=ny(13, 0), next_open=ny(9, 30, day=2)))
    cp = Copilot(trading, FakeData(25.0), RULES, tmp_path / "j.jsonl")
    assert cp.watch_step(ny(12, 50)) is None and not trading.closed_all
    assert "Früher Börsenschluss" in cp.watch_step(ny(12, 56)) and trading.closed_all


def test_vwap_is_volume_weighted_typical_price():
    from tradingbot.copilot import vwap
    bars = {"high": [11.0, 13.0], "low": [9.0, 11.0], "close": [10.0, 12.0], "volume": [100, 300]}
    assert vwap(bars) == pytest.approx([10.0, (10 * 100 + 12 * 300) / 400])


def test_suggest_stop_below_recent_low_and_min_distance():
    from tradingbot.copilot import suggest_stop
    bars = {"low": [24.0, 24.5, 24.3, 24.8, 24.9, 24.7, 24.6]}
    assert suggest_stop(bars, 25.0, RULES) == pytest.approx(24.29)       # Tief der letzten 6 = 24,30
    assert suggest_stop({"low": [24.99]}, 25.0, RULES) == pytest.approx(24.92)  # mind. 0,3 % Abstand
    assert suggest_stop({"low": []}, 25.0, RULES) is None


def test_preview_computes_size_and_reports_problems_without_ordering(tmp_path):
    trading = FakeTrading()
    cp = Copilot(trading, FakeData(25.0), RULES, tmp_path / "j.jsonl")
    ok = cp.preview("xyz", 24.0, ny(12, 0), target=27.0)
    assert ok["shares"] == 50 and ok["risk"] == pytest.approx(50.0) and ok["reward_r"] == pytest.approx(2.0)
    assert ok["problems"] == [] and trading.submitted == []
    bad = cp.preview("XYZ", 26.0, ny(12, 0))
    assert bad["shares"] == 0 and any("unter dem Kurs" in p for p in bad["problems"])

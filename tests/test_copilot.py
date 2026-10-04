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
    append_journal,
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


def test_close_when_stop_already_sold(tmp_path, monkeypatch):
    import tradingbot.copilot as copilot_mod
    monkeypatch.setattr(copilot_mod._systime, "sleep", lambda s: None)

    class StoppedOut(ClosingTrading):
        def close_position(self, symbol):
            raise RuntimeError('{"code":40410000,"message":"position not found: XYZ"}')

    cp = Copilot(StoppedOut(), FakeData(25.0), RULES, tmp_path / "j.jsonl")
    assert "bereits verkauft" in cp.close("xyz")


def test_strict_mode_blocks_stops_under_1pct_but_not_below_vwap(tmp_path, monkeypatch):
    import pandas as pd

    trading = FakeTrading()
    cp = Copilot(trading, FakeData(25.0), RULES, tmp_path / "j.jsonl")
    idx = pd.date_range("2026-10-01 09:30", periods=3, freq="5min", tz="America/New_York")
    bars = pd.DataFrame({"open": [26, 26, 26], "high": [26.5] * 3, "low": [25.5] * 3, "close": [26, 26, 26],
                         "volume": [1000] * 3}, index=idx)
    monkeypatch.setattr(cp, "today_bars", lambda s, n: bars)                 # VWAP ~26 > Kurs 25
    assert cp._strict_problems("XYZ", 25.0, 24.95, ny(12, 0)) == []          # aus: keine Sperre
    cp.save_settings(strict=True)
    p = cp._strict_problems("XYZ", 25.0, 24.95, ny(12, 0))
    assert any("Stop zu eng" in x for x in p) and not any("VWAP" in x for x in p)   # VWAP nur noch Hinweis
    assert cp._strict_problems("XYZ", 25.0, 24.0, ny(12, 0)) == []                    # 4 % Stop, unter VWAP: ok
    msg = cp.buy("XYZ", stop=24.8, setup="vwap", now=ny(12, 0))                     # 0,8 %: Standard ok, streng nicht
    assert msg.startswith("KEIN TRADE") and "Strenger Modus: Stop zu eng" in msg and trading.submitted == []


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
    assert suggest_stop({"low": [24.99]}, 25.0, RULES) == pytest.approx(24.87)  # mind. 0,5 % Abstand
    assert suggest_stop({"low": []}, 25.0, RULES) is None


def test_preview_computes_size_and_reports_problems_without_ordering(tmp_path):
    trading = FakeTrading()
    cp = Copilot(trading, FakeData(25.0), RULES, tmp_path / "j.jsonl")
    ok = cp.preview("xyz", 24.0, ny(12, 0), target=27.0)
    assert ok["shares"] == 50 and ok["risk"] == pytest.approx(50.0) and ok["reward_r"] == pytest.approx(2.0)
    assert ok["problems"] == [] and trading.submitted == []
    bad = cp.preview("XYZ", 26.0, ny(12, 0))
    assert bad["shares"] == 0 and any("unter dem Kurs" in p for p in bad["problems"])


class BarsData:
    """SIP: lückenlose Kerzen mit viel Volumen; IEX: wenige Kerzen mit wenig Volumen."""

    def __init__(self, sip, iex):
        self.frames = {"sip": sip, "iex": iex}

    def get_stock_bars(self, req):
        import pandas as pd
        df = self.frames[req.feed.value]
        # alpaca-py wandelt start/end in UTC ohne Zeitzone um
        start, end = (pd.Timestamp(t).tz_localize("UTC") if pd.Timestamp(t).tzinfo is None else pd.Timestamp(t)
                      for t in (req.start, req.end))
        df = df[(df.index >= start) & (df.index < end)]
        df = df.copy()
        df.index = pd.MultiIndex.from_product([["XYZ"], df.index], names=["symbol", "timestamp"])
        return SimpleNamespace(df=df)


def _frame(times, volume):
    import pandas as pd
    return pd.DataFrame({"open": 10.0, "high": 10.5, "low": 9.5, "close": 10.0, "volume": volume},
                        index=pd.DatetimeIndex(times))


def test_today_bars_uses_full_sip_until_delay_then_iex():
    sip_times = [ny(9, 30 + 5 * i) for i in range(6)]            # 9:30 .. 9:55
    iex_times = [ny(9, 35), ny(9, 50), ny(9, 55)]
    cp = Copilot(FakeTrading(), BarsData(_frame(sip_times, 10_000), _frame(iex_times, 20)), RULES, None)
    bars = cp.today_bars("xyz", ny(10, 1))                        # SIP bis 9:45 vollständig
    assert list(bars.index) == [ny(9, 30), ny(9, 35), ny(9, 40), ny(9, 50), ny(9, 55)]
    assert list(bars["volume"]) == [10_000, 10_000, 10_000, 20, 20]
    assert bars.attrs["live_from"] == ny(9, 45)
    assert bars.attrs["iex_share"] == pytest.approx(20 / 30_000)


def test_stale_iex_price_blocks_entry(tmp_path):
    from datetime import timedelta

    class StaleData(FakeData):
        def get_stock_latest_trade(self, req):
            return {req.symbol_or_symbols: SimpleNamespace(price=self.price, timestamp=ny(11, 50))}

    cp = Copilot(FakeTrading(), StaleData(25.0), RULES, tmp_path / "j.jsonl")
    assert any("veraltet" in p for p in cp.preview("XYZ", 24.0, ny(12, 0))["problems"])
    assert cp.preview("XYZ", 24.0, ny(11, 50) + timedelta(minutes=2))["problems"] == []


class BreakevenTrading(FakeTrading):
    """Offene OTO-Order mit Stop-Bein; replace_order_by_id verschiebt den Stop."""

    def __init__(self, current_price):
        super().__init__(positions=[SimpleNamespace(symbol="XYZ", qty="50", avg_entry_price="25.00",
                                                    current_price=str(current_price), unrealized_pl="0")])
        self.stop_leg = SimpleNamespace(id="leg1", side=SimpleNamespace(value="sell"), type=SimpleNamespace(value="stop"),
                                        status=SimpleNamespace(value="new"), stop_price="24.00")
        self.replaced = []

    def get_orders(self, filter=None):
        if filter.status.value == "open":
            parent = SimpleNamespace(id="p1", side=SimpleNamespace(value="buy"), type=SimpleNamespace(value="market"),
                                     status=SimpleNamespace(value="filled"), legs=[self.stop_leg])
            return [parent]
        return super().get_orders(filter)

    def replace_order_by_id(self, order_id, req):
        self.replaced.append((order_id, req.stop_price))
        self.stop_leg.stop_price = str(req.stop_price)


def _journal_with(tmp_path, breakeven):
    path = tmp_path / "j.jsonl"
    append_journal(path, JournalEntry(time=ny(12, 0).isoformat(), symbol="XYZ", setup="vwap", shares=50, price=25.0,
                                      stop=24.0, target=None, risk=50.0, breakeven=breakeven))
    return path


def test_breakeven_moves_stop_to_entry_at_plus_one_r(tmp_path):
    trading = BreakevenTrading(current_price=26.05)                      # +1 R = 26,00
    cp = Copilot(trading, FakeData(26.05), RULES, _journal_with(tmp_path, True))
    msg = cp.watch_step(ny(12, 30))
    assert "Einstand 25.00" in msg and trading.replaced == [("leg1", 25.0)]
    assert cp.watch_step(ny(12, 31)) is None and len(trading.replaced) == 1   # nur einmal


def test_breakeven_waits_below_one_r_and_respects_choice(tmp_path):
    trading = BreakevenTrading(current_price=25.90)
    cp = Copilot(trading, FakeData(25.9), RULES, _journal_with(tmp_path, True))
    assert cp.watch_step(ny(12, 30)) is None and trading.replaced == []
    # ohne Häkchen beim Kauf: auch bei +2 R bleibt der Stop, wo er ist
    other = tmp_path / "ohne"
    other.mkdir()
    trading = BreakevenTrading(current_price=27.00)
    cp = Copilot(trading, FakeData(27.0), RULES, _journal_with(other, False))
    assert cp.watch_step(ny(12, 30)) is None and trading.replaced == []


def test_old_journal_lines_without_breakeven_still_load(tmp_path):
    path = tmp_path / "j.jsonl"
    path.write_text('{"time": "2026-10-01T16:00:00+00:00", "symbol": "A", "setup": "x", "shares": 1, "price": 10.0, '
                    '"stop": 9.0, "target": null, "risk": 1.0, "note": "", "order_id": "o"}' + chr(10), encoding="utf-8")
    [e] = load_journal(path)
    assert e.breakeven is False


def test_stop_suggestion_meets_strict_minimum_after_fill():
    from tradingbot.copilot import STRICT_MIN_STOP, stop_rules, suggest_stop
    bars = {"low": [24.99, 24.95, 24.97]}                      # letztes Tief nur 0,2 % unter dem Kurs
    loose = suggest_stop(bars, 25.0, stop_rules(RULES, False))
    strict = suggest_stop(bars, 25.0, stop_rules(RULES, True))
    assert loose == pytest.approx(24.87)                        # normal: 0,5 %
    assert (25.0 - strict) / 25.0 >= STRICT_MIN_STOP            # streng/Übung: >= 1 %
    entry = 25.0 * 1.0009                                       # Einstieg zur nächsten Kerze etwas höher
    assert (entry - strict) / entry >= STRICT_MIN_STOP          # hält die Nachbesprechung trotzdem ein

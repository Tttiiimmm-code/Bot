from __future__ import annotations

import random
from datetime import date, datetime, time, timedelta
from types import SimpleNamespace

import pandas as pd
import pytest

from tradingbot import replay as rpl
from tradingbot.copilot import NY, entry_warnings

DAY = date(2026, 9, 29)


def bars_from(rows, start=time(12, 0), day=DAY):
    """rows: [(open, high, low, close)] als 5-Minuten-Kerzen ab `start`."""
    t0 = datetime.combine(day, start, tzinfo=NY)
    idx = [t0 + timedelta(minutes=5 * i) for i in range(len(rows))]
    return pd.DataFrame([{"open": o, "high": h, "low": lo, "close": c, "volume": 1000} for o, h, lo, c in rows],
                        index=pd.DatetimeIndex(idx))


def test_entry_at_next_open_and_target_hit():
    bars = bars_from([(10.0, 10.1, 9.9, 10.0), (10.05, 10.2, 10.0, 10.15), (10.15, 10.45, 10.1, 10.4)])
    pos = rpl.open_position(bars, 1, stop=9.85, target=10.45, setup="vwap-pullback")
    assert pos.entry == 10.05 and pos.one_r == pytest.approx(0.20)
    assert rpl.check_exit(bars, pos, 1) is None
    price, reason = rpl.check_exit(bars, pos, 2)
    assert (price, reason) == (10.45, "Ziel")
    res = rpl.make_result("XYZ", DAY.isoformat(), bars, pos, 2, price, reason)
    assert res.r == pytest.approx(2.0) and res.entry_time == "12:05" and res.exit_time == "12:10"


def test_stop_wins_when_stop_and_target_in_same_bar():
    bars = bars_from([(10.0, 10.0, 10.0, 10.0), (10.0, 10.6, 9.7, 10.0)])
    pos = rpl.open_position(bars, 1, stop=9.8, target=10.4, setup="x")
    assert rpl.check_exit(bars, pos, 1) == (9.8, "Stop")


def test_gap_below_stop_exits_at_open():
    bars = bars_from([(10.0, 10.0, 10.0, 10.0), (10.0, 10.1, 9.9, 10.0), (9.5, 9.6, 9.4, 9.5)])
    pos = rpl.open_position(bars, 1, stop=9.8, target=None, setup="x")
    assert rpl.check_exit(bars, pos, 1) is None
    assert rpl.check_exit(bars, pos, 2) == (9.5, "Stop (Kurslücke)")


def test_breakeven_moves_stop_after_plus_one_r_bar():
    bars = bars_from([(10.0,) * 4, (10.0, 10.25, 9.95, 10.2), (10.2, 10.2, 9.99, 10.0)])
    pos = rpl.open_position(bars, 1, stop=9.8, target=10.6, setup="x", breakeven=True)
    assert rpl.check_exit(bars, pos, 1) is None and pos.stop == 10.0     # +1 R erreicht -> Einstand
    assert rpl.check_exit(bars, pos, 2) == (10.0, "Stop auf Einstand")


def test_flatten_at_close_and_on_last_bar_of_short_day():
    bars = bars_from([(10.0,) * 4, (10.0, 10.1, 9.95, 10.05), (10.05, 10.1, 10.0, 10.08)], start=time(15, 40))
    pos = rpl.open_position(bars, 1, stop=9.8, target=None, setup="x")
    assert rpl.check_exit(bars, pos, 1) is None
    assert rpl.check_exit(bars, pos, 2) == (10.08, "Handelsschluss")   # Kerze 15:50
    short = bars_from([(10.0,) * 4, (10.0, 10.1, 9.95, 10.05)], start=time(12, 50))   # Schluss 13:00
    pos = rpl.open_position(short, 1, stop=9.8, target=None, setup="x")
    assert rpl.check_exit(short, pos, 1) == (10.05, "Handelsschluss")


def test_invalid_orders_rejected():
    bars = bars_from([(10.0,) * 4, (10.0,) * 4])
    with pytest.raises(ValueError):
        rpl.open_position(bars, 1, stop=10.1, target=None, setup="x")
    with pytest.raises(ValueError):
        rpl.open_position(bars, 1, stop=9.9, target=9.95, setup="x")


def test_journal_roundtrip_and_summary(tmp_path):
    path = tmp_path / "r.jsonl"
    for r in (2.0, -1.0, -1.0, 0.5):
        rpl.append_result(path, rpl.Result("X", "2026-09-29", "vwap", "12:00", 10, 9.8, None, "12:30", 10, "Ziel", r))
    s = rpl.summarize(rpl.load_results(path))
    assert s["n"] == 4 and s["win_rate"] == 0.5 and s["sum_r"] == pytest.approx(0.5)
    assert s["profit_factor"] == pytest.approx(1.25)


# ------------------------------------------------------------ Kursdaten mit Ersatz-Clients

def _session(d, close=time(16, 0)):
    return SimpleNamespace(date=d, open=time(9, 30), close=close)


class FakeTrading:
    def __init__(self, days):
        self.days = days

    def get_calendar(self, req):
        return [_session(d) for d in self.days if req.start <= d <= req.end]


class FakeData:
    """Vortag schließt bei 100; am Tag liegt der Kurs den ganzen Tag bei `level`."""

    def __init__(self, level=103.0):
        self.level = level
        self.calls = 0

    def get_stock_bars(self, req):
        self.calls += 1
        start = pd.Timestamp(req.start)
        start = start.tz_localize("UTC") if start.tzinfo is None else start
        prev_day = start.tz_convert(NY).date()
        rows, idx = [], []
        for d, px in ((prev_day, 100.0), (DAY, self.level)):
            t0 = datetime.combine(d, time(9, 30), tzinfo=NY)
            for i in range(78):
                idx.append(t0 + timedelta(minutes=5 * i))
                rows.append({"open": px, "high": px + 0.1, "low": px - 0.1, "close": px, "volume": 1000})
        df = pd.DataFrame(rows, index=pd.MultiIndex.from_product([[req.symbol_or_symbols], idx],
                                                                 names=["symbol", "timestamp"]))
        return SimpleNamespace(df=df)


def test_load_day_splits_today_and_previous_close():
    trading = FakeTrading([DAY - timedelta(days=1), DAY])
    bars, prev_close = rpl.load_day(FakeData(), trading, "xyz", DAY)
    assert prev_close == 100.0 and len(bars) == 78
    assert bars.index[0].time() == time(9, 30) and bars.index[-1].time() == time(15, 55)
    assert rpl.start_index(bars, time(12, 0)) == 30
    with pytest.raises(ValueError):
        rpl.load_day(FakeData(), trading, "xyz", DAY + timedelta(days=1))


def test_pick_random_day_prefers_stocks_up_at_start():
    trading = FakeTrading([DAY - timedelta(days=1), DAY])
    symbol, day, bars, prev_close = rpl.pick_random_day(FakeData(level=103.0), trading, DAY + timedelta(days=1),
                                                        rng=random.Random(1), symbols=("AAA",))
    assert (symbol, day, prev_close) == ("AAA", DAY, 100.0)
    # nie im Plus: nach `tries` Versuchen der erste gefundene Tag als Ersatz
    data = FakeData(level=99.0)
    symbol, day, _, _ = rpl.pick_random_day(data, trading, DAY + timedelta(days=1), rng=random.Random(1),
                                            symbols=("AAA",), tries=3)
    assert day == DAY and 1 <= data.calls <= 3   # Tage ohne Vortag in den Testdaten werden ohne Abruf übersprungen


# ------------------------------------------------------------ Hinweise beim Einstieg und Pfeile im Chart

def test_entry_warnings_below_vwap_and_stop_above_recent_low():
    bars = {"high": [10.5, 10.4, 10.3, 10.2], "low": [10.3, 10.2, 10.0, 9.9], "close": [10.4, 10.3, 10.1, 10.0],
            "volume": [1000, 1000, 1000, 1000]}
    w = entry_warnings(bars, price=10.0, stop=9.95)
    assert len(w) == 2 and "unter der VWAP" in w[0] and "über dem Tief" in w[1]
    up = {"high": [10.1, 10.3, 10.5], "low": [9.9, 10.1, 10.3], "close": [10.0, 10.2, 10.4], "volume": [1, 1, 1]}
    assert entry_warnings(up, price=10.45, stop=9.85) == []
    assert entry_warnings({"high": [], "low": [], "close": [], "volume": []}, 10.0, 9.0) == []


def test_chart_draws_trade_markers():
    from gui.chart import build_chart

    bars = bars_from([(10.0, 10.1, 9.9, 10.0), (10.0, 10.2, 9.95, 10.1)])
    fill = bars.index[1] + timedelta(minutes=2)
    fig = build_chart(bars, "XYZ", 9.8, None, markers=[(fill, "buy", 10.02), (fill, "sell", 10.1)],
                      uirevision="replay_XYZ")
    names = [t.name for t in fig.data]
    assert "Kauf" in names and "Verkauf" in names and fig.layout.uirevision == "replay_XYZ"
    buy = next(t for t in fig.data if t.name == "Kauf")
    assert pd.Timestamp(buy.x[0]) == bars.index[1]           # an die Kerze gesetzt


def test_goal_stats_and_above_vwap_field():
    from tradingbot.replay import Result, goal_stats

    def res(r, above, stop=99.0):
        return Result("X", "2026-09-30", "vwap", "10:00", 100.0, stop, None, "10:30", 101.0, "ziel", r, "", above,
                      "nur über VWAP kaufen")
    rs = [res(1.0, True), res(-1.0, False), res(2.0, True)]
    s = goal_stats(rs, "nur über VWAP kaufen")
    assert s == {"n": 3, "kept": 2, "avg_kept": 1.5, "avg_broken": -1.0}
    assert goal_stats(rs, "frei") is None


def test_review_tight_stop_below_vwap_and_target_reached_later():
    # Vorlauf über 10,10 (VWAP ~10,1), Einstieg 10,00 darunter, Stop 9,98 (0,2 %), Rücksetzer-Tief 9,90
    bars = bars_from([(10.2, 10.25, 10.15, 10.2), (10.1, 10.12, 9.91, 9.95), (10.0, 10.02, 9.95, 9.97),
                      (9.97, 10.1, 9.96, 10.08), (10.08, 10.2, 10.05, 10.18)])
    pos = rpl.open_position(bars, 2, stop=9.98, target=10.06, setup="vwap-pullback")
    price, reason = rpl.check_exit(bars, pos, 2)
    assert reason == "Stop"
    notes = rpl.review(bars, pos, 2, reason, wide_stop=9.90)
    kinds = [k for k, _ in notes]
    texts = " ".join(t for _, t in notes)
    assert "UNTER der VWAP" in texts and "Stop nur 0.20%" in texts
    assert "hättest du Ziel erreicht" in texts and "Der Stop war zu eng" in texts
    assert "Nach deinem Stop lief der Kurs noch bis zu deinem Ziel" in texts
    assert kinds.count("achtung") == 3


def test_review_wide_stop_would_also_fail_and_target_praise():
    bars = bars_from([(10.0, 10.05, 9.95, 10.0), (10.0, 10.0, 9.5, 9.6), (9.6, 9.6, 9.3, 9.4)])
    pos = rpl.open_position(bars, 1, stop=9.9, target=10.3, setup="x")
    price, reason = rpl.check_exit(bars, pos, 1)
    notes = rpl.review(bars, pos, 1, reason, wide_stop=9.7)
    assert any("die Idee war falsch" in t for _, t in notes)
    win = bars_from([(10.0, 10.05, 9.95, 10.0), (10.0, 10.4, 9.95, 10.3)])
    pos2 = rpl.open_position(win, 1, stop=9.9, target=10.3, setup="x")
    assert ("gut", "Ziel erreicht -- Plan eingehalten.") in rpl.review(win, pos2, 1, "Ziel", wide_stop=9.8)

from pathlib import Path

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

APP = str(Path(__file__).resolve().parents[1] / "gui" / "copilot_app.py")


@pytest.fixture(autouse=True)
def _fresh_copilot_cache():
    """get_copilot ist per st.cache_resource gecacht -- ohne Leeren bekäme jeder Test den Copilot des vorigen."""
    import streamlit as st

    st.cache_resource.clear()
    yield


def test_gui_without_env_file_shows_setup_instructions(tmp_path, monkeypatch):
    monkeypatch.setenv("COPILOT_ENV", str(tmp_path / "missing.env"))
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception
    assert any("copilot.env fehlt" in e.value for e in at.error)


class _FakeCopilot:
    """Minimaler Ersatz für Copilot: Markt offen, ein Symbol mit Kerzen, keine Positionen."""

    def __init__(self):
        from datetime import datetime, timedelta, timezone
        from types import SimpleNamespace

        import pandas as pd

        from tradingbot.copilot import NY, CopilotRules

        self.rules = CopilotRules()
        self.bought = []
        t0 = datetime.now(timezone.utc).astimezone(NY).replace(hour=10, minute=0, second=0, microsecond=0)
        self._bars = pd.DataFrame({"open": [10.0, 10.2], "high": [10.3, 10.5], "low": [9.9, 10.1],
                                   "close": [10.2, 10.4], "volume": [1000, 2000]},
                                  index=[t0, t0 + timedelta(minutes=5)])
        clock = SimpleNamespace(is_open=True, next_open=t0, next_close=t0 + timedelta(hours=6))
        self.trading_client = SimpleNamespace(get_clock=lambda: clock, get_all_positions=lambda: [])

    def state(self, now):
        from tradingbot.copilot import DayState
        return DayState()

    def today_bars(self, symbol, now):
        return self._bars

    def latest_price(self, symbol):
        # Kurs ändert sich bei jedem Neuaufbau -- wie live; darf den eingegebenen Stop nicht zurücksetzen
        self.calls = getattr(self, "calls", 0) + 1
        return 10.4 + 0.05 * self.calls

    def preview(self, symbol, stop, now, target=None):
        return {"symbol": symbol, "price": 10.4, "shares": 10, "risk": 10 * (10.4 - stop), "value": 104.0,
                "reward_r": None, "problems": []}

    def buy(self, symbol, stop, setup, now, target=None, note="", breakeven=False):
        self.bought.append((symbol, stop))
        self.breakeven = breakeven
        return f"GEKAUFT (Market): {symbol}"

    def _closed_trades(self, now, days=1):
        return [], []

    def journal_risk(self, symbol, now):
        return None


def test_gui_keeps_typed_stop_and_resets_confirmation_after_buy(tmp_path, monkeypatch):
    env = tmp_path / "copilot.env"
    env.write_text("ALPACA_API_KEY=x\nALPACA_SECRET_KEY=y\nALPACA_PAPER=true\n")
    monkeypatch.setenv("COPILOT_ENV", str(env))
    monkeypatch.setenv("COPILOT_JOURNAL", str(tmp_path / "j.jsonl"))
    fake = _FakeCopilot()
    import tradingbot.copilot as copilot_mod
    monkeypatch.setattr(copilot_mod, "Copilot", lambda *a, **k: fake)

    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception
    at.text_input[0].set_value("XYZ").run()
    stop = next(n for n in at.number_input if n.key == "stop_XYZ")
    stop.set_value(9.5).run()
    at.text_area[0].set_value("Notiz").run()          # andere Eingabe -> Neuaufbau der Seite
    assert next(n for n in at.number_input if n.key == "stop_XYZ").value == 9.5
    use = next(b for b in at.button if b.key == "use_XYZ")     # Vorschlag übernehmen (Tief 9.9 - 0.01)
    use.click().run()
    assert not at.exception
    assert next(n for n in at.number_input if n.key == "stop_XYZ").value == pytest.approx(9.89)
    next(n for n in at.number_input if n.key == "stop_XYZ").set_value(9.5).run()
    at.checkbox(key="confirmed").check().run()
    next(b for b in at.button if b.label == "Kaufen").click().run()
    assert not at.exception
    assert fake.bought == [("XYZ", 9.5)]
    assert at.checkbox(key="confirmed").value is False
    assert any("GEKAUFT" in s.value for s in at.success)


def test_gui_scan_shows_first_candidate_chart(tmp_path, monkeypatch):
    from types import SimpleNamespace

    env = tmp_path / "copilot.env"
    env.write_text("ALPACA_API_KEY=x\nALPACA_SECRET_KEY=y\nALPACA_PAPER=true\n")
    monkeypatch.setenv("COPILOT_ENV", str(env))
    monkeypatch.setenv("COPILOT_JOURNAL", str(tmp_path / "j.jsonl"))
    fake = _FakeCopilot()
    import tradingbot.copilot as copilot_mod
    import tradingbot.scanner as scanner_mod
    monkeypatch.setattr(copilot_mod, "Copilot", lambda *a, **k: fake)
    found = [SimpleNamespace(symbol="AAA", price=10.0, percent_change=12.0, relative_volume=3.0),
             SimpleNamespace(symbol="BBB", price=20.0, percent_change=8.0, relative_volume=2.5)]
    monkeypatch.setattr(scanner_mod.Scanner, "__init__", lambda self, cfg: None)
    monkeypatch.setattr(scanner_mod.Scanner, "scan", lambda self, criteria: found)

    at = AppTest.from_file(APP, default_timeout=60).run()
    next(b for b in at.button if b.label == "Kandidaten suchen").click().run()
    assert not at.exception
    assert at.text_input(key="symbol_input").value == "AAA"
    assert any(h.value == "2. Chart AAA" for h in at.subheader)
    assert any("aktualisiert sich alle 5 Minuten" in c.value for c in at.caption)   # Chart-Fragment gezeichnet
    # Checkliste steht beim Kaufen (aufklappbar) UND in der Anleitung -- AppTest listet Expander nicht auf
    assert sum("Kopf frei" in m.value for m in at.markdown) == 2
    texts = " ".join(m.value for m in at.markdown)
    assert "Checkliste vor jedem Kauf" in texts and "Typische Anfängerfehler" in texts  # Anleitung
    at.button(key="pick_BBB").click().run()                    # Zeile anklicken -> Chart BBB
    assert not at.exception
    assert any(h.value == "2. Chart BBB" for h in at.subheader)
    at.text_input(key="symbol_input").set_value("CCC").run()   # von Hand getippt bleibt stehen
    assert any(h.value == "2. Chart CCC" for h in at.subheader)


def test_chart_is_tradingview_like():
    from datetime import datetime, timedelta

    import pandas as pd

    from gui.chart import CHART_CONFIG, build_chart
    from tradingbot.copilot import NY

    t0 = datetime(2026, 10, 1, 10, 0, tzinfo=NY)
    bars = pd.DataFrame({"open": [10.0, 10.4], "high": [10.5, 10.6], "low": [9.9, 10.1], "close": [10.4, 10.2],
                         "volume": [1000, 2000]}, index=[t0, t0 + timedelta(minutes=5)])
    bars.attrs.update(live_from=t0 + timedelta(minutes=5))
    fig = build_chart(bars, "XYZ", stop=9.8, target=10.8)
    assert CHART_CONFIG["scrollZoom"] is True                   # Mausrad zoomt
    assert fig.layout.dragmode == "pan"                         # Ziehen verschiebt
    assert fig.layout.uirevision == "XYZ"                       # Zoom bleibt beim Neuladen
    assert [tr.type for tr in fig.data] == ["candlestick", "scatter", "bar"]   # Kerzen, VWAP, Volumen
    assert fig.layout.yaxis.side == "right"
    texts = [a.text for a in fig.layout.annotations]
    assert "Stop 9.80" in texts and "Ziel 10.80" in texts and " 10.20 " in texts


@pytest.mark.parametrize("unreal,delta,color", [("-12.5", "-12.50 $ offen", "RED"), ("7", "+7.00 $ offen", "GREEN"),
                                                ("0", "+0.00 $ offen", "GRAY")])
def test_header_open_pnl_colored_by_sign(tmp_path, monkeypatch, unreal, delta, color):
    from types import SimpleNamespace

    from streamlit.proto.Metric_pb2 import Metric

    env = tmp_path / "copilot.env"
    env.write_text("ALPACA_API_KEY=x" + chr(10) + "ALPACA_SECRET_KEY=y" + chr(10) + "ALPACA_PAPER=true" + chr(10))
    monkeypatch.setenv("COPILOT_ENV", str(env))
    monkeypatch.setenv("COPILOT_JOURNAL", str(tmp_path / "j.jsonl"))
    fake = _FakeCopilot()
    clock = fake.trading_client.get_clock()
    fake.trading_client = SimpleNamespace(get_clock=lambda: clock,
                                          get_all_positions=lambda: [SimpleNamespace(
                                              symbol="XYZ", qty="10", avg_entry_price="10.00", current_price="10.00",
                                              unrealized_pl=unreal)])
    import tradingbot.copilot as copilot_mod
    monkeypatch.setattr(copilot_mod, "Copilot", lambda *a, **k: fake)

    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception
    m = next(m for m in at.metric if m.label == "Heute realisiert")
    assert m.delta == delta
    assert Metric.MetricColor.Name(m.proto.color) == color


def test_practice_tab_load_buy_and_finish_trade(tmp_path, monkeypatch):
    from datetime import date, datetime, time, timedelta

    import pandas as pd

    import tradingbot.copilot as copilot_mod
    import tradingbot.replay as rpl
    from tradingbot.copilot import NY

    env = tmp_path / "copilot.env"
    env.write_text("ALPACA_API_KEY=x" + chr(10) + "ALPACA_SECRET_KEY=y" + chr(10) + "ALPACA_PAPER=true" + chr(10))
    monkeypatch.setenv("COPILOT_ENV", str(env))
    monkeypatch.setenv("COPILOT_JOURNAL", str(tmp_path / "j.jsonl"))
    monkeypatch.setenv("COPILOT_REPLAY_JOURNAL", str(tmp_path / "replay.jsonl"))
    fake = _FakeCopilot()
    fake.data_client = None   # wird durch das ersetzte pick_random_day nicht benutzt
    monkeypatch.setattr(copilot_mod, "Copilot", lambda *a, **k: fake)

    # Tag: bis 12:00 steigt der Kurs langsam, danach steigt er weiter bis zum Ziel
    day = date(2026, 9, 29)
    t0 = datetime.combine(day, time(9, 30), tzinfo=NY)
    rows = [100 + 0.05 * i for i in range(78)]
    bars = pd.DataFrame([{"open": p, "high": p + 0.1, "low": p - 0.1, "close": p + 0.04, "volume": 1000} for p in rows],
                        index=pd.DatetimeIndex([t0 + timedelta(minutes=5 * i) for i in range(78)]))
    monkeypatch.setattr(rpl, "pick_random_day", lambda *a, **k: ("XYZ", day, bars, 98.0))

    at = AppTest.from_file(APP, default_timeout=60).run()
    next(b for b in at.button if b.label == "Tag laden").click().run()
    assert not at.exception
    assert any(h.value.startswith("XYZ · 29.09.2026") for h in at.subheader), ([h.value for h in at.subheader], [e.value for e in at.error], [i.value for i in at.info][:3])
    stop = next(n for n in at.number_input if n.key == "rp_stop")
    stop.set_value(float(bars["close"].iloc[29]) - 0.5).run()
    next(b for b in at.button if b.label == "Kaufen" and b.key is None or b.label == "Kaufen").click().run()
    assert not at.exception
    next(b for b in at.button if b.label == "Bis Trade-Ende").click().run()
    assert not at.exception
    results = rpl.load_results(tmp_path / "replay.jsonl")
    assert len(results) == 1 and results[0].symbol == "XYZ" and results[0].reason == "Ziel"
    assert results[0].r == pytest.approx(2.0, abs=0.05)
    assert any(m.label == "Übungs-Trades" and m.value == "1" for m in at.metric)


def test_practice_tab_shows_load_error(tmp_path, monkeypatch):
    import tradingbot.copilot as copilot_mod
    import tradingbot.replay as rpl

    env = tmp_path / "copilot.env"
    env.write_text("ALPACA_API_KEY=x" + chr(10) + "ALPACA_SECRET_KEY=y" + chr(10) + "ALPACA_PAPER=true" + chr(10))
    monkeypatch.setenv("COPILOT_ENV", str(env))
    monkeypatch.setenv("COPILOT_JOURNAL", str(tmp_path / "j.jsonl"))
    monkeypatch.setenv("COPILOT_REPLAY_JOURNAL", str(tmp_path / "replay.jsonl"))
    fake = _FakeCopilot()
    fake.data_client = None
    monkeypatch.setattr(copilot_mod, "Copilot", lambda *a, **k: fake)

    def boom(*a, **k):
        raise ValueError("Netz weg")

    monkeypatch.setattr(rpl, "pick_random_day", boom)
    at = AppTest.from_file(APP, default_timeout=60).run()
    next(b for b in at.button if b.label == "Tag laden").click().run()
    assert not at.exception
    assert any("Tag konnte nicht geladen werden: Netz weg" in e.value for e in at.error), [e.value for e in at.error]

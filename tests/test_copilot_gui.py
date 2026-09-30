from pathlib import Path

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

APP = str(Path(__file__).resolve().parents[1] / "gui" / "copilot_app.py")


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

    def buy(self, symbol, stop, setup, now, target=None, note=""):
        self.bought.append((symbol, stop))
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
    at.button(key="pick_BBB").click().run()                    # Zeile anklicken -> Chart BBB
    assert not at.exception
    assert any(h.value == "2. Chart BBB" for h in at.subheader)
    at.text_input(key="symbol_input").set_value("CCC").run()   # von Hand getippt bleibt stehen
    assert any(h.value == "2. Chart CCC" for h in at.subheader)

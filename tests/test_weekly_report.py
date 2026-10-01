from contextlib import nullcontext
from datetime import datetime

from tradingbot.notify import CopilotAlerts, Notifier
from tradingbot.weekly_report import NY, summarize_week


def row(sym, setup, r, above, price=100.0, stop=99.0):
    return {"symbol": sym, "setup": setup, "pnl": r * 50, "r": r, "planned_price": price, "stop": stop,
            "above_vwap": above}


START, END = datetime(2026, 9, 28, tzinfo=NY), datetime(2026, 10, 2, 16, 15, tzinfo=NY)


def test_summary_counts_vwap_split_tight_stops_and_tips():
    rows = [row("A", "vwap-pullback", -1.0, False, stop=99.8), row("B", "vwap-pullback", -1.0, False, stop=99.7),
            row("C", "orb", 2.0, True), row("D", "orb", -1.0, True), row("E", "power-hour", -0.5, None)]
    title, text = summarize_week(rows, 12, START, END)
    assert title == "Wochenbericht 28.09.-02.10."
    assert "5 Trades, 1 Gewinner (20%), Summe -1.5 R (-75 $)" in text
    assert "über VWAP: 2x Ø +0.50 R · unter VWAP: 2x Ø -1.00 R" in text
    assert "eng (< 0,5 %): 2x Ø -1.00 R" in text
    assert "nur über der VWAP kaufen" in text and "Enge Stops" in text and "Bestes Setup diese Woche: orb" in text
    assert "12 von 100 Trades" in text


def test_summary_without_trades():
    assert "Keine abgeschlossenen Trades" in summarize_week([], 3, START, END)[1]


class Opener:
    def __init__(self):
        self.n = 0

    def __call__(self, req, timeout=None):
        self.n += 1
        return nullcontext()


def test_weekly_step_only_friday_after_close_and_once(tmp_path):
    op = Opener()
    a = CopilotAlerts(Notifier("t", opener=op), tmp_path / "s.json")
    build = lambda: ("Wochenbericht", "Text")  # noqa: E731
    assert a.weekly_step(datetime(2026, 10, 1, 17, 0, tzinfo=NY), build) == []     # Donnerstag
    assert a.weekly_step(datetime(2026, 10, 2, 15, 0, tzinfo=NY), build) == []     # Freitag vor Schluss
    assert a.weekly_step(datetime(2026, 10, 2, 16, 15, tzinfo=NY), build) == ["Wochenbericht"]
    assert a.weekly_step(datetime(2026, 10, 2, 16, 20, tzinfo=NY), build) == []    # nur einmal
    assert op.n == 1

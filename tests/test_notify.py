from contextlib import nullcontext
from datetime import datetime

from tradingbot.notify import CopilotAlerts, Notifier
from tradingbot.orb_scanner import NY, OrbSetup


class FakeOpener:
    def __init__(self, fail=False):
        self.requests = []
        self.fail = fail

    def __call__(self, req, timeout=None):
        if self.fail:
            raise OSError("kein Netz")
        self.requests.append(req)
        return nullcontext()


def now(hh=10, mm=0, day=1):
    return datetime(2026, 10, day, hh, mm, tzinfo=NY)


def setup(sym, state, side="long", trig=None):
    return OrbSetup(sym, 3.0, side, 10.5, 9.9, 10.5, 9.9, 11.7, state, state, trig)


def test_notifier_posts_to_topic_with_ascii_title():
    op = FakeOpener()
    n = Notifier("geheim123", opener=op)
    assert n.send("Ausbruch über Hoch", "Text mit Ümlaut", "high", "rocket")
    req = op.requests[0]
    assert req.full_url == "https://ntfy.sh/geheim123" and req.data == "Text mit Ümlaut".encode()
    assert req.get_header("Title") == "Ausbruch ueber Hoch" and req.get_header("Priority") == "high"


def test_notifier_disabled_and_network_error_never_raise():
    assert not Notifier(None).send("a", "b")
    assert not Notifier("t", opener=FakeOpener(fail=True)).send("a", "b")


def test_melder_summary_once_breakout_once_then_outcome(tmp_path):
    op = FakeOpener()
    a = CopilotAlerts(Notifier("t", opener=op), tmp_path / "s.json")
    sent = a.melder_step(now(), [setup("AAA", "wartet"), setup("BBB", "wartet", side="short")])
    assert len(sent) == 1 and "AAA long" in sent[0] and "BBB short" in sent[0]
    assert a.melder_step(now(10, 5), [setup("AAA", "wartet")]) == []          # nichts Neues
    trig = now(10, 7)
    sent = a.melder_step(now(10, 10), [setup("AAA", "läuft", trig=trig)])
    assert len(sent) == 1 and "AAA bricht aus (16:07 Uhr)" in sent[0] and "Stop 9.90" in sent[0]
    # neue Instanz (Neustart): kein Doppel, Ausgang wird gemeldet
    b = CopilotAlerts(Notifier("t", opener=op), tmp_path / "s.json")
    assert b.melder_step(now(10, 15), [setup("AAA", "läuft", trig=trig)]) == []
    assert b.melder_step(now(10, 30), [setup("AAA", "ziel", trig=trig)]) == ["AAA: Ziel erreicht (+2 R)"]
    # Short-Setups lösen nie eine Ausbruchsmeldung aus; neuer Tag -> neue Zusammenfassung
    assert b.melder_step(now(10, 0, day=2), [setup("CCC", "läuft", side="short")])[0].startswith("Top 5")


def test_positions_closed_and_watch_messages(tmp_path):
    op = FakeOpener()
    a = CopilotAlerts(Notifier("t", opener=op), tmp_path / "s.json")
    calls = []
    assert a.positions_step(now(), {"AAA", "BBB"}, None, lambda: calls.append(1) or 0.0) == []
    assert calls == []                                                          # nur bei Schließung abgefragt
    sent = a.positions_step(now(10, 1), {"BBB"}, "AAA: Stop auf Einstand nachgezogen.", lambda: 42.5)
    assert sent[0].startswith("AAA: Stop auf Einstand") and "AAA: Position geschlossen" in sent[1]
    assert "+42.50 $" in sent[1]
    assert a.positions_step(now(10, 2), {"BBB"}, None) == []

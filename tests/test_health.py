from datetime import datetime

from tradingbot import health


class FakeNotifier:
    def __init__(self):
        self.msgs = []

    def send(self, title, text, priority="default", tags=""):
        self.msgs.append((title, text))
        return True


def test_problems_detects_stopped_service_failed_timer_and_stale_recorder(tmp_path):
    states = {"is-active momentum.service": "failed", "show -p Result --value forward-stocks.service": "exit-code"}
    run = lambda *a: states.get(" ".join(a), "active" if a[0] == "is-active" else "success")  # noqa: E731
    f = tmp_path / "bybit.csv"
    f.write_text("x")
    import os
    os.utime(f, (0, 0))                                   # uralt -> Recorder steht
    p = health.problems(run=run, disk_path=str(tmp_path), liq_dir=tmp_path)
    assert "Dienst momentum läuft nicht (failed)" in p
    assert "Letzter Lauf forward-stocks fehlgeschlagen (exit-code)" in p
    assert any("Recorder" in x for x in p)


def test_step_reports_changes_once_and_daily_summary(tmp_path):
    n, state = FakeNotifier(), tmp_path / "s.json"
    t = datetime(2026, 10, 2, 7, 0, tzinfo=health.BERLIN)
    health.step(n, state, t, check=lambda: ["Dienst momentum läuft nicht (failed)"])
    health.step(n, state, t, check=lambda: ["Dienst momentum läuft nicht (failed)"])     # nicht wiederholen
    assert [m[0] for m in n.msgs] == ["VPS: Problem"]
    health.step(n, state, t, check=lambda: [])
    assert n.msgs[-1][0] == "VPS: wieder in Ordnung"
    health.step(n, state, datetime(2026, 10, 2, 8, 40, tzinfo=health.BERLIN), check=lambda: [])
    health.step(n, state, datetime(2026, 10, 2, 9, 0, tzinfo=health.BERLIN), check=lambda: [])
    assert sum(m[0] == "VPS: Tagesstatus" for m in n.msgs) == 1 and "Alles läuft" in n.msgs[-1][1]


def test_failed_alert_is_retried(tmp_path):
    n, state = FakeNotifier(), tmp_path / "s.json"
    t = datetime(2026, 10, 2, 7, 0, tzinfo=health.BERLIN)
    n.send = lambda *a, **k: False                                     # ntfy nicht erreichbar
    health.step(n, state, t, check=lambda: ["Dienst pelosi-bot läuft nicht (failed)"])
    n.send = FakeNotifier.send.__get__(n)
    health.step(n, state, t, check=lambda: ["Dienst pelosi-bot läuft nicht (failed)"])
    assert [m[0] for m in n.msgs] == ["VPS: Problem"]                  # beim nächsten Lauf nachgeholt

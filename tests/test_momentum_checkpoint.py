from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from tradingbot import momentum_checkpoint as mc


def trade(i, pnl, shares=100, day=24):
    t0 = datetime(2026, 9, day, 14, 0, tzinfo=timezone.utc) + timedelta(minutes=i)
    return SimpleNamespace(entry_time=t0, exit_time=t0 + timedelta(minutes=5), pnl=pnl, shares=shares)


class FakeNotifier:
    def __init__(self, ok=True):
        self.ok, self.sent = ok, []

    def send(self, title, message, priority="default", tags=""):
        self.sent.append((title, message))
        return self.ok


def test_counts_from_start_and_applies_costs():
    ts = [trade(0, 10.0, day=22), trade(1, 10.0), trade(2, -5.0)]
    c = mc.counted(ts)
    assert len(c) == 2                                       # 22.09. zählt nicht
    s = mc.stats(c)
    assert s["net"] == (10 - 1) + (-5 - 1)                   # 1 Cent x 100 Aktien je Trade
    assert s["pf"] == 9 / 6


def test_checkpoint_100_sent_once_with_first_100_only(tmp_path):
    ts = [trade(i, -50.0 if i % 4 else 60.0) for i in range(120)]
    n = FakeNotifier()
    state = tmp_path / "s.json"
    sent = mc.step(ts, n, state)
    assert len(sent) == 1 and "Prüfpunkt 100" in sent[0] and "ABBRUCH-REGEL ERFÜLLT" in sent[0]
    assert mc.step(ts, n, state) == []                       # nur einmal
    assert len(n.sent) == 1


def test_failed_send_is_retried_and_150_verdict(tmp_path):
    ts = [trade(i, 100.0 if i % 2 else -20.0) for i in range(150)]
    state = tmp_path / "s.json"
    assert mc.step(ts, FakeNotifier(ok=False), state) == []
    sent = mc.step(ts, FakeNotifier(), state)
    assert len(sent) == 2
    assert "nicht erfüllt" in sent[0] and "Prüfpunkt 150" in sent[1] and "BESTANDEN" in sent[1]

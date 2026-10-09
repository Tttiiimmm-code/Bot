from datetime import date

import numpy as np
import pandas as pd
import pytest

from tradingbot import forward_gold as fg
from tradingbot import forward_status as fs


def minutes(prices, start="2026-10-05 00:00", spread=0.02):
    idx = pd.date_range(start, periods=len(prices), freq="min", tz="UTC")
    c = np.asarray(prices, float)
    bid = pd.DataFrame({"open": c, "high": c + 0.1, "low": c - 0.1, "close": c}, index=idx)
    return fg.prepare(bid, bid + spread)


def test_breakout_entry_and_target():
    flat = [100.0] * (70 * 60)                       # 70 Stunden Seitwärts (Vorlauf >= 63 h): Level 100,1, ATR ~0,2
    ramp = [100.0 + 0.01 * k for k in range(1, 300)]  # danach Anstieg
    trades = fg.simulate(minutes(flat + ramp), fg.GoldConfig())
    assert len(trades) >= 1                          # weiterer Anstieg -> spätere Ausbrüche möglich
    t = trades[0]
    assert t["entry"] == pytest.approx(100.1 + 0.1 * 0.2, abs=0.02)          # Buy-Stop Level + 0,1 ATR
    assert t["r"] == pytest.approx(2.0, abs=0.05)                            # Ziel 4 ATR / Stop 2 ATR
    assert t["swap_r"] > 0 and t["r_net"] < t["r"]


def test_stop_and_ledger_idempotent(tmp_path):
    flat = [100.0] * (70 * 60)
    spike_fall = [100.3] + [100.3 - 0.02 * k for k in range(1, 200)]       # Ausbruch, dann Absturz
    trades = fg.simulate(minutes(flat + spike_fall), fg.GoldConfig())
    assert len(trades) == 1 and trades[0]["r"] == pytest.approx(-1.0, abs=0.1)
    path = tmp_path / "g.csv"
    assert fg.write_ledger(path, trades, date(2026, 10, 5)) == 1
    assert fg.write_ledger(path, trades, date(2026, 10, 5)) == 0
    assert fg.write_ledger(path, trades, date(2026, 10, 8)) == -1        # Einstieg (7.10.) vor first_day zählt nicht
    assert "noch keine Trades" in fg.summarize(path)


def test_status_family2(tmp_path):
    path = tmp_path / "forward_gold.csv"
    fg.write_ledger(path, [{"entry_time": "2026-10-06T10:00:00+00:00", "exit_time": "2026-10-06T14:00:00+00:00",
                            "entry": 1, "exit": 2, "risk": 1, "r": 2.0, "swap_r": 0.01, "r_net": 1.99}],
                    date(2026, 10, 5))
    rows = {r["name"]: r for r in fs.status(tmp_path, date(2026, 10, 7))}
    g = rows["gold_breakout"]
    assert g["n"] == 1 and g["mean"] == pytest.approx(1.99) and g["t_crit"] == 2.0


def test_month_frame_on_first_day_of_month_needs_no_download(tmp_path, monkeypatch):
    """Am Monatsersten ist der Zeitraum des neuen Monats leer -- kein Abruf (sonst gälte die leere
    Antwort seit der Erkennung leerer Downloads als Datenausfall)."""
    from tradingbot import forward_test as ft

    monkeypatch.setattr(ft, "fetch_minutes", lambda *a, **k: pytest.fail("kein Abruf erwartet"))
    df = fg._month_frame("bid", 2026, 11, tmp_path, date(2026, 11, 1))
    assert df.empty and list(df.columns) == ["open", "high", "low", "close"]

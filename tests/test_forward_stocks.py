from datetime import date

import numpy as np
import pandas as pd
import pytest

from tradingbot import forward_stocks as fs


def minute_bars(rows, day="2026-10-01"):
    idx = pd.date_range(f"{day} 09:30", periods=len(rows), freq="min", tz="America/New_York")
    return pd.DataFrame(rows, columns=["open", "high", "low", "close"], index=idx)


# Range 9:30-9:34: Hoch 10,5, Tief 9,9, grüne Kerze (Open 10, Schluss 10,5)
OR_ROWS = [(10, 10.1, 9.9, 10.1), (10.1, 10.2, 10.0, 10.2), (10.2, 10.3, 10.1, 10.3), (10.3, 10.4, 10.2, 10.4),
           (10.4, 10.5, 10.3, 10.5)]


def test_orb_trade_target_hit_matches_round_107():
    bars = minute_bars(OR_ROWS + [(10.45, 10.6, 10.4, 10.55), (10.6, 11.2, 10.5, 10.7), (10.7, 10.8, 10.6, 10.75)])
    t = fs.orb_trade(bars, target_r=1.0)
    # Einstieg 10,5 (Level), Stop 9,9 (Gegenseite), sd 0,6, Ziel 11,1 in Minute 6
    assert t["side"] == "long" and t["entry"] == 10.5 and t["stop"] == 9.9 and t["exit"] == pytest.approx(11.1)
    assert t["r_net"] == pytest.approx(1 - 2 * (0.0001 * 10.5 + 0.01) / 0.6, abs=1e-4)


def test_orb_trade_stop_in_entry_minute_is_worst_case():
    bars = minute_bars(OR_ROWS + [(10.45, 10.6, 9.8, 9.9), (9.9, 10.0, 9.7, 9.8)])
    t = fs.orb_trade(bars)
    assert t["exit"] == 9.9 and t["r_net"] < -1


def test_orb_trade_short_and_no_trade_cases():
    red = [(10.5, 10.6, 10.4, 10.4), (10.4, 10.4, 10.2, 10.2), (10.2, 10.3, 10.1, 10.1), (10.1, 10.1, 10.0, 10.0),
           (10.0, 10.1, 9.9, 10.0)]
    t = fs.orb_trade(minute_bars(red + [(9.95, 9.95, 9.5, 9.6), (9.6, 9.6, 8.0, 8.1)]))
    assert t["side"] == "short" and t["entry"] == 9.9 and t["stop"] == 10.6
    # kein Ausbruch -> kein Trade; erster Bar nicht 9:30 -> kein Trade
    assert fs.orb_trade(minute_bars(OR_ROWS + [(10.4, 10.45, 10.3, 10.4)])) is None
    late = minute_bars(OR_ROWS + [(10.45, 10.6, 10.4, 10.55)])
    assert fs.orb_trade(late.iloc[1:]) is None


def test_quality_pick_prefers_high_margin_and_low_issuance():
    opm = pd.Series({"A": 0.30, "B": 0.10, "C": 0.25, "D": -0.05})
    iss = pd.Series({"A": 0.00, "B": 0.00, "C": 0.40, "D": 0.10})
    assert fs.quality_pick(opm, iss, ["A", "B", "C", "D", "E"], 2) == ["A", "B"]


def test_point_in_time_availability():
    assert fs.annual_year(pd.Timestamp("2026-09-30")) == 2025
    assert fs.annual_year(pd.Timestamp("2026-04-30")) == 2024
    q = fs.available_quarter(pd.Timestamp("2026-09-30"))
    assert (q.year, q.quarter) == (2026, 2)       # Q2 endet 30.6., verfügbar ab 30.9.
    q = fs.available_quarter(pd.Timestamp("2026-10-30"))
    assert (q.year, q.quarter) == (2026, 2)


def test_month_schedule_and_quality_rows(tmp_path):
    days = pd.bdate_range("2025-06-02", "2026-12-15")
    syms = ["A", "B", "C"]
    rng = np.random.default_rng(0)
    c = pd.DataFrame(20 + rng.random((len(days), 3)), index=days, columns=syms)
    o = c.copy()
    v = pd.DataFrame(1e6, index=days, columns=syms)
    o.loc[:, "A"] *= np.linspace(1, 2, len(days))        # A steigt stark
    sched = fs.month_schedule(days)
    assert sched[-1][2] is None                           # letzter Monat noch offen
    cfg = fs.StockForwardConfig(first_day=date(2026, 10, 1), quality_top=1,
                                quality_ledger=tmp_path / "q.csv", orb_ledger=tmp_path / "o.csv")
    rows = fs.quality_rows(cfg, o, c, v, {}, lambda signal, members: ["A"])
    assert rows[0]["signal"] == "2026-09-30" and rows[0]["entry_date"] == "2026-10-01"
    assert rows[0]["net_excess"] > 0 and rows[0]["turnover"] == 1.0
    assert rows[-1]["net_excess"] == ""                   # laufender Monat ohne Abrechnung
    fs.update_quality_ledger(cfg.quality_ledger, rows)
    assert fs.update_quality_ledger(cfg.quality_ledger, rows) == 0     # idempotent
    assert sum(r["net_excess"] != "" for r in rows) == 2    # Okt. und Nov. abgerechnet
    assert "quality_top50: 2 Monate" in fs.summarize(cfg)


def test_quality_due_only_after_month_end():
    ledger = {"2026-09-30": {}}
    assert fs.quality_due(ledger, date(2026, 10, 2))          # erste Woche: immer
    assert not fs.quality_due(ledger, date(2026, 10, 20))     # Septemberzeile da -> überspringen
    assert fs.quality_due({}, date(2026, 10, 20))             # Lauf verpasst -> nachholen


def test_orb_ledger_idempotent(tmp_path):
    cfg = fs.StockForwardConfig(first_day=date(2026, 10, 1), orb_ledger=tmp_path / "o.csv")
    t = fs.orb_trade(minute_bars(OR_ROWS + [(10.45, 10.6, 10.4, 10.55), (10.6, 11.2, 10.5, 10.7)]))
    rows = [{"date": "2026-10-01", "symbol": "XYZ", **t}]
    assert fs.update_orb_ledger(cfg.orb_ledger, rows) == 1
    assert fs.update_orb_ledger(cfg.orb_ledger, rows) == 0
    assert "orb_or5: 1 Trades" in fs.summarize(cfg)

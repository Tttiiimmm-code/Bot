from __future__ import annotations

import pandas as pd
import pytest

from tradingbot.research.gold import day_trade


def minutes(path_by_hour):
    """Minutenkerzen eines UTC-Tages: path_by_hour[h] = (open, high, low, close) je Minute der Stunde."""
    rows, idx = [], []
    for h in range(24):
        o, hi, lo, c = path_by_hour.get(h, (100, 100.2, 99.8, 100))
        for m in range(60):
            idx.append(pd.Timestamp(f"2024-03-05 {h:02d}:{m:02d}", tz="UTC"))
            rows.append((o, hi, lo, c))
    return pd.DataFrame(rows, index=idx, columns=["open", "high", "low", "close"])


def test_long_breakout_hits_target():
    day = minutes({8: (100.3, 100.5, 100.25, 100.45), 9: (100.45, 100.7, 100.4, 100.65)})
    r = day_trade(day, tp_mult=1.0, cost_per_side=0.0)
    # Range 99,8-100,2 (Höhe 0,4): Einstieg max(Open 100,3; 100,2) = 100,3, Ziel 100,7
    assert r == pytest.approx(100.7 / 100.3 - 1)


def test_stop_counts_first_when_both_in_same_bar():
    day = minutes({8: (100.1, 100.9, 99.7, 100.0)})
    r = day_trade(day, tp_mult=1.0, cost_per_side=0.0)
    assert r == pytest.approx(99.8 / 100.2 - 1)  # Einstieg 100,2, Stop 99,8


def test_month_end_fix_uses_last_weekday_and_london_time():
    from tradingbot.research.gold import month_end_fix_returns

    # 31.05.2024 ist ein Freitag; London Sommerzeit: 14:00 = 13:00 UTC, 16:00 = 15:00 UTC
    idx = pd.date_range("2024-05-30 00:00", "2024-05-31 23:59", freq="min", tz="UTC")
    eur = pd.Series(1.08, index=idx)
    eur[eur.index >= pd.Timestamp("2024-05-31 15:00", tz="UTC")] = 1.0746  # EUR -0,5 % bis 16:00 London
    r = month_end_fix_returns({"eurusd": eur}, {"eurusd": True}, 14, 16, usd_long=True, cost_per_side=0.0)
    assert list(r.index) == [pd.Timestamp("2024-05-31").date()]
    assert r.iloc[0] == pytest.approx(0.005, rel=1e-3)  # USD long gewinnt 0,5 %


def test_no_trade_without_breakout():
    assert day_trade(minutes({}), tp_mult=None) is None

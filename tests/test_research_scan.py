from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from tradingbot.research.scan import (
    RULES,
    alpha_t,
    benjamini_hochberg,
    rule_positions,
    strategy_returns,
)


def series(values, start="2020-01-06"):
    return pd.Series(np.asarray(values, dtype=float), index=pd.bdate_range(start, periods=len(values)).date)


def test_trend_and_crossover_positions():
    c = series(list(range(1, 30)) + list(range(30, 1, -1)))
    lo = rule_positions(c, "sma_trend", 5, False)
    ls = rule_positions(c, "sma_trend", 5, True)
    assert lo.iloc[20] == 1 and lo.iloc[-1] == 0 and ls.iloc[-1] == -1
    assert lo.iloc[:4].eq(0).all()  # Warm-up


def test_donchian_enters_on_breakout_and_exits_on_half_window_low():
    c = series([10] * 25 + [11, 12, 13] + [12.5, 12, 11.5, 11, 10.5, 9] + [9] * 5)
    pos = rule_positions(c, "donchian", 20, False)
    assert pos.iloc[25] == 1  # Ausbruch über 20-Tage-Hoch
    assert pos.iloc[-1] == 0


def test_weekday_rule_holds_only_into_target_day():
    c = series(np.ones(10), start="2020-01-06")  # Montag
    pos = rule_positions(c, "weekday", 0, False)
    days = [pd.Timestamp(d).weekday() for d in c.index]
    # Position am Freitag für die Montagsrendite
    assert all(p == (1.0 if days[i + 1] == 0 else 0.0) for i, p in enumerate(pos.iloc[:-1]))


def test_strategy_returns_costs_and_alpha():
    rng = np.random.default_rng(0)
    bench = series(rng.normal(0, 0.01, 1000))
    strat = 0.0005 + 0.5 * bench + series(rng.normal(0, 0.002, 1000))
    a, t = alpha_t(strat, bench)
    assert a == pytest.approx(0.0005, rel=0.2) and t > 5
    pos = series([1, 1, 0, 0])
    r = strategy_returns(pos, series([0.0, 0.01, 0.02, 0.03]), 0.001)
    assert r.tolist() == pytest.approx([0.0, 0.01 - 0.001, 0.02, -0.001])


def test_benjamini_hochberg():
    p = np.array([0.001, 0.2, 0.01, 0.04, 0.9])
    assert benjamini_hochberg(p, 0.10).tolist() == [True, False, True, True, False]
    assert len(RULES) == 49

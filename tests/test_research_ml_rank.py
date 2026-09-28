from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from tradingbot.research.ml_rank import (
    FEATURES,
    Week,
    WeekData,
    build_panel,
    cross_rank,
    holding_returns,
    raw_features,
    ridge_fit,
    select,
    simulate,
    universe_mask,
    walk_forward,
    weekly_schedule,
)


def make_wide(n_days=320, n_sym=30, seed=0):
    rng = np.random.default_rng(seed)
    days = pd.bdate_range("2017-01-02", periods=n_days)
    cols = [f"S{i}" for i in range(n_sym)]
    c = pd.DataFrame(50 * np.exp(np.cumsum(rng.normal(0, 0.02, (n_days, n_sym)), axis=0)), index=days, columns=cols)
    o = c.shift(1).fillna(c) * (1 + rng.normal(0, 0.002, c.shape))
    h = np.maximum(o, c) * 1.01
    lo = np.minimum(o, c) * 0.99
    v = pd.DataFrame(1e6, index=days, columns=cols)
    return {"open": o, "high": h, "low": lo, "close": c, "volume": v}


def test_features_do_not_use_future_prices():
    w = make_wide()
    t = w["close"].index[280]
    base = raw_features(w["open"], w["high"], w["low"], w["close"], w["volume"])
    future = {k: v.copy() for k, v in w.items()}
    for k in ("open", "high", "low", "close"):
        future[k].loc[future[k].index > t] *= 3.0
    changed = raw_features(future["open"], future["high"], future["low"], future["close"], future["volume"])
    for k in FEATURES:
        pd.testing.assert_series_equal(base[k].loc[t], changed[k].loc[t], check_names=False)


def test_universe_requires_price_liquidity_and_history():
    days = pd.bdate_range("2017-01-02", periods=300)
    c = pd.DataFrame({"A": 10.0, "CHEAP": 4.0, "THIN": 10.0}, index=days)
    v = pd.DataFrame({"A": 1e6, "CHEAP": 1e7, "THIN": 1e3}, index=days)
    m = universe_mask(c, v)
    assert not m["A"].iloc[250] and m["A"].iloc[251]  # 252. Tag mit Historie
    assert not m["CHEAP"].any() and not m["THIN"].any()


def test_weekly_schedule_signal_entry_exit():
    days = pd.bdate_range("2024-01-01", "2024-01-31").delete(3)  # Do 04.01. fehlt
    weeks = weekly_schedule(days)
    assert weeks[0] == Week(pd.Timestamp("2024-01-05"), pd.Timestamp("2024-01-08"), pd.Timestamp("2024-01-15"))
    for w in weeks:
        assert w.signal < w.entry < w.exit


def test_holding_return_uses_last_close_after_delisting():
    days = pd.bdate_range("2024-01-01", periods=6)
    o = pd.DataFrame({"A": [10, 10, 11, 12, 13, 14.0], "D": [10, 10, 10, np.nan, np.nan, np.nan]}, index=days)
    c = pd.DataFrame({"A": [10, 10, 11, 12, 13, 14.0], "D": [10, 10, 8, np.nan, np.nan, np.nan]}, index=days)
    r = holding_returns(o, c, Week(days[0], days[1], days[5]))
    assert r["A"] == pytest.approx(0.4)
    assert r["D"] == pytest.approx(-0.2)


def test_cross_rank_handles_nan():
    r = cross_rank(np.array([3.0, np.nan, 1.0, 2.0]))
    assert r[1] == 0.5
    assert r[2] < r[3] < r[0]


def test_select_keeps_holdings_inside_buffer():
    syms = np.array(list("ABCDEFGHIJ"))
    score = np.arange(10, 0, -1, dtype=float)  # A bestes
    assert select(syms, score, set(), 2, 4) == ["A", "B"]
    assert select(syms, score, {"D", "J"}, 2, 4) == ["D", "A"]  # D bleibt (Top 4), J fliegt


def test_simulate_turnover_and_costs():
    w1 = Week(pd.Timestamp("2024-01-05"), pd.Timestamp("2024-01-08"), pd.Timestamp("2024-01-15"))
    w2 = Week(pd.Timestamp("2024-01-12"), pd.Timestamp("2024-01-15"), pd.Timestamp("2024-01-22"))
    syms = np.array(["A", "B"])
    X = np.zeros((2, len(FEATURES)), dtype="float32")
    panel = [WeekData(w1, syms, X, np.array([0.10, -0.10]), np.array([0.75, 0.25])),
             WeekData(w2, syms, X, np.array([0.0, 0.0]), np.array([0.5, 0.5]))]
    scores = {w1.signal: np.array([1.0, 0.0]), w2.signal: np.array([0.0, 1.0])}
    res = simulate(panel, scores, top=1, keep=1, cost_per_side=0.001)
    assert res.turnover == pytest.approx([1.0, 2.0])
    assert res.net == pytest.approx([0.10 - 0.001, -0.002])
    ew = simulate(panel, None, cost_per_side=0.001)
    # nach Woche 1: A 0,55/1,0 B 0,45/1,0 -> Rückkehr auf 0,5/0,5 = Umschlag 0,1
    assert ew.turnover == pytest.approx([1.0, 0.1])


def test_walk_forward_trains_only_on_finished_weeks():
    seen = []

    def fit(X, y):
        seen.append(len(y))
        return lambda Z: np.zeros(len(Z))

    w = make_wide(n_days=400)
    panel = build_panel(w)
    first = panel[10].week.signal
    walk_forward(panel, fit, first_test=first, train_start=panel[0].week.signal, retrain_every=4)
    finished = [p for p in panel if p.week.exit < first]
    assert seen[0] == sum(len(p.y) for p in finished)
    assert panel[9].week.exit >= first  # die direkt vorherige Woche ist noch offen


def test_ridge_recovers_linear_signal():
    rng = np.random.default_rng(1)
    X = rng.random((2000, 3))
    y = 0.5 * X[:, 0] - 0.2 * X[:, 2] + 0.1
    pred = ridge_fit(X, y, alpha=1e-6)(X)
    assert pred == pytest.approx(y, abs=1e-6)


def test_chunked_features_match_full_computation():
    w = make_wide(n_days=320, n_sym=25)
    at = w["close"].index[[260, 300]]
    chunked = raw_features(w["open"], w["high"], w["low"], w["close"], w["volume"], at=at, chunk=7)
    full = raw_features(w["open"], w["high"], w["low"], w["close"], w["volume"])
    for k in FEATURES:
        np.testing.assert_allclose(chunked[k].to_numpy(), full[k].loc[at].to_numpy(), rtol=1e-5)


def test_monthly_schedule_uses_last_trading_day_of_month():
    days = pd.bdate_range("2024-01-01", "2024-05-31")
    months = weekly_schedule(days, freq="M")
    assert months[0] == Week(pd.Timestamp("2024-01-31"), pd.Timestamp("2024-02-01"), pd.Timestamp("2024-03-01"))
    assert [m.signal for m in months] == [pd.Timestamp("2024-01-31"), pd.Timestamp("2024-02-29"),
                                          pd.Timestamp("2024-03-29")]

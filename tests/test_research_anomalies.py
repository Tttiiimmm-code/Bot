from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from tradingbot.research.anomalies import (
    cross_section_weights,
    financed_returns,
    halloween_weights,
    momentum_12_1,
    vol_managed_weights,
)


def days(n, start="2019-01-01"):
    return pd.bdate_range(start, periods=n).date


def test_vol_managed_caps_and_scales_inverse_to_vol():
    rng = np.random.default_rng(0)
    idx = days(300)
    calm = 100 * np.cumprod(1 + rng.normal(0, 0.002, 150))   # ~3 % Vola -> Deckel
    wild = calm[-1] * np.cumprod(1 + rng.normal(0, 0.03, 150))  # ~48 % Vola
    w = vol_managed_weights(pd.Series(np.concatenate([calm, wild]), index=idx), cap=1.5)
    assert w.iloc[140] == pytest.approx(1.5)
    assert 0.2 < w.iloc[-1] < 0.5


def test_halloween_invested_only_for_nov_to_apr_returns():
    idx = pd.bdate_range("2019-04-25", "2019-11-05").date
    w = halloween_weights(idx)
    by_day = dict(zip(idx, w))
    assert by_day[pd.Timestamp("2019-04-29").date()] == 1.0   # Rendite am 30.4. zählt
    assert by_day[pd.Timestamp("2019-04-30").date()] == 0.0   # Rendite am 1.5. nicht
    assert by_day[pd.Timestamp("2019-10-31").date()] == 1.0   # Rendite am 1.11. zählt


def test_financed_returns_charges_interest_on_leverage_and_costs():
    idx = days(3)
    close = pd.Series([100.0, 101.0, 102.01], index=idx)
    w = pd.Series([1.5, 1.5, 1.5], index=idx)
    r = financed_returns(w, close, cost_per_side=0.001, borrow_rate=0.0252)
    assert r.iloc[0] == pytest.approx(1.5 * 0.01 - 0.5 * 0.0001 - 0.001 * 1.5)
    assert r.iloc[1] == pytest.approx(1.5 * 0.01 - 0.5 * 0.0001)


def test_cross_section_picks_top_momentum_monthly():
    idx = days(300)
    t = np.arange(300)
    close = pd.DataFrame({"A": 100 * 1.002 ** t, "B": 100 * 0.999 ** t, "C": 100 * 1.001 ** t}, index=idx)
    uni = pd.DataFrame(True, index=idx, columns=close.columns)
    w = cross_section_weights(close, uni, momentum_12_1(close), n=1, highest=True)
    assert w.iloc[-1].tolist() == [1.0, 0.0, 0.0]
    lo = cross_section_weights(close, uni, momentum_12_1(close), n=1, highest=False)
    assert lo.iloc[-1].tolist() == [0.0, 1.0, 0.0]


def test_parse_fomc_pages():
    from datetime import date

    from tradingbot.research.anomalies import parse_fomc_current, parse_fomc_historical

    hist = ["January 26-27 Meeting - 2010", "May 9 Conference Call - 2010", "March 16 Meeting - 2010",
            "January 31-February 1 Meeting - 2012", "July 31-August 1  Meeting - 2012",
            "Oct/Nov 31-1 Meeting - 2017"]
    assert parse_fomc_historical(hist) == [date(2010, 1, 27), date(2010, 3, 16), date(2012, 2, 1),
                                           date(2012, 8, 1), date(2017, 11, 1)]
    cur = ["2023 FOMC Meetings", "Jan/Feb", "31-1", "Statement:", "March", "21-22*", "Minutes:"]
    assert parse_fomc_current(cur) == [date(2023, 2, 1), date(2023, 3, 22)]


def test_event_day_weights_hold_into_event():
    from tradingbot.research.anomalies import event_day_weights

    idx = days(5)
    w = event_day_weights(idx, [idx[2]])
    assert w.tolist() == [0.0, 1.0, 0.0, 0.0, 0.0]


def test_pairs_trading_profits_from_mean_reverting_pair():
    from tradingbot.research.anomalies import pairs_trading

    n = 400
    rng = np.random.default_rng(1)
    common = 100 * np.cumprod(1 + rng.normal(0, 0.01, n))
    noise = np.sin(np.arange(n) / 5) * 0.03  # stark mean-revertierender Abstand
    close = pd.DataFrame({"A": common * (1 + noise), "B": common * (1 - noise),
                          "C": 50 * np.cumprod(1 + rng.normal(0, 0.02, n)),
                          "D": 80 * np.cumprod(1 + rng.normal(0, 0.02, n))}, index=days(n))
    uni = pd.DataFrame(True, index=close.index, columns=close.columns)
    r = pairs_trading(close, uni, n_pairs=1, k=1.0, formation=252, trading=126, cost_per_side=0.0)
    assert r.sum() > 0.05  # A/B wird gewählt und verdient an der Rückkehr zum Mittel

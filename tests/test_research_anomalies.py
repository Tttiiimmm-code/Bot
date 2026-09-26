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


def test_ibs_band_enters_on_deep_weak_close_and_exits_above_prior_high():
    from tradingbot.research.anomalies import ibs_band_positions

    n = 40
    idx = days(n)
    close = np.full(n, 100.0)
    close[30] = 90.0   # tiefer Schluss, nahe Tagestief
    close[31] = 90.5   # unter Vortageshoch (91) -> Position bleibt
    close[32] = 102.0  # über Vortageshoch
    df = pd.DataFrame({"high": close + 1, "low": close - 1, "close": close}, index=idx)
    df.loc[idx[30], "low"] = 89.8
    pos = ibs_band_positions(df)
    assert pos.iloc[29] == 0 and pos.iloc[30] == 1 and pos.iloc[31] == 1 and pos.iloc[32] == 0


def test_double7_needs_uptrend_and_seven_day_low():
    from tradingbot.research.anomalies import double7_positions

    up = list(np.linspace(100, 200, 210)) + [195, 190, 185, 186, 187, 188, 189, 190, 191, 200]
    pos = double7_positions(pd.Series(up, index=days(len(up))))
    assert pos.iloc[209] == 0 and pos.iloc[212] == 1 and pos.iloc[-1] == 0


def test_slot_weights_respects_max_positions_rank_stop_and_hold():
    from tradingbot.research.anomalies import slot_weights

    idx = days(6)
    close = pd.DataFrame({"A": [10, 10, 9, 9, 9, 9.0], "B": [10.0] * 6, "C": [10.0] * 6}, index=idx)
    entry = pd.DataFrame(False, index=idx, columns=close.columns)
    entry.iloc[0] = [True, True, True]
    no_exit = pd.DataFrame(False, index=idx, columns=close.columns)
    rank = pd.DataFrame({"A": 3.0, "B": 2.0, "C": 1.0}, index=idx)
    w = slot_weights(close, entry, no_exit, rank, max_positions=2, stop=0.08, max_hold=3)
    assert w.iloc[0].tolist() == [0.5, 0.5, 0.0]   # nur 2 Plätze, A und B nach Rang
    assert w.iloc[2].tolist() == [0.0, 0.5, 0.0]   # A: -10 % -> Stop
    assert w.iloc[3].tolist() == [0.0, 0.0, 0.0]   # B: Haltedauer 3 erreicht


def test_pullback_entry_first_close_below_sma50_in_uptrend():
    from tradingbot.research.anomalies import pullback_entry

    up = list(np.linspace(50, 150, 260)) + [120.0]
    e = pullback_entry(pd.DataFrame({"X": up}, index=days(len(up))))
    assert e["X"].iloc[-1] and not e["X"].iloc[-2]


def test_fx_excess_returns_add_rate_differential_with_one_month_lag():
    from tradingbot.research.anomalies import fx_excess_returns

    idx = pd.bdate_range("2020-01-01", "2020-03-31").date
    spot = {"AUD": pd.Series(0.7, index=idx)}  # USD je AUD, konstant
    rates = {"USD": pd.Series([1.0, 1.0, 1.0], index=pd.to_datetime(["2019-12-01", "2020-01-01", "2020-02-01"])),
             "AUD": pd.Series([3.52, 1.0, 1.0], index=pd.to_datetime(["2019-12-01", "2020-01-01", "2020-02-01"]))}
    ex = fx_excess_returns(spot, rates)
    jan = ex.loc[[d for d in idx if d.month == 1], "AUD"].iloc[1:]
    feb = ex.loc[[d for d in idx if d.month == 2], "AUD"]
    assert jan.iloc[0] == pytest.approx((3.52 - 1.0) / 100 / 252)  # Dezember-Zins gilt im Januar
    assert feb.iloc[0] == pytest.approx(0.0)
    assert (ex["USD"] == 0).all()


def test_rank_long_short_and_auction_positions():
    from tradingbot.research.anomalies import auction_positions, rank_long_short

    idx = pd.bdate_range("2020-01-27", periods=10).date
    score = pd.DataFrame([[1, 2, 3, 4, 5, 6]] * 10, index=idx, columns=list("ABCDEF"), dtype=float)
    w = rank_long_short(score, k=2)
    assert w.iloc[-1].tolist() == [-0.5, -0.5, 0, 0, 0.5, 0.5]
    assert w.iloc[0].abs().sum() == 0  # vor dem ersten Monatsende noch leer
    pos = auction_positions(idx, [idx[2]], k=3)
    assert pos.tolist() == [0, 0, 1, 1, 1, 0, 0, 0, 0, 0]


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

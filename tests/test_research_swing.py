from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from tradingbot.research.engine import CostModel
from tradingbot.research.swing import (
    ReversalParams,
    alpha_vs_benchmark,
    overnight,
    rsi2_reversion,
    weekly_reversal,
)

NO_COST = CostModel(0, 0, 0)


def make_daily(close, open_=None, pre=None):
    close = np.asarray(close, dtype=float)
    days = pd.bdate_range("2018-01-02", periods=len(close)).date
    open_ = close if open_ is None else np.asarray(open_, dtype=float)
    pre = close if pre is None else np.asarray(pre, dtype=float)
    ts = pd.DatetimeIndex([pd.Timestamp(d) for d in days])
    return pd.DataFrame({
        "open": open_, "close": close, "pre_close": pre,
        "open_time": ts + pd.Timedelta(hours=9, minutes=30),
        "close_time": ts + pd.Timedelta(hours=15, minutes=59),
    }, index=days)


def test_overnight_earns_close_to_next_open():
    n = 205
    close = np.full(n, 100.0)
    open_ = np.full(n, 101.0)  # jede Nacht +1 %
    res = overnight(make_daily(close, open_), trend_filter=False, costs=NO_COST)
    assert len(res.trades) == n - 1 - 200
    assert res.daily_returns.iloc[0] == pytest.approx(0.01)
    assert res.daily_returns.index[0] == make_daily(close).index[201]


def test_overnight_trend_filter_skips_downtrend():
    close = np.linspace(200, 100, 260)
    res = overnight(make_daily(close), trend_filter=True, costs=NO_COST)
    assert res.trades == []


def test_rsi2_enters_on_dip_in_uptrend_and_exits_above_sma5():
    close = list(np.linspace(100, 150, 230))
    close += [145, 140, 150, 152]  # nach stetigem Anstieg reicht ein Minustag für RSI(2) < 10
    res = rsi2_reversion(make_daily(close), entry_below=10, exit_rule="sma5", costs=NO_COST)
    assert len(res.trades) == 1
    t = res.trades[0]
    assert t.entry_price == pytest.approx(145) and t.exit_price == pytest.approx(150)


def test_rsi2_signal_uses_pre_close_not_close():
    close = list(np.linspace(100, 150, 230)) + [145, 140, 150, 152]
    pre = list(close)
    pre[230] = 150.5  # um 15:50 noch im Plus -> an diesem Tag kein Einstieg zu 145
    res = rsi2_reversion(make_daily(close, pre=pre), entry_below=10, exit_rule="sma5", costs=NO_COST)
    assert all(t.entry_price != pytest.approx(145) for t in res.trades)


def test_rsi2_exit_rsi70():
    close = list(np.linspace(100, 150, 230)) + [145, 140, 150, 152, 155]
    res = rsi2_reversion(make_daily(close), entry_below=10, exit_rule="rsi70", costs=NO_COST)
    assert res.trades and res.trades[0].reason == "rsi70"


def _matrices(n_days=40, n_syms=4):
    days = pd.bdate_range("2019-01-02", periods=n_days).date
    cols = [f"S{i}" for i in range(n_syms)]
    closes = pd.DataFrame(100.0, index=days, columns=cols)
    opens = closes.copy()
    uni = pd.DataFrame(True, index=days, columns=cols)
    return opens, closes, uni


def test_weekly_reversal_buys_biggest_loser_at_next_open():
    opens, closes, uni = _matrices()
    days = closes.index
    # S2 fällt bis Tag 21 um 10 %, erholt sich danach
    closes.loc[days[17]:days[21], "S2"] = 90.0
    opens.loc[days[22]:, "S2"] = 90.0
    closes.loc[days[22]:, "S2"] = 99.0
    opens.loc[days[23]:, "S2"] = 99.0
    res = weekly_reversal(opens, closes, uni, ReversalParams(n_stocks=1, lookback=5, hold=5), NO_COST)
    first = res.trades[0]
    assert first.symbol == "S2" and first.entry_price == pytest.approx(90.0)
    assert first.exit_price == pytest.approx(99.0)
    assert res.daily_returns.loc[days[22]] == pytest.approx(0.10)


def test_weekly_reversal_handles_delisting():
    opens, closes, uni = _matrices()
    days = closes.index
    closes.loc[days[17]:days[21], "S1"] = 80.0
    opens.loc[days[22], "S1"] = 80.0
    closes.loc[days[22], "S1"] = 84.0
    closes.loc[days[23]:, "S1"] = np.nan
    opens.loc[days[23]:, "S1"] = np.nan
    res = weekly_reversal(opens, closes, uni, ReversalParams(n_stocks=1), NO_COST)
    t = res.trades[0]
    assert t.symbol == "S1" and t.exit_price == pytest.approx(84.0)


def test_alpha_regression_recovers_known_alpha():
    rng = np.random.default_rng(0)
    bench = pd.Series(rng.normal(0, 0.01, 2000))
    r = 0.0004 + 0.5 * bench + pd.Series(rng.normal(0, 0.002, 2000))
    alpha, t, beta = alpha_vs_benchmark(r, bench)
    assert alpha == pytest.approx(0.0004 * 252, rel=0.15)
    assert beta == pytest.approx(0.5, abs=0.02) and t > 5


def test_trend_close_to_close_holds_only_above_sma():
    from tradingbot.research.swing import trend_close_to_close

    close = [100.0] * 10 + [110.0, 121.0, 100.0, 90.0]
    res = trend_close_to_close(make_daily(close), lookback=5, costs=NO_COST)
    r = res.daily_returns
    # Tag 10: Kurs 110 > SMA 100 -> investiert für 10->11 (+10 %)
    assert r.iloc[r.index.get_loc(make_daily(close).index[11])] == pytest.approx(0.10)
    # Tag 12: Kurs 100 < SMA(100,100,100,110,121)=106,2 -> nicht investiert für 12->13
    assert r.iloc[-1] == 0.0


def test_multi_asset_weights_monthly_absolute_and_dual():
    from tradingbot.research.swing import multi_asset_weights

    days = pd.bdate_range("2018-01-01", periods=300).date
    close = pd.DataFrame({"UP": np.linspace(100, 200, 300), "DOWN": np.linspace(200, 100, 300),
                          "FLATUP": np.linspace(100, 110, 300)}, index=days)
    pre = close.copy()
    w = multi_asset_weights(close, pre, "m12", "absolute")
    last = w.iloc[-1]
    assert last["UP"] == pytest.approx(1 / 3) and last["DOWN"] == 0 and last["FLATUP"] == pytest.approx(1 / 3)
    d = multi_asset_weights(close, pre, "m12", "dual", top_k=1)
    assert d.iloc[-1].tolist() == [1.0, 0.0, 0.0]
    # Gewichte ändern sich nur am Monatsende
    changes = w.diff().abs().sum(axis=1)
    changed_days = [day for day, c in changes.items() if c > 0]
    assert all(pd.Timestamp(day).is_month_end or (pd.Timestamp(day) + pd.offsets.BDay(1)).month != pd.Timestamp(day).month
               for day in changed_days)

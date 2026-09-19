import pandas as pd

from tradingbot.backtest import run_backtest


def test_backtest_profits_on_clean_uptrend_with_dip():
    values = [10, 9, 8, 7, 6] + [7, 9, 12, 16, 21, 27, 34, 42, 51]
    close = pd.Series(values, index=pd.date_range("2024-01-01", periods=len(values), freq="D"))

    result = run_backtest(close, short_window=2, long_window=4, starting_cash=1000.0)

    assert result.num_trades >= 1
    assert result.final_equity > 0
    assert len(result.equity_curve) == len(close)


def test_backtest_no_signal_keeps_cash_flat():
    close = pd.Series([100] * 15, index=pd.date_range("2024-01-01", periods=15, freq="D"))

    result = run_backtest(close, short_window=3, long_window=6, starting_cash=1000.0)

    assert result.num_trades == 0
    assert result.final_equity == 1000.0
    assert result.total_return_pct == 0.0
    assert result.total_costs == 0.0


def test_zero_costs_produce_zero_total_costs():
    values = [10, 9, 8, 7, 6, 7, 9, 12, 16, 21, 27, 34, 30, 25, 18, 10]
    close = pd.Series(values, index=pd.date_range("2024-01-01", periods=len(values), freq="D"))

    result = run_backtest(
        close, short_window=2, long_window=4, starting_cash=1000.0,
        commission_pct=0.0, slippage_pct=0.0,
    )

    assert result.num_trades >= 1
    assert result.total_costs == 0.0


def test_higher_costs_reduce_final_equity():
    values = [10, 9, 8, 7, 6, 7, 9, 12, 16, 21, 27, 34, 30, 25, 18, 10]
    close = pd.Series(values, index=pd.date_range("2024-01-01", periods=len(values), freq="D"))

    cheap = run_backtest(
        close, short_window=2, long_window=4, starting_cash=1000.0,
        commission_pct=0.0, slippage_pct=0.0,
    )
    expensive = run_backtest(
        close, short_window=2, long_window=4, starting_cash=1000.0,
        commission_pct=0.01, slippage_pct=0.01,
    )

    assert cheap.num_trades == expensive.num_trades
    assert expensive.total_costs > cheap.total_costs
    assert expensive.final_equity < cheap.final_equity

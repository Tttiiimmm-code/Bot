import numpy as np
import pandas as pd
import pytest

from tradingbot.backtest import run_backtest


def test_zero_price_day_does_not_crash_and_skips_trade():
    """Regressionstest: ein Kurs von exakt 0 (z.B. Delisting, defekter
    Datenpunkt) an einem Golden-Cross-Tag würde beim Teilen durch
    fill_price einen ZeroDivisionError auslösen. Solche Tage werden jetzt
    als nicht handelbar übersprungen statt zu crashen."""
    values = [41.78, 48.87, 31.91, 35.06, 23.09, 26.67, 2.5, 34.07, 0.0, 33.33]
    close = pd.Series(values, index=pd.date_range("2024-01-01", periods=len(values), freq="D"))

    result = run_backtest(close, short_window=2, long_window=4, stop_loss_pct=0.0)

    assert not result.equity_curve.isna().any()
    assert not pd.isna(result.final_equity)


def test_negative_price_day_does_not_crash():
    values = [10, 9, 8, 7, 6, 7, 9, -5, 12, 16]
    close = pd.Series(values, index=pd.date_range("2024-01-01", periods=len(values), freq="D"))

    result = run_backtest(close, short_window=2, long_window=4, stop_loss_pct=0.0)

    assert not result.equity_curve.isna().any()


def test_cost_and_risk_params_must_be_below_one():
    """Regressionstest: commission_pct/slippage_pct >= 1 (100%) lässt
    Vorzeichen kippen (z.B. negative shares) und korrumpiert den
    Backtest-Zustand dauerhaft -- muss abgelehnt werden statt still
    falsche Ergebnisse zu produzieren."""
    close = pd.Series(
        [10, 9, 8, 7, 6, 7, 9, 12, 16],
        index=pd.date_range("2024-01-01", periods=9, freq="D"),
    )

    with pytest.raises(ValueError):
        run_backtest(close, 2, 4, commission_pct=1.5)
    with pytest.raises(ValueError):
        run_backtest(close, 2, 4, slippage_pct=1.0)
    with pytest.raises(ValueError):
        run_backtest(close, 2, 4, stop_loss_pct=1.0)
    with pytest.raises(ValueError):
        run_backtest(close, 2, 4, commission_pct=-0.01)


def test_nan_gap_while_holding_position_does_not_poison_equity_curve():
    """Regressionstest: 0 * NaN und x * NaN sind beide NaN -- ein fehlender
    Kurs (Datenlücke) darf die Equity-Kurve nicht mit NaN verunreinigen,
    weder für den Lücken-Tag selbst noch (über final_equity) für alle
    folgenden Tage."""
    values = [10, 9, 8, 7, 6, 7, 9, 12, 16, np.nan, 21, 27]
    close = pd.Series(values, index=pd.date_range("2024-01-01", periods=len(values), freq="D"))

    result = run_backtest(close, short_window=2, long_window=4, starting_cash=1000.0, stop_loss_pct=0.0)

    assert not result.equity_curve.isna().any()
    assert not pd.isna(result.final_equity)
    assert not pd.isna(result.total_return_pct)


def test_nan_gap_before_any_position_does_not_poison_equity_curve():
    """0 * NaN ist ebenfalls NaN -- auch ohne offene Position (shares=0)
    darf ein fehlender Kurs am Anfang der Serie die Equity-Kurve nicht
    verunreinigen."""
    values = [np.nan, 10, 9, 8, 7, 6, 7, 9, 12, 16]
    close = pd.Series(values, index=pd.date_range("2024-01-01", periods=len(values), freq="D"))

    result = run_backtest(close, short_window=2, long_window=4, starting_cash=1000.0, stop_loss_pct=0.0)

    assert not result.equity_curve.isna().any()
    assert result.equity_curve.iloc[0] == 1000.0


def test_buy_cost_matches_shares_times_price_shortfall():
    """trade.cost muss exakt der Differenz zwischen eingesetztem Kapital und
    dem fairen Wert (Anzahl Aktien * unbeeinflusster Kurs) entsprechen --
    das deckt sowohl Provision als auch Slippage in einer Formel ab."""
    values = [10, 9, 8, 7, 6, 7, 9]
    close = pd.Series(values, index=pd.date_range("2024-01-01", periods=len(values), freq="D"))

    result = run_backtest(
        close, short_window=2, long_window=4, starting_cash=1000.0,
        commission_pct=0.01, slippage_pct=0.01, stop_loss_pct=0.0,
    )

    buy = result.trades[0]
    assert buy.side == "BUY"
    raw_price = close.loc[buy.date]
    expected_cost = 1000.0 - buy.shares * raw_price
    assert buy.cost == pytest.approx(expected_cost)


def test_sell_cost_matches_shares_times_price_shortfall():
    values = [10, 9, 8, 7, 6, 7, 9, 8, 6, 4]
    close = pd.Series(values, index=pd.date_range("2024-01-01", periods=len(values), freq="D"))

    result = run_backtest(
        close, short_window=2, long_window=4, starting_cash=1000.0,
        commission_pct=0.01, slippage_pct=0.01, stop_loss_pct=0.0,
    )

    sell = next(t for t in result.trades if t.side in ("SELL", "STOP"))
    raw_price = close.loc[sell.date]
    expected_cost = sell.shares * raw_price - (sell.shares * sell.price * (1 - 0.01))
    assert sell.cost == pytest.approx(expected_cost)


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


def test_stop_loss_exits_before_crossover_on_sharp_drop():
    # BUY-Signal (Golden Cross) bei Index 6, danach fällt der Kurs sofort
    # stark -- weit vor einem regulären Death-Cross-Signal.
    values = [10, 9, 8, 7, 6, 7, 9, 8, 7, 6, 5, 4, 3]
    close = pd.Series(values, index=pd.date_range("2024-01-01", periods=len(values), freq="D"))

    result = run_backtest(
        close, short_window=2, long_window=4, starting_cash=1000.0,
        stop_loss_pct=0.08,
    )

    sides = [t.side for t in result.trades]
    assert sides == ["BUY", "STOP"]
    # Der Stop muss unmittelbar nach dem starken Einbruch greifen, nicht erst
    # am Ende der Zeitreihe wie es ein reines Crossover-Signal täte.
    assert result.trades[1].date < close.index[-1]


def test_stop_loss_disabled_rides_out_the_drawdown():
    values = [10, 9, 8, 7, 6, 7, 9, 8, 7, 6, 5, 4, 3]
    close = pd.Series(values, index=pd.date_range("2024-01-01", periods=len(values), freq="D"))

    with_stop = run_backtest(
        close, short_window=2, long_window=4, starting_cash=1000.0, stop_loss_pct=0.08
    )
    without_stop = run_backtest(
        close, short_window=2, long_window=4, starting_cash=1000.0, stop_loss_pct=0.0
    )

    assert "STOP" in [t.side for t in with_stop.trades]
    assert "STOP" not in [t.side for t in without_stop.trades]
    # Ohne Stop reitet die Position den weiteren Absturz voll mit --
    # das Endkapital muss entsprechend niedriger sein als mit Stop.
    assert without_stop.final_equity < with_stop.final_equity


def test_stop_loss_uses_slippage_adjusted_entry_price():
    values = [10, 9, 8, 7, 6, 7, 9, 8, 7, 6, 5, 4, 3]
    close = pd.Series(values, index=pd.date_range("2024-01-01", periods=len(values), freq="D"))

    result = run_backtest(
        close, short_window=2, long_window=4, starting_cash=1000.0,
        slippage_pct=0.001, stop_loss_pct=0.08,
    )

    buy_trade, stop_trade = result.trades
    stop_threshold = buy_trade.price * (1 - 0.08)
    assert stop_trade.price <= stop_threshold * (1 + 1e-9)


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

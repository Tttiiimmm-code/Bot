import pandas as pd

from tradingbot.strategy import Signal, generate_signal, generate_signal_series


def make_series(values):
    return pd.Series(values, index=pd.date_range("2024-01-01", periods=len(values), freq="D"))


def test_golden_cross_generates_buy():
    # Erst fallend (short < long), am letzten Punkt kreuzt short von unten nach oben.
    values = [10, 9, 8, 7, 6, 7, 9]
    close = make_series(values)
    signal = generate_signal(close, short_window=2, long_window=4)
    assert signal == Signal.BUY


def test_death_cross_generates_sell():
    # Erst steigend (short > long), am letzten Punkt kreuzt short von oben nach unten.
    values = [6, 7, 8, 9, 10, 9, 7]
    close = make_series(values)
    signal = generate_signal(close, short_window=2, long_window=4)
    assert signal == Signal.SELL


def test_flat_prices_generate_hold():
    close = make_series([100] * 20)
    signal = generate_signal(close, short_window=3, long_window=10)
    assert signal == Signal.HOLD


def test_not_enough_data_generates_hold():
    close = make_series([1, 2, 3])
    signal = generate_signal(close, short_window=5, long_window=10)
    assert signal == Signal.HOLD


def test_generate_signal_series_matches_generate_signal_at_each_point():
    values = [10, 9, 8, 7, 6, 7, 9, 12, 16, 21, 27, 34, 30, 25, 18, 10]
    close = make_series(values)
    series_signals = generate_signal_series(close, short_window=2, long_window=4)

    for i in range(5, len(close) + 1):
        prefix = close.iloc[:i]
        single = generate_signal(prefix, short_window=2, long_window=4)
        assert series_signals.iloc[i - 1] == single

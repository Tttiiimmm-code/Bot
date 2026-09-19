import pandas as pd
import pytest

from tradingbot.backtest import run_backtest
from tradingbot.validation import validate


def make_series(values):
    return pd.Series(values, index=pd.date_range("2024-01-01", periods=len(values), freq="D"))


def test_invalid_train_ratio_raises():
    close = make_series([100] * 30)
    with pytest.raises(ValueError):
        validate(close, [(5, 20)], train_ratio=0.0)
    with pytest.raises(ValueError):
        validate(close, [(5, 20)], train_ratio=1.0)


def test_no_candidate_fits_raises():
    close = make_series([100] * 10)
    with pytest.raises(ValueError):
        validate(close, [(20, 50)], train_ratio=0.5)


def test_best_is_selected_purely_by_train_performance():
    values = [10, 9, 8, 7, 6, 7, 9, 12, 16, 21, 27, 34, 30, 25, 18, 10, 8, 6, 9, 14, 20, 27, 35, 44]
    close = make_series(values)
    grid = [(2, 4), (3, 6), (5, 10)]

    result = validate(close, grid, train_ratio=0.5)

    # Die gewählte Kombination muss die beste Trainings-Rendite aller
    # Kandidaten haben -- unabhängig davon, wie sie im Test abschneidet.
    assert all(
        c.train.return_pct <= result.best.train.return_pct for c in result.all_candidates
    )


def test_train_segment_has_no_lookahead_into_test_data():
    """Die Trainings-Metriken dürfen sich nicht ändern, wenn man die
    Testdaten anhängt/entfernt -- der gleitende Durchschnitt schaut nur
    zurück, es darf also kein Leck aus der Zukunft geben."""
    train_values = [10, 9, 8, 7, 6, 7, 9, 12, 16, 21, 27, 34]
    test_values_a = [30, 25, 18, 10]
    test_values_b = [50, 80, 120, 200]

    full_index = pd.date_range("2024-01-01", periods=len(train_values) + 4, freq="D")
    close_a = pd.Series(train_values + test_values_a, index=full_index)
    close_b = pd.Series(train_values + test_values_b, index=full_index)

    grid = [(2, 4)]
    train_ratio = len(train_values) / len(full_index)

    result_a = validate(close_a, grid, train_ratio=train_ratio)
    result_b = validate(close_b, grid, train_ratio=train_ratio)

    assert result_a.best.train.return_pct == result_b.best.train.return_pct
    assert result_a.best.train.num_trades == result_b.best.train.num_trades


def test_train_segment_matches_standalone_backtest_on_same_prefix():
    values = [10, 9, 8, 7, 6, 7, 9, 12, 16, 21, 27, 34, 30, 25, 18, 10]
    close = make_series(values)
    short_w, long_w = 2, 4
    train_ratio = 0.6

    result = validate(close, [(short_w, long_w)], train_ratio=train_ratio)
    split_idx = int(len(close) * train_ratio)

    standalone = run_backtest(close.iloc[:split_idx], short_w, long_w)

    assert result.best.train.return_pct == pytest.approx(standalone.total_return_pct)
    assert result.best.train.num_trades == standalone.num_trades

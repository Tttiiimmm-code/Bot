import argparse

import pytest

from main import _fraction_below_one, _parse_grid, _positive_int, _train_ratio


def test_parses_valid_grid():
    assert _parse_grid("5:20,10:30,50:200") == [(5, 20), (10, 30), (50, 200)]


def test_parses_single_pair():
    assert _parse_grid("5:20") == [(5, 20)]


def test_rejects_missing_colon():
    with pytest.raises(argparse.ArgumentTypeError):
        _parse_grid("5-20")


def test_rejects_non_numeric_values():
    with pytest.raises(argparse.ArgumentTypeError):
        _parse_grid("kurz:lang")


def test_rejects_short_greater_or_equal_long():
    with pytest.raises(argparse.ArgumentTypeError):
        _parse_grid("30:10")

    with pytest.raises(argparse.ArgumentTypeError):
        _parse_grid("20:20")


def test_rejects_short_window_below_one():
    with pytest.raises(argparse.ArgumentTypeError):
        _parse_grid("0:20")


def test_rejects_empty_string():
    with pytest.raises(argparse.ArgumentTypeError):
        _parse_grid("")


def test_one_bad_pair_rejects_whole_grid():
    with pytest.raises(argparse.ArgumentTypeError):
        _parse_grid("5:20,30:10")


def test_positive_int_accepts_positive_values():
    assert _positive_int("250") == 250
    assert _positive_int("1") == 1


def test_positive_int_rejects_zero_and_negative():
    with pytest.raises(argparse.ArgumentTypeError):
        _positive_int("0")
    with pytest.raises(argparse.ArgumentTypeError):
        _positive_int("-5")


def test_train_ratio_accepts_open_interval():
    assert _train_ratio("0.7") == 0.7
    assert _train_ratio("0.01") == 0.01
    assert _train_ratio("0.99") == 0.99


def test_train_ratio_rejects_boundaries_and_outside():
    for value in ["0", "1", "1.5", "-0.1"]:
        with pytest.raises(argparse.ArgumentTypeError):
            _train_ratio(value)


def test_fraction_below_one_accepts_zero_and_fractions_below_one():
    assert _fraction_below_one("0") == 0.0
    assert _fraction_below_one("0.001") == 0.001
    assert _fraction_below_one("0.99") == 0.99


def test_fraction_below_one_rejects_negative_and_one_or_more():
    with pytest.raises(argparse.ArgumentTypeError):
        _fraction_below_one("-0.001")
    with pytest.raises(argparse.ArgumentTypeError):
        _fraction_below_one("1")
    with pytest.raises(argparse.ArgumentTypeError):
        _fraction_below_one("1.5")

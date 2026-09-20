import argparse

import pytest

from main import _fraction_below_one, _parse_grid, _positive_int, _symbol, _train_ratio


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


def test_rejects_oversized_long_window():
    """Regressionstest: ohne Obergrenze würde ein zu großes langes Fenster
    später einen OverflowError auslösen."""
    with pytest.raises(argparse.ArgumentTypeError):
        _parse_grid("5:200000000000")


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


def test_positive_int_rejects_oversized_value():
    """Regressionstest: ohne Obergrenze würde ein extrem großes --days
    später in timedelta(days=...) einen OverflowError auslösen."""
    with pytest.raises(argparse.ArgumentTypeError):
        _positive_int("999999999999999999")


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


def test_symbol_normalizes_case_and_whitespace():
    assert _symbol("aapl") == "AAPL"
    assert _symbol("  msft  ") == "MSFT"


def test_symbol_rejects_empty_string():
    with pytest.raises(argparse.ArgumentTypeError):
        _symbol("")
    with pytest.raises(argparse.ArgumentTypeError):
        _symbol("   ")


def _make_config(symbol: str):
    from tradingbot.config import Config

    return Config(
        api_key="k",
        secret_key="s",
        paper=True,
        symbol=symbol,
        qty=1.0,
        short_window=20,
        long_window=50,
        poll_interval_seconds=60,
        stop_loss_pct=0.08,
        take_profit_pct=0.15,
        risk_per_trade_pct=0.0,
        trend_window=200,
        rsi_window=14,
    )


def test_backtest_symbol_flag_overrides_env_config(monkeypatch):
    """--symbol soll für einen einzelnen backtest/validate-Aufruf das
    SYMBOL aus .env überschreiben, ohne .env selbst zu ändern -- so lassen
    sich mehrere Symbole durchtesten, ohne die Datei jedes Mal zu editieren."""
    import main as main_module

    monkeypatch.setattr("sys.argv", ["main.py", "backtest", "--symbol", "msft"])
    monkeypatch.setattr(main_module.Config, "from_env", classmethod(lambda cls: _make_config("AAPL")))
    seen_configs = []
    monkeypatch.setattr(main_module, "cmd_backtest", lambda config, *a, **k: seen_configs.append(config))

    main_module.main()

    assert seen_configs[0].symbol == "MSFT"


def test_run_command_rejects_symbol_flag(monkeypatch):
    """Sicherheitsrelevant: run (Live-/Paper-Trading-Loop) darf --symbol gar
    nicht erst als Option kennen -- sonst könnte ein CLI-Tippfehler
    versehentlich ein anderes als das in .env konfigurierte Symbol
    handeln lassen. argparse lehnt die unbekannte Option mit SystemExit ab,
    bevor cmd_run() je aufgerufen wird."""
    import main as main_module

    monkeypatch.setattr("sys.argv", ["main.py", "run", "--symbol", "MSFT"])
    monkeypatch.setattr(main_module.Config, "from_env", classmethod(lambda cls: _make_config("AAPL")))
    monkeypatch.setattr(main_module, "cmd_run", lambda config: pytest.fail("cmd_run darf nicht aufgerufen werden"))

    with pytest.raises(SystemExit):
        main_module.main()


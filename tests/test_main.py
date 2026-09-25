import argparse
from datetime import timedelta

import pytest

from main import _format_duration, _fraction_below_one, _parse_grid, _positive_int, _symbol, _train_ratio


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


def test_momentum_run_command_rejects_symbol_flag(monkeypatch):
    """Wie test_run_command_rejects_symbol_flag: momentum-run durchsucht den
    ganzen Markt (wie scan) und kennt --symbol daher bewusst nicht."""
    import main as main_module

    monkeypatch.setattr("sys.argv", ["main.py", "momentum-run", "--symbol", "MSFT"])
    monkeypatch.setattr(main_module.Config, "from_env", classmethod(lambda cls: _make_config("AAPL")))
    monkeypatch.setattr(
        main_module,
        "cmd_momentum_run",
        lambda *a, **k: pytest.fail("cmd_momentum_run darf nicht aufgerufen werden"),
    )

    with pytest.raises(SystemExit):
        main_module.main()


def test_momentum_run_dispatches_with_parsed_arguments(monkeypatch):
    import main as main_module

    monkeypatch.setattr(
        "sys.argv",
        ["main.py", "momentum-run", "--max-risk-dollars", "250", "--max-concurrent-positions", "2"],
    )
    monkeypatch.setattr(main_module.Config, "from_env", classmethod(lambda cls: _make_config("AAPL")))
    seen_args = []
    monkeypatch.setattr(main_module, "cmd_momentum_run", lambda config, *a, **k: seen_args.append(a))

    main_module.main()

    args = seen_args[0]
    # Reihenfolge wie in cmd_momentum_run()/main(): ... max_risk_dollars,
    # reward_risk_ratio, ... max_concurrent_positions, ...
    assert args[9] == pytest.approx(250.0)  # max_risk_dollars
    assert args[20] == 2  # max_concurrent_positions


def test_momentum_backtest_rejects_symbol_and_symbols_together(monkeypatch, capsys):
    """--symbol und --symbols schließen sich gegenseitig aus -- sonst wäre
    unklar, ob der Einzel- oder der Mehrfach-Backtest gemeint ist."""
    import main as main_module

    monkeypatch.setattr(
        "sys.argv", ["main.py", "momentum-backtest", "--symbol", "AAPL", "--symbols", "MSFT,TSLA"]
    )
    monkeypatch.setattr(main_module.Config, "from_env", classmethod(lambda cls: _make_config("AAPL")))
    monkeypatch.setattr(
        main_module, "cmd_momentum_backtest", lambda *a, **k: pytest.fail("darf nicht aufgerufen werden")
    )
    monkeypatch.setattr(
        main_module, "cmd_momentum_backtest_multi", lambda *a, **k: pytest.fail("darf nicht aufgerufen werden")
    )

    with pytest.raises(SystemExit):
        main_module.main()

    assert "schließen sich gegenseitig aus" in capsys.readouterr().err


def test_momentum_backtest_dispatches_to_multi_when_symbols_given(monkeypatch):
    import main as main_module

    monkeypatch.setattr(
        "sys.argv", ["main.py", "momentum-backtest", "--symbols", "aapl,msft", "--starting-cash", "5000"]
    )
    monkeypatch.setattr(main_module.Config, "from_env", classmethod(lambda cls: _make_config("AAPL")))
    seen_args = []
    monkeypatch.setattr(main_module, "cmd_momentum_backtest_multi", lambda config, *a, **k: seen_args.append((config, a)))
    monkeypatch.setattr(
        main_module, "cmd_momentum_backtest", lambda *a, **k: pytest.fail("darf nicht aufgerufen werden")
    )

    main_module.main()

    config, args = seen_args[0]
    assert args[0] == ["AAPL", "MSFT"]  # symbols, normalisiert
    assert args[3] == pytest.approx(5000.0)  # starting_cash (nach calendar_days, feed)


def test_momentum_backtest_dispatches_to_single_without_symbols(monkeypatch):
    import main as main_module

    monkeypatch.setattr("sys.argv", ["main.py", "momentum-backtest", "--symbol", "MSFT"])
    monkeypatch.setattr(main_module.Config, "from_env", classmethod(lambda cls: _make_config("AAPL")))
    seen_configs = []
    monkeypatch.setattr(main_module, "cmd_momentum_backtest", lambda config, *a, **k: seen_configs.append(config))
    monkeypatch.setattr(
        main_module, "cmd_momentum_backtest_multi", lambda *a, **k: pytest.fail("darf nicht aufgerufen werden")
    )

    main_module.main()

    assert seen_configs[0].symbol == "MSFT"


def test_format_duration_under_a_minute():
    assert _format_duration(timedelta(seconds=47)) == "0:47"


def test_format_duration_minutes_and_seconds():
    assert _format_duration(timedelta(minutes=1, seconds=7)) == "1:07"


def test_format_duration_hours():
    assert _format_duration(timedelta(hours=1, minutes=2, seconds=3)) == "1:02:03"


def test_momentum_report_dispatches_with_default_days(monkeypatch):
    import main as main_module

    monkeypatch.setattr("sys.argv", ["main.py", "momentum-report"])
    monkeypatch.setattr(main_module.Config, "from_env", classmethod(lambda cls: _make_config("AAPL")))
    seen_args = []
    monkeypatch.setattr(main_module, "cmd_momentum_report", lambda config, *a: seen_args.append(a))

    main_module.main()

    assert seen_args[0] == (1,)


def test_momentum_report_dispatches_with_custom_days(monkeypatch):
    import main as main_module

    monkeypatch.setattr("sys.argv", ["main.py", "momentum-report", "--days", "5"])
    monkeypatch.setattr(main_module.Config, "from_env", classmethod(lambda cls: _make_config("AAPL")))
    seen_args = []
    monkeypatch.setattr(main_module, "cmd_momentum_report", lambda config, *a: seen_args.append(a))

    main_module.main()

    assert seen_args[0] == (5,)



def _make_live_config(symbol: str):
    import dataclasses

    return dataclasses.replace(_make_config(symbol), paper=False)


def test_momentum_run_refuses_live_trading_without_flag(monkeypatch, capsys):
    """Regression: momentum-run ist nur für Paper-Trading gedacht, startete
    aber mit ALPACA_PAPER=false kommentarlos mit echtem Geld."""
    import main as main_module
    import tradingbot.momentum_live as momentum_live

    monkeypatch.setattr("sys.argv", ["main.py", "momentum-run"])
    monkeypatch.setattr(main_module.Config, "from_env", classmethod(lambda cls: _make_live_config("AAPL")))
    monkeypatch.setattr(
        momentum_live, "LiveMomentumBot",
        lambda *a, **k: pytest.fail("LiveMomentumBot darf ohne --allow-live-trading nicht starten"),
    )

    with pytest.raises(SystemExit) as exc_info:
        main_module.main()

    assert exc_info.value.code == 1
    assert "--allow-live-trading" in capsys.readouterr().err


def test_momentum_run_allows_live_trading_with_flag(monkeypatch):
    import main as main_module
    import tradingbot.momentum_live as momentum_live

    monkeypatch.setattr("sys.argv", ["main.py", "momentum-run", "--allow-live-trading"])
    monkeypatch.setattr(main_module.Config, "from_env", classmethod(lambda cls: _make_live_config("AAPL")))
    started = []

    class FakeBot:
        def __init__(self, config, criteria, live_config):
            started.append(config.paper)

        def run_forever(self):
            pass

    monkeypatch.setattr(momentum_live, "LiveMomentumBot", FakeBot)

    main_module.main()

    assert started == [False]


@pytest.mark.parametrize("argv, expected", [([], True), (["--no-broker-stop"], False)])
def test_momentum_run_broker_stop_flag(monkeypatch, argv, expected):
    import main as main_module
    import tradingbot.momentum_live as momentum_live

    monkeypatch.setattr("sys.argv", ["main.py", "momentum-run", *argv])
    monkeypatch.setattr(main_module.Config, "from_env", classmethod(lambda cls: _make_config("AAPL")))
    seen = []

    class FakeBot:
        def __init__(self, config, criteria, live_config):
            seen.append(live_config.broker_stop_orders)

        def run_forever(self):
            pass

    monkeypatch.setattr(momentum_live, "LiveMomentumBot", FakeBot)

    main_module.main()

    assert seen == [expected]


def test_momentum_backtest_passes_weakness_exit(monkeypatch):
    import main as main_module

    monkeypatch.setattr("sys.argv", ["main.py", "momentum-backtest", "--symbols", "AAPL", "--weakness-exit", "new_low"])
    monkeypatch.setattr(main_module.Config, "from_env", classmethod(lambda cls: _make_config("AAPL")))
    seen_kwargs = []
    monkeypatch.setattr(main_module, "cmd_momentum_backtest_multi", lambda *a, **k: seen_kwargs.append(k))

    main_module.main()

    assert seen_kwargs[0]["weakness_exit"] == "new_low"


def test_momentum_run_weakness_exit_defaults_to_red_candle(monkeypatch):
    import main as main_module

    monkeypatch.setattr("sys.argv", ["main.py", "momentum-run"])
    monkeypatch.setattr(main_module.Config, "from_env", classmethod(lambda cls: _make_config("AAPL")))
    seen_kwargs = []
    monkeypatch.setattr(main_module, "cmd_momentum_run", lambda *a, **k: seen_kwargs.append(k))

    main_module.main()

    assert seen_kwargs[0]["weakness_exit"] == "red_candle"


def test_momentum_run_passes_weakness_exit_none(monkeypatch):
    import main as main_module

    monkeypatch.setattr("sys.argv", ["main.py", "momentum-run", "--weakness-exit", "none"])
    monkeypatch.setattr(main_module.Config, "from_env", classmethod(lambda cls: _make_config("AAPL")))
    seen_kwargs = []
    monkeypatch.setattr(main_module, "cmd_momentum_run", lambda *a, **k: seen_kwargs.append(k))

    main_module.main()

    assert seen_kwargs[0]["weakness_exit"] == "none"


# ---------------------------------------------------------------------------
# momentum-compare
# ---------------------------------------------------------------------------


def _compare_env(tmp_path, name: str, key: str):
    path = tmp_path / f"{name}.env"
    path.write_text(f"ALPACA_API_KEY={key}\nALPACA_SECRET_KEY=s-{key}\nALPACA_PAPER=true\n")
    return str(path)


def test_momentum_compare_prints_accounts_side_by_side(tmp_path, monkeypatch, capsys):
    from datetime import datetime, timedelta, timezone
    from types import SimpleNamespace

    from alpaca.trading.enums import OrderSide

    import main as main_module

    now = datetime.now(timezone.utc)

    def order(symbol, side, price, minutes_ago):
        t = now - timedelta(minutes=minutes_ago)
        return SimpleNamespace(symbol=symbol, side=side, filled_qty="10", filled_avg_price=str(price),
                               filled_at=t, submitted_at=t)

    orders_by_key = {
        "k1": [order("SECZ", OrderSide.BUY, 15.74, 60), order("SECZ", OrderSide.SELL, 15.53, 59)],
        "k2": [order("SECZ", OrderSide.BUY, 15.74, 60), order("SECZ", OrderSide.SELL, 16.11, 40),
               order("GLND", OrderSide.BUY, 3.70, 30), order("GLND", OrderSide.SELL, 3.94, 20)],
    }

    class FakeClient:
        def __init__(self, api_key, secret_key, paper):
            assert paper is True
            self.key = api_key

        def get_orders(self, filter):
            return [o for o in orders_by_key[self.key] if filter.after < o.submitted_at <= filter.until]

        def get_account(self):
            return SimpleNamespace(equity="100000.00" if self.key == "k1" else "100500.00")

    monkeypatch.setattr("alpaca.trading.client.TradingClient", FakeClient)
    monkeypatch.setattr(main_module.Config, "from_env", classmethod(lambda cls: (_ for _ in ()).throw(AssertionError)))
    monkeypatch.setattr("sys.argv", [
        "main.py", "momentum-compare", "--days", "1",
        "--account", f"red={_compare_env(tmp_path, 'red', 'k1')}",
        "--account", f"none={_compare_env(tmp_path, 'none', 'k2')}",
    ])

    main_module.main()

    out = capsys.readouterr().out
    assert "Konto-Vergleich" in out
    assert "-2.10" in out  # SECZ red: (15.53 - 15.74) * 10
    assert "+3.70" in out  # SECZ none: (16.11 - 15.74) * 10
    assert "100,500.00" in out
    assert "1 Setup(s) von allen Konten gehandelt, 1 nur von einem Teil" in out


def test_momentum_compare_rejects_same_account_twice(tmp_path, monkeypatch, capsys):
    import main as main_module

    monkeypatch.setattr("sys.argv", [
        "main.py", "momentum-compare",
        "--account", f"a={_compare_env(tmp_path, 'a', 'same')}",
        "--account", f"b={_compare_env(tmp_path, 'b', 'same')}",
    ])

    with pytest.raises(SystemExit):
        main_module.main()
    assert "dasselbe Konto" in capsys.readouterr().err


def test_momentum_compare_requires_two_accounts(tmp_path, monkeypatch, capsys):
    import main as main_module

    monkeypatch.setattr("sys.argv", ["main.py", "momentum-compare", "--account", f"a={_compare_env(tmp_path, 'a', 'k')}"])

    with pytest.raises(SystemExit):
        main_module.main()
    assert "mindestens zwei Konten" in capsys.readouterr().err


def test_momentum_compare_rejects_missing_env_file(monkeypatch, capsys):
    import main as main_module

    monkeypatch.setattr("sys.argv", ["main.py", "momentum-compare", "--account", "a=/gibt/es/nicht.env",
                                     "--account", "b=/auch/nicht.env"])

    with pytest.raises(SystemExit):
        main_module.main()
    assert "existiert nicht" in capsys.readouterr().err

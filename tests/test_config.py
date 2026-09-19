import pytest

from tradingbot.config import Config


def set_required_env(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "key")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "secret")


def test_missing_api_key_raises(monkeypatch):
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_SECRET_KEY", raising=False)
    with pytest.raises(RuntimeError):
        Config.from_env()


def test_defaults_are_valid(monkeypatch):
    set_required_env(monkeypatch)
    for var in [
        "SYMBOL", "QTY", "SHORT_WINDOW", "LONG_WINDOW",
        "POLL_INTERVAL_SECONDS", "STOP_LOSS_PCT", "ALPACA_PAPER",
    ]:
        monkeypatch.delenv(var, raising=False)

    config = Config.from_env()

    assert config.symbol == "AAPL"
    assert config.qty == 1.0
    assert config.short_window == 20
    assert config.long_window == 50
    assert config.poll_interval_seconds == 60
    assert config.stop_loss_pct == 0.08
    assert config.paper is True


def test_short_window_must_be_smaller_than_long_window(monkeypatch):
    set_required_env(monkeypatch)
    monkeypatch.setenv("SHORT_WINDOW", "50")
    monkeypatch.setenv("LONG_WINDOW", "20")
    with pytest.raises(ValueError):
        Config.from_env()


def test_short_window_must_be_at_least_one(monkeypatch):
    set_required_env(monkeypatch)
    monkeypatch.setenv("SHORT_WINDOW", "0")
    monkeypatch.setenv("LONG_WINDOW", "20")
    with pytest.raises(ValueError):
        Config.from_env()


def test_qty_must_be_positive(monkeypatch):
    set_required_env(monkeypatch)
    monkeypatch.setenv("QTY", "0")
    with pytest.raises(ValueError):
        Config.from_env()

    monkeypatch.setenv("QTY", "-5")
    with pytest.raises(ValueError):
        Config.from_env()


@pytest.mark.parametrize("value", ["nan", "inf", "-inf"])
def test_qty_rejects_nan_and_infinite(monkeypatch, value):
    """Regressionstest: `qty <= 0` allein lässt NaN (Vergleich immer False)
    und +inf durch -- eine solche Menge würde unvalidiert an die
    Broker-API weitergereicht."""
    set_required_env(monkeypatch)
    monkeypatch.setenv("QTY", value)
    with pytest.raises(ValueError):
        Config.from_env()


def test_poll_interval_must_be_positive(monkeypatch):
    set_required_env(monkeypatch)
    monkeypatch.setenv("POLL_INTERVAL_SECONDS", "0")
    with pytest.raises(ValueError):
        Config.from_env()


def test_stop_loss_pct_must_be_in_valid_range(monkeypatch):
    set_required_env(monkeypatch)

    monkeypatch.setenv("STOP_LOSS_PCT", "-0.1")
    with pytest.raises(ValueError):
        Config.from_env()

    monkeypatch.setenv("STOP_LOSS_PCT", "1.0")
    with pytest.raises(ValueError):
        Config.from_env()


def test_stop_loss_pct_rejects_nan(monkeypatch):
    """Regressionstest: zwei separate Vergleiche (`< 0` und `>= 1`) lassen
    NaN durch, da beide für NaN False ergeben. Der spätere Live-Check
    `stop_loss_pct > 0` in bot.py wäre für NaN ebenfalls immer False,
    sodass der Stop-Loss unbemerkt nie greifen würde."""
    set_required_env(monkeypatch)
    monkeypatch.setenv("STOP_LOSS_PCT", "nan")
    with pytest.raises(ValueError):
        Config.from_env()


def test_stop_loss_pct_zero_is_allowed_and_disables_stop(monkeypatch):
    set_required_env(monkeypatch)
    monkeypatch.setenv("STOP_LOSS_PCT", "0")

    config = Config.from_env()

    assert config.stop_loss_pct == 0.0


def test_empty_symbol_raises(monkeypatch):
    set_required_env(monkeypatch)
    monkeypatch.setenv("SYMBOL", "   ")
    with pytest.raises(ValueError):
        Config.from_env()


def test_symbol_is_normalized_to_uppercase_and_trimmed(monkeypatch):
    set_required_env(monkeypatch)
    monkeypatch.setenv("SYMBOL", "  aapl  ")

    config = Config.from_env()

    assert config.symbol == "AAPL"


@pytest.mark.parametrize("value", ["true", "True", "1", "yes", " true "])
def test_alpaca_paper_accepts_known_true_values(monkeypatch, value):
    set_required_env(monkeypatch)
    monkeypatch.setenv("ALPACA_PAPER", value)
    assert Config.from_env().paper is True


@pytest.mark.parametrize("value", ["false", "False", "0", "no", " false "])
def test_alpaca_paper_accepts_known_false_values(monkeypatch, value):
    set_required_env(monkeypatch)
    monkeypatch.setenv("ALPACA_PAPER", value)
    assert Config.from_env().paper is False


@pytest.mark.parametrize("value", ["flase", "paper", "on", "maybe", ""])
def test_alpaca_paper_rejects_unrecognized_values(monkeypatch, value):
    """Regressionstest: ein Tippfehler wie 'flase' darf niemals
    stillschweigend als Live-Trading (paper=False) interpretiert werden --
    das wäre ein Fail-Unsafe-Default mit echtem Geld im Spiel."""
    set_required_env(monkeypatch)
    monkeypatch.setenv("ALPACA_PAPER", value)
    with pytest.raises(ValueError):
        Config.from_env()

import numpy as np
import pandas as pd
import pytest

from tradingbot.strategy import Signal, compute_rsi, generate_signal, generate_signal_series


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


def test_rejects_oversized_long_window():
    """Regressionstest: ohne Obergrenze würde ein zu großes long_window
    einen OverflowError in close.rolling() auslösen statt einer sauberen
    Fehlermeldung."""
    close = make_series(list(range(20)))
    with pytest.raises(ValueError):
        generate_signal(close, short_window=5, long_window=10**19)


def test_generate_signal_series_matches_generate_signal_at_each_point():
    values = [10, 9, 8, 7, 6, 7, 9, 12, 16, 21, 27, 34, 30, 25, 18, 10]
    close = make_series(values)
    short_window, long_window = 2, 4
    series_signals = generate_signal_series(close, short_window, long_window)

    # Ab i=long_window (nicht erst long_window+1), damit auch der allererste
    # gültige MA-Punkt geprüft wird -- genau dort trat der Bug auf, bei dem
    # generate_signal_series fälschlich ein BUY/SELL erzeugte, obwohl noch
    # gar kein vorheriger MA-Zustand zum Vergleich existierte.
    for i in range(long_window, len(close) + 1):
        prefix = close.iloc[:i]
        single = generate_signal(prefix, short_window, long_window)
        assert series_signals.iloc[i - 1] == single


def test_tie_is_valid_predecessor_for_down_cross():
    """Regressionstest: berührt der kurze SMA den langen exakt (Gleichstand)
    und fällt danach darunter, muss das als SELL erkannt werden -- sowohl
    von generate_signal als auch von der vektorisierten Serien-Version.
    Ein reines "above"-Bool-Flag (kurz > lang) würde den Gleichstand
    fälschlich als "nicht oben" einstufen und dieses SELL verpassen."""
    values = [10, 10, 10, 10, 6, 6]
    close = make_series(values)
    short_window, long_window = 2, 4

    single = generate_signal(close.iloc[:5], short_window, long_window)
    assert single == Signal.SELL

    series_signals = generate_signal_series(close, short_window, long_window)
    assert series_signals.iloc[4] == Signal.SELL


def test_tie_is_valid_predecessor_for_up_cross():
    """Symmetrischer Fall: Gleichstand, danach steigt short_ma darüber -> BUY."""
    values = [6, 6, 6, 6, 10, 10]
    close = make_series(values)
    short_window, long_window = 2, 4

    single = generate_signal(close.iloc[:5], short_window, long_window)
    assert single == Signal.BUY

    series_signals = generate_signal_series(close, short_window, long_window)
    assert series_signals.iloc[4] == Signal.BUY


def test_generate_signal_series_matches_generate_signal_randomized():
    """Breite, deterministische Stichprobe (fester Seed) über viele Fenster-
    kombinationen und kleine Wertebereiche (-> viele Gleichstände), die
    generate_signal_series gegen die als korrekt geltende generate_signal
    an jedem Punkt prüft. Deckt Randfälle ab, die einzelne handgeschriebene
    Tests leicht übersehen (s. die beiden Tie-Bugs, die dieser Test-Stil
    aufgedeckt hat)."""
    rng = np.random.default_rng(42)

    for _ in range(50):
        n = int(rng.integers(10, 40))
        values = rng.integers(1, 8, size=n).astype(float)
        close = pd.Series(values, index=pd.date_range("2024-01-01", periods=n, freq="D"))
        short_w = int(rng.integers(1, 5))
        long_w = short_w + int(rng.integers(1, 6))
        if long_w >= n:
            continue

        series_signals = generate_signal_series(close, short_w, long_w)
        for i in range(long_w, n + 1):
            single = generate_signal(close.iloc[:i], short_w, long_w)
            assert series_signals.iloc[i - 1] == single, (
                f"Mismatch bei n={n} short={short_w} long={long_w} i={i}"
            )


def test_generate_signal_and_series_agree_across_a_data_gap():
    """Regressionstest: eine NaN-Lücke in close (z.B. fehlender Tages-Bar)
    darf generate_signal (Live-Bot) und generate_signal_series
    (Backtest/Validierung) nicht auseinanderlaufen lassen. Vor der
    Umstellung auf eine gemeinsame Implementierung verglich generate_signal
    über die Lücke hinweg den letzten gültigen Wert VOR der Lücke mit dem
    ersten gültigen Wert DANACH, als wären sie benachbart -- und erzeugte
    so ein Signal, das die Serien-Version (korrekt) nicht sah."""
    values = [10, 9, 8, 7, 6, 7, 9, np.nan, 20, 25]
    close = make_series(values)
    short_window, long_window = 2, 4

    single = generate_signal(close, short_window, long_window)
    series_last = generate_signal_series(close, short_window, long_window).iloc[-1]

    assert single == series_last == Signal.HOLD


def test_trend_filter_suppresses_buy_below_trend_ma():
    """Golden Cross weit unter dem langfristigen Trend-Durchschnitt (z.B.
    ein Rebound in einem Abwärtstrend) darf mit aktiviertem Trendfilter
    nicht als BUY durchgehen."""
    values = [50] * 30 + [10, 9, 8, 7, 6, 7, 9]
    close = make_series(values)

    assert generate_signal(close, short_window=2, long_window=4) == Signal.BUY
    assert generate_signal(close, short_window=2, long_window=4, trend_window=30) == Signal.HOLD


def test_trend_filter_allows_buy_above_trend_ma():
    """Golden Cross deutlich über dem Trend-Durchschnitt bleibt BUY."""
    values = [10] * 30 + [50, 49, 48, 47, 46, 47, 49]
    close = make_series(values)

    assert generate_signal(close, short_window=2, long_window=4, trend_window=30) == Signal.BUY


def test_trend_filter_never_suppresses_sell():
    """Filter dürfen niemals einen Ausstieg (Death Cross) blockieren."""
    values = [10] * 30 + [46, 47, 48, 49, 50, 49, 47]
    close = make_series(values)

    signal = generate_signal(close, short_window=2, long_window=4, trend_window=30)
    assert signal == Signal.SELL


def test_trend_filter_disabled_by_default_matches_unfiltered():
    values = [10, 9, 8, 7, 6, 7, 9, 12, 16, 21, 27, 34, 30, 25, 18, 10]
    close = make_series(values)
    unfiltered = generate_signal_series(close, short_window=2, long_window=4)
    explicit_zero = generate_signal_series(close, short_window=2, long_window=4, trend_window=0)
    assert (unfiltered == explicit_zero).all()


def test_rsi_range_is_zero_to_hundred():
    rng = np.random.default_rng(1)
    values = 100 + np.cumsum(rng.normal(0, 1, 60))
    close = pd.Series(values, index=pd.date_range("2024-01-01", periods=60, freq="D"))

    rsi = compute_rsi(close, window=14)

    assert rsi.dropna().between(0, 100).all()


def test_rsi_is_high_after_only_gains():
    close = make_series(list(range(1, 20)))  # streng monoton steigend
    rsi = compute_rsi(close, window=5)
    assert rsi.iloc[-1] == pytest.approx(100.0)


def test_rsi_is_low_after_only_losses():
    close = make_series(list(range(20, 1, -1)))  # streng monoton fallend
    rsi = compute_rsi(close, window=5)
    assert rsi.iloc[-1] == pytest.approx(0.0)


def test_rsi_is_neutral_on_flat_prices():
    close = make_series([100] * 20)
    rsi = compute_rsi(close, window=5)
    assert rsi.iloc[-1] == pytest.approx(50.0)


def test_rsi_filter_suppresses_buy_without_bullish_momentum():
    """Konstruiert eine Serie, bei der der Golden Cross zwar auftritt, der
    RSI aber (durch vorangegangene stärkere Verluste im RSI-Fenster) unter
    50 liegt -- der RSI-Filter muss das BUY dann unterdrücken."""
    # Starker Einbruch, dann ein kleiner Rebound, der gerade so einen
    # Golden Cross auslöst, aber im RSI-Fenster überwiegen die Verluste.
    values = [100, 80, 60, 45, 35, 30, 28, 27, 26.5, 26, 27, 29]
    close = make_series(values)

    signal_unfiltered = generate_signal(close, short_window=2, long_window=4)
    signal_rsi_filtered = generate_signal(close, short_window=2, long_window=4, rsi_window=8)

    assert signal_unfiltered == Signal.BUY
    assert signal_rsi_filtered == Signal.HOLD


def test_rsi_filter_never_suppresses_sell():
    values = [10] * 10 + [20, 30, 40, 50, 40, 20]
    close = make_series(values)

    unfiltered = generate_signal(close, short_window=2, long_window=4)
    rsi_filtered = generate_signal(close, short_window=2, long_window=4, rsi_window=8)

    assert unfiltered == Signal.SELL
    assert rsi_filtered == Signal.SELL


def test_rsi_filter_disabled_by_default_matches_unfiltered():
    values = [10, 9, 8, 7, 6, 7, 9, 12, 16, 21, 27, 34, 30, 25, 18, 10]
    close = make_series(values)
    unfiltered = generate_signal_series(close, short_window=2, long_window=4)
    explicit_zero = generate_signal_series(close, short_window=2, long_window=4, rsi_window=0)
    assert (unfiltered == explicit_zero).all()


def test_rejects_negative_trend_and_rsi_window():
    close = make_series(list(range(20)))
    with pytest.raises(ValueError):
        generate_signal(close, short_window=2, long_window=4, trend_window=-1)
    with pytest.raises(ValueError):
        generate_signal(close, short_window=2, long_window=4, rsi_window=-1)


def test_first_valid_bar_never_generates_spurious_signal():
    """Regressionstest: am allerersten Tag, an dem der lange SMA berechenbar
    wird, darf kein BUY/SELL entstehen -- es gibt noch keinen vorherigen
    MA-Zustand, von dem aus "gekreuzt" werden könnte. Eine monoton steigende
    Serie deckt das zuverlässig auf, da der kurze SMA dort direkt am ersten
    gültigen Punkt über dem langen SMA liegt."""
    close = make_series(list(range(1, 20)))  # 1..19, streng monoton steigend
    short_window, long_window = 2, 4

    series_signals = generate_signal_series(close, short_window, long_window)
    first_valid_idx = long_window - 1

    assert series_signals.iloc[first_valid_idx] == Signal.HOLD
    assert generate_signal(close.iloc[: first_valid_idx + 1], short_window, long_window) == Signal.HOLD

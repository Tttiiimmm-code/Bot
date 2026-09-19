import numpy as np
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

"""Moving-Average-Crossover-Strategie mit optionalen Bestätigungsfiltern.

Signal-Logik:
- BUY, sobald der kurze SMA von unten nach oben durch den langen SMA kreuzt
  (Golden Cross) -- UND, falls aktiviert, Trendfilter und RSI-Filter
  zustimmen.
- SELL, sobald der kurze SMA von oben nach unten durch den langen SMA kreuzt
  (Death Cross). SELL wird NIE gefiltert: die Filter sollen verhindern, in
  einem ungünstigen Umfeld neu einzusteigen, dürfen aber niemals einen
  Ausstieg blockieren.
- HOLD sonst.
"""

from __future__ import annotations

from enum import Enum

import pandas as pd


class Signal(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


# Gemeinsame Obergrenze für alle Fenstergrößen (SMA, Trendfilter, RSI),
# verwendet von config.py, main.py (_parse_grid) und hier -- ein größerer
# Wert würde in close.rolling() bzw. bei der Kursdaten-Zeitraumberechnung
# einen OverflowError auslösen; 100000 ist bereits absurd weit über jedem
# sinnvollen Fenster.
MAX_WINDOW = 100_000


def _validate_window(name: str, window: int, *, allow_zero: bool) -> None:
    minimum = 0 if allow_zero else 1
    if window < minimum:
        raise ValueError(f"{name} muss mindestens {minimum} sein.")
    if window > MAX_WINDOW:
        raise ValueError(f"{name} darf höchstens {MAX_WINDOW} sein.")


def compute_moving_averages(
    close: pd.Series, short_window: int, long_window: int
) -> pd.DataFrame:
    if short_window < 1:
        raise ValueError("short_window muss mindestens 1 sein.")
    if short_window >= long_window:
        raise ValueError("short_window muss kleiner als long_window sein.")
    if long_window > MAX_WINDOW:
        raise ValueError(f"long_window darf höchstens {MAX_WINDOW} sein.")

    return pd.DataFrame(
        {
            "close": close,
            "short_ma": close.rolling(window=short_window).mean(),
            "long_ma": close.rolling(window=long_window).mean(),
        }
    )


def compute_rsi(close: pd.Series, window: int) -> pd.Series:
    """Relative Strength Index (Cutler's RSI: einfacher gleitender
    Durchschnitt von Gewinnen/Verlusten statt Wilder-Glättung -- deterministisch
    und konsistent mit den einfachen SMAs, die der Rest der Strategie nutzt).

    Werte 0-100. Ein komplett flacher Kursverlauf im Fenster (weder Gewinn
    noch Verlust) ergibt rechnerisch 0/0 -- wird explizit auf den neutralen
    Wert 50 gesetzt statt NaN, da "kein Momentum" hier die korrekte Aussage
    ist (nicht "nicht berechenbar", das bleibt für echte Warmup-Phasen
    reserviert).
    """
    _validate_window("rsi_window", window, allow_zero=False)

    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(window=window).mean()
    avg_loss = loss.rolling(window=window).mean()

    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    rsi = rsi.mask((avg_gain == 0) & (avg_loss == 0), 50.0)
    return rsi


def generate_signal_series(
    close: pd.Series,
    short_window: int,
    long_window: int,
    trend_window: int = 0,
    rsi_window: int = 0,
) -> pd.Series:
    """Berechnet für jeden Zeitpunkt in `close` ein Signal (BUY/SELL/HOLD).

    BUY, wenn der kurze SMA von <= auf > den langen SMA wechselt (Golden
    Cross); SELL bei umgekehrtem Wechsel (Death Cross); sonst HOLD. Ein
    exakter Gleichstand (short_ma == long_ma) gilt als gültiger Vorgänger-
    Zustand für BEIDE Richtungen -- ein reines "above"-Bool-Flag würde das
    für Down-Crosses verpassen, da ein Gleichstand dabei fälschlich als
    "nicht oben" eingestuft würde.

    Am allerersten Tag, an dem der lange SMA berechenbar wird, gibt es noch
    keinen gültigen "vorherigen" MA-Zustand, mit dem verglichen werden
    könnte -- ohne die `valid`/`prev_valid`-Prüfung würde das fälschlich
    als BUY/SELL gewertet. Aus demselben Grund verlangt ein Wechsel direkt
    NACH einer Datenlücke (NaN in `close`, z.B. ein fehlender Tages-Bar)
    ebenfalls erst wieder zwei aufeinanderfolgende gültige Tage, bevor neu
    signalisiert wird -- die Lücke wird nie stillschweigend übersprungen.

    Optionale Bestätigungsfilter (wirken NUR auf BUY, nie auf SELL -- ein
    Ausstieg darf nie durch einen Filter blockiert werden):
    - `trend_window` > 0: BUY nur, wenn der Kurs über dem gleitenden
      Durchschnitt dieses Fensters liegt (z.B. 200-Tage-SMA als
      Trendfilter). Reduziert Fehlsignale in Seitwärts-/Abwärtsmärkten.
    - `rsi_window` > 0: BUY nur, wenn der RSI über 50 liegt (aufwärts
      gerichtetes Momentum bestätigt den Crossover).
    """
    _validate_window("trend_window", trend_window, allow_zero=True)
    _validate_window("rsi_window", rsi_window, allow_zero=True)

    ma = compute_moving_averages(close, short_window, long_window)
    valid = ma["short_ma"].notna() & ma["long_ma"].notna()
    diff = ma["short_ma"] - ma["long_ma"]

    prev_valid = valid.shift(1, fill_value=False)
    prev_diff = diff.shift(1)

    crossed_up = valid & prev_valid & (prev_diff <= 0) & (diff > 0)
    crossed_down = valid & prev_valid & (prev_diff >= 0) & (diff < 0)

    if trend_window > 0:
        trend_ma = close.rolling(window=trend_window).mean()
        in_uptrend = close > trend_ma  # NaN-Vergleiche sind False -> Warmup korrekt unterdrückt
        crossed_up = crossed_up & in_uptrend

    if rsi_window > 0:
        rsi = compute_rsi(close, rsi_window)
        bullish_momentum = rsi > 50  # NaN-Vergleich ebenfalls False während Warmup
        crossed_up = crossed_up & bullish_momentum

    signals = pd.Series(Signal.HOLD, index=ma.index, dtype=object)
    signals[crossed_up] = Signal.BUY
    signals[crossed_down] = Signal.SELL
    return signals


def generate_signal(
    close: pd.Series,
    short_window: int,
    long_window: int,
    trend_window: int = 0,
    rsi_window: int = 0,
) -> Signal:
    """Berechnet das aktuelle Signal für den letzten Zeitpunkt in `close`.

    Implementiert als letzter Wert von `generate_signal_series`, damit
    Live-Trading (das diese Funktion pro Zyklus aufruft) und
    Backtest/Validierung (die `generate_signal_series` direkt nutzen)
    niemals auseinanderlaufen können.
    """
    series = generate_signal_series(close, short_window, long_window, trend_window, rsi_window)
    if series.empty:
        return Signal.HOLD
    return series.iloc[-1]

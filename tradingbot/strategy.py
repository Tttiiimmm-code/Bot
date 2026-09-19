"""Moving-Average-Crossover-Strategie.

Signal-Logik:
- BUY, sobald der kurze SMA von unten nach oben durch den langen SMA kreuzt
  (Golden Cross).
- SELL, sobald der kurze SMA von oben nach unten durch den langen SMA kreuzt
  (Death Cross).
- HOLD sonst.
"""

from __future__ import annotations

from enum import Enum

import pandas as pd


class Signal(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


# Gemeinsame Obergrenze für SMA-Fenstergrößen, verwendet von config.py,
# main.py (_parse_grid) und hier -- ein größerer Wert würde in
# close.rolling() bzw. bei der Kursdaten-Zeitraumberechnung einen
# OverflowError auslösen; 100000 ist bereits absurd weit über jedem
# sinnvollen Fenster.
MAX_WINDOW = 100_000


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


def generate_signal_series(
    close: pd.Series, short_window: int, long_window: int
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
    """
    ma = compute_moving_averages(close, short_window, long_window)
    valid = ma["short_ma"].notna() & ma["long_ma"].notna()
    diff = ma["short_ma"] - ma["long_ma"]

    prev_valid = valid.shift(1, fill_value=False)
    prev_diff = diff.shift(1)

    crossed_up = valid & prev_valid & (prev_diff <= 0) & (diff > 0)
    crossed_down = valid & prev_valid & (prev_diff >= 0) & (diff < 0)

    signals = pd.Series(Signal.HOLD, index=ma.index, dtype=object)
    signals[crossed_up] = Signal.BUY
    signals[crossed_down] = Signal.SELL
    return signals


def generate_signal(close: pd.Series, short_window: int, long_window: int) -> Signal:
    """Berechnet das aktuelle Signal für den letzten Zeitpunkt in `close`.

    Implementiert als letzter Wert von `generate_signal_series`, damit
    Live-Trading (das diese Funktion pro Zyklus aufruft) und
    Backtest/Validierung (die `generate_signal_series` direkt nutzen)
    niemals auseinanderlaufen können.
    """
    series = generate_signal_series(close, short_window, long_window)
    if series.empty:
        return Signal.HOLD
    return series.iloc[-1]

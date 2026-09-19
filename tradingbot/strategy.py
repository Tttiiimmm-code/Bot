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


def compute_moving_averages(
    close: pd.Series, short_window: int, long_window: int
) -> pd.DataFrame:
    if short_window >= long_window:
        raise ValueError("short_window muss kleiner als long_window sein.")

    return pd.DataFrame(
        {
            "close": close,
            "short_ma": close.rolling(window=short_window).mean(),
            "long_ma": close.rolling(window=long_window).mean(),
        }
    )


def generate_signal(close: pd.Series, short_window: int, long_window: int) -> Signal:
    """Berechnet das aktuelle Signal aus den letzten beiden Kerzen.

    Erfordert mindestens `long_window + 1` Datenpunkte, sonst HOLD.
    """
    ma = compute_moving_averages(close, short_window, long_window).dropna()
    if len(ma) < 2:
        return Signal.HOLD

    prev, curr = ma.iloc[-2], ma.iloc[-1]

    crossed_up = prev["short_ma"] <= prev["long_ma"] and curr["short_ma"] > curr["long_ma"]
    crossed_down = prev["short_ma"] >= prev["long_ma"] and curr["short_ma"] < curr["long_ma"]

    if crossed_up:
        return Signal.BUY
    if crossed_down:
        return Signal.SELL
    return Signal.HOLD


def generate_signal_series(
    close: pd.Series, short_window: int, long_window: int
) -> pd.Series:
    """Vektorisierte Version für Backtests: ein Signal pro Zeile.

    Spiegelt exakt die Vergleichsoperatoren von `generate_signal` wider
    (<=/>= für den vorherigen Punkt, </> für den aktuellen), inklusive der
    Behandlung eines exakten Gleichstands (short_ma == long_ma) als
    gültiger Vorgänger-Zustand für BEIDE Richtungen -- ein reines
    "above"-Bool-Flag würde das für Down-Crosses verpassen, da ein
    Gleichstand dabei fälschlich als "nicht oben" eingestuft würde.

    Am allerersten Tag, an dem der lange SMA berechenbar wird, gibt es noch
    keinen gültigen "vorherigen" MA-Zustand, mit dem verglichen werden
    könnte -- ohne die `valid`/`prev_valid`-Prüfung würde das fälschlich
    als BUY/SELL gewertet.
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

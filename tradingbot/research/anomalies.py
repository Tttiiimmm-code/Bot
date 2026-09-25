"""Runde 8: bekannte Anomalien (Familien P-T in research/PROTOCOL.md).

Alle Funktionen liefern Gewichte (Tage x Assets bzw. Tage), festgelegt zum
Schlusskurs von Tag t und gültig für die Rendite t -> t+1; ausgewertet mit
crypto.run_weights (Umschlagskosten) bzw. financed_returns (Hebelzins).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

HALLOWEEN_MONTHS = {11, 12, 1, 2, 3, 4}


def _month_ends(index) -> np.ndarray:
    days = pd.DatetimeIndex([pd.Timestamp(d) for d in index])
    nxt = np.append(days.month[1:], -1)
    return np.asarray(days.month != nxt)


def vol_managed_weights(close: pd.Series, cap: float, target_vol: float = 0.15,
                        window: int = 21) -> pd.Series:
    """P: Gewicht = min(cap, target_vol / annualisierte Vola der letzten
    `window` Tagesrenditen bis einschließlich t)."""
    vol = close.pct_change().rolling(window).std() * np.sqrt(252)
    return (target_vol / vol).clip(upper=cap).where(vol.notna(), 0.0)


def halloween_weights(index) -> pd.Series:
    """Q: investiert für die Rendite t -> t+1, wenn t+1 in November-April liegt."""
    months = pd.Series([d.month for d in index], index=index)
    return months.shift(-1).isin(HALLOWEEN_MONTHS).astype(float)


def financed_returns(weight: pd.Series, close: pd.Series, cost_per_side: float,
                     borrow_rate: float = 0.06) -> pd.Series:
    """Einzel-Asset mit Hebel: Rendite t+1 = w_t * r_{t+1} - Zins auf (w_t - 1)+
    - Kosten auf |w_t - w_{t-1}|."""
    r = close.pct_change()
    w = weight.reindex(close.index).fillna(0.0)
    held = w.shift(1).fillna(0.0)
    financing = (held - 1).clip(lower=0) * borrow_rate / 252
    turnover = (w - held).abs().shift(1).fillna(0.0)
    return (held * r - financing - cost_per_side * turnover).iloc[1:].fillna(0.0)


def cross_section_weights(close: pd.DataFrame, universe: pd.DataFrame, score: pd.DataFrame,
                          n: int, highest: bool) -> pd.DataFrame:
    """S/T: an jedem Monatsende die n Titel mit höchstem (bzw. niedrigstem)
    Score im Universum, gleichgewichtet bis zum nächsten Monatsende; ohne
    Kurs (Delisting) fällt die Position weg."""
    is_end = _month_ends(close.index)
    S, U = score.to_numpy(float), universe.to_numpy(bool)
    avail = close.notna().to_numpy()
    W = np.zeros(close.shape)
    current = np.zeros(close.shape[1])
    for t in range(len(close.index)):
        if is_end[t]:
            s = np.where(U[t] & np.isfinite(S[t]), S[t], np.nan)
            valid = np.flatnonzero(~np.isnan(s))
            current = np.zeros(close.shape[1])
            if len(valid) >= n:
                order = valid[np.argsort(s[valid])]
                pick = order[-n:] if highest else order[:n]
                current[pick] = 1.0 / n
        W[t] = np.where(avail[t], current, 0.0)
    return pd.DataFrame(W, index=close.index, columns=close.columns)


def momentum_12_1(close: pd.DataFrame) -> pd.DataFrame:
    return close.shift(21) / close.shift(252) - 1


def low_volatility(close: pd.DataFrame) -> pd.DataFrame:
    return close.pct_change(fill_method=None).rolling(63, min_periods=50).std()

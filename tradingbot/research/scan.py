"""Runde 10: systematischer Scan vieler Standardregeln über viele Assets mit
Korrektur für multiples Testen (research/PROTOCOL.md).

Jede Regel liefert eine Positionsreihe (-1/0/+1), festgelegt zum Schluss von
t und gültig für die Rendite t -> t+1. Kennzahl: Alpha-t-Wert der Strategie
gegenüber dem Halten des Assets; Auswahl per Benjamini-Hochberg (Stufe 1),
Bestätigung im unabhängigen Zeitraum per Bonferroni (Stufe 2).
"""

from __future__ import annotations

from statistics import NormalDist

import numpy as np
import pandas as pd

_N = NormalDist()


def _rsi(c: pd.Series, k: int) -> pd.Series:
    ch = c.diff()
    gain = ch.clip(lower=0).ewm(alpha=1 / k, adjust=False).mean()
    loss = (-ch).clip(lower=0).ewm(alpha=1 / k, adjust=False).mean()
    return 100 - 100 / (1 + gain / loss.replace(0, np.nan))


def _state(enter_long, exit_long, enter_short, exit_short, long_short: bool) -> np.ndarray:
    """Zustandsautomat für Einstieg/Ausstieg-Regeln (Arrays von bool)."""
    pos, out = 0, np.zeros(len(enter_long))
    for t in range(len(out)):
        if pos == 1 and exit_long[t]:
            pos = 0
        elif pos == -1 and exit_short[t]:
            pos = 0
        if pos == 0:
            if enter_long[t]:
                pos = 1
            elif long_short and enter_short[t]:
                pos = -1
        out[t] = pos
    return out


def rule_positions(c: pd.Series, family: str, param, long_short: bool) -> pd.Series:
    """Positionsreihe einer Regel auf der Schlusskursreihe `c`."""
    low = -1.0 if long_short else 0.0
    if family == "sma_trend":
        sma = c.rolling(param).mean()
        pos = np.where(c > sma, 1.0, low)
        return pd.Series(np.where(sma.notna(), pos, 0.0), index=c.index)
    if family == "sma_cross":
        f, s = param
        fast, slow = c.rolling(f).mean(), c.rolling(s).mean()
        pos = np.where(fast > slow, 1.0, low)
        return pd.Series(np.where(slow.notna(), pos, 0.0), index=c.index)
    if family == "tsmom":
        past = c / c.shift(param) - 1
        pos = np.where(past > 0, 1.0, low)
        return pd.Series(np.where(past.notna(), pos, 0.0), index=c.index)
    if family == "donchian":
        hi, lo = c.shift(1).rolling(param).max(), c.shift(1).rolling(param).min()
        hi2, lo2 = c.shift(1).rolling(param // 2).max(), c.shift(1).rolling(param // 2).min()
        a = _state((c > hi).to_numpy(), (c < lo2).to_numpy(), (c < lo).to_numpy(), (c > hi2).to_numpy(),
                   long_short)
        return pd.Series(a, index=c.index)
    if family in ("rsi2", "rsi14"):
        r = _rsi(c, 2 if family == "rsi2" else 14)
        a = _state((r < param).to_numpy(), (r > 50).to_numpy(), (r > 100 - param).to_numpy(),
                   (r < 50).to_numpy(), long_short)
        return pd.Series(a, index=c.index)
    if family == "bollinger":
        sma, sd = c.rolling(20).mean(), c.rolling(20).std()
        a = _state((c < sma - param * sd).to_numpy(), (c >= sma).to_numpy(),
                   (c > sma + param * sd).to_numpy(), (c <= sma).to_numpy(), long_short)
        return pd.Series(a, index=c.index)
    if family == "weekday":
        # long für die Rendite des Folgetags, wenn dieser Wochentag `param` ist (0 = Montag)
        nxt = pd.Series([pd.Timestamp(d).weekday() for d in c.index], index=c.index).shift(-1)
        return (nxt == param).astype(float)
    raise ValueError(family)


RULES: list[tuple[str, object, bool]] = (
    [("sma_trend", n, ls) for n in (10, 20, 50, 100, 200) for ls in (False, True)]
    + [("sma_cross", fs, ls) for fs in ((5, 20), (10, 50), (20, 100), (50, 200)) for ls in (False, True)]
    + [("tsmom", L, ls) for L in (20, 60, 120, 250) for ls in (False, True)]
    + [("donchian", n, ls) for n in (20, 55, 100) for ls in (False, True)]
    + [("rsi2", x, ls) for x in (10, 30) for ls in (False, True)]
    + [("rsi14", 30, ls) for ls in (False, True)]
    + [("bollinger", z, ls) for z in (1.5, 2.0, 2.5) for ls in (False, True)]
    + [("weekday", d, False) for d in range(5)]
)


def strategy_returns(pos: pd.Series, asset_ret: pd.Series, cost_per_side: float) -> pd.Series:
    held = pos.shift(1).fillna(0.0)
    turnover = (pos - held).abs().shift(1).fillna(0.0)
    return (held * asset_ret - cost_per_side * turnover).fillna(0.0)


def alpha_t(strat: pd.Series, bench: pd.Series) -> tuple[float, float]:
    """(Alpha je Tag, t-Wert) aus OLS strat = a + b * bench."""
    df = pd.concat([strat.rename("s"), bench.rename("b")], axis=1).dropna()
    if len(df) < 60 or df["s"].std() == 0:
        return 0.0, 0.0
    X = np.column_stack([np.ones(len(df)), df["b"].to_numpy()])
    y = df["s"].to_numpy()
    coef, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ coef
    cov = resid @ resid / (len(df) - 2) * np.linalg.inv(X.T @ X)
    return float(coef[0]), (float(coef[0] / np.sqrt(cov[0, 0])) if cov[0, 0] > 0 else 0.0)


def one_sided_p(t: float) -> float:
    return 1 - _N.cdf(t)


def benjamini_hochberg(pvalues, q: float) -> np.ndarray:
    """Maske der Entdeckungen bei FDR q."""
    p = np.asarray(pvalues, dtype=float)
    order = np.argsort(p)
    passed = p[order] <= q * (np.arange(1, len(p) + 1) / len(p))
    k = np.flatnonzero(passed).max() + 1 if passed.any() else 0
    mask = np.zeros(len(p), dtype=bool)
    mask[order[:k]] = True
    return mask

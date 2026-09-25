"""Kandidaten-Strategien für die Forschung (siehe Plan, Phase 2).

Alle Parameter-Defaults stammen aus den jeweiligen Veröffentlichungen, nicht
aus eigener Optimierung.

Zeitkonvention: Alpaca-Minuten-Bars tragen den Zeitstempel ihres BEGINNS.
Der Bar "9:59" schließt also um 10:00 -- "Schlusskurs um 10:00" ist der
Close des Bars mit Sitzungsminute 29 (0 = 9:30).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd

from tradingbot.research.engine import Sessions, Trade

SESSION_MINUTES = 390


@dataclass
class _Day:
    minute: np.ndarray  # Sitzungsminute je Bar (0 = 9:30)
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    volume: np.ndarray
    index: pd.DatetimeIndex


def _day_arrays(bars: pd.DataFrame) -> _Day:
    idx = bars.index
    return _Day(
        minute=np.asarray(idx.hour * 60 + idx.minute - 570),
        open=bars["open"].to_numpy(float),
        high=bars["high"].to_numpy(float),
        low=bars["low"].to_numpy(float),
        close=bars["close"].to_numpy(float),
        volume=bars["volume"].to_numpy(float),
        index=idx,
    )


class _DayCache:
    """Berechnet Tages-Arrays einmal pro Handelstag."""

    def __init__(self) -> None:
        self._cache: dict[date, _Day] = {}
        self._moves: dict[date, np.ndarray] = {}

    def day(self, sessions: Sessions, i: int) -> _Day:
        d, bars = sessions[i]
        if d not in self._cache:
            self._cache[d] = _day_arrays(bars)
        return self._cache[d]

    def moves(self, sessions: Sessions, i: int) -> np.ndarray:
        """|Close / Tages-Open - 1| je Sitzungsminute (NaN bei fehlendem Bar)."""
        d = sessions[i][0]
        if d not in self._moves:
            day = self.day(sessions, i)
            out = np.full(SESSION_MINUTES, np.nan)
            ok = (day.minute >= 0) & (day.minute < SESSION_MINUTES)
            out[day.minute[ok]] = np.abs(day.close[ok] / day.open[0] - 1)
            self._moves[d] = out
        return self._moves[d]


def _daily_vol(sessions: Sessions, cache: _DayCache, i: int, lookback: int) -> float:
    """Std der Close-zu-Close-Tagesrenditen der `lookback` Tage VOR Tag i."""
    closes = np.array([cache.day(sessions, k).close[-1] for k in range(i - lookback - 1, i)])
    r = np.diff(closes) / closes[:-1]
    return float(np.std(r, ddof=1))


@dataclass
class NoiseAreaBreakout:
    """Intraday-Momentum auf Index-ETFs nach Zarattini, Aziz & Barbon (2024),
    "Beat the Market: An Effective Intraday Momentum Strategy for S&P500
    ETF (SPY)".

    Rauschzone: Obergrenze = max(Open, Vortagesschluss) * (1 + k*sigma(t)),
    Untergrenze = min(Open, Vortagesschluss) * (1 - k*sigma(t)), sigma(t) =
    mittlere absolute Bewegung seit Open zur selben Uhrzeit über die letzten
    `lookback` Tage. Prüfung alle `check_minutes` ab 10:00: Schluss über
    Obergrenze -> long, unter Untergrenze -> short. Trailing-Stop: long
    raus, wenn Schluss < max(Obergrenze, VWAP) (short spiegelbildlich).
    Alles wird zum Handelsschluss glattgestellt. Positionsgröße:
    target_vol / Tagesvolatilität der letzten `lookback` Tage, gedeckelt
    auf max_leverage (die Engine deckelt zusätzlich aufs Konto).
    `max_entries`: höchstens so viele Einstiege pro Tag (None = beliebig).
    Im Cash-Konto ist nur 1 sinnvoll: ein zweiter Kauf am selben Tag
    liefe mit unabgewickeltem Verkaufserlös (Good-Faith-Violation).
    """

    lookback: int = 14
    band_mult: float = 1.0
    check_minutes: int = 30
    target_vol: float = 0.02
    max_leverage: float = 4.0
    long_only: bool = False
    max_entries: int | None = None
    name: str = "noise_breakout"
    _cache: _DayCache = field(default_factory=_DayCache, repr=False)

    @property
    def warmup_days(self) -> int:
        return self.lookback + 1

    def trades_for_day(self, sessions: Sessions, i: int) -> list[Trade]:
        d = sessions[i][0]
        day = self._cache.day(sessions, i)
        if len(day.close) < 2 or day.minute[0] != 0:
            return []
        prev_close = self._cache.day(sessions, i - 1).close[-1]
        sigma = np.nanmean(
            np.vstack([self._cache.moves(sessions, k) for k in range(i - self.lookback, i)]), axis=0
        )
        vol = _daily_vol(sessions, self._cache, i, self.lookback)
        exposure = min(self.max_leverage, self.target_vol / vol) if vol > 0 else 0.0
        if exposure <= 0:
            return []

        o = day.open[0]
        m = np.clip(day.minute, 0, SESSION_MINUTES - 1)
        upper = max(o, prev_close) * (1 + self.band_mult * sigma[m])
        lower = min(o, prev_close) * (1 - self.band_mult * sigma[m])
        typical = (day.high + day.low + day.close) / 3
        vwap = np.cumsum(typical * day.volume) / np.maximum(np.cumsum(day.volume), 1e-12)

        trades: list[Trade] = []
        pos, entry_j, entries = 0, -1, 0
        last = len(day.close) - 1
        for j in range(last):  # am letzten Bar wird nicht mehr eingestiegen
            end_minute = day.minute[j] + 1
            if end_minute < 30 or end_minute % self.check_minutes != 0:
                continue
            c = day.close[j]
            if np.isnan(upper[j]) or np.isnan(lower[j]):
                continue
            want = pos
            if pos == 1 and c < max(upper[j], vwap[j]):
                want = 0
            elif pos == -1 and c > min(lower[j], vwap[j]):
                want = 0
            if want == 0 and (self.max_entries is None or entries < self.max_entries):
                if c > upper[j]:
                    want = 1
                elif c < lower[j] and not self.long_only:
                    want = -1
            if want != pos:
                if pos != 0:
                    trades.append(self._trade(d, day, pos, entry_j, j + 1, day.open[j + 1], exposure, "stop"))
                pos, entry_j = want, j + 1
                entries += want != 0
        if pos != 0:
            trades.append(self._trade(d, day, pos, entry_j, last, day.close[last], exposure, "close"))
        return trades

    @staticmethod
    def _trade(d, day: _Day, side, entry_j, exit_j, exit_price, exposure, reason) -> Trade:
        return Trade(
            day=d,
            side=side,
            entry_time=day.index[entry_j],
            entry_price=day.open[entry_j],
            exit_time=day.index[exit_j],
            exit_price=exit_price,
            exposure=exposure,
            reason=reason,
        )


@dataclass
class LastHalfHourMomentum:
    """Intraday-Momentum nach Gao, Han, Li & Zhou (2018), "Market intraday
    momentum": die Rendite vom Vortagesschluss bis 10:00 sagt die Richtung
    der letzten halben Stunde voraus. Einstieg zum Open des 15:30-Bars in
    Signalrichtung, Ausstieg zum Handelsschluss. Nur volle Handelstage.
    `min_abs_signal`: Mindestbetrag der Morgenrendite für einen Trade.
    """

    long_only: bool = False
    min_abs_signal: float = 0.0
    exposure: float = 1.0
    name: str = "last_half_hour"
    warmup_days: int = 1
    _cache: _DayCache = field(default_factory=_DayCache, repr=False)

    def trades_for_day(self, sessions: Sessions, i: int) -> list[Trade]:
        d = sessions[i][0]
        day = self._cache.day(sessions, i)
        pos_10 = np.flatnonzero(day.minute == 29)
        pos_1530 = np.flatnonzero(day.minute == 360)
        if len(pos_10) == 0 or len(pos_1530) == 0 or day.minute[-1] != SESSION_MINUTES - 1:
            return []
        prev_close = self._cache.day(sessions, i - 1).close[-1]
        signal = day.close[pos_10[0]] / prev_close - 1
        if signal == 0 or abs(signal) <= self.min_abs_signal:
            return []
        side = 1 if signal > 0 else -1
        if side < 0 and self.long_only:
            return []
        j = pos_1530[0]
        return [
            Trade(
                day=d,
                side=side,
                entry_time=day.index[j],
                entry_price=day.open[j],
                exit_time=day.index[-1],
                exit_price=day.close[-1],
                exposure=self.exposure,
                reason="close",
            )
        ]


@dataclass
class GapFade:
    """Gap-Fade (Familie D, siehe research/PROTOCOL.md): moderate
    Eröffnungslücken werden gegen die Lückenrichtung gehandelt.

    Einstieg zum Open des 9:31-Bars, wenn min_gap <= |Lücke| <= max_gap.
    Ziel = Vortagesschluss (Limit, gefüllt erst, wenn ein Bar ihn
    überschreitet). Stop = Tages-Open -/+ stop_mult * |Lücke|, gefüllt zum
    Stop-Kurs oder schlechteren Bar-Open. Ziel und Stop im selben Bar ->
    Stop. Sonst Ausstieg zum Schluss des letzten Bars vor `exit_minute`
    (Sitzungsminute, 390 = Handelsschluss).
    """

    min_gap: float = 0.0025
    max_gap: float = 0.02
    stop_mult: float = 1.0
    exit_minute: int = SESSION_MINUTES
    long_only: bool = False
    exposure: float = 1.0
    name: str = "gap_fade"
    warmup_days: int = 1
    _cache: _DayCache = field(default_factory=_DayCache, repr=False)

    def trades_for_day(self, sessions: Sessions, i: int) -> list[Trade]:
        d = sessions[i][0]
        day = self._cache.day(sessions, i)
        if len(day.close) < 3 or day.minute[0] != 0 or day.minute[1] != 1:
            return []
        prev_close = self._cache.day(sessions, i - 1).close[-1]
        o = day.open[0]
        gap = o / prev_close - 1
        if not self.min_gap <= abs(gap) <= self.max_gap:
            return []
        side = 1 if gap < 0 else -1
        if side < 0 and self.long_only:
            return []
        j = 1
        entry = day.open[j]
        target = prev_close
        stop = o * (1 - side * self.stop_mult * abs(gap))
        # Lücke schon in der ersten Minute geschlossen -> kein Trade mehr
        if side * (target - entry) <= 0:
            return []

        exit_j, exit_price, reason = None, None, "time"
        for k in range(j, len(day.close)):
            if day.minute[k] >= self.exit_minute:
                break
            hit = None
            if side > 0:
                if day.low[k] <= stop:
                    hit = min(day.open[k], stop), "stop"
                elif day.high[k] > target:
                    hit = max(day.open[k], target), "target"
            else:
                if day.high[k] >= stop:
                    hit = max(day.open[k], stop), "stop"
                elif day.low[k] < target:
                    hit = min(day.open[k], target), "target"
            if hit is not None:
                exit_j, (exit_price, reason) = k, hit
                break
            exit_j, exit_price = k, day.close[k]
        if exit_j is None:
            return []
        return [
            Trade(
                day=d,
                side=side,
                entry_time=day.index[j],
                entry_price=entry,
                exit_time=day.index[exit_j],
                exit_price=exit_price,
                exposure=self.exposure,
                reason=reason,
            )
        ]

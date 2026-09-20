"""Historischer Backtest der Warrior-Trading-Momentum-Day-Trading-Strategie
(Ross Cameron, https://www.warriortrading.com/momentum-day-trading-strategy/)
auf Minuten-Kursdaten.

WICHTIGE EINSCHRÄNKUNGEN (siehe README für Details):

- Dies ist eine regelbasierte NÄHERUNG der im Artikel beschriebenen,
  diskretionären Chartmuster (Bull Flag / Flat Top Breakout) -- die
  exakten Schwellenwerte für "starker Anstieg" oder "Extension Bar" sind
  im Original nicht numerisch definiert und wurden hier sinnvoll, aber
  notwendigerweise etwas willkürlich gewählt (siehe Parameter-Defaults).
- Der markweite Scanner-Teil der Strategie (Float < 100 Mio., News-
  Katalysator) ist NICHT implementiert: Alpacas Marktdaten-API liefert
  weder Float noch ist hier eine News-Anbindung eingebaut. Dieses Modul
  bekommt ein bereits feststehendes Symbol übergeben, es durchsucht nicht
  den Gesamtmarkt.
- NUR für historische Analyse gedacht. Für Live-Handel ungeeignet: die
  Strategie beruht darauf, die erste Kerze nach einem Pullback in Echtzeit
  zu kaufen -- mit Alpacas verzögertem kostenlosem Datenplan (siehe
  broker.get_minute_bars) wäre das kein echtzeitnahes Signal mehr.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum

import numpy as np
import pandas as pd

# Wiederverwendet aus backtest.py statt einer eigenen, identischen
# Fill-Preis/Kosten-Berechnung -- eine einzige Quelle der Wahrheit für
# "wie wirkt sich Slippage/Provision auf einen Verkauf aus" über Tages-
# und Minuten-Backtest hinweg.
from tradingbot.backtest import _execute_sell

REQUIRED_COLUMNS = ("open", "high", "low", "close", "volume")


class ExitReason(str, Enum):
    TARGET = "TARGET"  # 2:1-Ziel erreicht, 50% verkauft
    STOP = "STOP"  # Stop-Loss (Pullback-Tief bzw. Breakeven) ausgelöst
    RED_CANDLE = "RED_CANDLE"  # erste rote Kerze (vor Teilverkauf)
    EXTENSION = "EXTENSION"  # ungewöhnlich starker Spike, Gewinn mitgenommen
    END_OF_DAY = "END_OF_DAY"  # Zwangsschluss am Sitzungsende (kein Overnight-Halten)


@dataclass
class MomentumExit:
    time: pd.Timestamp
    price: float
    shares: int
    reason: ExitReason


@dataclass
class MomentumTrade:
    day: pd.Timestamp
    pattern: str  # "BULL_FLAG" oder "FLAT_TOP"
    entry_time: pd.Timestamp
    entry_price: float
    initial_stop_price: float
    shares: int
    exits: list[MomentumExit] = field(default_factory=list)

    @property
    def shares_closed(self) -> int:
        return sum(e.shares for e in self.exits)

    @property
    def gross_pnl(self) -> float:
        return sum(e.price * e.shares for e in self.exits) - self.entry_price * self.shares

    @property
    def risk_per_share(self) -> float:
        return self.entry_price - self.initial_stop_price


@dataclass
class MomentumBacktestResult:
    trades: list[MomentumTrade]
    final_equity: float
    total_return_pct: float
    win_rate: float
    num_trades: int
    total_costs: float
    days_evaluated: int
    days_skipped_insufficient_lookback: int
    days_skipped_insufficient_trend_history: int


def _validate_bars(bars: pd.DataFrame) -> None:
    missing = [c for c in REQUIRED_COLUMNS if c not in bars.columns]
    if missing:
        raise ValueError(f"bars fehlen die Spalten {missing} (benötigt: {REQUIRED_COLUMNS}).")
    if not isinstance(bars.index, pd.DatetimeIndex):
        raise ValueError("bars muss einen DatetimeIndex haben (siehe Broker.get_minute_bars).")


def _daily_trend_ok(day_bars: pd.DataFrame, daily_sma: float | None) -> bool:
    """Näherung für Kriterium 2 ('starker Tageschart, über den gleitenden
    Durchschnitten'): der erste Kurs der Sitzung muss über dem gleitenden
    Durchschnitt der VORHERIGEN Tage liegen (kein Lookahead: der SMA-Wert
    bezieht das aktuelle, noch laufende Handelsdatum nicht mit ein)."""
    if daily_sma is None or not math.isfinite(daily_sma):
        return False
    return day_bars["close"].iloc[0] > daily_sma


def _relative_volume_reference(days: list[pd.Timestamp], day_bars_by_day: dict, lookback_days: int):
    """Baut für jeden Tag (ab dem `lookback_days`-ten) eine Referenzkurve
    der durchschnittlichen kumulierten Lautstärke je Minute-seit-Sitzungs-
    beginn über die vorangegangenen `lookback_days` Tage.

    Ausrichtung erfolgt über die POSITION innerhalb der Sitzung (0., 1., 2.
    Minute seit Open), nicht über die Uhrzeit -- bei Frühschluss-Handels-
    tagen (Feiertage) kann das leicht verschoben sein, für die Zwecke
    dieses Näherungs-Backtests ausreichend genau (Frühschlusstage sind
    selten).
    """
    cum_vol_by_day = {
        day: day_bars_by_day[day]["volume"].cumsum().to_numpy() for day in days
    }

    reference: dict[pd.Timestamp, np.ndarray | None] = {}
    for i, day in enumerate(days):
        if i < lookback_days:
            reference[day] = None
            continue
        prior_days = days[i - lookback_days : i]
        max_len = len(cum_vol_by_day[day])
        sums = np.zeros(max_len)
        counts = np.zeros(max_len)
        for prior in prior_days:
            prior_cum = cum_vol_by_day[prior]
            n = min(len(prior_cum), max_len)
            sums[:n] += prior_cum[:n]
            counts[:n] += 1
        with np.errstate(invalid="ignore", divide="ignore"):
            avg = np.divide(sums, counts, out=np.full(max_len, np.nan), where=counts > 0)
        reference[day] = avg
    return reference


def _simulate_day(
    day: pd.Timestamp,
    day_bars: pd.DataFrame,
    rel_vol_reference: np.ndarray | None,
    daily_sma: float | None,
    *,
    max_risk_dollars: float,
    available_cash: float,
    reward_risk_ratio: float,
    min_relative_volume: float,
    flagpole_min_gain_pct: float,
    flagpole_max_bars: int,
    min_pullback_bars: int,
    max_pullback_bars: int,
    max_pullback_retrace_pct: float,
    extension_multiplier: float,
    trading_window_start,
    trading_window_end,
    commission_pct: float,
    slippage_pct: float,
) -> tuple[list[MomentumTrade], float, float]:
    """Simuliert einen einzelnen Handelstag und gibt (Trades, cash_delta,
    total_costs) zurück. Höchstens EINE offene Position gleichzeitig (die
    Strategie im Artikel handelt jeweils ein Setup nach dem anderen)."""
    trades: list[MomentumTrade] = []
    cash_delta = 0.0
    total_costs = 0.0

    if not _daily_trend_ok(day_bars, daily_sma) or rel_vol_reference is None:
        return trades, cash_delta, total_costs

    closes = day_bars["close"].to_numpy()
    opens = day_bars["open"].to_numpy()
    highs = day_bars["high"].to_numpy()
    lows = day_bars["low"].to_numpy()
    volumes = day_bars["volume"].to_numpy()
    times = day_bars.index
    n = len(day_bars)
    cum_volume = np.cumsum(volumes)

    # Zustandsautomat: SEARCHING -> (Flagpole erkannt) -> PULLBACK -> IN_POSITION -> SEARCHING
    state = "SEARCHING"
    swing_low_idx = 0
    pullback_start_idx: int | None = None
    pullback_low = math.inf
    pullback_highs: list[float] = []
    flagpole_peak = 0.0
    flagpole_gain_abs = 0.0

    position: MomentumTrade | None = None
    stop_price = 0.0
    target_price = 0.0
    breakeven = False
    avg_bar_range = 0.0

    for i in range(n):
        bar_time = times[i]
        in_window = trading_window_start <= bar_time.time() < trading_window_end

        if state == "IN_POSITION" and position is not None:
            remaining = position.shares - position.shares_closed
            exited_this_bar = False

            # Stop zuerst prüfen: konservative Annahme, falls Stop UND Ziel
            # im selben 1-Min-Balken erreichbar wären (siehe backtest.py-
            # Konvention für denselben Kompromiss auf Tagesbasis).
            if lows[i] <= stop_price:
                proceeds, cost, fill_price = _execute_sell(remaining, stop_price, commission_pct, slippage_pct)
                total_costs += cost
                cash_delta += proceeds
                position.exits.append(
                    MomentumExit(bar_time, fill_price, remaining, ExitReason.STOP)
                )
                exited_this_bar = True
            elif not breakeven and highs[i] >= target_price:
                half = remaining // 2 or remaining
                proceeds, cost, fill_price = _execute_sell(half, target_price, commission_pct, slippage_pct)
                total_costs += cost
                cash_delta += proceeds
                position.exits.append(
                    MomentumExit(bar_time, fill_price, half, ExitReason.TARGET)
                )
                stop_price = position.entry_price
                breakeven = True
                remaining -= half
                if remaining <= 0:
                    exited_this_bar = True

            if not exited_this_bar and remaining > 0:
                bar_range = highs[i] - lows[i]
                is_extension = (
                    avg_bar_range > 0
                    and bar_range >= extension_multiplier * avg_bar_range
                    and closes[i] > position.entry_price
                )
                is_red = closes[i] < opens[i]
                if is_extension:
                    proceeds, cost, fill_price = _execute_sell(remaining, closes[i], commission_pct, slippage_pct)
                    total_costs += cost
                    cash_delta += proceeds
                    position.exits.append(
                        MomentumExit(bar_time, fill_price, remaining, ExitReason.EXTENSION)
                    )
                    exited_this_bar = True
                elif is_red and not breakeven:
                    proceeds, cost, fill_price = _execute_sell(remaining, closes[i], commission_pct, slippage_pct)
                    total_costs += cost
                    cash_delta += proceeds
                    position.exits.append(
                        MomentumExit(bar_time, fill_price, remaining, ExitReason.RED_CANDLE)
                    )
                    exited_this_bar = True

            if i == n - 1 and position.shares_closed < position.shares:
                remaining = position.shares - position.shares_closed
                proceeds, cost, fill_price = _execute_sell(remaining, closes[i], commission_pct, slippage_pct)
                total_costs += cost
                cash_delta += proceeds
                position.exits.append(
                    MomentumExit(bar_time, fill_price, remaining, ExitReason.END_OF_DAY)
                )
                exited_this_bar = True

            if exited_this_bar and position.shares_closed >= position.shares:
                trades.append(position)
                position = None
                state = "SEARCHING"
                swing_low_idx = i
                continue
            continue

        if state == "SEARCHING":
            if closes[i] < closes[swing_low_idx]:
                swing_low_idx = i
            if not in_window:
                continue
            bars_since_low = i - swing_low_idx
            if bars_since_low == 0 or bars_since_low > flagpole_max_bars:
                continue
            gain_pct = (closes[i] - closes[swing_low_idx]) / closes[swing_low_idx]
            if gain_pct < flagpole_min_gain_pct:
                continue
            rel_vol = _relative_volume_at(cum_volume[i], rel_vol_reference, i)
            if rel_vol is None or rel_vol < min_relative_volume:
                continue
            # Flagpole bestätigt.
            state = "PULLBACK"
            flagpole_peak = closes[i]
            flagpole_gain_abs = closes[i] - closes[swing_low_idx]
            pullback_start_idx = i + 1
            pullback_low = math.inf
            pullback_highs = []
            continue

        if state == "PULLBACK":
            assert pullback_start_idx is not None
            pullback_bars_so_far = i - pullback_start_idx + 1
            pullback_low = min(pullback_low, lows[i])
            pullback_highs.append(highs[i])

            invalidated = (
                pullback_low <= flagpole_peak - max_pullback_retrace_pct * flagpole_gain_abs
                or pullback_bars_so_far > max_pullback_bars
            )
            if invalidated:
                state = "SEARCHING"
                swing_low_idx = i
                continue

            breakout = pullback_bars_so_far >= min_pullback_bars and closes[i] > flagpole_peak
            if breakout and in_window:
                risk_per_share = closes[i] - pullback_low
                if risk_per_share <= 0:
                    state = "SEARCHING"
                    swing_low_idx = i
                    continue

                entry_price = closes[i] * (1 + slippage_pct)
                cost_per_share = entry_price * (1 + commission_pct)
                # Risikobasierte Stückzahl: wenn schon das Risiko EINER Aktie
                # max_risk_dollars übersteigt (z.B. sehr volatiler Pullback),
                # ist risk_based_shares 0 -- das Setup wird dann komplett
                # übersprungen, NICHT durch einen Rückfall auf "kaufe mit dem
                # gesamten verfügbaren Kapital" ersetzt (das würde die
                # Risikobegrenzung faktisch aushebeln). Bei knappem, aber
                # positivem Kapital wird stattdessen auf das tatsächlich
                # verfügbare Cash gedeckelt (inkl. Slippage/Provision, damit
                # der gedeckelte Kauf das Cash nicht knapp unterschreitet).
                risk_based_shares = int(max_risk_dollars // risk_per_share)
                if risk_based_shares <= 0:
                    state = "SEARCHING"
                    swing_low_idx = i
                    continue
                current_cash = available_cash + cash_delta
                cash_based_shares = int(current_cash // cost_per_share)
                shares = min(risk_based_shares, cash_based_shares)
                if shares <= 0:
                    state = "SEARCHING"
                    swing_low_idx = i
                    continue

                # Die Flat-Top-Klassifizierung darf das Hoch des Breakout-
                # Balkens selbst nicht mit einbeziehen -- der ist per
                # Definition höher als das Pullback-Plateau (sonst wäre es
                # kein Breakout) und würde eine echte Flat-Top-Formation
                # fälschlich als Bull Flag einstufen. Bleiben dadurch weniger
                # als 2 Vergleichs-Bars übrig (z.B. min_pullback_bars=1),
                # lässt sich "flach" gar nicht beurteilen -- dann Standard
                # BULL_FLAG statt des alten `or pullback_highs`-Fallbacks,
                # der in genau diesem Fall wieder das Breakout-Hoch mit sich
                # selbst verglichen hätte (Differenz immer 0 -> immer
                # fälschlich FLAT_TOP).
                prior_pullback_highs = pullback_highs[:-1]
                pattern = (
                    "FLAT_TOP"
                    if len(prior_pullback_highs) >= 2
                    and (max(prior_pullback_highs) - min(prior_pullback_highs)) <= 0.003 * flagpole_peak
                    else "BULL_FLAG"
                )
                commission = entry_price * shares * commission_pct
                slippage_cost = (entry_price - closes[i]) * shares
                cash_delta -= entry_price * shares + commission
                total_costs += commission + slippage_cost

                position = MomentumTrade(
                    day=day,
                    pattern=pattern,
                    entry_time=bar_time,
                    entry_price=entry_price,
                    initial_stop_price=pullback_low,
                    shares=shares,
                )
                stop_price = pullback_low
                target_price = entry_price + reward_risk_ratio * risk_per_share
                breakeven = False
                avg_bar_range = float(
                    np.mean(highs[pullback_start_idx : i + 1] - lows[pullback_start_idx : i + 1])
                )
                state = "IN_POSITION"
            continue

    # Sicherheitsnetz: ein Einstieg kann auf dem LETZTEN Balken des Tages
    # ausgelöst werden (Breakout erst in der Schlussminute) -- dann greift
    # die END_OF_DAY-Zwangsschließung innerhalb der Schleife nicht mehr
    # (die läuft nur, solange der Zustand beim Betreten von Balken i bereits
    # IN_POSITION war). Ohne dieses Sicherheitsnetz würde die Position
    # lautlos aus dem Trade-Log verschwinden, obwohl das eingesetzte
    # Kapital bereits abgebucht wurde ("Phantom"-Position).
    if position is not None and position.shares_closed < position.shares:
        remaining = position.shares - position.shares_closed
        proceeds, cost, fill_price = _execute_sell(remaining, closes[n - 1], commission_pct, slippage_pct)
        total_costs += cost
        cash_delta += proceeds
        position.exits.append(MomentumExit(times[n - 1], fill_price, remaining, ExitReason.END_OF_DAY))
        trades.append(position)

    return trades, cash_delta, total_costs


def _relative_volume_at(cum_volume_i: float, reference: np.ndarray, i: int) -> float | None:
    if i >= len(reference):
        return None
    ref = reference[i]
    if not math.isfinite(ref) or ref <= 0:
        return None
    return cum_volume_i / ref




def run_momentum_backtest(
    bars: pd.DataFrame,
    starting_cash: float = 10_000.0,
    max_risk_dollars: float = 500.0,
    reward_risk_ratio: float = 2.0,
    min_relative_volume: float = 2.0,
    lookback_days: int = 20,
    flagpole_min_gain_pct: float = 0.03,
    flagpole_max_bars: int = 15,
    min_pullback_bars: int = 2,
    max_pullback_bars: int = 5,
    max_pullback_retrace_pct: float = 0.5,
    daily_trend_window: int = 50,
    extension_multiplier: float = 4.0,
    trading_window_start=None,
    trading_window_end=None,
    commission_pct: float = 0.0,
    slippage_pct: float = 0.0005,
) -> MomentumBacktestResult:
    """Backtest der Bull-Flag/Flat-Top-Momentum-Strategie auf Minutendaten.

    `bars`: DataFrame mit Spalten open/high/low/close/volume, DatetimeIndex
    (siehe Broker.get_minute_bars -- bereits auf reguläre Handelszeiten
    gefiltert). `trading_window_start`/`trading_window_end` sind
    `datetime.time`-Objekte für den Zeitraum, in dem NEUE Einstiege gesucht
    werden (Standard 9:30-11:30, die vom Artikel empfohlene Kernzeit);
    bereits offene Positionen werden unabhängig vom Fenster bis Sitzungs-
    ende verwaltet.

    Siehe Modul-Docstring für die Einschränkungen dieser Näherung
    (kein markweiter Scanner, kein Float-/Katalysator-Filter, nicht für
    Live-Handel geeignet).
    """
    from datetime import time as dt_time

    if trading_window_start is None:
        trading_window_start = dt_time(9, 30)
    if trading_window_end is None:
        trading_window_end = dt_time(11, 30)
    if trading_window_start >= trading_window_end:
        # Sonst ist `trading_window_start <= t < trading_window_end` für
        # JEDE Balkenzeit False -- der Lauf würde lautlos 0 Trades liefern
        # (nie ein Fehler), statt den vertauschten/leeren Zeitraum zu melden.
        raise ValueError(
            f"trading_window_start ({trading_window_start}) muss vor trading_window_end "
            f"({trading_window_end}) liegen."
        )

    _validate_bars(bars)
    if not (math.isfinite(starting_cash) and starting_cash > 0):
        raise ValueError(f"starting_cash muss eine positive, endliche Zahl sein, war {starting_cash}.")
    if not (math.isfinite(max_risk_dollars) and max_risk_dollars > 0):
        raise ValueError(f"max_risk_dollars muss eine positive, endliche Zahl sein, war {max_risk_dollars}.")
    if not (math.isfinite(reward_risk_ratio) and reward_risk_ratio > 0):
        raise ValueError(f"reward_risk_ratio muss eine positive, endliche Zahl sein, war {reward_risk_ratio}.")
    if not (math.isfinite(min_relative_volume) and min_relative_volume > 0):
        raise ValueError(f"min_relative_volume muss eine positive, endliche Zahl sein, war {min_relative_volume}.")
    if lookback_days <= 0:
        raise ValueError(f"lookback_days muss positiv sein, war {lookback_days}.")
    if daily_trend_window <= 0:
        raise ValueError(f"daily_trend_window muss positiv sein, war {daily_trend_window}.")
    if not (math.isfinite(flagpole_min_gain_pct) and flagpole_min_gain_pct > 0):
        raise ValueError(f"flagpole_min_gain_pct muss eine positive, endliche Zahl sein, war {flagpole_min_gain_pct}.")
    if flagpole_max_bars <= 0:
        raise ValueError(f"flagpole_max_bars muss positiv sein, war {flagpole_max_bars}.")
    if min_pullback_bars <= 0 or max_pullback_bars <= 0:
        raise ValueError(
            f"min_pullback_bars/max_pullback_bars müssen positiv sein, "
            f"waren {min_pullback_bars}/{max_pullback_bars}."
        )
    if min_pullback_bars > max_pullback_bars:
        # Sonst kann pullback_bars_so_far den Breakout-Schwellenwert nie
        # erreichen, bevor das Setup als ungültig verworfen wird -- die
        # Strategie würde lautlos NIE einen Trade eingehen.
        raise ValueError(
            f"min_pullback_bars ({min_pullback_bars}) darf nicht größer als "
            f"max_pullback_bars ({max_pullback_bars}) sein."
        )
    if not 0 <= max_pullback_retrace_pct < 1:
        raise ValueError(
            f"max_pullback_retrace_pct muss zwischen 0 (inklusiv) und 1 (exklusiv) liegen, "
            f"war {max_pullback_retrace_pct}."
        )
    if not (math.isfinite(extension_multiplier) and extension_multiplier > 0):
        raise ValueError(f"extension_multiplier muss eine positive, endliche Zahl sein, war {extension_multiplier}.")

    day_keys = pd.Series(bars.index.date, index=bars.index)
    days = sorted(day_keys.unique())
    day_bars_by_day = {day: bars.loc[day_keys == day] for day in days}

    daily_close = pd.Series({day: b["close"].iloc[-1] for day, b in day_bars_by_day.items()}).sort_index()
    daily_sma = daily_close.rolling(window=daily_trend_window).mean().shift(1)

    rel_vol_reference = _relative_volume_reference(days, day_bars_by_day, lookback_days)

    cash = starting_cash
    all_trades: list[MomentumTrade] = []
    total_costs = 0.0
    days_skipped_lookback = sum(1 for v in rel_vol_reference.values() if v is None)
    # Tage, die zwar genug Vortage für das Relativvolumen haben, aber noch
    # nicht für den daily_trend_window-SMA (NaN) -- ohne diese zweite
    # Zählung würden solche Tage fälschlich als "ausgewertet" gemeldet,
    # obwohl _daily_trend_ok für sie IMMER False zurückgibt und daher nie
    # ein Trade zustande kommen kann.
    days_skipped_trend = sum(
        1
        for day, v in rel_vol_reference.items()
        if v is not None and not (pd.notna(daily_sma.get(day)) and math.isfinite(daily_sma.get(day)))
    )

    for day in days:
        trades, cash_delta, day_costs = _simulate_day(
            day,
            day_bars_by_day[day],
            rel_vol_reference[day],
            daily_sma.get(day),
            max_risk_dollars=max_risk_dollars,
            available_cash=cash,
            reward_risk_ratio=reward_risk_ratio,
            min_relative_volume=min_relative_volume,
            flagpole_min_gain_pct=flagpole_min_gain_pct,
            flagpole_max_bars=flagpole_max_bars,
            min_pullback_bars=min_pullback_bars,
            max_pullback_bars=max_pullback_bars,
            max_pullback_retrace_pct=max_pullback_retrace_pct,
            extension_multiplier=extension_multiplier,
            trading_window_start=trading_window_start,
            trading_window_end=trading_window_end,
            commission_pct=commission_pct,
            slippage_pct=slippage_pct,
        )
        cash += cash_delta
        total_costs += day_costs
        all_trades.extend(trades)

    final_equity = cash
    total_return_pct = (final_equity / starting_cash - 1) * 100
    wins = sum(1 for t in all_trades if t.gross_pnl > 0)
    win_rate = wins / len(all_trades) if all_trades else 0.0

    return MomentumBacktestResult(
        trades=all_trades,
        final_equity=final_equity,
        total_return_pct=total_return_pct,
        win_rate=win_rate,
        num_trades=len(all_trades),
        total_costs=total_costs,
        days_evaluated=len(days) - days_skipped_lookback - days_skipped_trend,
        days_skipped_insufficient_lookback=days_skipped_lookback,
        days_skipped_insufficient_trend_history=days_skipped_trend,
    )

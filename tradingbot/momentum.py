"""Bull-Flag/Flat-Top-Momentum-Strategie (Ross Cameron/Warrior Trading,
https://www.warriortrading.com/momentum-day-trading-strategy/) auf
Minuten-Kursdaten.

Enthält den geteilten Entscheidungs-Zustandsautomaten (MomentumEngine),
der SOWOHL vom historischen Backtest (run_momentum_backtest, balkenweise
über ein komplettes, im Speicher gehaltenes Tages-Array) als auch vom
Live-Bot (tradingbot/momentum_live.py, balkenweise über live abgefragte
Balken) verwendet wird -- eine einzige Quelle der Handelsregeln, damit
Backtest und Live-Ausführung nicht auseinanderlaufen.

WICHTIGE EINSCHRÄNKUNGEN (siehe README für Details):

- Dies ist eine regelbasierte NÄHERUNG der im Artikel beschriebenen,
  diskretionären Chartmuster (Bull Flag / Flat Top Breakout) -- die
  exakten Schwellenwerte für "starker Anstieg" oder "Extension Bar" sind
  im Original nicht numerisch definiert und wurden hier sinnvoll, aber
  notwendigerweise etwas willkürlich gewählt (siehe Parameter-Defaults).
- Kein Float-Filter: Alpacas Marktdaten-API liefert keinen Aktien-Float
  (siehe tradingbot/scanner.py für die übrigen Auswahlkriterien).
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
# Schwäche-Ausstieg VOR dem Ziel-Teilverkauf: "red_candle" = erste Kerze,
# die rot schließt; "new_low" = erste Kerze, deren Tief unter dem der
# Vorkerze liegt (Warrior Trading: "first candle to make a new low");
# "none" = kein Schwäche-Ausstieg, nur Stop/Ziel/Extension (bei dünnen
# IEX-Daten ist eine einzelne rote Kerze oft nur ein Abschluss einen Cent
# tiefer -- im Backtest und live am 24.09. schnitt das Gewinner ab).
WEAKNESS_EXITS = ("red_candle", "new_low", "none")


class ExitReason(str, Enum):
    TARGET = "TARGET"  # 2:1-Ziel erreicht, 50% verkauft
    STOP = "STOP"  # Stop-Loss (Pullback-Tief bzw. Breakeven) ausgelöst
    RED_CANDLE = "RED_CANDLE"  # erste rote Kerze (vor Teilverkauf)
    NEW_LOW = "NEW_LOW"  # erste Kerze mit Tief unter dem der Vorkerze (vor Teilverkauf)
    EXTENSION = "EXTENSION"  # ungewöhnlich starker Spike, Gewinn mitgenommen
    END_OF_DAY = "END_OF_DAY"  # Zwangsschluss am Sitzungsende (kein Overnight-Halten)
    CIRCUIT_BREAKER = "CIRCUIT_BREAKER"  # Zwangsschluss durch den Tages-Maximalverlust-Schutz (nur Live-Bot)


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


def _daily_trend_ok(first_close: float, daily_sma: float | None) -> bool:
    """Näherung für Kriterium 2 ('starker Tageschart, über den gleitenden
    Durchschnitten'): der erste Kurs der Sitzung muss über dem gleitenden
    Durchschnitt der VORHERIGEN Tage liegen (kein Lookahead: der SMA-Wert
    bezieht das aktuelle, noch laufende Handelsdatum nicht mit ein).
    Nimmt bewusst einen einzelnen Preis statt eines ganzen day_bars-
    DataFrames entgegen -- geteilte Grundlage für den Backtest (erster
    Schlusskurs des Tages) UND den Live-Bot (tradingbot/momentum_live.py,
    Schlusskurs des ersten balkenweise verarbeiteten Balkens), ohne dass
    Letzterer dafür ein künstliches Ein-Zeilen-DataFrame bauen müsste."""
    if daily_sma is None or not math.isfinite(daily_sma):
        return False
    return first_close > daily_sma


def _build_relative_volume_reference(prior_days_cum_volumes: list[np.ndarray], max_len: int) -> np.ndarray:
    """Baut die Referenzkurve (durchschnittliche kumulierte Lautstärke je
    Minute seit Sitzungsbeginn, ausgerichtet über die UHRZEIT seit
    Sitzungsbeginn -- siehe _cum_volume_by_session_minute, der Index i
    steht für Minute i nach 9:30, nicht für den i-ten Balken) aus den
    kumulierten Tagesvolumen-Kurven mehrerer Vortage. Geteilte Grundlage
    für den Backtest
    (_relative_volume_reference, viele Tage auf einmal) UND den Live-Bot
    (tradingbot/momentum_live.py, eine Referenzkurve pro Symbol und
    Handelstag) -- eine einzige Quelle der Berechnung."""
    sums = np.zeros(max_len)
    counts = np.zeros(max_len)
    for prior_cum in prior_days_cum_volumes:
        n = min(len(prior_cum), max_len)
        sums[:n] += prior_cum[:n]
        counts[:n] += 1
    with np.errstate(invalid="ignore", divide="ignore"):
        avg = np.divide(sums, counts, out=np.full(max_len, np.nan), where=counts > 0)
    return avg


def _session_minutes(index: pd.DatetimeIndex) -> np.ndarray:
    """Minuten seit 9:30 (Sitzungsbeginn) für jeden Balken eines Tages.
    `index` muss in America/New_York-Zeit vorliegen (siehe
    broker._filter_regular_session)."""
    session_open = index[0].normalize() + pd.Timedelta(hours=9, minutes=30)
    return ((index - session_open).total_seconds() // 60).astype(int).to_numpy()


def _cum_volume_by_session_minute(day_bars: pd.DataFrame) -> np.ndarray:
    """Kumuliertes Volumen je UHRZEIT-Minute seit Sitzungsbeginn (Position i
    = 9:30 + i Minuten). Minuten ohne Balken zählen mit Volumen 0 -- IEX
    liefert bei dünn gehandelten Small-Caps viele Minuten gar nicht. Eine
    Ausrichtung nach Balken-POSITION statt Uhrzeit würde Referenz und
    Live-Abfrage (die per Uhrzeit-Minute indiziert, siehe momentum_live.py)
    auseinanderlaufen lassen."""
    minutes = _session_minutes(day_bars.index)
    volume = np.zeros(int(minutes.max()) + 1)
    np.add.at(volume, minutes, day_bars["volume"].to_numpy(dtype=float))
    return np.cumsum(volume)


def _relative_volume_reference(days: list[pd.Timestamp], day_bars_by_day: dict, lookback_days: int):
    """Baut für jeden Tag (ab dem `lookback_days`-ten) eine Referenzkurve
    der durchschnittlichen kumulierten Lautstärke je Minute-seit-Sitzungs-
    beginn über die vorangegangenen `lookback_days` Tage (siehe
    _build_relative_volume_reference)."""
    cum_vol_by_day = {day: _cum_volume_by_session_minute(day_bars_by_day[day]) for day in days}

    reference: dict[pd.Timestamp, np.ndarray | None] = {}
    for i, day in enumerate(days):
        if i < lookback_days:
            reference[day] = None
            continue
        prior_days = days[i - lookback_days : i]
        max_len = len(cum_vol_by_day[day])
        prior_cum_volumes = [cum_vol_by_day[prior] for prior in prior_days]
        reference[day] = _build_relative_volume_reference(prior_cum_volumes, max_len)
    return reference


def _relative_volume_at(cum_volume_i: float, reference: np.ndarray, i: int) -> float | None:
    if i >= len(reference):
        return None
    ref = reference[i]
    if not math.isfinite(ref) or ref <= 0:
        return None
    return cum_volume_i / ref


@dataclass
class BreakoutEvent:
    """Von MomentumEngine.process_bar() ausgegeben, wenn ein Bull-Flag/
    Flat-Top-Einstieg ausgelöst hat. Enthält bewusst KEINE Stückzahl --
    die Positionsgröße hängt vom verfügbaren Kapital ab (Backtest: im
    Voraus bekannt; Live: erfordert einen Kontostand-Abruf), das entscheidet
    der Aufrufer. Muss mit genau einem Aufruf von record_entry() oder
    decline_entry() beantwortet werden, bevor der nächste Balken verarbeitet
    wird (siehe MomentumEngine-Docstring)."""

    pattern: str  # "BULL_FLAG" oder "FLAT_TOP"
    time: pd.Timestamp
    reference_price: float  # Schlusskurs des Breakout-Balkens
    stop_price: float  # Pullback-Tief
    risk_per_share: float
    # Diagnose-Felder für Nachvollziehbarkeit (Logging live/Auswertung
    # Backtest) -- fließen NICHT in die Handelsentscheidung ein, die ist
    # zu diesem Zeitpunkt schon getroffen. Defaults, damit bestehender
    # Code/Tests mit den ursprünglichen 5 Positionsargumenten weiter
    # funktionieren.
    swing_low_price: float = 0.0
    flagpole_gain_pct: float = 0.0
    pullback_bars: int = 0
    relative_volume: float | None = None


@dataclass
class ExitSignal:
    """Von MomentumEngine.process_bar() bzw. force_exit() ausgegeben, wenn
    (ein Teil) der offenen Position verkauft werden soll. `shares` ist von
    der Engine bereits final bestimmt (z.B. die Hälfte beim ersten
    Zielerreichen, sonst die komplette Restposition) -- der Aufrufer führt
    nur noch die eigentliche Ausführung durch und meldet das Ergebnis über
    record_exit() zurück."""

    reason: ExitReason
    time: pd.Timestamp
    reference_price: float
    shares: int


class MomentumEngine:
    """Balkenweiser Zustandsautomat (SEARCHING -> PULLBACK -> IN_POSITION
    -> SEARCHING) für EIN Symbol, der die Bull-Flag/Flat-Top-Erkennung und
    das Positions-/Ausstiegsmanagement der Strategie kapselt.

    Bewusst getrennt von Positionsgröße/Orderausführung: process_bar() gibt
    nur Ereignisse zurück (BreakoutEvent/ExitSignal); der Aufrufer (Backtest
    oder Live-Bot) entscheidet Stückzahl/Ausführung und meldet das Ergebnis
    über record_entry()/record_exit() zurück, BEVOR der nächste Balken an
    process_bar() übergeben wird. Diese Trennung ist der Grund, warum
    dieselbe Engine unverändert sowohl im (deterministischen, sofort
    gefüllten) Backtest als auch im Live-Bot (echte Orders, Kontostand-
    Abruf) funktioniert.

    Nutzungsvertrag (bei Missachtung wird RuntimeError geworfen, siehe
    process_bar): auf jedes BreakoutEvent muss vor dem nächsten
    process_bar()-Aufruf GENAU EIN record_entry() oder decline_entry()
    folgen; auf jedes ExitSignal muss ein passendes record_exit() folgen.
    """

    def __init__(
        self,
        *,
        flagpole_min_gain_pct: float,
        flagpole_max_bars: int,
        min_pullback_bars: int,
        max_pullback_bars: int,
        max_pullback_retrace_pct: float,
        reward_risk_ratio: float,
        extension_multiplier: float,
        min_relative_volume: float,
        weakness_exit: str = "red_candle",
    ):
        if weakness_exit not in WEAKNESS_EXITS:
            raise ValueError(f"weakness_exit muss eines von {WEAKNESS_EXITS} sein, war {weakness_exit!r}.")
        if min_pullback_bars < 1:
            # Ohne Rücksetzer-Kerze gäbe es kein Rücksetzer-Tief als Stop --
            # der Breakout-Balken selbst würde Stop = Schluss liefern (Risiko 0).
            raise ValueError(f"min_pullback_bars muss mindestens 1 sein, war {min_pullback_bars}.")
        self._weakness_exit = weakness_exit
        self._flagpole_min_gain_pct = flagpole_min_gain_pct
        self._flagpole_max_bars = flagpole_max_bars
        self._min_pullback_bars = min_pullback_bars
        self._max_pullback_bars = max_pullback_bars
        self._max_pullback_retrace_pct = max_pullback_retrace_pct
        self._reward_risk_ratio = reward_risk_ratio
        self._extension_multiplier = extension_multiplier
        self._min_relative_volume = min_relative_volume

        self.state = "SEARCHING"
        self._swing_low_price = math.inf
        self._bars_since_swing_low = 0
        # Schlusskurs des zuletzt verarbeiteten Balkens, unabhängig vom
        # Zustand -- wird gebraucht, um nach einer geschlossenen Position
        # die Swing-Tief-Referenz mit dem zuletzt beobachteten MARKTPREIS
        # neu zu starten (siehe record_exit), nicht mit dem Ausführungspreis
        # des eigenen Exits (der z.B. bei einem Stop durch Slippage/die
        # Stop-Schwelle selbst systematisch von diesem abweicht).
        self._last_close = 0.0
        # Hoch/Tief des zuletzt verarbeiteten Balkens -- Breakout-Trigger
        # ("erste Kerze, die über dem Hoch der Vorkerze schließt") und
        # NEW_LOW-Ausstieg vergleichen jeweils mit der Vorkerze.
        self._prev_high = math.inf
        self._prev_low = -math.inf
        # Höchstes HOCH der Flaggenstange (inkl. Fortsetzungs-Kerzen mit
        # neuem Hoch, bevor der Rücksetzer beginnt).
        self._flagpole_peak = 0.0
        self._flagpole_gain_abs = 0.0
        self._flagpole_relative_volume: float | None = None
        self._pullback_low = math.inf
        self._pullback_highs: list[float] = []
        self._pullback_bars_count = 0
        self._pullback_range_sum = 0.0

        self._pending_breakout: BreakoutEvent | None = None

        # Positionszustand (nur während state == "IN_POSITION" relevant).
        self._entry_price = 0.0
        self._entry_time: pd.Timestamp | None = None
        self._pattern = ""
        self._shares_total = 0
        self._shares_closed = 0
        self._stop_price = 0.0
        self._target_price = 0.0
        self._breakeven = False
        self._avg_bar_range = 0.0

    @property
    def in_position(self) -> bool:
        return self.state == "IN_POSITION"

    @property
    def shares_open(self) -> int:
        return self._shares_total - self._shares_closed

    @property
    def entry_price(self) -> float:
        """Nur aussagekräftig, während in_position True ist (bzw.
        unmittelbar nach record_exit() für Logging vor dem nächsten
        Einstieg -- danach überschrieben)."""
        return self._entry_price

    @property
    def stop_price(self) -> float:
        return self._stop_price

    @property
    def target_price(self) -> float:
        return self._target_price

    @property
    def avg_bar_range(self) -> float:
        return self._avg_bar_range

    def process_bar(
        self,
        time: pd.Timestamp,
        open_: float,
        high: float,
        low: float,
        close: float,
        volume: float,
        *,
        in_window: bool,
        relative_volume: float | None,
        daily_trend_ok: bool,
    ) -> list[BreakoutEvent | ExitSignal]:
        """Verarbeitet genau einen neuen Balken und gibt eine Liste von
        Ereignissen zurück: leer (nichts zu tun), ein BreakoutEvent, oder
        ein bis zwei ExitSignal (z.B. Ziel-Teilverkauf UND anschließend --
        auf DEMSELBEN Balken -- ein Extension-Bar-Ausstieg des Rests, siehe
        _process_position_bar). Der Aufrufer muss jedes Ereignis der Reihe
        nach mit record_entry()/decline_entry() bzw. record_exit()
        beantworten, bevor der nächste Balken übergeben wird."""
        if self._pending_breakout is not None:
            raise RuntimeError(
                "process_bar() aufgerufen, während ein BreakoutEvent noch unbeantwortet ist -- "
                "vorher record_entry() oder decline_entry() aufrufen."
            )

        self._last_close = close

        if self.state == "IN_POSITION":
            events = self._process_position_bar(time, open_, high, low, close)
        elif self.state == "SEARCHING":
            self._process_searching_bar(time, high, close, in_window, relative_volume, daily_trend_ok)
            events = []
        elif self.state == "PULLBACK":
            event = self._process_pullback_bar(time, high, low, close, in_window)
            events = [event] if event is not None else []
        else:
            raise AssertionError(f"Unbekannter Zustand: {self.state}")

        self._prev_high = high
        self._prev_low = low
        return events

    def _process_searching_bar(
        self,
        time: pd.Timestamp,
        high: float,
        close: float,
        in_window: bool,
        relative_volume: float | None,
        daily_trend_ok: bool,
    ) -> None:
        if close < self._swing_low_price:
            self._swing_low_price = close
            self._bars_since_swing_low = 0
        else:
            self._bars_since_swing_low += 1

        if not (in_window and daily_trend_ok):
            return
        if self._bars_since_swing_low == 0 or self._bars_since_swing_low > self._flagpole_max_bars:
            return
        gain_pct = (close - self._swing_low_price) / self._swing_low_price
        if gain_pct < self._flagpole_min_gain_pct:
            return
        if relative_volume is None or relative_volume < self._min_relative_volume:
            return

        # Flagpole bestätigt.
        self.state = "PULLBACK"
        self._flagpole_peak = high
        self._flagpole_gain_abs = high - self._swing_low_price
        self._flagpole_relative_volume = relative_volume
        self._start_pullback()

    def _start_pullback(self) -> None:
        self._pullback_low = math.inf
        self._pullback_highs = []
        self._pullback_bars_count = 0
        self._pullback_range_sum = 0.0

    def _process_pullback_bar(
        self, time: pd.Timestamp, high: float, low: float, close: float, in_window: bool
    ) -> BreakoutEvent | None:
        """Nach der Flaggenstange, in dieser Reihenfolge:

        1. Breakout: nach mindestens min_pullback_bars ECHTEN Rücksetzer-
           Kerzen schließt eine Kerze über dem Hoch der Vorkerze (Warrior
           Trading: "first candle to make a new high", bestätigt durch den
           Schluss). Vorher genügte "Schluss über dem Flaggenstangen-
           Schluss" nach beliebigen Folgekerzen -- das kaufte auch
           Seitwärtsphasen ohne jeden Rücksetzer und sogar die erste
           Schwächekerze nach einem Hoch (siehe Live-Trades GRML/MSS vom
           23.09.), mit einem Stop praktisch am Einstiegskurs.
        2. Neues Hoch über der Flaggenstange ohne Breakout: die Stange läuft
           noch weiter -- ihr Hoch wird nachgezogen, der Rücksetzer beginnt
           von vorn (eine Fortsetzungskerze ist kein Rücksetzer).
        3. Sonst: Rücksetzer-Kerze (Hoch nicht über der Stange). Zu tief
           (max_pullback_retrace_pct der Stangenhöhe) oder zu lang
           (max_pullback_bars) verwirft das Setup."""
        if in_window and self._pullback_bars_count >= self._min_pullback_bars and close > self._prev_high:
            # Ein Breakout-Balken, der vorher unter die Rücksetzer-Grenze
            # durchsticht, würde einen Stop liefern, den kein gültiger
            # Rücksetzer zulässt -- Setup verwerfen statt kaufen.
            if self._too_deep(min(self._pullback_low, low)):
                self._reset_to_searching_after(close)
                return None
            return self._emit_breakout(time, high, low, close)

        if high > self._flagpole_peak:
            self._flagpole_peak = high
            self._flagpole_gain_abs = high - self._swing_low_price
            self._start_pullback()
            # Neues Hoch, aber Docht tief in die Stange hinein: Umkehrkerze,
            # kein sauberes Fortsetzen -- ihr Tief darf nicht einfach
            # verschwinden, nur weil der Rücksetzer neu beginnt.
            if self._too_deep(low):
                self._reset_to_searching_after(close)
            return None

        self._pullback_bars_count += 1
        self._pullback_low = min(self._pullback_low, low)
        self._pullback_highs.append(high)
        self._pullback_range_sum += high - low

        if self._too_deep(self._pullback_low) or self._pullback_bars_count > self._max_pullback_bars:
            self._reset_to_searching_after(close)
        return None

    def _too_deep(self, low: float) -> bool:
        """Liegt `low` tiefer als max_pullback_retrace_pct der Stangenhöhe
        unter ihrem Hoch?"""
        return low <= self._flagpole_peak - self._max_pullback_retrace_pct * self._flagpole_gain_abs

    def _emit_breakout(self, time: pd.Timestamp, high: float, low: float, close: float) -> BreakoutEvent:
        # Stop = Tief des Rücksetzers; ein Breakout-Balken, der kurz noch
        # tiefer ausschlägt, zieht ihn mit nach unten.
        stop_price = min(self._pullback_low, low)
        # Flat Top: die Hochs der Rücksetzer-Kerzen liegen (fast) gleich auf
        # -- ab 2 Vergleichs-Kerzen beurteilbar, sonst Standard BULL_FLAG.
        pattern = (
            "FLAT_TOP"
            if len(self._pullback_highs) >= 2
            and (max(self._pullback_highs) - min(self._pullback_highs)) <= 0.003 * self._flagpole_peak
            else "BULL_FLAG"
        )
        self._pending_breakout = BreakoutEvent(
            pattern=pattern,
            time=time,
            reference_price=close,
            stop_price=stop_price,
            risk_per_share=close - stop_price,
            swing_low_price=self._swing_low_price,
            flagpole_gain_pct=self._flagpole_gain_abs / self._swing_low_price,
            pullback_bars=self._pullback_bars_count,
            relative_volume=self._flagpole_relative_volume,
        )
        # Durchschnittliche Kerzengröße aus Rücksetzer + Breakout-Balken --
        # Referenz für den Extension-Bar-Ausstieg, record_entry() übernimmt
        # sie unverändert.
        self._avg_bar_range = (self._pullback_range_sum + high - low) / (self._pullback_bars_count + 1)
        return self._pending_breakout

    def _reset_to_searching_after(self, close: float) -> None:
        self.state = "SEARCHING"
        self._swing_low_price = close
        self._bars_since_swing_low = 0

    def decline_entry(self) -> None:
        """Der Aufrufer verzichtet auf den Einstieg (z.B. Stückzahl nach
        Risiko-/Kapitalprüfung <= 0) -- zurück zu SEARCHING, wie im
        Backtest (siehe _process_pullback_bar-Fallback)."""
        if self._pending_breakout is None:
            raise RuntimeError("decline_entry() ohne offenes BreakoutEvent aufgerufen.")
        self._reset_to_searching_after(self._pending_breakout.reference_price)
        self._pending_breakout = None

    def record_entry(self, shares: int, fill_price: float, time: pd.Timestamp) -> None:
        """Bestätigt das zuletzt ausgegebene BreakoutEvent mit der
        tatsächlichen Stückzahl/dem tatsächlichen Füllkurs (Backtest:
        sofort simuliert; Live: nach Order-Ausführung)."""
        if self._pending_breakout is None:
            raise RuntimeError("record_entry() ohne offenes BreakoutEvent aufgerufen.")
        if shares <= 0:
            raise ValueError(f"shares muss positiv sein, war {shares}.")
        breakout = self._pending_breakout
        self._pending_breakout = None

        self._entry_price = fill_price
        self._entry_time = time
        self._pattern = breakout.pattern
        self._shares_total = shares
        self._shares_closed = 0
        self._stop_price = breakout.stop_price
        self._target_price = fill_price + self._reward_risk_ratio * breakout.risk_per_share
        self._breakeven = False
        self.state = "IN_POSITION"

    def _process_position_bar(
        self, time: pd.Timestamp, open_: float, high: float, low: float, close: float
    ) -> list[ExitSignal]:
        """Kann bis zu ZWEI ExitSignal für denselben Balken liefern: einen
        Ziel-Teilverkauf (50%) gefolgt vom sofortigen Ausstieg des Rests
        über Extension-Bar -- beide Bedingungen können auf demselben Balken
        zutreffen (Original-Verhalten, siehe _simulate_day-Historie). Ohne
        persistente Zustandsänderung berechnet (Breakeven/Restmenge nur
        lokal simuliert) -- erst record_exit() pro Ereignis übernimmt sie
        dauerhaft, damit ein fehlgeschlagener Live-Order-Versuch beim
        ersten Ereignis das zweite nicht fälschlich als bereits vollzogen
        markiert."""
        remaining = self.shares_open
        signals: list[ExitSignal] = []

        # Stop zuerst prüfen: konservative Annahme, falls Stop UND Ziel im
        # selben 1-Min-Balken erreichbar wären (siehe backtest.py-Konvention
        # für denselben Kompromiss auf Tagesbasis). Stop ist immer der
        # einzige und letzte Ausstieg auf diesem Balken (volle Restmenge).
        if low <= self._stop_price:
            # Eröffnet der Balken bereits UNTER dem Stop (Kurslücke), ist der
            # Stop-Preis nie handelbar gewesen -- realistischer Fill ist der
            # Eröffnungskurs. Sonst würde der Backtest Verluste bei Gaps
            # systematisch schönen (gerade bei volatilen Small-Caps).
            return [ExitSignal(ExitReason.STOP, time, min(open_, self._stop_price), remaining)]

        breakeven_after = self._breakeven
        if not self._breakeven and high >= self._target_price:
            half = remaining // 2 or remaining
            signals.append(ExitSignal(ExitReason.TARGET, time, self._target_price, half))
            remaining -= half
            breakeven_after = True
            if remaining <= 0:
                return signals

        bar_range = high - low
        is_extension = (
            self._avg_bar_range > 0
            and bar_range >= self._extension_multiplier * self._avg_bar_range
            and close > self._entry_price
        )
        if is_extension:
            signals.append(ExitSignal(ExitReason.EXTENSION, time, close, remaining))
        elif not breakeven_after:
            if self._weakness_exit == "red_candle" and close < open_:
                signals.append(ExitSignal(ExitReason.RED_CANDLE, time, close, remaining))
            elif self._weakness_exit == "new_low" and low < self._prev_low:
                signals.append(ExitSignal(ExitReason.NEW_LOW, time, close, remaining))
        return signals

    def force_exit(self, time: pd.Timestamp, price: float, reason: ExitReason = ExitReason.END_OF_DAY) -> ExitSignal | None:
        """Erzwingt die vollständige Schließung der offenen Position (z.B.
        Sitzungsende, kein Overnight-Halten) -- unabhängig von den
        regulären Ausstiegsbedingungen. None, wenn keine Position offen ist."""
        if self.state != "IN_POSITION" or self.shares_open <= 0:
            return None
        return ExitSignal(reason, time, price, self.shares_open)

    def record_exit(self, shares_sold: int, fill_price: float, *, is_target_partial: bool = True) -> bool:
        """Meldet die tatsächliche Ausführung eines ExitSignal zurück.
        Gibt True zurück, wenn die Position dadurch vollständig geschlossen
        wurde (Zustand fällt zurück auf SEARCHING), sonst False (Teil-
        verkauf, Position bleibt offen).

        `is_target_partial` (Standard True): ob dieser Teilverkauf ein
        TARGET-Treffer war -- nur dann wandert der Stop auf den
        Einstiegspreis (Breakeven), wie es die Engine selbst für ihre
        eigenen ExitSignal-Teilverkäufe garantiert (siehe
        _process_position_bar: nur TARGET liefert je ein ExitSignal für
        weniger als die volle Restmenge). Ein AUSSERHALB der Engine
        entstandener Teil-Fill mit einer ANDEREN Ursache -- z.B. eine
        Broker-seitige Stop-Order (momentum_live.py._record_broker_stop_fill),
        die bei einer dünn gehandelten Aktie nur teilweise ausgeführt wird,
        bevor sie storniert/verworfen wird -- ist KEIN Zielgewinn, sondern
        weiterhin ein ausgelöster Stop: mit is_target_partial=False bleibt
        der bisherige Stop (bzw. ein zuvor schon erreichtes Breakeven)
        unverändert, statt fälschlich auf Breakeven angehoben zu werden
        (das würde einen bereits verletzten Stop nachträglich "reparieren"
        und die verbleibenden Aktien bis zum nächsten Balken ohne
        korrekten Schutz lassen)."""
        if self.state != "IN_POSITION":
            raise RuntimeError("record_exit() ohne offene Position aufgerufen.")
        if shares_sold <= 0 or shares_sold > self.shares_open:
            raise ValueError(f"shares_sold ({shares_sold}) muss zwischen 1 und {self.shares_open} liegen.")

        self._shares_closed += shares_sold
        if self.shares_open <= 0:
            # Swing-Tief-Referenz mit dem zuletzt beobachteten MARKTPREIS
            # (Schlusskurs des letzten verarbeiteten Balkens) neu starten,
            # NICHT mit fill_price -- der eigene Ausführungspreis (z.B. bei
            # einem Stop durch Slippage UNTER der Stop-Schwelle) spiegelt
            # den tatsächlichen Marktzustand systematisch verzerrt wider
            # und würde eine neue Flagpole danach künstlich leichter
            # auslösbar machen. Konsistent mit decline_entry() und dem
            # Pullback-Invalidierungs-Pfad, die aus demselben Grund beide
            # bereits einen Schlusskurs (nicht fill_price) verwenden.
            self._reset_to_searching_after(self._last_close)
            return True

        if is_target_partial:
            # Teilverkauf durch Zielerreichung: Stop auf den Einstiegspreis
            # nachziehen (Breakeven), Position bleibt offen.
            self._stop_price = self._entry_price
            self._breakeven = True
        return False


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
    weakness_exit: str = "red_candle",
) -> tuple[list[MomentumTrade], float, float]:
    """Simuliert einen einzelnen Handelstag mit MomentumEngine und gibt
    (Trades, cash_delta, total_costs) zurück. Höchstens EINE offene
    Position gleichzeitig (die Strategie im Artikel handelt jeweils ein
    Setup nach dem anderen)."""
    trades: list[MomentumTrade] = []
    cash_delta = 0.0
    total_costs = 0.0

    if not _daily_trend_ok(day_bars["close"].iloc[0], daily_sma) or rel_vol_reference is None:
        return trades, cash_delta, total_costs

    closes = day_bars["close"].to_numpy()
    opens = day_bars["open"].to_numpy()
    highs = day_bars["high"].to_numpy()
    lows = day_bars["low"].to_numpy()
    volumes = day_bars["volume"].to_numpy()
    times = day_bars.index
    n = len(day_bars)
    cum_volume = np.cumsum(volumes)
    session_minutes = _session_minutes(times)

    engine = MomentumEngine(
        flagpole_min_gain_pct=flagpole_min_gain_pct,
        flagpole_max_bars=flagpole_max_bars,
        min_pullback_bars=min_pullback_bars,
        max_pullback_bars=max_pullback_bars,
        max_pullback_retrace_pct=max_pullback_retrace_pct,
        reward_risk_ratio=reward_risk_ratio,
        extension_multiplier=extension_multiplier,
        min_relative_volume=min_relative_volume,
        weakness_exit=weakness_exit,
    )
    current_trade: MomentumTrade | None = None

    for i in range(n):
        bar_time = times[i]
        in_window = trading_window_start <= bar_time.time() < trading_window_end
        rel_vol = _relative_volume_at(cum_volume[i], rel_vol_reference, session_minutes[i])

        events = engine.process_bar(
            bar_time,
            opens[i],
            highs[i],
            lows[i],
            closes[i],
            volumes[i],
            in_window=in_window,
            relative_volume=rel_vol,
            daily_trend_ok=True,  # bereits oben für den ganzen Tag geprüft
        )

        # Bis zu zwei Ereignisse pro Balken möglich (z.B. Ziel-Teilverkauf
        # gefolgt vom sofortigen Ausstieg des Rests über Extension-Bar,
        # siehe MomentumEngine._process_position_bar) -- der Reihe nach
        # abarbeiten, jedes einzeln bei der Engine bestätigen.
        for event in events:
            if isinstance(event, BreakoutEvent):
                entry_price = event.reference_price * (1 + slippage_pct)
                cost_per_share = entry_price * (1 + commission_pct)
                # Risikobasierte Stückzahl: wenn schon das Risiko EINER
                # Aktie max_risk_dollars übersteigt, wird das Setup komplett
                # übersprungen -- NICHT durch einen Rückfall auf "kaufe mit
                # dem gesamten verfügbaren Kapital" ersetzt (das würde die
                # Risikobegrenzung faktisch aushebeln).
                risk_based_shares = int(max_risk_dollars // event.risk_per_share)
                current_cash = available_cash + cash_delta
                cash_based_shares = int(current_cash // cost_per_share)
                shares = min(risk_based_shares, cash_based_shares)
                if shares <= 0:
                    engine.decline_entry()
                    continue

                commission = entry_price * shares * commission_pct
                slippage_cost = (entry_price - event.reference_price) * shares
                cash_delta -= entry_price * shares + commission
                total_costs += commission + slippage_cost

                engine.record_entry(shares, entry_price, bar_time)
                current_trade = MomentumTrade(
                    day=day,
                    pattern=event.pattern,
                    entry_time=bar_time,
                    entry_price=entry_price,
                    initial_stop_price=event.stop_price,
                    shares=shares,
                )
                continue

            proceeds, cost, fill_price = _execute_sell(
                event.shares, event.reference_price, commission_pct, slippage_pct
            )
            total_costs += cost
            cash_delta += proceeds
            assert current_trade is not None
            current_trade.exits.append(MomentumExit(event.time, fill_price, event.shares, event.reason))
            fully_closed = engine.record_exit(
                event.shares, fill_price, is_target_partial=(event.reason == ExitReason.TARGET)
            )
            if fully_closed:
                trades.append(current_trade)
                current_trade = None

    # Sicherheitsnetz: ein Einstieg kann auf dem LETZTEN Balken des Tages
    # ausgelöst werden (Breakout erst in der Schlussminute), oder eine
    # Position kann bis zum Sitzungsende offen bleiben -- in beiden Fällen
    # wird am Ende zwangsweise zum letzten Schlusskurs glattgestellt statt
    # die Position lautlos verschwinden zu lassen (Kapital wäre sonst
    # abgebucht, aber kein zugehöriger Trade-Eintrag vorhanden).
    if engine.in_position:
        force = engine.force_exit(times[n - 1], closes[n - 1])
        if force is not None:
            proceeds, cost, fill_price = _execute_sell(
                force.shares, force.reference_price, commission_pct, slippage_pct
            )
            total_costs += cost
            cash_delta += proceeds
            assert current_trade is not None
            current_trade.exits.append(MomentumExit(force.time, fill_price, force.shares, force.reason))
            engine.record_exit(force.shares, fill_price)
            trades.append(current_trade)

    return trades, cash_delta, total_costs


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
    weakness_exit: str = "red_candle",
) -> MomentumBacktestResult:
    """Backtest der Bull-Flag/Flat-Top-Momentum-Strategie auf Minutendaten.

    `bars`: DataFrame mit Spalten open/high/low/close/volume, DatetimeIndex
    (siehe Broker.get_minute_bars -- bereits auf reguläre Handelszeiten
    gefiltert). `trading_window_start`/`trading_window_end` sind
    `datetime.time`-Objekte für den Zeitraum, in dem NEUE Einstiege gesucht
    werden (Standard 9:30-11:30, die vom Artikel empfohlene Kernzeit);
    bereits offene Positionen werden unabhängig vom Fenster bis Sitzungs-
    ende verwaltet.

    Siehe Modul-Docstring für die Einschränkungen dieser Näherung (kein
    Float-Filter).
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
    if weakness_exit not in WEAKNESS_EXITS:
        raise ValueError(f"weakness_exit muss eines von {WEAKNESS_EXITS} sein, war {weakness_exit!r}.")

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
            weakness_exit=weakness_exit,
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


@dataclass
class SymbolMomentumResult:
    symbol: str
    result: MomentumBacktestResult


@dataclass
class MultiSymbolMomentumBacktestResult:
    per_symbol: list[SymbolMomentumResult]
    total_trades: int
    total_costs: float
    total_gross_pnl: float
    overall_win_rate: float


def run_momentum_backtest_multi(
    bars_by_symbol: dict[str, pd.DataFrame],
    starting_cash_per_symbol: float = 10_000.0,
    **kwargs,
) -> MultiSymbolMomentumBacktestResult:
    """Führt run_momentum_backtest() UNABHÄNGIG für jedes Symbol in
    `bars_by_symbol` aus (jeweils mit demselben `starting_cash_per_symbol`,
    als hätte man für JEDES Symbol separat dieses Kapital reserviert) und
    fasst die Ergebnisse zusammen -- ein schneller Mittelweg, um die
    Strategie über mehrere selbst gewählte Kandidaten hinweg statt nur für
    ein einzelnes Symbol zu testen.

    WICHTIG: dies simuliert NICHT ein einzelnes, gemeinsames Konto mit
    begrenztem Gesamtkapital, das sich mehrere gleichzeitig offene
    Positionen teilt, und auch keine Obergrenze gleichzeitiger Positionen
    (das macht live `momentum-run` über `--max-concurrent-positions`,
    siehe tradingbot/momentum_live.py) -- jedes Symbol wird komplett
    unabhängig behandelt, als stünde für JEDES Symbol dasselbe
    Startkapital separat zur Verfügung. Echte historische Kandidatensuche
    (welche Aktien der Scanner an einem vergangenen Tag gefunden hätte)
    ist damit ebenfalls NICHT abgedeckt -- `bars_by_symbol` muss die
    Symbole bereits selbst vorgeben (siehe README für die Gründe:
    Alpacas Screener-API kennt kein historisches Datum).

    `**kwargs` werden unverändert an jeden einzelnen
    run_momentum_backtest()-Aufruf durchgereicht (alle Parameter außer
    `bars`/`starting_cash`, z.B. max_risk_dollars, reward_risk_ratio, ...)
    -- eine einzige Quelle der Validierung/Defaults statt einer
    duplizierten Parameterliste hier."""
    if not bars_by_symbol:
        raise ValueError("bars_by_symbol darf nicht leer sein.")

    per_symbol = [
        SymbolMomentumResult(
            symbol=symbol,
            result=run_momentum_backtest(bars, starting_cash=starting_cash_per_symbol, **kwargs),
        )
        for symbol, bars in bars_by_symbol.items()
    ]

    all_trades = [t for s in per_symbol for t in s.result.trades]
    total_costs = sum(s.result.total_costs for s in per_symbol)
    total_gross_pnl = sum(t.gross_pnl for t in all_trades)
    wins = sum(1 for t in all_trades if t.gross_pnl > 0)
    overall_win_rate = wins / len(all_trades) if all_trades else 0.0

    return MultiSymbolMomentumBacktestResult(
        per_symbol=per_symbol,
        total_trades=len(all_trades),
        total_costs=total_costs,
        total_gross_pnl=total_gross_pnl,
        overall_win_rate=overall_win_rate,
    )

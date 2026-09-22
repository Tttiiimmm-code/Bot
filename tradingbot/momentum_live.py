"""Live-Trading-Loop: kombiniert den marktweiten Scanner (tradingbot/scanner.py)
mit der Bull-Flag/Flat-Top-Momentum-Engine (tradingbot/momentum.py) zu einem
echten (Paper-)Trading-Loop, der EIGENSTÄNDIG Kandidaten sucht und Orders
platziert -- im Gegensatz zu `momentum-backtest` (nur historische Analyse)
und `scan` (rein lesend).

Datengrundlage: Alpacas IEX-Feed statt des Standard-/SIP-Feeds. Empirisch
verifiziert (siehe README): NUR der SIP-Feed hat ohne Zusatzabo
("Algo Trader Plus") eine ~15-Minuten-Verzögerung, der kostenlose IEX-Feed
liefert sowohl per REST- als auch per WebSocket-Abfrage ECHTZEIT-Daten --
das macht diesen Live-Bot ohne kostenpflichtiges Datenabo überhaupt erst
sinnvoll möglich.

WICHTIGE EINSCHRÄNKUNGEN (siehe README für Details):

- IEX deckt nur einen Bruchteil (~2-3%) des gesamten Marktvolumens ab --
  Muster-/Relativvolumen-Erkennung basiert auf einem unvollständigen
  Abbild des Marktes, nicht der vollen konsolidierten Tape (SIP).
- Kein WebSocket-Streaming, sondern Polling (siehe LiveMomentumConfig.
  poll_interval_seconds) -- Reaktionszeit auf ein Setup ist durch das
  Poll-Intervall nach unten begrenzt.
- Kein Zustand übersteht einen Neustart: bei einem Absturz mit offener(n)
  Position(en) verliert der Bot jede Kenntnis davon (kein Persistenz-
  Layer) -- nach einem Absturz IMMER manuell im Alpaca-Dashboard prüfen,
  ob noch offene Positionen/Orders existieren.
- Kein Float-Filter (siehe scanner.py/momentum.py).
- Dies ist NUR für Paper-Trading gedacht und wurde als solches entwickelt
  und getestet -- vor echtem Kapitaleinsatz eigenverantwortlich über
  mehrere Handelstage im Paper-Modus beobachten.
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field
from datetime import datetime, time as dt_time, timedelta, timezone
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from alpaca.common.exceptions import APIError
from alpaca.data.enums import Adjustment, DataFeed
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, OrderStatus, TimeInForce
from alpaca.trading.requests import MarketOrderRequest, StopOrderRequest

from tradingbot.broker import _CALENDAR_DAYS_PER_TRADING_DAY, _filter_regular_session
from tradingbot.config import Config
from tradingbot.momentum import (
    BreakoutEvent,
    ExitReason,
    ExitSignal,
    MomentumEngine,
    _build_relative_volume_reference,
    _cum_volume_by_session_minute,
    _daily_trend_ok,
    _relative_volume_at,
)
from tradingbot.scanner import Scanner, ScanCriteria, latest_trading_session

logger = logging.getLogger(__name__)


@dataclass
class LiveMomentumConfig:
    """Strategie-, Risiko- und Timing-Parameter des Live-Bots. Die
    Strategie-Parameter (flagpole_*/pullback_*/reward_risk_ratio/
    extension_multiplier/min_relative_volume) haben dieselbe Bedeutung wie
    bei run_momentum_backtest() -- siehe dort für Details."""

    max_risk_dollars: float = 500.0
    reward_risk_ratio: float = 2.0
    min_relative_volume: float = 2.0
    lookback_days: int = 20
    daily_trend_window: int = 50
    flagpole_min_gain_pct: float = 0.03
    flagpole_max_bars: int = 15
    min_pullback_bars: int = 2
    max_pullback_bars: int = 5
    max_pullback_retrace_pct: float = 0.5
    extension_multiplier: float = 4.0
    trading_window_start: dt_time = field(default_factory=lambda: dt_time(9, 30))
    trading_window_end: dt_time = field(default_factory=lambda: dt_time(11, 30))
    # Obergrenze gleichzeitig OFFENER Positionen -- begrenzt das gesamte
    # Kapitalrisiko unabhängig von max_risk_dollars pro einzelnem Trade.
    max_concurrent_positions: int = 3
    # Obergrenze gleichzeitig BEOBACHTETER Symbole (offene Position oder
    # nicht) -- ohne diese Grenze würde jeder neue Scan-Durchlauf beliebig
    # viele weitere Symbole zur täglichen Balkenabfrage hinzufügen (ein
    # abgefragtes Symbol pro Poll-Zyklus), was die Zykluszeit und
    # API-Last unbegrenzt wachsen ließe.
    max_tracked_symbols: int = 20
    # Anteil des Tages-Start-Eigenkapitals, bei dessen Verlust der Bot für
    # den Rest des Handelstags pausiert (Sample Trading Plan: "Daily Max
    # loss: 10%% of my account").
    daily_max_loss_pct: float = 0.10
    scan_interval_seconds: int = 300
    poll_interval_seconds: int = 60
    order_fill_timeout_seconds: int = 30
    order_poll_interval_seconds: float = 1.0
    # Wie viele Minuten vor Sitzungsende alle offenen Positionen zwangs-
    # weise glattgestellt werden (kein Overnight-Halten, siehe Artikel).
    flatten_minutes_before_close: int = 5
    # Zusätzlich zum Software-Stop eine echte Stop-Order bei Alpaca
    # hinterlegen (Sicherheitsnetz, greift auch bei Absturz/Netzausfall
    # des Bots) -- siehe LiveMomentumBot._ensure_broker_stop.
    broker_stop_orders: bool = True


def _validate_live_config(c: LiveMomentumConfig) -> None:
    if not (math.isfinite(c.max_risk_dollars) and c.max_risk_dollars > 0):
        raise ValueError(f"max_risk_dollars muss eine positive, endliche Zahl sein, war {c.max_risk_dollars}.")
    if not (math.isfinite(c.reward_risk_ratio) and c.reward_risk_ratio > 0):
        raise ValueError(f"reward_risk_ratio muss eine positive, endliche Zahl sein, war {c.reward_risk_ratio}.")
    if not (math.isfinite(c.min_relative_volume) and c.min_relative_volume > 0):
        raise ValueError(f"min_relative_volume muss eine positive, endliche Zahl sein, war {c.min_relative_volume}.")
    if c.lookback_days <= 0:
        raise ValueError(f"lookback_days muss positiv sein, war {c.lookback_days}.")
    if c.daily_trend_window <= 0:
        raise ValueError(f"daily_trend_window muss positiv sein, war {c.daily_trend_window}.")
    if not (math.isfinite(c.flagpole_min_gain_pct) and c.flagpole_min_gain_pct > 0):
        raise ValueError(
            f"flagpole_min_gain_pct muss eine positive, endliche Zahl sein, war {c.flagpole_min_gain_pct}."
        )
    if c.flagpole_max_bars <= 0:
        raise ValueError(f"flagpole_max_bars muss positiv sein, war {c.flagpole_max_bars}.")
    if c.min_pullback_bars <= 0 or c.max_pullback_bars <= 0:
        raise ValueError(
            f"min_pullback_bars/max_pullback_bars müssen positiv sein, "
            f"waren {c.min_pullback_bars}/{c.max_pullback_bars}."
        )
    if c.min_pullback_bars > c.max_pullback_bars:
        raise ValueError(
            f"min_pullback_bars ({c.min_pullback_bars}) darf nicht größer als "
            f"max_pullback_bars ({c.max_pullback_bars}) sein."
        )
    if not 0 <= c.max_pullback_retrace_pct < 1:
        raise ValueError(
            f"max_pullback_retrace_pct muss zwischen 0 (inklusiv) und 1 (exklusiv) liegen, "
            f"war {c.max_pullback_retrace_pct}."
        )
    if not (math.isfinite(c.extension_multiplier) and c.extension_multiplier > 0):
        raise ValueError(
            f"extension_multiplier muss eine positive, endliche Zahl sein, war {c.extension_multiplier}."
        )
    if c.trading_window_start >= c.trading_window_end:
        raise ValueError(
            f"trading_window_start ({c.trading_window_start}) muss vor trading_window_end "
            f"({c.trading_window_end}) liegen."
        )
    if c.max_concurrent_positions <= 0:
        raise ValueError(f"max_concurrent_positions muss positiv sein, war {c.max_concurrent_positions}.")
    if c.max_tracked_symbols <= 0:
        raise ValueError(f"max_tracked_symbols muss positiv sein, war {c.max_tracked_symbols}.")
    if c.max_tracked_symbols < c.max_concurrent_positions:
        raise ValueError(
            f"max_tracked_symbols ({c.max_tracked_symbols}) darf nicht kleiner als "
            f"max_concurrent_positions ({c.max_concurrent_positions}) sein -- sonst könnten nie genug "
            "Symbole gleichzeitig beobachtet werden, um die erlaubten gleichzeitigen Positionen zu füllen."
        )
    if not 0 < c.daily_max_loss_pct < 1:
        raise ValueError(
            f"daily_max_loss_pct muss zwischen 0 (exklusiv) und 1 (exklusiv) liegen, war {c.daily_max_loss_pct}."
        )
    if c.scan_interval_seconds <= 0:
        raise ValueError(f"scan_interval_seconds muss positiv sein, war {c.scan_interval_seconds}.")
    if c.poll_interval_seconds <= 0:
        raise ValueError(f"poll_interval_seconds muss positiv sein, war {c.poll_interval_seconds}.")
    if c.order_fill_timeout_seconds <= 0:
        raise ValueError(f"order_fill_timeout_seconds muss positiv sein, war {c.order_fill_timeout_seconds}.")
    if not (math.isfinite(c.order_poll_interval_seconds) and c.order_poll_interval_seconds > 0):
        raise ValueError(
            f"order_poll_interval_seconds muss eine positive, endliche Zahl sein, "
            f"war {c.order_poll_interval_seconds}."
        )
    if c.flatten_minutes_before_close < 1:
        # 0 wäre zwar rechnerisch zulässig (flatten_cutoff_et == session_close_et),
        # ließe der Zwangs-Verkaufs-Order aber keinerlei Puffer, um vor dem
        # tatsächlichen Handelsschluss noch auszuführen -- praktisch
        # nutzlos bis riskant. Die CLI (main.py, _positive_int) verlangt
        # ohnehin schon >= 1; dieselbe Grenze hier, damit die Bibliothek
        # selbst (z.B. bei direkter LiveMomentumConfig-Nutzung ohne CLI)
        # keine schwächere Garantie gibt als die CLI-Oberfläche.
        raise ValueError(
            f"flatten_minutes_before_close muss mindestens 1 sein, war {c.flatten_minutes_before_close}."
        )


@dataclass
class _PendingExit:
    """Eine Verkaufs-Order, die nicht innerhalb von order_fill_timeout_seconds
    gefüllt wurde -- wird über mehrere run_once()-Zyklen hinweg
    weiterverfolgt (siehe LiveMomentumBot._resolve_pending_exits)."""

    order_id: str
    event: ExitSignal


@dataclass
class _SymbolState:
    engine: MomentumEngine
    rel_vol_reference: np.ndarray
    daily_sma: float | None
    session_open: datetime  # ET-aware
    trend_ok: bool | None = None
    cum_volume: float = 0.0
    last_close: float = 0.0
    last_bar_time: pd.Timestamp | None = None
    pending_exit: _PendingExit | None = None
    # Weitere ExitSignal desselben Balkens, die wegen eines pending_exit
    # nicht sofort verarbeitet werden konnten (siehe _process_new_bars) --
    # werden nachgeholt, sobald pending_exit sich auflöst (siehe
    # _resolve_pending_exits).
    deferred_exits: list[ExitSignal] = field(default_factory=list)
    # True, wenn dieses Symbol über einen Tageswechsel hinweg mit noch
    # offener Position/Order übernommen wurde (siehe
    # LiveMomentumBot._start_new_day) -- rel_vol_reference/daily_sma/
    # session_open gehören dann noch zum VORHERIGEN Tag und dürfen NICHT
    # mehr für neue Muster-Erkennung verwendet werden. Wird entfernt,
    # sobald die Position/Order endgültig abgeschlossen ist (siehe
    # _resolve_pending_exits), statt dauerhaft einen Platz in
    # max_tracked_symbols zu blockieren.
    carried_over: bool = False
    # ID der bei Alpaca hinterlegten Stop-Order (Sicherheitsnetz für die
    # offene Position), None = aktuell keine hinterlegt.
    broker_stop_order_id: str | None = None


def _round_stop_price(price: float) -> float:
    """Alpaca akzeptiert Stop-Preise ab 1 $ nur in Cent-Schritten, darunter
    mit bis zu 4 Nachkommastellen."""
    return round(price, 2) if price >= 1 else round(price, 4)


def _fetch_minute_bars_for_symbol(
    data_client: StockHistoricalDataClient, symbol: str, calendar_days: int, now: datetime
) -> pd.DataFrame:
    """Wie Broker.get_minute_bars, aber für ein beliebiges Symbol (nicht das
    in Config fest hinterlegte) und über den IEX- statt den Standard-/SIP-
    Feed -- IEX ist bei Alpaca ohne Zusatzabo ECHTZEIT (siehe Moduldoc), der
    Standard-Feed ohne Zusatzabo nur verzögert abfragbar. Ein künstlicher
    Verzögerungs-Sicherheitsabstand (siehe broker._DATA_DELAY) ist damit
    unnötig."""
    end = now
    start = end - timedelta(days=calendar_days)
    request = StockBarsRequest(
        symbol_or_symbols=symbol,
        timeframe=TimeFrame.Minute,
        start=start,
        end=end,
        adjustment=Adjustment.ALL,
        feed=DataFeed.IEX,
    )
    bars = data_client.get_stock_bars(request).df
    return _filter_regular_session(bars, symbol)


class LiveMomentumBot:
    """Balkenweiser Live-Trading-Loop: periodisches Scannen nach Kandidaten
    (Scanner) + inkrementelle Bull-Flag/Flat-Top-Erkennung je Symbol
    (MomentumEngine) + echte Order-Platzierung (TradingClient).

    Nutzung: LiveMomentumBot(config, criteria, live_config).run_forever().
    Jeder Aufruf von run_once() ist EIN Zyklus (Kandidaten ggf. neu suchen,
    neue Balken je beobachtetem Symbol abrufen und verarbeiten) -- siehe
    TradingBot.run_forever() für dasselbe Polling-Loop-mit-Fehler-
    Isolierung-Muster.
    """

    def __init__(
        self,
        config: Config,
        criteria: ScanCriteria,
        live_config: LiveMomentumConfig | None = None,
        *,
        scanner: Scanner | None = None,
        trading_client: TradingClient | None = None,
        data_client: StockHistoricalDataClient | None = None,
    ):
        self.config = config
        self.criteria = criteria
        self.live_config = live_config or LiveMomentumConfig()
        _validate_live_config(self.live_config)

        self.scanner = scanner or Scanner(config)
        self.trading_client = trading_client or TradingClient(config.api_key, config.secret_key, paper=config.paper)
        self.data_client = data_client or StockHistoricalDataClient(config.api_key, config.secret_key)

        self._symbols: dict[str, _SymbolState] = {}
        self._trading_day = None
        self._halted = False
        self._flatten_triggered_today = False
        self._day_start_equity: float | None = None
        self._last_scan_time: datetime | None = None

    def _start_new_day(self, session, now: datetime) -> None:
        # Symbole mit noch offener Position oder unbestätigter Order NICHT
        # stillschweigend verwerfen -- unter normalem Betrieb sollte das
        # dank des Flatten-Cutoffs (siehe run_once) nicht mehr vorkommen,
        # aber falls doch (z.B. eine Flatten-Order war beim Sitzungsende
        # noch nicht bestätigt, oder der Bot war über den Tageswechsel
        # hinweg nicht erreichbar), bliebe sonst eine REALE, im Depot
        # liegende Position komplett unbeobachtet zurück.
        carried_over = {
            symbol: state
            for symbol, state in self._symbols.items()
            if state.pending_exit is not None or state.engine.in_position
        }
        if carried_over:
            logger.critical(
                "%d Symbol(e) mit noch offener Position bzw. unbestätigter Verkaufs-Order aus dem "
                "vorherigen Handelstag übernommen (sollte im Normalbetrieb dank Flatten-Cutoff nicht "
                "vorkommen -- ggf. manuell im Alpaca-Dashboard prüfen): %s",
                len(carried_over),
                ", ".join(sorted(carried_over)),
            )
        for symbol, state in carried_over.items():
            state.carried_over = True
            try:
                if state.pending_exit is None and state.engine.in_position:
                    # Echte Position ohne (mehr) verfolgte Order -- kann
                    # nur bei einem verpassten Flatten-Cutoff (z.B.
                    # Bot-Ausfall über Nacht) vorkommen. Sofort zwangsweise
                    # glattstellen, statt sie mit dem session_open/
                    # rel_vol_reference des VORHERIGEN Tages weiterlaufen
                    # zu lassen (_process_new_bars würde sonst einen
                    # völlig falschen minute_index gegen das GESTRIGE
                    # session_open berechnen). Der neue force_exit deckt
                    # die GESAMTE offene Restmenge ab und macht dadurch
                    # auch ein evtl. noch zurückgestelltes Ausstiegssignal
                    # aus dem Vortag gegenstandslos -- deshalb NUR in
                    # diesem Zweig leeren, nicht für Symbole, deren
                    # pending_exit den Tageswechsel übersteht (siehe
                    # unten -- deren deferred_exits bleiben gültig und
                    # nötig).
                    state.deferred_exits = []
                    event = state.engine.force_exit(
                        pd.Timestamp(now), state.last_close, reason=ExitReason.END_OF_DAY
                    )
                    if event is not None:
                        self._submit_exit(symbol, state, event)
            except Exception:
                # Fehlerisoliert wie _resolve_pending_exits(): ein Fehler
                # beim Glattstellen EINES übernommenen Symbols darf nicht
                # verhindern, dass der Tageswechsel für alle ANDEREN
                # Symbole (und die anschließende _resolve_pending_exits()-
                # Prüfung, siehe run_once) trotzdem abgeschlossen wird.
                logger.exception(
                    "Fehler beim Zwangs-Glattstellen von %s beim Tageswechsel, wird im nächsten Zyklus "
                    "erneut versucht.",
                    symbol,
                )

        logger.info("Neuer Handelstag erkannt (%s) -- Bot-Zustand wird zurückgesetzt.", session.date)
        self._trading_day = session.date
        self._symbols = carried_over
        self._halted = False
        self._flatten_triggered_today = False
        self._day_start_equity = None
        self._last_scan_time = None

    def run_once(self, now: datetime | None = None) -> None:
        """Führt einen einzelnen Live-Zyklus aus.

        `now` überschreibt den als "aktuell" behandelten Zeitpunkt
        (Standard: die echte Wanduhrzeit) -- hauptsächlich für Tests
        gedacht, analog zu Scanner.scan()s reference_time-Parameter, damit
        Tageswechsel/Sitzungsgrenzen/Flatten-Cutoff deterministisch
        durchgespielt werden können."""
        now = now if now is not None else datetime.now(timezone.utc)
        session = latest_trading_session(self.trading_client, now)
        if session.date != self._trading_day:
            self._start_new_day(session, now)

        # Ausstehende Verkäufe IMMER zuerst prüfen -- unabhängig von
        # Pause-/Flatten-Zustand UND unabhängig davon, ob `now` gerade
        # innerhalb der Handelssitzung liegt: eine kurz vor Sitzungsende
        # platzierte (z.B. Flatten-)Order darf nicht dadurch unbeobachtet
        # bleiben, dass der nächste Zyklus schon als "außerhalb der
        # Sitzung" gilt und vorher zurückkehrt.
        self._resolve_pending_exits()

        now_et = now.astimezone(ZoneInfo("America/New_York"))
        session_open_et = session.open.replace(tzinfo=ZoneInfo("America/New_York"))
        session_close_et = session.close.replace(tzinfo=ZoneInfo("America/New_York"))

        if now_et < session_open_et:
            logger.debug("Vor Sitzungsbeginn (%s), überspringe Zyklus.", session.date)
            return

        # WICHTIG: dieser Zweig muss VOR jedem "now_et >= session_close_et
        # -> überspringen"-Check kommen (den gab es hier früher separat) --
        # sonst könnte ein grobes --poll-interval-seconds (>=
        # --flatten-minutes-before-close * 60) das gesamte Cutoff-Fenster
        # zwischen zwei Zyklen überspringen (ein Zyklus kurz VOR dem
        # Cutoff, der nächste schon NACH Sitzungsende) und offene
        # Positionen blieben bis zum nächsten Handelstag ungeschlossen
        # liegen -- genau das "kein Overnight-Halten"-Versprechen würde
        # damit gebrochen. flatten_cutoff_et <= session_close_et gilt
        # immer (flatten_minutes_before_close >= 0), das Fenster "nach
        # Sitzungsende" ist also automatisch mit abgedeckt.
        flatten_cutoff_et = session_close_et - timedelta(minutes=self.live_config.flatten_minutes_before_close)
        if now_et >= flatten_cutoff_et:
            if not self._flatten_triggered_today:
                logger.info(
                    "Sitzungsende nähert sich (Cutoff %s ET) -- schließe alle offenen Positionen.",
                    flatten_cutoff_et.time(),
                )
                self._flatten_triggered_today = True
            # Jeden Zyklus erneut aufrufen (idempotent), nicht nur beim
            # ersten Überschreiten des Cutoffs -- sonst bliebe eine zum
            # Cutoff-Zeitpunkt noch offene (pending_exit) Order, die sich
            # erst DANACH in einen Teil-Fill auflöst, für den Rest der
            # Sitzung unbewacht. _flatten_triggered_today steuert nur die
            # einmalige Log-Meldung oben, nicht den eigentlichen
            # Glattstellungsversuch.
            self._flatten_all(now)
            return

        if self._halted:
            # Wie beim Flatten-Cutoff oben: JEDEN Zyklus erneut aufrufen
            # statt nur einmal beim Auslösen -- ein Symbol mit einer zum
            # Halte-Zeitpunkt noch offenen (pending_exit) Order wird von
            # _flatten_all() dort bewusst übersprungen (keine zweite,
            # konkurrierende Verkaufs-Order) -- löst sich diese Order
            # später (via _resolve_pending_exits() oben) in einen
            # Teil-Fill auf, bleibt ohne diesen wiederholten Aufruf die
            # verbleibende Restmenge für den Rest des pausierten
            # Handelstags komplett unbewacht (der Circuit-Breaker soll
            # ausnahmslos ALLE Positionen schließen). _flatten_all() ist
            # idempotent -- bereits geschlossene bzw. noch mit einer
            # eigenen offenen Order wartende Symbole werden dort selbst
            # wieder übersprungen.
            self._flatten_all(now)
            return

        account = self.trading_client.get_account()
        equity = float(account.equity)
        if self._day_start_equity is None:
            self._day_start_equity = equity
            logger.info("Start-Eigenkapital für %s: %.2f", session.date, equity)
        elif self._day_start_equity > 0:
            drawdown_pct = (self._day_start_equity - equity) / self._day_start_equity
            if drawdown_pct >= self.live_config.daily_max_loss_pct:
                logger.critical(
                    "Tages-Maximalverlust erreicht: %.2f%% >= %.2f%% (Start=%.2f, aktuell=%.2f) -- "
                    "schließe alle offenen Positionen und pausiere für den Rest des Handelstags.",
                    drawdown_pct * 100,
                    self.live_config.daily_max_loss_pct * 100,
                    self._day_start_equity,
                    equity,
                )
                self._halted = True
                self._flatten_all(now)
                return

        # Bereits beobachtete Symbole (inkl. offener Positionen) ZUERST
        # verarbeiten, erst DANACH scannen: der Kontextaufbau für neue
        # Kandidaten (mehrere Monate Minutendaten je Symbol) kann viele
        # Sekunden dauern -- Stops/Ausstiege offener Positionen dürfen nicht
        # so lange warten. Neu aufgenommene Symbole werden direkt im
        # Anschluss an den Scan noch im selben Zyklus verarbeitet.
        already_tracked = set(self._symbols)
        self._process_symbols(already_tracked, now)

        if self._last_scan_time is None or (now - self._last_scan_time) >= timedelta(
            seconds=self.live_config.scan_interval_seconds
        ):
            self._rescan(now, session)
            self._process_symbols(set(self._symbols) - already_tracked, now)

    def _process_symbols(self, symbols: set[str], now: datetime) -> None:
        for symbol, state in list(self._symbols.items()):
            if symbol not in symbols:
                continue
            if state.pending_exit is not None or state.deferred_exits:
                # deferred_exits kann hier bereits VOR diesem Aufruf nicht-
                # leer sein, wenn _resolve_pending_exits() (s.o.) einen
                # erneuten Zustellversuch gerade selbst wieder ohne Fill
                # abgeschlossen hat (siehe _submit_exit) -- neue Balken für
                # dieses Symbol erst wieder verarbeiten, sobald es sich
                # auflöst, aus demselben Grund wie in _process_new_bars.
                continue
            try:
                self._process_new_bars(symbol, state, now)
            except Exception:
                logger.exception("Fehler bei der Balkenverarbeitung für %s, überspringe Symbol in diesem Zyklus.", symbol)

    def _rescan(self, now: datetime, session) -> None:
        self._last_scan_time = now
        try:
            candidates = self.scanner.scan(self.criteria, reference_time=now)
        except Exception:
            logger.exception("Scan fehlgeschlagen, versuche es beim nächsten Intervall erneut.")
            return

        for candidate in candidates:
            if len(self._symbols) >= self.live_config.max_tracked_symbols:
                break
            if candidate.symbol in self._symbols:
                continue
            try:
                context = self._build_symbol_context(candidate.symbol, now, session)
            except Exception:
                logger.exception("Kontextaufbau für %s fehlgeschlagen, überspringe Kandidat.", candidate.symbol)
                continue
            if context is None:
                continue
            rel_vol_reference, daily_sma, session_open_et = context

            engine = MomentumEngine(
                flagpole_min_gain_pct=self.live_config.flagpole_min_gain_pct,
                flagpole_max_bars=self.live_config.flagpole_max_bars,
                min_pullback_bars=self.live_config.min_pullback_bars,
                max_pullback_bars=self.live_config.max_pullback_bars,
                max_pullback_retrace_pct=self.live_config.max_pullback_retrace_pct,
                reward_risk_ratio=self.live_config.reward_risk_ratio,
                extension_multiplier=self.live_config.extension_multiplier,
                min_relative_volume=self.live_config.min_relative_volume,
            )
            self._symbols[candidate.symbol] = _SymbolState(
                engine=engine,
                rel_vol_reference=rel_vol_reference,
                daily_sma=daily_sma,
                session_open=session_open_et,
            )
            logger.info(
                "Neues Kandidaten-Symbol aufgenommen: %s (Kurs=%.2f, Tagesgewinn=%.1f%%, Rel.Vol=%.1fx, Quelle=%s)",
                candidate.symbol,
                candidate.price,
                candidate.percent_change,
                candidate.relative_volume,
                ",".join(candidate.sources),
            )

    def _build_symbol_context(
        self, symbol: str, now: datetime, session
    ) -> tuple[np.ndarray, float | None, datetime] | None:
        """Baut die Relativvolumen-Referenzkurve und den Trend-SMA-
        Schwellenwert für `symbol` aus den vorangegangenen Handelstagen
        (die Referenzberechnung ist dieselbe wie im Backtest, siehe
        _build_relative_volume_reference). None, wenn nicht genug
        historische Minutendaten für lookback_days vorliegen -- das Symbol
        wird dann für heute übersprungen (kein Trade ohne Referenzkurve
        möglich, siehe MomentumEngine._process_searching_bar)."""
        # max() mit daily_trend_window: die Referenzkurve braucht nur
        # lookback_days Vortage, der Trend-SMA-Schwellenwert aber
        # daily_trend_window Vortage -- mit den Standardwerten
        # (lookback_days=20, daily_trend_window=50) würde ein Fenster, das
        # nur nach lookback_days bemessen ist, nie genug Historie für den
        # SMA liefern, sodass daily_sma für IMMER None bliebe und der Bot
        # lautlos nie einen Trade platzieren würde (daily_trend_ok bleibt
        # dauerhaft False, siehe _process_new_bars).
        required_days = max(self.live_config.lookback_days, self.live_config.daily_trend_window)
        calendar_days = int(required_days * _CALENDAR_DAYS_PER_TRADING_DAY) + 10
        bars = _fetch_minute_bars_for_symbol(self.data_client, symbol, calendar_days, now)
        if bars.empty:
            return None

        day_keys = pd.Series(bars.index.date, index=bars.index)
        prior_days = sorted(d for d in day_keys.unique() if d < session.date)
        if len(prior_days) < self.live_config.lookback_days:
            return None

        day_bars_by_day = {d: bars.loc[day_keys == d] for d in prior_days}
        recent_days = prior_days[-self.live_config.lookback_days :]
        cum_vols = [_cum_volume_by_session_minute(day_bars_by_day[d]) for d in recent_days]
        max_len = max(len(c) for c in cum_vols)
        rel_vol_reference = _build_relative_volume_reference(cum_vols, max_len)

        daily_sma = None
        if len(prior_days) >= self.live_config.daily_trend_window:
            recent_closes = [
                day_bars_by_day[d]["close"].iloc[-1] for d in prior_days[-self.live_config.daily_trend_window :]
            ]
            daily_sma = float(sum(recent_closes) / len(recent_closes))

        session_open_et = session.open.replace(tzinfo=ZoneInfo("America/New_York"))
        return rel_vol_reference, daily_sma, session_open_et

    def _process_new_bars(self, symbol: str, state: _SymbolState, now: datetime) -> None:
        start = (
            state.last_bar_time + pd.Timedelta(minutes=1)
            if state.last_bar_time is not None
            else pd.Timestamp(state.session_open)
        )
        if start >= now:
            return

        request = StockBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=TimeFrame.Minute,
            start=start,
            end=now,
            adjustment=Adjustment.ALL,
            feed=DataFeed.IEX,
        )
        df = self.data_client.get_stock_bars(request).df
        bars = _filter_regular_session(df, symbol)
        if bars.empty:
            return

        # Aufhol-Schwelle: wird ein Symbol erst Stunden nach Sitzungsbeginn
        # neu aufgenommen (last_bar_time war None) oder war der Bot länger
        # offline, liefert obige Anfrage einen ganzen Rückstand an Bars auf
        # einen Schlag. Ohne diese Schwelle würde die Schleife unten JEDES
        # historische Signal darin sofort als ECHTE Order zum AKTUELLEN statt
        # zum historischen Signal-Kurs ausführen -- das erzeugt genau die Serie
        # dicht getakteter echter Trades, die ein (Wieder-)Start sonst auslöst.
        # Nur Bars innerhalb der Schwelle um `now` dürfen echte Orders
        # auslösen; ältere Bars laufen weiter durch die Engine (für korrekte
        # Muster-/Swing-Tief-Erkennung), werden aber nur simuliert nachvollzogen.
        stale_cutoff = now - timedelta(seconds=max(2 * self.live_config.poll_interval_seconds, 120))

        for bar_time, row in bars.iterrows():
            state.cum_volume += float(row["volume"])
            state.last_close = float(row["close"])
            if state.trend_ok is None:
                state.trend_ok = _daily_trend_ok(state.last_close, state.daily_sma)
            minute_index = int((bar_time - state.session_open).total_seconds() // 60)
            relative_volume = _relative_volume_at(state.cum_volume, state.rel_vol_reference, minute_index)
            in_window = self.live_config.trading_window_start <= bar_time.time() < self.live_config.trading_window_end

            events = state.engine.process_bar(
                bar_time,
                float(row["open"]),
                float(row["high"]),
                float(row["low"]),
                state.last_close,
                float(row["volume"]),
                in_window=in_window,
                relative_volume=relative_volume,
                daily_trend_ok=state.trend_ok,
            )
            state.last_bar_time = bar_time

            for i, event in enumerate(events):
                if isinstance(event, BreakoutEvent):
                    if bar_time < stale_cutoff:
                        # Balken liegt vor der Aufhol-Schwelle -- kein
                        # echter Einstieg für ein längst vergangenes
                        # Signal (siehe stale_cutoff oben); Engine fällt
                        # zurück auf SEARCHING (decline_entry()).
                        state.engine.decline_entry()
                        continue
                    self._handle_breakout(symbol, state, event)
                else:
                    # Ein ExitSignal setzt voraus, dass die Engine
                    # IN_POSITION ist -- und das ist nur nach einem
                    # ECHTEN Fill möglich (record_entry() wird nur in
                    # _handle_breakout() nach einer echten Order-
                    # Ausführung aufgerufen, siehe unten -- niemals für
                    # einen wegen Staleness abgelehnten Einstieg). Ein
                    # Ausstieg für eine echte Position muss deshalb IMMER
                    # real ausgeführt werden, unabhängig vom Alter des
                    # auslösenden Balkens -- sonst bliebe eine echte,
                    # bereits gefüllte Position ungeschützt (der Stop
                    # würde nie auslösen), während die Engine intern
                    # schon "flach" wäre.
                    self._submit_exit(symbol, state, event)
                if state.pending_exit is not None or state.deferred_exits:
                    # Eine noch unbestätigte Verkaufs-Order (pending_exit)
                    # ODER ein bereits zurückgestelltes, aber noch nicht
                    # ausgeführtes Ausstiegssignal (deferred_exits -- z.B.
                    # weil _submit_exit für ein VORIGES Ereignis wiederholt
                    # OHNE jeden Fill scheiterte, siehe dort) blockiert die
                    # Engine für dieses Symbol (record_exit() muss laut
                    # MomentumEngine-Nutzungsvertrag vor dem nächsten
                    # process_bar() erfolgt sein, UND ein deferred_exits-
                    # Eintrag wurde für einen shares_open-Stand berechnet,
                    # der durch einen NEUEN Balken sofort veralten würde) --
                    # weitere Balken dieses Zyklus werden übersprungen, bis
                    # _resolve_pending_exits() im nächsten Zyklus alles
                    # auflöst bzw. nachholt. Ein WEITERES Ereignis desselben
                    # Balkens (z.B. der Extension-Rest nach einem noch
                    # unbestätigten Ziel-Teilverkauf, siehe
                    # MomentumEngine._process_position_bar) darf dabei
                    # NICHT stillschweigend verloren gehen -- zurückstellen
                    # statt verwerfen.
                    remaining_events = events[i + 1 :]
                    if remaining_events:
                        state.deferred_exits.extend(remaining_events)
                        logger.warning(
                            "%d weitere(s) Ausstiegssignal(e) für %s wegen einer noch ausstehenden "
                            "Verkaufs-Order zurückgestellt.",
                            len(remaining_events),
                            symbol,
                        )
                    return

    def _handle_breakout(self, symbol: str, state: _SymbolState, event: BreakoutEvent) -> None:
        # Vollstaendige Muster-Begruendung -- unabhaengig davon, ob der
        # Einstieg unten noch an Kapital-/Positionslimits scheitert, damit
        # auch ein abgelehnter Breakout nachvollziehbar bleibt.
        logger.info(
            "Breakout erkannt: %s (%s) @ %.4f -- Swing-Tief=%.4f, Flaggenstange=+%.1f%%, "
            "Rel.Vol=%s, Pullback-Balken=%d, Stop=%.4f, Risiko/Aktie=%.4f",
            symbol,
            event.pattern,
            event.reference_price,
            event.swing_low_price,
            event.flagpole_gain_pct * 100,
            f"{event.relative_volume:.1f}x" if event.relative_volume is not None else "?",
            event.pullback_bars,
            event.stop_price,
            event.risk_per_share,
        )
        open_positions = sum(1 for s in self._symbols.values() if s.engine.in_position)
        if open_positions >= self.live_config.max_concurrent_positions:
            logger.info(
                "Breakout bei %s (%s) ignoriert: bereits %d/%d gleichzeitige Positionen offen.",
                symbol,
                event.pattern,
                open_positions,
                self.live_config.max_concurrent_positions,
            )
            state.engine.decline_entry()
            return

        account = self.trading_client.get_account()
        cash = max(float(account.cash), 0.0)
        risk_based_shares = int(self.live_config.max_risk_dollars // event.risk_per_share)
        cash_based_shares = int(cash // event.reference_price)
        shares = min(risk_based_shares, cash_based_shares)
        if shares <= 0:
            logger.info(
                "Breakout bei %s (%s) ignoriert: Stückzahl <= 0 (Risiko-Obergrenze=%d, Cash-Obergrenze=%d).",
                symbol,
                event.pattern,
                risk_based_shares,
                cash_based_shares,
            )
            state.engine.decline_entry()
            return

        order = self.trading_client.submit_order(
            MarketOrderRequest(symbol=symbol, qty=shares, side=OrderSide.BUY, time_in_force=TimeInForce.DAY)
        )
        logger.info("Kauf-Order platziert: %s %s Stück (Muster=%s, id=%s)", symbol, shares, event.pattern, order.id)

        try:
            filled = self._wait_for_fill(order.id, self.live_config.order_fill_timeout_seconds)
            if filled is None:
                # Order nach Ablauf des Timeouts weiterhin unentschieden --
                # explizit stornieren. Ein Race ist möglich (Order wird GENAU
                # während des Stornierungsversuchs doch noch gefüllt); Alpacas
                # cancel_order_by_id meldet dafür keinen Fehler, deshalb danach
                # den Order-Status ein letztes Mal als verlässliche Quelle
                # abfragen statt dem Stornierungsversuch blind zu vertrauen.
                try:
                    self.trading_client.cancel_order_by_id(order.id)
                except APIError:
                    pass
                filled = self.trading_client.get_order_by_id(order.id)
        except Exception:
            # Ein unerwarteter Fehler (z.B. transienter APIError) WÄHREND
            # des Wartens/Stornierens lässt den tatsächlichen Order-Status
            # unbekannt zurück -- die Order könnte real gefüllt worden
            # sein. decline_entry() gibt der Engine wenigstens ihren
            # SEARCHING-Zustand zurück (record_entry()/decline_entry()
            # muss laut Nutzungsvertrag ohnehin vor dem nächsten
            # process_bar() erfolgen, sonst bricht dieses Symbol JEDEN
            # weiteren Zyklus mit RuntimeError ab) -- eine tatsächlich
            # gefüllte Order bliebe dadurch aber unbewacht und muss
            # manuell im Alpaca-Dashboard geprüft werden.
            logger.critical(
                "Unerwarteter Fehler beim Warten auf die Kauf-Order für %s (id=%s) -- Order-Status "
                "unbekannt, ggf. manuell im Alpaca-Dashboard prüfen. Verzichte vorerst auf den Einstieg.",
                symbol,
                order.id,
            )
            state.engine.decline_entry()
            return

        # filled_qty ist die verlässliche Quelle dafür, ob (teilweise)
        # etwas gekauft wurde -- NICHT allein der Status: ein Cancel nach
        # Teil-Fill liefert Status=CANCELED, aber filled_qty > 0. Würde nur
        # auf Status=FILLED geprüft, bliebe ein solcher Teil-Fill unverbucht,
        # während die Aktien real im Depot liegen (unbewachte Position ohne
        # Stop/Ziel in der Engine).
        shares_filled = int(float(filled.filled_qty))
        if shares_filled <= 0:
            logger.warning(
                "Kauf-Order für %s endete ohne Fill (Status=%s) -- verzichte auf den Einstieg.",
                symbol,
                filled.status,
            )
            state.engine.decline_entry()
            return

        fill_price = float(filled.filled_avg_price)
        if shares_filled < shares:
            logger.warning(
                "Kauf-Order für %s nur teilweise gefüllt: %s von %s Stück (Status=%s) -- Position wird "
                "mit der tatsächlich gefüllten Stückzahl verwaltet.",
                symbol,
                shares_filled,
                shares,
                filled.status,
            )
        state.engine.record_entry(shares_filled, fill_price, event.time)
        logger.info(
            "Kauf gefüllt: %s %s Stück @ %.2f (Muster=%s, Stop=%.2f, Ziel=%.2f)",
            symbol,
            shares_filled,
            fill_price,
            event.pattern,
            event.stop_price,
            fill_price + self.live_config.reward_risk_ratio * event.risk_per_share,
        )
        self._ensure_broker_stop(symbol, state)

    # --- Broker-seitige Stop-Order (Sicherheitsnetz) ------------------------
    #
    # Der eigentliche Stop bleibt die Software-Logik der MomentumEngine. Die
    # Stop-Order bei Alpaca ist nur ein Netz für den Fall, dass der Bot
    # ausfällt (Absturz, Neustart, Netzausfall). Invarianten:
    # - Vor JEDEM eigenen Verkauf wird sie storniert (_submit_exit), sonst
    #   hält Alpaca die Aktien für sie zurück und der Verkauf wird abgelehnt.
    # - Löst sie selbst aus, wird der Fill in der Engine verbucht
    #   (_check_broker_stop bzw. beim Stornierungsversuch).
    # - Nach jedem Teilverkauf/Stornieren wird sie mit aktueller Stückzahl
    #   und aktuellem Stop-Preis neu angelegt (_ensure_broker_stop).

    def _ensure_broker_stop(self, symbol: str, state: _SymbolState) -> None:
        """Legt eine Stop-Order für die offene Position an, falls noch keine
        existiert. Fehler werden nur geloggt -- der Software-Stop greift
        weiterhin, das Anlegen wird im nächsten Zyklus erneut versucht."""
        if not self.live_config.broker_stop_orders:
            return
        engine = state.engine
        if not engine.in_position or state.pending_exit is not None or state.broker_stop_order_id is not None:
            return
        if engine.shares_open <= 0 or engine.stop_price <= 0:
            return
        stop_price = _round_stop_price(engine.stop_price)
        if state.last_close and state.last_close <= stop_price:
            # Kurs liegt schon am/unter dem Stop -- Alpaca würde eine Sell-
            # Stop-Order über dem Marktpreis ablehnen, und der Software-Stop
            # verkauft ohnehin sofort.
            return
        try:
            order = self.trading_client.submit_order(
                StopOrderRequest(
                    symbol=symbol,
                    qty=engine.shares_open,
                    side=OrderSide.SELL,
                    time_in_force=TimeInForce.DAY,
                    stop_price=stop_price,
                )
            )
        except Exception:
            logger.exception(
                "Stop-Order bei Alpaca für %s konnte nicht angelegt werden -- Software-Stop bleibt aktiv, "
                "neuer Versuch im nächsten Zyklus.",
                symbol,
            )
            return
        state.broker_stop_order_id = order.id
        logger.info(
            "Stop-Order bei Alpaca hinterlegt: %s %s Stück @ Stop %.4f (id=%s)",
            symbol,
            engine.shares_open,
            stop_price,
            order.id,
        )

    def _record_broker_stop_fill(self, symbol: str, state: _SymbolState, order) -> None:
        """Verbucht einen (Teil-)Fill der Broker-Stop-Order in der Engine."""
        filled_qty = int(float(order.filled_qty or 0))
        if filled_qty <= 0 or not state.engine.in_position:
            return
        filled_qty = min(filled_qty, state.engine.shares_open)
        fill_price = float(order.filled_avg_price)
        fully_closed = state.engine.record_exit(filled_qty, fill_price)
        logger.warning(
            "Stop-Order bei Alpaca für %s ausgelöst: %s Stück @ %.4f verkauft%s",
            symbol,
            filled_qty,
            fill_price,
            " -- Position vollständig geschlossen" if fully_closed else "",
        )
        if fully_closed:
            self._clear_stale_deferred_exits(symbol, state)

    def _check_broker_stop(self, symbol: str, state: _SymbolState) -> None:
        """Prüft, ob die Broker-Stop-Order inzwischen einen Endzustand
        erreicht hat (ausgelöst/verfallen), und verbucht ggf. den Fill."""
        if state.broker_stop_order_id is None:
            return
        order = self.trading_client.get_order_by_id(state.broker_stop_order_id)
        if order.status not in (OrderStatus.FILLED, OrderStatus.CANCELED, OrderStatus.REJECTED, OrderStatus.EXPIRED):
            return
        state.broker_stop_order_id = None
        self._record_broker_stop_fill(symbol, state, order)

    def _cancel_broker_stop(self, symbol: str, state: _SymbolState) -> bool:
        """Storniert die Broker-Stop-Order vor einem eigenen Verkauf und
        verbucht einen evtl. schon erfolgten Fill (Race: Stop löst genau
        jetzt aus). False, wenn die Stornierung nicht bestätigt werden
        konnte -- dann darf NICHT verkauft werden (Aktien noch reserviert,
        Gefahr eines doppelten Verkaufs)."""
        order_id = state.broker_stop_order_id
        if order_id is None:
            return True
        try:
            self.trading_client.cancel_order_by_id(order_id)
        except APIError:
            pass  # z.B. bereits gefüllt/verfallen -- der Status unten ist maßgeblich
        order = self._wait_for_fill(order_id, self.live_config.order_fill_timeout_seconds)
        if order is None:
            logger.critical(
                "Stop-Order für %s (id=%s) konnte nicht rechtzeitig storniert werden -- Verkauf wird "
                "zurückgestellt und im nächsten Zyklus erneut versucht.",
                symbol,
                order_id,
            )
            return False
        state.broker_stop_order_id = None
        self._record_broker_stop_fill(symbol, state, order)
        return True

    def _clear_stale_deferred_exits(self, symbol: str, state: _SymbolState) -> None:
        """Wird aufgerufen, sobald eine Position vollständig geschlossen
        wurde (fully_closed=True von record_exit()). Ein zu diesem
        Zeitpunkt noch nicht-leeres deferred_exits kann nur ein Rest aus
        einem VORHERIGEN, unabhängig konsolidierten Vollausstieg sein
        (z.B. Circuit-Breaker/Flatten-Cutoff via _flatten_all, der die
        GESAMTE damals offene Restmenge inkl. eines noch zurückgestellten
        Geschwister-Ereignisses in einem Rutsch abgedeckt hat) -- ohne
        dieses Leeren würde ein solcher Eintrag als "noch zu verkaufen"
        stehen bleiben, obwohl real nichts mehr offen ist, und (a) über
        die pending_exit/deferred_exits-Wächter in _process_new_bars/
        run_once dieses Symbol DAUERHAFT von jeder weiteren Balken-
        verarbeitung blockieren (der Drain in _resolve_pending_exit_for_symbol
        setzt `engine.in_position` voraus, das nach einem Vollausstieg
        für immer False bleibt), und (b) bei einer künftigen neuen
        Position fälschlich als noch ausstehend gelten."""
        if state.deferred_exits:
            logger.warning(
                "%d zurückgestellte(s) Ausstiegssignal(e) für %s nach vollständigem Ausstieg verworfen "
                "(bereits durch einen konsolidierten Vollausstieg abgedeckt).",
                len(state.deferred_exits),
                symbol,
            )
            state.deferred_exits = []

    def _reconcile_terminal_exit_order(
        self, symbol: str, state: _SymbolState, order, event: ExitSignal
    ) -> ExitSignal | None:
        """`order` ist in einem Endzustand OHNE (vollständigen) Fill
        (CANCELED/REJECTED/EXPIRED) und wird sich nicht mehr ändern. Ein
        etwaiger TEIL-Fill VOR dem Abbruch (filled_qty > 0 trotz nicht-
        FILLED-Status -- Alpaca storniert nur die Restmenge, der bereits
        gefüllte Teil bleibt bestehen) muss HIER in die Engine verbucht
        werden, bevor der Aufrufer über die verbleibende Stückzahl neu
        entscheidet -- sonst würde ein solcher Teil-Fill nie in
        record_exit() ankommen (reale Aktien verkauft, aber nirgends
        gebucht). Gibt ein ExitSignal für die tatsächlich verbleibende
        Stückzahl zurück (None, wenn dadurch nichts mehr offen ist -- die
        Position also bereits vollständig geschlossen wurde).

        WICHTIG: die verbleibende Stückzahl ist `event.shares - filled_qty`
        -- NICHT `state.engine.shares_open`. `event` kann nur EIN TEIL der
        Position abdecken (z.B. die TARGET-Hälfte, während ein
        Geschwister-Ereignis wie EXTENSION für den Rest bereits separat in
        state.deferred_exits wartet, siehe _process_new_bars) -- shares_open
        würde in diesem Fall auch die Stückzahl des Geschwister-Ereignisses
        mit beanspruchen und zu einer doppelt beauftragten Verkaufsmenge
        führen, sobald auch das Geschwister-Ereignis verarbeitet wird."""
        filled_qty = int(float(order.filled_qty))
        if filled_qty <= 0:
            return event

        fill_price = float(order.filled_avg_price)
        fully_closed = state.engine.record_exit(filled_qty, fill_price)
        logger.critical(
            "Verkaufs-Order für %s (Status=%s) vor Abbruch teilweise gefüllt: %s Stück @ %.2f nachträglich verbucht.",
            symbol,
            order.status,
            filled_qty,
            fill_price,
        )
        if fully_closed:
            self._clear_stale_deferred_exits(symbol, state)
            return None
        remaining_for_event = event.shares - filled_qty
        if remaining_for_event <= 0:
            return None
        return ExitSignal(event.reason, event.time, event.reference_price, remaining_for_event)

    def _submit_exit(self, symbol: str, state: _SymbolState, event: ExitSignal, _retries_left: int = 1) -> None:
        # Broker-Stop zuerst stornieren (hält sonst die Aktien zurück) --
        # hat er inzwischen selbst ausgelöst, ist dieser Verkauf ganz oder
        # teilweise schon erledigt.
        if not self._cancel_broker_stop(symbol, state):
            state.deferred_exits.append(event)
            return
        if not state.engine.in_position:
            return
        if event.shares > state.engine.shares_open:
            event = ExitSignal(event.reason, event.time, event.reference_price, state.engine.shares_open)
        try:
            self._submit_exit_order(symbol, state, event, _retries_left)
        finally:
            # Nach Teilverkauf (Breakeven-Stop) bzw. fehlgeschlagenem Verkauf
            # das Sicherheitsnetz für die verbleibende Menge neu anlegen.
            self._ensure_broker_stop(symbol, state)

    def _submit_exit_order(
        self, symbol: str, state: _SymbolState, event: ExitSignal, _retries_left: int = 1
    ) -> None:
        order = self.trading_client.submit_order(
            MarketOrderRequest(symbol=symbol, qty=event.shares, side=OrderSide.SELL, time_in_force=TimeInForce.DAY)
        )
        # Einstieg/Stop/Ziel HIER loggen (vor record_exit() weiter unten,
        # das die Position ggf. schließt und diese Werte damit ungültig
        # macht) -- macht den Ausstiegsgrund nachvollziehbar (z.B. "Kurs
        # 11.25 < Stop 11.30" statt nur "Grund=STOP" ohne Kontext).
        logger.info(
            "Verkaufs-Order platziert: %s %s Stück (Grund=%s, Kurs=%.4f, Einstieg=%.4f, Stop=%.4f, "
            "Ziel=%.4f, id=%s)",
            symbol,
            event.shares,
            event.reason,
            event.reference_price,
            state.engine.entry_price,
            state.engine.stop_price,
            state.engine.target_price,
            order.id,
        )

        try:
            filled = self._wait_for_fill(order.id, self.live_config.order_fill_timeout_seconds)
        except Exception:
            # Anders als bei einer Kauf-Order NICHT decline_entry()-artig
            # aufgeben: die Order könnte real (teilweise) gefüllt sein und
            # es existiert kein "kein Verkauf"-Fallback, der reales Risiko
            # sicher wegdiskutieren dürfte. state.pending_exit auf die
            # bereits platzierte Order setzen -- _resolve_pending_exits()
            # prüft ihren tatsächlichen Status im nächsten Zyklus erneut
            # (derselbe verlässliche Mechanismus wie beim regulären
            # Timeout-Fall unten).
            logger.critical(
                "Unerwarteter Fehler beim Warten auf die Verkaufs-Order für %s (id=%s) -- wird als "
                "ausstehend markiert und im nächsten Zyklus erneut geprüft. ACHTUNG: ggf. manuell im "
                "Alpaca-Dashboard prüfen.",
                symbol,
                order.id,
            )
            state.pending_exit = _PendingExit(order_id=order.id, event=event)
            return

        if filled is not None and filled.status == OrderStatus.FILLED:
            filled_qty = int(float(filled.filled_qty))
            fill_price = float(filled.filled_avg_price)
            fully_closed = state.engine.record_exit(filled_qty, fill_price)
            logger.info(
                "Verkauf gefüllt: %s %s Stück @ %.2f (Grund=%s)%s",
                symbol,
                filled_qty,
                fill_price,
                event.reason,
                " -- Position vollständig geschlossen"
                if fully_closed
                else " -- Teilverkauf, Stop auf Einstieg (Breakeven) nachgezogen",
            )
            if fully_closed:
                self._clear_stale_deferred_exits(symbol, state)
            return

        if filled is None:
            # Order nach Ablauf des Timeouts weiterhin in einem NICHT
            # terminalen Zustand -- wird über _resolve_pending_exits() in
            # den folgenden Zyklen weiterverfolgt (dort auch die
            # Endzustands-/Teil-Fill-Behandlung, siehe
            # _reconcile_terminal_exit_order).
            logger.critical(
                "Verkaufs-Order für %s (%s Stück, Grund=%s, id=%s) nicht innerhalb von %ds gefüllt -- "
                "wird in den folgenden Zyklen weiterverfolgt. ACHTUNG: reale Position und Bot-Zustand können "
                "bis zur Bestätigung auseinanderlaufen, ggf. manuell im Alpaca-Dashboard prüfen.",
                symbol,
                event.shares,
                event.reason,
                order.id,
                self.live_config.order_fill_timeout_seconds,
            )
            state.pending_exit = _PendingExit(order_id=order.id, event=event)
            return

        # Endzustand OHNE (vollständigen) Fill (CANCELED/REJECTED/EXPIRED)
        # -- anders als bei einer Kauf-Order wird NIE stillschweigend
        # aufgegeben: die Engine hält die Position weiterhin für offen,
        # reales Risiko bliebe sonst unbewacht.
        retry_event = self._reconcile_terminal_exit_order(symbol, state, filled, event)
        if retry_event is None:
            return

        if _retries_left > 0:
            logger.critical(
                "Verkaufs-Order für %s endete ohne vollständigen Fill (Status=%s) -- sende sofort eine neue "
                "Verkaufs-Order für die verbleibenden %s Stück.",
                symbol,
                filled.status,
                retry_event.shares,
            )
            self._submit_exit(symbol, state, retry_event, _retries_left=_retries_left - 1)
            return

        logger.critical(
            "Verkaufs-Order für %s endete wiederholt ohne vollständigen Fill (letzter Status=%s) -- wird "
            "zurückgestellt und im nächsten Zyklus erneut versucht.",
            symbol,
            filled.status,
        )
        state.deferred_exits.append(retry_event)

    def _resolve_pending_exits(self) -> None:
        """Wird bei JEDEM run_once()-Zyklus zuerst aufgerufen: pollt jede
        noch offene Verkaufs-Order (pending_exit) und holt danach evtl.
        zurückgestellte Ausstiegssignale nach (deferred_exits -- siehe
        _process_new_bars für den Fall "zwei Ausstiegssignale auf
        demselben Balken" und _submit_exit für den Fall "wiederholt kein
        vollständiger Fill"), sofern kein neuer pending_exit entstanden
        ist und die Position noch offen ist.

        Pro Symbol einzeln fehlerisoliert (wie die Balkenverarbeitung in
        run_once) -- ein Fehler bei EINEM Symbol (z.B. ein transienter
        APIError bei get_order_by_id) darf nicht verhindern, dass alle
        ANDEREN Symbole mit eigenen, ggf. zeitkritischen ausstehenden
        Verkaufs-Orders in demselben Zyklus noch geprüft werden."""
        for symbol, state in list(self._symbols.items()):
            try:
                self._resolve_pending_exit_for_symbol(symbol, state)
            except Exception:
                logger.exception(
                    "Fehler beim Auflösen der ausstehenden Verkaufs-Order/zurückgestellter Ausstiegssignale "
                    "für %s, versuche es im nächsten Zyklus erneut.",
                    symbol,
                )

    def _resolve_pending_exit_for_symbol(self, symbol: str, state: _SymbolState) -> None:
        self._check_broker_stop(symbol, state)
        pending = state.pending_exit
        if pending is not None:
            order = self.trading_client.get_order_by_id(pending.order_id)
            if order.status == OrderStatus.FILLED:
                filled_qty = int(float(order.filled_qty))
                fill_price = float(order.filled_avg_price)
                fully_closed = state.engine.record_exit(filled_qty, fill_price)
                logger.info(
                    "Zuvor ausstehende Verkaufs-Order für %s nun gefüllt: %s Stück @ %.2f%s",
                    symbol,
                    filled_qty,
                    fill_price,
                    " -- Position vollständig geschlossen" if fully_closed else " -- Teilverkauf",
                )
                state.pending_exit = None
                if fully_closed:
                    self._clear_stale_deferred_exits(symbol, state)
            elif order.status in (OrderStatus.CANCELED, OrderStatus.REJECTED, OrderStatus.EXPIRED):
                state.pending_exit = None
                retry_event = self._reconcile_terminal_exit_order(symbol, state, order, pending.event)
                if retry_event is not None:
                    logger.critical(
                        "Ausstehende Verkaufs-Order für %s endete ohne vollständigen Fill (Status=%s) -- "
                        "sende sofort eine neue Verkaufs-Order für die verbleibenden %s Stück.",
                        symbol,
                        order.status,
                        retry_event.shares,
                    )
                    self._submit_exit(symbol, state, retry_event)
            else:
                logger.info("Verkaufs-Order für %s weiterhin offen (Status=%s), warte weiter.", symbol, order.status)

        if state.pending_exit is None and state.deferred_exits and state.engine.in_position:
            next_event = state.deferred_exits.pop(0)
            self._submit_exit(symbol, state, next_event)

        # Sicherheitsnetz nach Auflösung einer ausstehenden Order (bzw. nach
        # verfallener/ausgelöster Stop-Order) wiederherstellen.
        self._ensure_broker_stop(symbol, state)

        if state.carried_over and state.pending_exit is None and not state.engine.in_position:
            # Von einem vorherigen Handelstag übernommenes Symbol ist jetzt
            # endgültig abgeschlossen (siehe _start_new_day) -- dessen
            # rel_vol_reference/session_open gehören zum VORHERIGEN Tag und
            # dürfen für neue Muster-Erkennung nicht weiterverwendet
            # werden. Komplett aus der Beobachtung entfernen, statt
            # dauerhaft einen Platz in max_tracked_symbols zu blockieren --
            # ein künftiger Scan kann es bei Bedarf mit frischem
            # Tageskontext neu aufnehmen.
            del self._symbols[symbol]
            logger.info("%s (vom Vortag übernommen) endgültig abgeschlossen -- nicht mehr beobachtet.", symbol)

    def _flatten_all(self, now: datetime) -> None:
        """Wird sowohl einmalig beim Auslösen (Circuit-Breaker/Flatten-
        Cutoff) als auch wiederholt bei JEDEM folgenden run_once()-Zyklus
        aufgerufen, solange gepaust bzw. der Cutoff überschritten ist --
        idempotent (bereits geschlossene oder mit einer eigenen offenen
        Order wartende Symbole werden unten übersprungen), damit eine zum
        Auslöse-Zeitpunkt noch offene Order, die sich SPÄTER in einen
        Teil-Fill auflöst, nicht auf ewig unbewacht bleibt. Pro Symbol
        fehlerisoliert wie die übrigen Order-Verwaltungs-Loops (siehe
        _resolve_pending_exits/_start_new_day)."""
        reason = ExitReason.CIRCUIT_BREAKER if self._halted else ExitReason.END_OF_DAY
        for symbol, state in list(self._symbols.items()):
            if state.pending_exit is not None or not state.engine.in_position:
                continue
            try:
                event = state.engine.force_exit(pd.Timestamp(now), state.last_close, reason=reason)
                if event is not None:
                    self._submit_exit(symbol, state, event)
            except Exception:
                logger.exception(
                    "Fehler beim Zwangs-Glattstellen von %s, wird im nächsten Zyklus erneut versucht.", symbol
                )

    def _wait_for_fill(self, order_id: str, timeout_seconds: float):
        """Pollt eine Order, bis sie einen Endzustand erreicht (gefüllt/
        storniert/abgelehnt/abgelaufen), oder das Timeout verstreicht. Gibt
        im Timeout-Fall None zurück (Order evtl. noch offen) -- der
        Aufrufer entscheidet, wie er reagiert (siehe _handle_breakout/
        _submit_exit)."""
        terminal = {OrderStatus.FILLED, OrderStatus.CANCELED, OrderStatus.REJECTED, OrderStatus.EXPIRED}
        deadline = time.monotonic() + timeout_seconds
        while True:
            order = self.trading_client.get_order_by_id(order_id)
            if order.status in terminal:
                return order
            if time.monotonic() >= deadline:
                return None
            time.sleep(self.live_config.order_poll_interval_seconds)

    def run_forever(self) -> None:
        logger.info(
            "Starte Live-Momentum-Bot (paper=%s, scan_intervall=%ds, poll_intervall=%ds, "
            "max_gleichzeitige_positionen=%d, max_beobachtete_symbole=%d, tages_max_verlust=%.1f%%)",
            self.config.paper,
            self.live_config.scan_interval_seconds,
            self.live_config.poll_interval_seconds,
            self.live_config.max_concurrent_positions,
            self.live_config.max_tracked_symbols,
            self.live_config.daily_max_loss_pct * 100,
        )
        try:
            while True:
                try:
                    self.run_once()
                except Exception:
                    logger.exception("Fehler im Live-Momentum-Zyklus, versuche es beim nächsten Intervall erneut.")
                time.sleep(self.live_config.poll_interval_seconds)
        except KeyboardInterrupt:
            logger.info("Live-Momentum-Bot wird beendet (KeyboardInterrupt).")

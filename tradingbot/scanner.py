"""Marktweiter Aktien-Scanner nach den in den Warrior-Trading-Dokumenten
("Stock Selection"-PDF, "Sample Trading Plan"-PDF) beschriebenen Kriterien:

1. Aktie bereits deutlich im Plus (Standard: >= 10%)
2. Kursspanne (Standard: $1-$20, Ross Camerons genereller Bereich)
3. Hohes relatives Volumen (Standard: >= 5x 30-Tage-Durchschnitt)
4. Optional: aktueller News-Katalysator

Float (< 20 Mio. Aktien im "heißen", < 10 Mio. im "kalten" Markt laut
Sample Trading Plan) ist NICHT umgesetzt -- Alpacas Marktdaten-API liefert
keinen Aktien-Float (siehe README).

WICHTIG: Alpacas Screener-API (get_market_movers/get_most_actives) liefert
ausschließlich den AKTUELLEN Marktzustand, keinen historischen Datumsparameter
-- dieser Scanner ist deshalb ein reines LIVE-Diagnosewerkzeug (keine
Orders, nur Marktdaten-Abfragen) und lässt sich NICHT in den historischen
momentum-backtest einbauen. Er eignet sich, um manuell einen Kandidaten zu
finden, den man dann per `momentum-backtest --symbol X` historisch prüft.
"""

from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
from alpaca.data.enums import Adjustment
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.historical.news import NewsClient
from alpaca.data.historical.screener import ScreenerClient
from alpaca.data.requests import (
    MarketMoversRequest,
    MostActivesBy,
    MostActivesRequest,
    NewsRequest,
    StockBarsRequest,
)
from alpaca.data.timeframe import TimeFrame
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import GetCalendarRequest

from tradingbot.broker import _CALENDAR_DAYS_PER_TRADING_DAY, _DATA_DELAY
from tradingbot.config import Config

# Obergrenze für die News-Annotation: Alpacas API begrenzt `limit` auf die
# GESAMTZAHL der Artikel über ALLE angefragten Symbole hinweg (nicht pro
# Symbol) -- 200 statt eines knappen Standardwerts, damit an einem
# nachrichtenreichen Tag nicht die Artikel gerade der interessantesten
# Kandidaten aus dem Ergebnis fallen. Bleibt trotzdem eine Näherung, keine
# erschöpfende Abfrage.
_NEWS_FETCH_LIMIT = 200

logger = logging.getLogger(__name__)

# Keine Stammaktien: Warrants, Units (SPAC-Bündel), Rights -- erkennbar nur
# am Asset-Namen, nicht zuverlässig am Symbol (z.B. endet auch "SNOW" auf W).
_NON_COMMON_NAME = re.compile(r"\b(warrants?|units?|rights?)\b", re.IGNORECASE)


def latest_trading_session(trading_client: TradingClient, now: datetime):
    """Der letzte Handelstag, dessen Tages-Bar bei `now` bereits
    existieren SOLLTE, laut Alpacas echtem Handelskalender -- im
    Gegensatz zu einer geratenen Kalendertage-Toleranz behandelt das
    Wochenenden UND Feiertage (auch mehrtägige, z.B. Frühschluss vor
    Feiertagen) exakt, ohne dass diese Logik bei jedem neuen Feiertag
    erneut bricht.

    `GetCalendarRequest(end=...)` filtert nur nach Kalendertag, nicht
    Uhrzeit -- ist `now` VOR der Marktöffnung eines regulären
    Handelstags (z.B. Montag 7 Uhr vorbörslich), liefert die Anfrage
    trotzdem diesen Tag als letzten Eintrag, obwohl dessen Bar noch gar
    nicht existiert (der letzte tatsächlich verfügbare Bar ist der vom
    Vorhandelstag, z.B. Freitag). In diesem Fall auf den vorletzten
    Kalendereintrag zurückfallen.
    """
    end_date = now.astimezone(ZoneInfo("America/New_York")).date()
    request = GetCalendarRequest(start=end_date - timedelta(days=10), end=end_date)
    calendar = trading_client.get_calendar(request)
    if not calendar:
        raise ValueError(
            f"Alpacas Handelskalender lieferte keine Handelstage im Zeitraum bis {end_date} "
            "zurück -- unerwartet, evtl. API-Problem."
        )
    session = calendar[-1]
    if session.date == end_date:
        now_et = now.astimezone(ZoneInfo("America/New_York"))
        session_open = session.open.replace(tzinfo=ZoneInfo("America/New_York"))
        if now_et < session_open and len(calendar) >= 2:
            session = calendar[-2]
    return session


def elapsed_session_fraction(now: datetime, session) -> float:
    """Anteil der Handelssitzung `session` (inkl. evtl. Frühschluss),
    der bei `now` bereits verstrichen ist -- 1.0, wenn `now` nicht
    innerhalb dieser Sitzung liegt (z.B. `session` ist ein bereits
    abgeschlossener, vergangener Handelstag: dessen Tagesvolumen ist
    dann bereits vollständig, keine Projektion nötig/sinnvoll). Dank
    `latest_trading_session` ist `now` hier praktisch nie VOR `session.open`
    (dann wäre bereits die vorherige Sitzung gewählt worden) -- der
    Fall wird trotzdem defensiv wie "Sitzung noch nicht begonnen"
    behandelt (Projektions-Untergrenze), nicht wie "abgeschlossen"."""
    now_et = now.astimezone(ZoneInfo("America/New_York"))
    session_open = session.open.replace(tzinfo=ZoneInfo("America/New_York"))
    session_close = session.close.replace(tzinfo=ZoneInfo("America/New_York"))
    if now_et.date() != session.date or now_et >= session_close:
        return 1.0
    if now_et <= session_open:
        return 0.01
    elapsed_minutes = (now_et - session_open).total_seconds() / 60
    total_minutes = (session_close - session_open).total_seconds() / 60
    # Untergrenze verhindert eine Division durch (fast) 0 kurz nach
    # Handelsbeginn, die das projizierte Volumen sonst ins Absurde
    # treiben würde.
    return max(elapsed_minutes / total_minutes, 0.01)


@dataclass
class ScanCandidate:
    symbol: str
    price: float
    percent_change: float
    relative_volume: float
    has_recent_news: bool | None  # None = nicht geprüft (require_news=False)
    sources: list[str] = field(default_factory=list)  # "mover" und/oder "active"


@dataclass
class ScanCriteria:
    min_price: float = 1.0
    max_price: float = 20.0
    min_percent_change: float = 10.0
    min_relative_volume: float = 5.0
    relative_volume_lookback_days: int = 30
    require_news: bool = False
    news_lookback_hours: int = 24
    top_movers: int = 30
    top_actives: int = 30


def _validate_criteria(c: ScanCriteria) -> None:
    if not (0 < c.min_price < c.max_price):
        raise ValueError(f"min_price ({c.min_price}) muss positiv und kleiner als max_price ({c.max_price}) sein.")
    if not math.isfinite(c.min_percent_change):
        raise ValueError(f"min_percent_change muss endlich sein, war {c.min_percent_change}.")
    if c.min_relative_volume <= 0:
        raise ValueError(f"min_relative_volume muss positiv sein, war {c.min_relative_volume}.")
    if c.relative_volume_lookback_days <= 0:
        raise ValueError(f"relative_volume_lookback_days muss positiv sein, war {c.relative_volume_lookback_days}.")
    if c.news_lookback_hours <= 0:
        raise ValueError(f"news_lookback_hours muss positiv sein, war {c.news_lookback_hours}.")
    if c.top_movers <= 0 or c.top_actives <= 0:
        raise ValueError(f"top_movers/top_actives müssen positiv sein, waren {c.top_movers}/{c.top_actives}.")


class Scanner:
    def __init__(self, config: Config):
        self.config = config
        self.screener_client = ScreenerClient(config.api_key, config.secret_key)
        self.data_client = StockHistoricalDataClient(config.api_key, config.secret_key)
        self.news_client = NewsClient(config.api_key, config.secret_key)
        # Nur für den Handelskalender genutzt (letzter Handelstag,
        # tatsächliche Sitzungszeiten inkl. Frühschluss-Tage) -- kein
        # Order-Zugriff nötig, Konto-Endpoint wird hier nie aufgerufen.
        self.trading_client = TradingClient(config.api_key, config.secret_key, paper=config.paper)
        self._is_common_stock_cache: dict[str, bool] = {}

    def _is_common_stock(self, symbol: str) -> bool:
        """False für Warrants/Units/Rights (z.B. CRMLW) und nicht handelbare
        Assets. Bei einem API-Fehler True (Kandidat lieber behalten als den
        Scan scheitern lassen)."""
        cached = self._is_common_stock_cache.get(symbol)
        if cached is not None:
            return cached
        try:
            asset = self.trading_client.get_asset(symbol)
        except Exception:
            logger.warning("Asset-Info für %s nicht abrufbar -- Kandidat wird behalten.", symbol)
            return True
        result = bool(asset.tradable) and not _NON_COMMON_NAME.search(asset.name or "")
        self._is_common_stock_cache[symbol] = result
        return result

    def scan(self, criteria: ScanCriteria, reference_time: datetime | None = None) -> list[ScanCandidate]:
        """Führt einen einzelnen Scan des AKTUELLEN Marktzustands aus (siehe
        Modul-Docstring: kein historisches Datum wählbar).

        `reference_time` überschreibt den Zeitpunkt, zu dem die Marktdaten
        als "aktuell" gelten (Standard: der spätere von `movers.last_updated`/
        `actives.last_updated`, direkt aus den Screener-Antworten -- NICHT die
        rohe Wanduhrzeit `datetime.now()`, die an Wochenenden/Feiertagen
        mehrere Kalendertage von den letzten tatsächlichen Handelsdaten
        abweichen kann). Hauptsächlich für Tests gedacht, um Sitzungsanteil-/
        Volumensprojektions- und Aktualitätsprüfung deterministisch zu
        machen -- welcher Kalendertag der zuletzt abgeschlossene bzw.
        laufende Handelstag ist, wird über Alpacas echten Handelskalender
        bestimmt (siehe `latest_trading_session`), nicht geraten.
        """
        _validate_criteria(criteria)

        movers = self.screener_client.get_market_movers(MarketMoversRequest(top=criteria.top_movers))
        actives = self.screener_client.get_most_actives(
            MostActivesRequest(top=criteria.top_actives, by=MostActivesBy.VOLUME)
        )
        # Der spätere der beiden last_updated-Werte: movers/actives sind
        # zwei unabhängige, nacheinander ausgeführte Aufrufe mit je eigenem
        # Zeitstempel -- der spätere ist die aktuellere bekannte Information
        # über den Marktzustand.
        now = reference_time if reference_time is not None else max(movers.last_updated, actives.last_updated)
        session = latest_trading_session(self.trading_client, now)
        last_trading_day_et = session.date
        session_fraction = elapsed_session_fraction(now, session)

        gainer_by_symbol = {g.symbol: g for g in movers.gainers}
        active_symbols = {a.symbol for a in actives.most_actives}
        all_symbols = sorted(set(gainer_by_symbol) | active_symbols)
        if not all_symbols:
            return []

        bars_by_symbol = self._fetch_daily_bars(all_symbols, criteria.relative_volume_lookback_days, now)

        candidates: list[ScanCandidate] = []
        for symbol in all_symbols:
            bars = bars_by_symbol.get(symbol)
            # Mindestens 2 Bars nötig: der letzte ("heute") plus mindestens
            # ein Vortag als Referenz für Vortagesschluss/Volumendurchschnitt.
            if bars is None or len(bars) < 2:
                continue
            # Auf das angeforderte Lookback-Fenster deckeln -- der Abruf holt
            # bewusst etwas mehr Kalendertage als Puffer (Wochenenden/
            # Feiertage), ohne dieses .tail() würde der Durchschnitt über
            # MEHR Tage laufen, als relative_volume_lookback_days verspricht.
            bars = bars.tail(criteria.relative_volume_lookback_days + 1)

            # Der letzte Bar muss dem laut Handelskalender jüngsten
            # (abgeschlossenen oder laufenden) Handelstag entsprechen --
            # sonst könnte ein pausiertes/kaum gehandeltes Symbol mit
            # veralteten Daten fälschlich als aktueller Kandidat durchgehen.
            # Toleranz von 1 Tag nur für die UTC-Mitternacht-vs-NY-
            # Zeitzonenverschiebung der Bar-Zeitstempel selbst, nicht für
            # Wochenenden/Feiertage (die deckt bereits der Handelskalender ab).
            last_bar_date_et = bars.index[-1].tz_convert("America/New_York").date()
            if (last_trading_day_et - last_bar_date_et).days > 1:
                continue

            today = bars.iloc[-1]
            history = bars.iloc[:-1]

            gainer = gainer_by_symbol.get(symbol)
            # Für Movers den LIVE-Preis aus derselben Screener-Antwort
            # nehmen, aus der auch percent_change stammt -- der separat
            # gebündelt abgerufene Tages-Bar kann bis zu _DATA_DELAY alt
            # oder unvollständig sein und mit dem Live-Preis auseinander-
            # laufen. Für reine "Most Actives"-Kandidaten (kein Live-Preis
            # in der Antwort) bleibt der Bar-Schlusskurs die einzige Quelle.
            price = float(gainer.price) if gainer is not None else float(today["close"])

            if gainer is not None:
                percent_change = float(gainer.percent_change)
            else:
                prev_close = float(history["close"].iloc[-1])
                if prev_close <= 0:
                    continue
                percent_change = (price / prev_close - 1) * 100

            if not (criteria.min_price <= price <= criteria.max_price):
                continue
            if percent_change < criteria.min_percent_change:
                continue

            avg_volume = float(history["volume"].mean())
            if not (avg_volume > 0):
                continue
            # Während der Sitzung ist das bisherige Tagesvolumen nur ein
            # TEIL eines vollen Handelstags -- ein direkter Vergleich mit
            # dem (vollständigen) historischen Tagesdurchschnitt würde das
            # relative Volumen systematisch unterschätzen, gerade vormittags
            # wenn ein Scanner am nützlichsten wäre. Projektion auf ein
            # Tagesäquivalent über den seit Handelsbeginn verstrichenen
            # Anteil der Sitzung (grobe, aber übliche Heuristik).
            projected_volume = float(today["volume"]) / session_fraction
            relative_volume = projected_volume / avg_volume
            if relative_volume < criteria.min_relative_volume:
                continue

            # Erst NACH den billigen Filtern (nur verbliebene Kandidaten
            # kosten einen API-Aufruf, pro Symbol gecacht).
            if not self._is_common_stock(symbol):
                continue

            sources = []
            if gainer is not None:
                sources.append("mover")
            if symbol in active_symbols:
                sources.append("active")

            candidates.append(
                ScanCandidate(
                    symbol=symbol,
                    price=price,
                    percent_change=percent_change,
                    relative_volume=relative_volume,
                    has_recent_news=None,
                    sources=sources,
                )
            )

        if candidates:
            self._annotate_news(candidates, criteria.news_lookback_hours, now)
            if criteria.require_news:
                candidates = [c for c in candidates if c.has_recent_news]

        candidates.sort(key=lambda c: c.percent_change, reverse=True)
        return candidates

    def _fetch_daily_bars(self, symbols: list[str], lookback_days: int, now: datetime) -> dict[str, pd.DataFrame]:
        # `now` statt roher Wanduhrzeit: hält das Bar-Fenster konsistent mit
        # dem überall sonst in scan() verwendeten Referenzzeitpunkt (siehe
        # `reference_time`-Parameter von scan()) -- sonst könnte bei einer
        # abweichenden/eingefrorenen Referenz (Tests, oder ein veralteter
        # Screener-Snapshot) ein anderer Kalenderausschnitt abgefragt werden,
        # als last_trading_day_et/session_fraction zugrunde liegt.
        end = now - _DATA_DELAY
        start = end - timedelta(days=int(lookback_days * _CALENDAR_DAYS_PER_TRADING_DAY) + 10)
        request = StockBarsRequest(
            symbol_or_symbols=symbols,
            timeframe=TimeFrame.Day,
            start=start,
            end=end,
            # Ohne Split-/Dividenden-Adjustierung würde z.B. ein Reverse-
            # Split bei genau den niedrigpreisigen, volatilen Small-Caps,
            # die dieser Scanner sucht, Kurs UND Volumen künstlich verzerren
            # (siehe broker.py für denselben Kompromiss).
            adjustment=Adjustment.ALL,
        )
        df = self.data_client.get_stock_bars(request).df
        if df.empty:
            return {}
        result = {}
        available_symbols = df.index.get_level_values("symbol").unique()
        for symbol in symbols:
            if symbol in available_symbols:
                result[symbol] = df.xs(symbol, level="symbol")
        return result

    def _annotate_news(self, candidates: list[ScanCandidate], lookback_hours: int, now: datetime) -> None:
        symbols = [c.symbol for c in candidates]
        start = now - timedelta(hours=lookback_hours)
        request = NewsRequest(symbols=",".join(symbols), start=start, limit=_NEWS_FETCH_LIMIT)
        try:
            news = self.news_client.get_news(request)
        except Exception:
            # News-Katalysator ist laut Artikel/PDF eine BEVORZUGTE, keine
            # zwingende Bedingung (außer bei require_news=True) -- ein
            # Fehler bei der News-Abfrage soll den ganzen Scan nicht zum
            # Absturz bringen, nur die Katalysator-Markierung ausbleiben.
            for c in candidates:
                c.has_recent_news = None
            return

        # Alpacas News-API liefert vereinzelt Symbole mit führendem/
        # nachgestelltem Leerzeichen (empirisch beobachtet) -- ohne strip()
        # würde der Abgleich lautlos fehlschlagen.
        symbols_with_news = {
            s.strip() for item in news.data.get("news", []) for s in item.symbols
        }
        for c in candidates:
            c.has_recent_news = c.symbol in symbols_with_news

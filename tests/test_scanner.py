from __future__ import annotations

from types import SimpleNamespace

from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from tradingbot.config import Config
from tradingbot.scanner import Scanner, ScanCriteria

# Fester Zeitpunkt NACH US-Handelsschluss (19:00 EDT) -- macht
# _elapsed_session_fraction deterministisch 1.0 (keine Tagesvolumen-
# Projektion verzerrt die erwarteten relative_volume-Werte in den Tests)
# und dient zugleich als Anker für "heute" in den Test-Bar-Daten.
TEST_NOW = datetime(2024, 3, 15, 23, 0, 0, tzinfo=timezone.utc)


class FakeCalendarEntry:
    """Bildet nur die drei von Scanner._latest_session()/
    _elapsed_session_fraction() genutzten Felder von Alpacas echtem
    Kalender-Eintrag nach (date, open, close als naive Zeiten in ET)."""

    def __init__(self, session_date, open_time=time(9, 30), close_time=time(16, 0)):
        self.date = session_date
        self.open = datetime.combine(session_date, open_time)
        self.close = datetime.combine(session_date, close_time)


def make_calendar_entry_for(reference: datetime) -> FakeCalendarEntry:
    """Baut einen Handelskalender-Eintrag für den ET-Kalendertag von
    `reference`, mit regulären Handelszeiten (9:30-16:00)."""
    session_date = reference.astimezone(ZoneInfo("America/New_York")).date()
    return FakeCalendarEntry(session_date)


def make_config() -> Config:
    return Config(
        api_key="dummy",
        secret_key="dummy",
        paper=True,
        symbol="TEST",
        qty=1.0,
        short_window=2,
        long_window=4,
        poll_interval_seconds=60,
        stop_loss_pct=0.08,
        take_profit_pct=0.0,
        risk_per_trade_pct=0.0,
        trend_window=0,
        rsi_window=0,
    )


def make_scanner(asset_names: dict[str, str] | None = None) -> Scanner:
    scanner = Scanner(make_config())
    names = asset_names or {}
    scanner.trading_client.get_asset = lambda symbol: SimpleNamespace(
        tradable=True, name=names.get(symbol, f"{symbol} Inc. Common Stock")
    )
    return scanner


class FakeMover:
    def __init__(self, symbol, percent_change, price=0.0, change=0.0):
        self.symbol = symbol
        self.percent_change = percent_change
        self.price = price
        self.change = change


class FakeActiveStock:
    def __init__(self, symbol, volume=0.0, trade_count=0.0):
        self.symbol = symbol
        self.volume = volume
        self.trade_count = trade_count


class FakeMoversResponse:
    def __init__(self, gainers, last_updated=TEST_NOW):
        self.gainers = gainers
        self.losers = []
        self.last_updated = last_updated


class FakeActivesResponse:
    def __init__(self, most_actives, last_updated=TEST_NOW):
        self.most_actives = most_actives
        self.last_updated = last_updated


class FakeNewsItem:
    def __init__(self, symbols):
        self.symbols = symbols


class FakeNewsSet:
    def __init__(self, items):
        self.data = {"news": items}


class FakeBarSet:
    def __init__(self, df: pd.DataFrame):
        self.df = df


def make_multi_symbol_bars(data: dict[str, list[tuple[float, float]]]) -> pd.DataFrame:
    """data: {symbol: [(close, volume), ...]} -- letzter Eintrag ist "heute"
    (siehe TEST_NOW, mit dem scanner.scan() in den Tests aufgerufen wird --
    Scanner.scan() prüft den letzten Bar auf Aktualität, siehe Freshness-
    Check)."""
    if not data:
        return pd.DataFrame(columns=["close", "volume"])
    frames = []
    today = pd.Timestamp(TEST_NOW).normalize()
    for symbol, rows in data.items():
        timestamps = pd.date_range(end=today, periods=len(rows), freq="D", tz="UTC")
        index = pd.MultiIndex.from_arrays([[symbol] * len(rows), timestamps], names=["symbol", "timestamp"])
        closes = [r[0] for r in rows]
        volumes = [r[1] for r in rows]
        frames.append(pd.DataFrame({"close": closes, "volume": volumes}, index=index))
    return pd.concat(frames)


def install_fakes(scanner, gainers, actives, bars_df, news_items=None, calendar_reference=TEST_NOW):
    scanner.screener_client.get_market_movers = lambda request: FakeMoversResponse(gainers)
    scanner.screener_client.get_most_actives = lambda request: FakeActivesResponse(actives)
    scanner.data_client.get_stock_bars = lambda request: FakeBarSet(bars_df)
    scanner.trading_client.get_calendar = lambda request: [make_calendar_entry_for(calendar_reference)]
    if news_items is not None:
        scanner.news_client.get_news = lambda request: FakeNewsSet(news_items)
    else:
        scanner.news_client.get_news = lambda request: FakeNewsSet([])


def test_filters_by_price_percent_change_and_relative_volume():
    scanner = make_scanner()
    gainers = [
        FakeMover("GOOD", percent_change=25.0, price=5.0),  # passt alle Kriterien
        FakeMover("TOO_CHEAP", percent_change=25.0, price=0.5),  # unter min_price
        FakeMover("TOO_EXPENSIVE", percent_change=25.0, price=50.0),  # über max_price
        FakeMover("TOO_LOW_GAIN", percent_change=3.0, price=5.0),  # unter min_percent_change
    ]
    bars = make_multi_symbol_bars({
        "GOOD": [(4.0, 100_000)] * 30 + [(5.0, 600_000)],  # rel.vol = 6x
        "TOO_CHEAP": [(0.4, 100_000)] * 30 + [(0.5, 600_000)],
        "TOO_EXPENSIVE": [(40.0, 100_000)] * 30 + [(50.0, 600_000)],
        "TOO_LOW_GAIN": [(4.0, 100_000)] * 30 + [(4.1, 600_000)],
    })
    install_fakes(scanner, gainers, [], bars)

    candidates = scanner.scan(ScanCriteria(min_price=1.0, max_price=20.0, min_percent_change=10.0, min_relative_volume=5.0), reference_time=TEST_NOW)

    assert [c.symbol for c in candidates] == ["GOOD"]
    assert candidates[0].price == 5.0
    assert candidates[0].percent_change == 25.0
    assert candidates[0].relative_volume == pytest.approx(6.0)
    assert candidates[0].sources == ["mover"]


def test_relative_volume_below_threshold_is_excluded():
    scanner = make_scanner()
    gainers = [FakeMover("LOWVOL", percent_change=20.0, price=5.0)]
    bars = make_multi_symbol_bars({
        "LOWVOL": [(4.0, 100_000)] * 30 + [(5.0, 150_000)],  # rel.vol = 1.5x
    })
    install_fakes(scanner, gainers, [], bars)

    candidates = scanner.scan(ScanCriteria(min_relative_volume=5.0), reference_time=TEST_NOW)

    assert candidates == []


def test_symbol_only_in_actives_computes_percent_change_from_prior_close():
    scanner = make_scanner()
    actives = [FakeActiveStock("ACTONLY", volume=600_000)]
    bars = make_multi_symbol_bars({
        "ACTONLY": [(4.0, 100_000)] * 30 + [(5.0, 600_000)],  # +25% ggü. Vortag, rel.vol=6x
    })
    install_fakes(scanner, [], actives, bars)

    candidates = scanner.scan(ScanCriteria(min_price=1.0, max_price=20.0, min_percent_change=10.0, min_relative_volume=5.0), reference_time=TEST_NOW)

    assert len(candidates) == 1
    assert candidates[0].symbol == "ACTONLY"
    assert candidates[0].percent_change == pytest.approx(25.0)
    assert candidates[0].sources == ["active"]


def test_symbol_present_in_both_movers_and_actives_has_both_sources():
    scanner = make_scanner()
    gainers = [FakeMover("BOTH", percent_change=20.0, price=5.0)]
    actives = [FakeActiveStock("BOTH", volume=600_000)]
    bars = make_multi_symbol_bars({"BOTH": [(4.0, 100_000)] * 30 + [(5.0, 600_000)]})
    install_fakes(scanner, gainers, actives, bars)

    candidates = scanner.scan(ScanCriteria(min_relative_volume=5.0), reference_time=TEST_NOW)

    assert len(candidates) == 1
    assert set(candidates[0].sources) == {"mover", "active"}


def test_missing_bars_for_a_symbol_skips_it_without_crashing():
    """Regressionstest: taucht ein Kandidat im Movers/Actives-Ergebnis auf,
    aber der gebündelte Bar-Abruf liefert für dieses Symbol keine Daten
    (z.B. gerade delisted), darf der Scan nicht abstürzen -- das Symbol
    wird einfach übersprungen."""
    scanner = make_scanner()
    gainers = [
        FakeMover("HASBARS", percent_change=20.0, price=5.0),
        FakeMover("NOBARS", percent_change=20.0, price=5.0),
    ]
    bars = make_multi_symbol_bars({"HASBARS": [(4.0, 100_000)] * 30 + [(5.0, 600_000)]})
    install_fakes(scanner, gainers, [], bars)

    candidates = scanner.scan(ScanCriteria(min_relative_volume=5.0), reference_time=TEST_NOW)

    assert [c.symbol for c in candidates] == ["HASBARS"]


def test_insufficient_bar_history_skips_symbol():
    """Nur ein einziger Bar (kein Vortag) reicht nicht für Vortagesschluss/
    Volumendurchschnitt -- muss übersprungen werden, nicht crashen."""
    scanner = make_scanner()
    gainers = [FakeMover("ONEBAR", percent_change=20.0, price=5.0)]
    bars = make_multi_symbol_bars({"ONEBAR": [(5.0, 600_000)]})
    install_fakes(scanner, gainers, [], bars)

    candidates = scanner.scan(ScanCriteria(), reference_time=TEST_NOW)

    assert candidates == []


def test_zero_average_volume_skips_symbol_without_crashing():
    """Regressionstest: eine Historie mit 0 Volumen (Datenlücke) würde bei
    der Division für das relative Volumen einen ZeroDivisionError bzw.
    inf/NaN erzeugen -- muss stattdessen übersprungen werden."""
    scanner = make_scanner()
    gainers = [FakeMover("ZEROVOL", percent_change=20.0, price=5.0)]
    bars = make_multi_symbol_bars({"ZEROVOL": [(4.0, 0.0)] * 30 + [(5.0, 600_000)]})
    install_fakes(scanner, gainers, [], bars)

    candidates = scanner.scan(ScanCriteria(), reference_time=TEST_NOW)

    assert candidates == []


def test_require_news_filters_out_candidates_without_recent_news():
    scanner = make_scanner()
    gainers = [
        FakeMover("HASNEWS", percent_change=20.0, price=5.0),
        FakeMover("NONEWS", percent_change=20.0, price=5.0),
    ]
    bars = make_multi_symbol_bars({
        "HASNEWS": [(4.0, 100_000)] * 30 + [(5.0, 600_000)],
        "NONEWS": [(4.0, 100_000)] * 30 + [(5.0, 600_000)],
    })
    # Alpacas News-API liefert vereinzelt Symbole mit Whitespace -- muss
    # trotzdem korrekt zugeordnet werden (strip()).
    news_items = [FakeNewsItem([" HASNEWS "])]
    install_fakes(scanner, gainers, [], bars, news_items=news_items)

    candidates = scanner.scan(ScanCriteria(min_relative_volume=5.0, require_news=True), reference_time=TEST_NOW)

    assert [c.symbol for c in candidates] == ["HASNEWS"]
    assert candidates[0].has_recent_news is True


def test_require_news_false_keeps_candidates_but_annotates_news_flag():
    scanner = make_scanner()
    gainers = [FakeMover("SYM", percent_change=20.0, price=5.0)]
    bars = make_multi_symbol_bars({"SYM": [(4.0, 100_000)] * 30 + [(5.0, 600_000)]})
    install_fakes(scanner, gainers, [], bars, news_items=[])

    candidates = scanner.scan(ScanCriteria(min_relative_volume=5.0, require_news=False), reference_time=TEST_NOW)

    assert len(candidates) == 1
    assert candidates[0].has_recent_news is False


def test_news_fetch_failure_does_not_crash_scan(monkeypatch):
    """Ein News-Katalysator ist laut Strategie bevorzugt, nicht zwingend
    (außer bei require_news=True) -- ein Fehler bei der News-Abfrage darf
    den gesamten Scan nicht zum Absturz bringen."""
    scanner = make_scanner()
    gainers = [FakeMover("SYM", percent_change=20.0, price=5.0)]
    bars = make_multi_symbol_bars({"SYM": [(4.0, 100_000)] * 30 + [(5.0, 600_000)]})
    scanner.screener_client.get_market_movers = lambda request: FakeMoversResponse(gainers)
    scanner.screener_client.get_most_actives = lambda request: FakeActivesResponse([])
    scanner.data_client.get_stock_bars = lambda request: FakeBarSet(bars)
    scanner.trading_client.get_calendar = lambda request: [make_calendar_entry_for(TEST_NOW)]

    def raise_error(request):
        raise ConnectionError("news API down")

    scanner.news_client.get_news = raise_error

    candidates = scanner.scan(ScanCriteria(min_relative_volume=5.0, require_news=False), reference_time=TEST_NOW)
    assert len(candidates) == 1
    assert candidates[0].has_recent_news is None

    # Bei require_news=True filtert ein None (unbekannt) konservativ heraus.
    candidates_required = scanner.scan(ScanCriteria(min_relative_volume=5.0, require_news=True), reference_time=TEST_NOW)
    assert candidates_required == []


def test_candidates_sorted_by_percent_change_descending():
    scanner = make_scanner()
    gainers = [
        FakeMover("LOW", percent_change=15.0, price=5.0),
        FakeMover("HIGH", percent_change=40.0, price=5.0),
        FakeMover("MID", percent_change=25.0, price=5.0),
    ]
    bars = make_multi_symbol_bars({
        "LOW": [(4.0, 100_000)] * 30 + [(5.0, 600_000)],
        "HIGH": [(4.0, 100_000)] * 30 + [(5.0, 600_000)],
        "MID": [(4.0, 100_000)] * 30 + [(5.0, 600_000)],
    })
    install_fakes(scanner, gainers, [], bars)

    candidates = scanner.scan(ScanCriteria(min_relative_volume=5.0), reference_time=TEST_NOW)

    assert [c.symbol for c in candidates] == ["HIGH", "MID", "LOW"]


def test_no_candidates_when_movers_and_actives_both_empty():
    scanner = make_scanner()
    install_fakes(scanner, [], [], make_multi_symbol_bars({}))

    candidates = scanner.scan(ScanCriteria(), reference_time=TEST_NOW)

    assert candidates == []


@pytest.mark.parametrize(
    "override,message_substr",
    [
        ({"min_price": 20.0, "max_price": 10.0}, "min_price"),
        ({"min_price": 0.0}, "min_price"),
        ({"min_percent_change": float("inf")}, "min_percent_change"),
        ({"min_relative_volume": 0.0}, "min_relative_volume"),
        ({"relative_volume_lookback_days": 0}, "relative_volume_lookback_days"),
        ({"news_lookback_hours": 0}, "news_lookback_hours"),
        ({"top_movers": 0}, "top_movers"),
        ({"top_actives": 0}, "top_actives"),
    ],
)
def test_rejects_invalid_criteria(override, message_substr):
    scanner = make_scanner()
    install_fakes(scanner, [], [], make_multi_symbol_bars({}))
    with pytest.raises(ValueError, match=message_substr):
        scanner.scan(ScanCriteria(**override), reference_time=TEST_NOW)


def test_stale_bar_data_is_excluded():
    """Regressionstest: ein Symbol, dessen letzter verfügbarer Bar mehr als
    einen Tag alt ist (z.B. pausiert/kaum gehandelt, aber noch mit
    zwischengespeicherten Scanner-Daten gelistet), darf nicht als aktueller
    Kandidat durchgehen. Bewusst der EINZIGE Kandidat im Test (keine
    anderen Symbole zum Vergleich) -- die Aktualitätsprüfung muss sich auf
    den echten Handelskalender stützen können, nicht auf einen Konsens
    unter mehreren Kandidaten."""
    scanner = make_scanner()
    gainers = [FakeMover("STALE", percent_change=20.0, price=5.0)]
    # Baut Bars, die vor 5 Tagen enden statt "heute" (TEST_NOW).
    stale_today = pd.Timestamp(TEST_NOW).normalize() - pd.Timedelta(days=5)
    timestamps = pd.date_range(end=stale_today, periods=31, freq="D", tz="UTC")
    index = pd.MultiIndex.from_arrays([["STALE"] * 31, timestamps], names=["symbol", "timestamp"])
    bars = pd.DataFrame({"close": [4.0] * 30 + [5.0], "volume": [100_000] * 30 + [600_000]}, index=index)
    install_fakes(scanner, gainers, [], bars)

    candidates = scanner.scan(ScanCriteria(min_relative_volume=5.0), reference_time=TEST_NOW)

    assert candidates == []


def test_monday_premarket_accepts_fridays_bar_as_current():
    """Regressionstest (Review-Runde 3, live reproduziert): Montag VOR
    Handelsbeginn (07:00 ET) ist Montag zwar laut Kalender ein gültiger
    Handelstag (die reale Alpaca-API liefert ihn als letzten Kalender-
    Eintrag bis end=Montag, unabhängig von der Uhrzeit -- GetCalendarRequest
    filtert nur nach Datum, nicht Uhrzeit), aber Montags eigener Bar
    existiert noch nicht (Markt noch nicht geöffnet). Der letzte
    tatsächlich verfügbare Bar ist der von Freitag -- das ist der korrekte,
    aktuelle Stand, keine veralteten Daten. _latest_session muss das
    erkennen und auf den VORHERIGEN Kalendereintrag (Freitag) zurückfallen,
    statt Montag zu verwenden (was faelschlich eine 3-Tage-Luecke zum
    Freitags-Bar ergäbe und den Kandidaten verwerfen würde)."""
    scanner = make_scanner()
    monday_premarket = datetime(2024, 3, 18, 11, 0, 0, tzinfo=timezone.utc)  # 07:00 EDT
    friday = datetime(2024, 3, 15, 23, 0, 0, tzinfo=timezone.utc)
    gainers = [FakeMover("MONDAY", percent_change=25.0, price=5.0)]
    bars = make_multi_symbol_bars({"MONDAY": [(4.0, 100_000)] * 30 + [(5.0, 600_000)]})  # endet Freitag (TEST_NOW)
    scanner.screener_client.get_market_movers = lambda request: FakeMoversResponse(
        gainers, last_updated=monday_premarket
    )
    scanner.screener_client.get_most_actives = lambda request: FakeActivesResponse([], last_updated=monday_premarket)
    scanner.data_client.get_stock_bars = lambda request: FakeBarSet(bars)
    # Realistische Kalender-Antwort wie die echte API: Montag (2024-03-18)
    # IST als letzter Eintrag enthalten (gültiger Handelstag, unabhängig
    # von der Uhrzeit), Freitag als vorletzter -- _latest_session muss
    # selbst erkennen, dass Montags Sitzung um 07:00 ET noch nicht
    # begonnen hat, und auf Freitag zurückfallen.
    scanner.trading_client.get_calendar = lambda request: [
        make_calendar_entry_for(friday),
        make_calendar_entry_for(monday_premarket),
    ]
    scanner.news_client.get_news = lambda request: FakeNewsSet([])

    candidates = scanner.scan(ScanCriteria(min_relative_volume=5.0), reference_time=monday_premarket)

    assert [c.symbol for c in candidates] == ["MONDAY"]


def test_monday_after_open_uses_mondays_own_session_not_fridays():
    """Gegenstück zu test_monday_premarket_accepts_fridays_bar_as_current:
    NACH Handelsbeginn (10:00 ET) ist Montags Sitzung bereits aktiv, kein
    Rückfall auf Freitag nötig -- ein Symbol, dessen Bar-Daten immer noch
    nur bis Freitag reichen (3 Tage hinter Montag zurück), muss jetzt
    korrekt als veraltet erkannt und ausgeschlossen werden."""
    scanner = make_scanner()
    monday_mid_session = datetime(2024, 3, 18, 14, 0, 0, tzinfo=timezone.utc)  # 10:00 EDT
    friday = datetime(2024, 3, 15, 23, 0, 0, tzinfo=timezone.utc)
    gainers = [FakeMover("STALEMON", percent_change=25.0, price=5.0)]
    bars = make_multi_symbol_bars({"STALEMON": [(4.0, 100_000)] * 30 + [(5.0, 600_000)]})  # endet Freitag
    scanner.screener_client.get_market_movers = lambda request: FakeMoversResponse(
        gainers, last_updated=monday_mid_session
    )
    scanner.screener_client.get_most_actives = lambda request: FakeActivesResponse(
        [], last_updated=monday_mid_session
    )
    scanner.data_client.get_stock_bars = lambda request: FakeBarSet(bars)
    scanner.trading_client.get_calendar = lambda request: [
        make_calendar_entry_for(friday),
        make_calendar_entry_for(monday_mid_session),
    ]
    scanner.news_client.get_news = lambda request: FakeNewsSet([])

    candidates = scanner.scan(ScanCriteria(min_relative_volume=5.0), reference_time=monday_mid_session)

    assert candidates == []


def test_default_reference_time_uses_movers_last_updated_not_wall_clock():
    """Regressionstest (live gefunden): ohne explizites reference_time muss
    movers.last_updated als Referenzzeitpunkt dienen, NICHT die rohe
    Wanduhrzeit datetime.now() -- an einem Sonntag liegen die aktuellsten
    Marktdaten vom Freitag zwangsläufig 2 Kalendertage zurück; mit
    datetime.now() als Referenz hätte die Freshness-Prüfung jeden
    Kandidaten fälschlich als 'veraltet' verworfen, obwohl movers/actives
    exakt diesen (letzten Handelstags-)Stand widerspiegeln."""
    scanner = make_scanner()
    # last_updated simuliert Freitagabend, "jetzt" waere technisch Sonntag
    # -- aber Scanner.scan() bekommt hier gar keine Wanduhrzeit uebergeben,
    # sie darf also gar nicht in die Freshness-Pruefung einfliessen.
    friday_evening = datetime(2024, 3, 15, 23, 0, 0, tzinfo=timezone.utc)
    gainers = [FakeMover("FRIDAY", percent_change=20.0, price=5.0)]
    bars = make_multi_symbol_bars({"FRIDAY": [(4.0, 100_000)] * 30 + [(5.0, 600_000)]})
    scanner.screener_client.get_market_movers = lambda request: FakeMoversResponse(
        gainers, last_updated=friday_evening
    )
    scanner.screener_client.get_most_actives = lambda request: FakeActivesResponse([], last_updated=friday_evening)
    scanner.data_client.get_stock_bars = lambda request: FakeBarSet(bars)
    scanner.trading_client.get_calendar = lambda request: [make_calendar_entry_for(friday_evening)]
    scanner.news_client.get_news = lambda request: FakeNewsSet([])

    # Kein reference_time-Override -- muss auf movers.last_updated zurueckfallen.
    candidates = scanner.scan(ScanCriteria(min_relative_volume=5.0))

    assert len(candidates) == 1
    assert candidates[0].symbol == "FRIDAY"


def test_relative_volume_projects_partial_session_volume():
    """Regressionstest: während der laufenden Sitzung ist das bisherige
    Tagesvolumen nur ein Teil eines vollen Tages -- ein naiver Vergleich
    mit dem vollständigen historischen Tagesdurchschnitt würde das relative
    Volumen systematisch unterschätzen. 30 Minuten nach Handelsbeginn
    (10:00 EDT) sollte das Volumen auf einen vollen Handelstag hochgerechnet
    werden: projected = volume / (30/390) = volume * 13."""
    scanner = make_scanner()
    gainers = [FakeMover("MIDSESSION", percent_change=20.0, price=5.0)]
    bars = make_multi_symbol_bars({
        "MIDSESSION": [(4.0, 100_000)] * 30 + [(5.0, 600_000)],
    })
    install_fakes(scanner, gainers, [], bars)
    mid_session = datetime(2024, 3, 15, 14, 0, 0, tzinfo=timezone.utc)  # 10:00 EDT

    candidates = scanner.scan(ScanCriteria(min_relative_volume=5.0), reference_time=mid_session)

    assert len(candidates) == 1
    # projected_volume = 600_000 / (30/390) = 7_800_000; rel.vol = 78.0
    assert candidates[0].relative_volume == pytest.approx(78.0)


def test_lookback_window_caps_history_to_requested_days():
    """Regressionstest: der Bar-Abruf holt bewusst mehr Kalendertage als
    Puffer (Wochenenden/Feiertage) -- der Durchschnitt darf trotzdem nur
    über GENAU relative_volume_lookback_days Vortage laufen, nicht über
    alle zurückgelieferten Bars. Ohne die .tail()-Kappung würden 10 alte
    Tage mit riesigem Volumen (1 Mio.) den Durchschnitt so weit nach oben
    ziehen, dass der Kandidat die Schwelle NICHT erreicht."""
    scanner = make_scanner()
    gainers = [FakeMover("CAPPED", percent_change=20.0, price=5.0)]
    # 10 alte Tage (hohes Volumen) + 30 aktuelle Tage (normales Volumen) + heute.
    old_days = [(4.0, 1_000_000)] * 10
    recent_days = [(4.0, 100_000)] * 30
    today_row = [(5.0, 600_000)]
    bars = make_multi_symbol_bars({"CAPPED": old_days + recent_days + today_row})
    install_fakes(scanner, gainers, [], bars)

    candidates = scanner.scan(
        ScanCriteria(min_relative_volume=5.0, relative_volume_lookback_days=30), reference_time=TEST_NOW
    )

    assert len(candidates) == 1
    # Mit korrekter Kappung auf die letzten 30 Vortage: avg=100_000, rel.vol=6.0.
    # Ohne Kappung (Bug): avg=(10*1_000_000+30*100_000)/40=325_000, rel.vol≈1.85 -> gefiltert.
    assert candidates[0].relative_volume == pytest.approx(6.0)


def test_price_for_mover_uses_live_screener_price_not_stale_bar_close():
    """Regressionstest: für Movers muss der LIVE-Preis aus der
    Screener-Antwort verwendet werden, nicht der separat gebündelt
    abgerufene (potenziell veraltete) Tages-Bar-Schlusskurs -- beide
    Quellen können auseinanderlaufen."""
    scanner = make_scanner()
    # Live-Preis (12.00) liegt klar unter max_price=20, der Bar-Schlusskurs
    # (25.00, veraltet) läge klar DARÜBER -- mit dem alten Verhalten (Preis
    # aus dem Bar) würde der Kandidat fälschlich durch den Preisfilter
    # fallen.
    gainers = [FakeMover("LIVEPRICE", percent_change=20.0, price=12.0)]
    bars = make_multi_symbol_bars({
        "LIVEPRICE": [(20.0, 100_000)] * 30 + [(25.0, 600_000)],
    })
    install_fakes(scanner, gainers, [], bars)

    candidates = scanner.scan(
        ScanCriteria(min_price=1.0, max_price=20.0, min_relative_volume=5.0), reference_time=TEST_NOW
    )

    assert len(candidates) == 1
    assert candidates[0].price == 12.0


def test_fetches_bars_with_split_adjustment(monkeypatch):
    """Regressionstest: ohne Split-/Dividenden-Adjustierung würde z.B. ein
    Reverse-Split bei genau den niedrigpreisigen Small-Caps, die dieser
    Scanner sucht, Kurs UND Volumen künstlich verzerren."""
    from alpaca.data.enums import Adjustment

    scanner = make_scanner()
    gainers = [FakeMover("SYM", percent_change=20.0, price=5.0)]
    bars = make_multi_symbol_bars({"SYM": [(4.0, 100_000)] * 30 + [(5.0, 600_000)]})

    captured_requests = []

    def fake_get_stock_bars(request):
        captured_requests.append(request)
        return FakeBarSet(bars)

    scanner.screener_client.get_market_movers = lambda request: FakeMoversResponse(gainers)
    scanner.screener_client.get_most_actives = lambda request: FakeActivesResponse([])
    scanner.data_client.get_stock_bars = fake_get_stock_bars
    scanner.trading_client.get_calendar = lambda request: [make_calendar_entry_for(TEST_NOW)]
    scanner.news_client.get_news = lambda request: FakeNewsSet([])

    scanner.scan(ScanCriteria(min_relative_volume=5.0), reference_time=TEST_NOW)

    assert len(captured_requests) == 1
    assert captured_requests[0].adjustment == Adjustment.ALL


def test_news_request_uses_a_generous_limit_not_a_tight_default():
    """Regressionstest: Alpacas News-API begrenzt `limit` auf die
    GESAMTZAHL der Artikel über ALLE angefragten Symbole hinweg, nicht pro
    Symbol -- ein knapper Standardwert (z.B. 50) würde an nachrichten-
    reichen Tagen Artikel gerade interessanter Kandidaten verdrängen."""
    scanner = make_scanner()
    gainers = [FakeMover("SYM", percent_change=20.0, price=5.0)]
    bars = make_multi_symbol_bars({"SYM": [(4.0, 100_000)] * 30 + [(5.0, 600_000)]})
    install_fakes(scanner, gainers, [], bars)

    captured_requests = []

    def spy_get_news(request):
        captured_requests.append(request)
        return FakeNewsSet([])

    scanner.news_client.get_news = spy_get_news

    scanner.scan(ScanCriteria(min_relative_volume=5.0), reference_time=TEST_NOW)

    assert len(captured_requests) == 1
    assert captured_requests[0].limit >= 200


def test_excludes_warrants_units_and_rights_by_asset_name():
    """Regression: der Scanner nahm Warrants/Varianten auf (z.B. CRMLW neben
    CRML). Erkennung über den Asset-Namen, nicht das Symbol (SNOW endet
    ebenfalls auf W)."""
    scanner = make_scanner({
        "CRMLW": "Critical Metals Corp. Warrant",
        "ABCU": "ABC Acquisition Corp. Units",
        "ABCR": "ABC Acquisition Corp. Rights",
        "SNOW": "Snowflake Inc. Class A Common Stock",
    })
    symbols = ["CRML", "CRMLW", "ABCU", "ABCR", "SNOW"]
    gainers = [FakeMover(s, percent_change=25.0, price=5.0) for s in symbols]
    bars = make_multi_symbol_bars({s: [(4.0, 100_000)] * 30 + [(5.0, 600_000)] for s in symbols})
    install_fakes(scanner, gainers, [], bars)

    candidates = scanner.scan(ScanCriteria(), reference_time=TEST_NOW)

    assert sorted(c.symbol for c in candidates) == ["CRML", "SNOW"]


def test_keeps_candidate_when_asset_lookup_fails():
    scanner = make_scanner()

    def failing_get_asset(symbol):
        raise RuntimeError("API down")

    scanner.trading_client.get_asset = failing_get_asset
    bars = make_multi_symbol_bars({"GOOD": [(4.0, 100_000)] * 30 + [(5.0, 600_000)]})
    install_fakes(scanner, [FakeMover("GOOD", percent_change=25.0, price=5.0)], [], bars)

    candidates = scanner.scan(ScanCriteria(), reference_time=TEST_NOW)

    assert [c.symbol for c in candidates] == ["GOOD"]

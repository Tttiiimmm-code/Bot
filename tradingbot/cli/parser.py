"""Kommandozeilen-Parser für main.py: Argument-Prüfungen und alle Unterbefehle."""
from __future__ import annotations

import argparse
import math
from datetime import date

from tradingbot.cli.sma import _parse_grid
from tradingbot.momentum import WEAKNESS_EXITS
from tradingbot.strategy import MAX_WINDOW


def _positive_int(value: str) -> int:
    """Für --days: eine großzügige Obergrenze verhindert einen
    OverflowError beim Aufbau des Anfragezeitraums (timedelta) bei einem
    zu langen Tippfehler -- 50000 Tage sind bereits ~200 Jahre."""
    n = int(value)
    if not 0 < n <= 50_000:
        raise argparse.ArgumentTypeError(f"muss zwischen 1 und 50000 liegen, nicht {n}")
    return n


def _account_spec(value: str) -> tuple[str, str]:
    """Für momentum-compare --account: "NAME=PFAD" -> (NAME, PFAD mit ~ aufgelöst)."""
    import os

    name, sep, path = value.partition("=")
    name, path = name.strip(), path.strip()
    if not sep or not name or not path:
        raise argparse.ArgumentTypeError(f"erwartet NAME=PFAD (z.B. none=~/bot2.env), nicht {value!r}")
    path = os.path.expanduser(path)
    if not os.path.isfile(path):
        raise argparse.ArgumentTypeError(f"Datei {path} existiert nicht")
    return name, path


def _train_ratio(value: str) -> float:
    ratio = float(value)
    if not 0 < ratio < 1:
        raise argparse.ArgumentTypeError(f"muss zwischen 0 und 1 liegen (exklusiv), nicht {ratio}")
    return ratio


def _fraction_below_one(value: str) -> float:
    """Für commission-pct/slippage-pct/stop-loss-pct/risk-per-trade-pct:
    alle fließen in run_backtest als Multiplikator auf einen Preis-/
    Kapitalbetrag ein. Ab 1 (100%) kippen die Vorzeichen (z.B. negative
    shares bei commission_pct>=1, negativer Verkaufspreis bei
    slippage_pct>=1) und korrumpieren den Backtest-Zustand dauerhaft --
    daher hier hart auf [0, 1) begrenzt statt nur "nicht negativ"."""
    x = float(value)
    if not 0 <= x < 1:
        raise argparse.ArgumentTypeError(f"muss zwischen 0 und kleiner 1 (100%) liegen, nicht {x}")
    return x


def _non_negative_finite(value: str) -> float:
    """Für take-profit-pct: anders als die obigen Prozentsätze kein
    Divisor/Multiplikator, der bei >=1 das Vorzeichen kippt (ein
    Kursziel von 100%+ über dem Einstieg ist sinnvoll) -- nur negative
    und nicht-endliche Werte (NaN/Inf) sind unsinnig."""
    x = float(value)
    if not (math.isfinite(x) and x >= 0):
        raise argparse.ArgumentTypeError(f"muss eine nicht-negative, endliche Zahl sein, nicht {x}")
    return x


def _symbol(value: str) -> str:
    """Normalisiert wie Config.from_env() (strip + Großschreibung), damit
    --symbol AAPL und --symbol aapl identisch behandelt werden."""
    symbol = value.strip().upper()
    if not symbol:
        raise argparse.ArgumentTypeError("darf nicht leer sein")
    return symbol


def _symbol_list(value: str) -> list[str]:
    """Für --symbols: kommagetrennte Liste, jedes Symbol normalisiert wie
    _symbol() (strip + Großschreibung). Duplikate werden entfernt, die
    Reihenfolge bleibt erhalten."""
    symbols = [s.strip().upper() for s in value.split(",")]
    symbols = [s for s in symbols if s]
    if not symbols:
        raise argparse.ArgumentTypeError("darf nicht leer sein")
    seen: set[str] = set()
    deduped = []
    for s in symbols:
        if s not in seen:
            seen.add(s)
            deduped.append(s)
    return deduped


def _positive_float(value: str) -> float:
    x = float(value)
    if not (math.isfinite(x) and x > 0):
        raise argparse.ArgumentTypeError(f"muss eine positive, endliche Zahl sein, nicht {x}")
    return x


def _window_or_disabled(value: str) -> int:
    """Für trend-window/rsi-window: 0 deaktiviert den Filter, sonst wie
    bei --days/long_window durch MAX_WINDOW vor einem OverflowError in
    close.rolling() geschützt."""
    n = int(value)
    if not 0 <= n <= MAX_WINDOW:
        raise argparse.ArgumentTypeError(f"muss zwischen 0 (aus) und {MAX_WINDOW} liegen, nicht {n}")
    return n


def _add_strategy_arguments(subparser: argparse.ArgumentParser):
    """Fügt die für backtest und validate identischen Kosten-/Risiko-/
    Filter-Flags hinzu -- an einer Stelle definiert, damit beide
    Subcommands garantiert dieselben Wertebereiche/Defaults akzeptieren.

    Die Defaults hier sind bewusst NICHT dieselben wie die konservativen
    (deaktivierten) Bibliotheks-Defaults von run_backtest()/validate():
    die CLI soll die im Chat als sinnvoll ausgewählten Verbesserungen
    (Trendfilter, RSI-Filter, Take-Profit) standardmäßig aktiv zeigen,
    während die Kernfunktionen für programmatische Aufrufer/Tests
    rückwärtskompatibel abgeschaltet bleiben.
    """
    subparser.add_argument(
        "--symbol",
        type=_symbol,
        default=None,
        help="Zu testendes Symbol, überschreibt SYMBOL aus .env nur für diesen Aufruf "
        "(z.B. --symbol MSFT). Standard: SYMBOL aus .env.",
    )
    subparser.add_argument(
        "--commission-pct",
        type=_fraction_below_one,
        default=0.0,
        help="Provision pro Order als Anteil des Ordervolumens, z.B. 0.001 = 0.1%% (Standard: 0.0, Alpaca ist provisionsfrei).",
    )
    subparser.add_argument(
        "--slippage-pct",
        type=_fraction_below_one,
        default=0.0005,
        help="Erwartete Slippage pro Order gegenüber dem Schlusskurs, z.B. 0.0005 = 0.05%% (Standard: 0.05%%).",
    )
    subparser.add_argument(
        "--stop-loss-pct",
        type=_fraction_below_one,
        default=0.08,
        help="Trailing-Stop als Anteil unter dem Höchststand seit Einstieg, z.B. 0.08 = 8%%. 0 deaktiviert den Stop (Standard: 0.08).",
    )
    subparser.add_argument(
        "--take-profit-pct",
        type=_non_negative_finite,
        default=0.15,
        help="Take-Profit als Anteil über dem Einstiegspreis, z.B. 0.15 = 15%%. 0 deaktiviert (Standard: 0.15).",
    )
    subparser.add_argument(
        "--risk-per-trade-pct",
        type=_fraction_below_one,
        default=0.0,
        help="Positionsgröße so wählen, dass beim initialen Stop höchstens dieser Anteil des Kapitals "
        "verloren geht (nur wirksam mit --stop-loss-pct > 0). 0 = volles Kapital pro Trade (Standard: 0.0).",
    )
    subparser.add_argument(
        "--trend-window",
        type=_window_or_disabled,
        default=200,
        help="Trendfilter: BUY nur, wenn der Kurs über dieser SMA liegt. 0 deaktiviert (Standard: 200).",
    )
    subparser.add_argument(
        "--rsi-window",
        type=_window_or_disabled,
        default=14,
        help="RSI-Filter: BUY nur, wenn der RSI über 50 liegt. 0 deaktiviert (Standard: 14).",
    )


def build_parser() -> argparse.ArgumentParser:
    """Baut den vollständigen Kommandozeilen-Parser aller Befehle."""
    parser = argparse.ArgumentParser(description="Moving-Average-Crossover Tradingbot (Alpaca)")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("run", help="Startet die Live-/Paper-Trading-Loop.")

    backtest_parser = subparsers.add_parser("backtest", help="Backtest gegen historische Kurse.")
    backtest_parser.add_argument(
        "--days", type=_positive_int, default=250, help="Anzahl historischer Handelstage (Standard: 250)."
    )
    _add_strategy_arguments(backtest_parser)

    validate_parser = subparsers.add_parser(
        "validate", help="Out-of-Sample-Validierung: Parameter auf Trainingsdaten wählen, auf Testdaten prüfen."
    )
    validate_parser.add_argument(
        "--days", type=_positive_int, default=600, help="Anzahl historischer Handelstage (Standard: 600)."
    )
    validate_parser.add_argument(
        "--train-ratio",
        type=_train_ratio,
        default=0.7,
        help="Anteil der Daten für die Parametersuche, Rest ist Out-of-Sample-Test (Standard: 0.7).",
    )
    validate_parser.add_argument(
        "--grid",
        type=_parse_grid,
        default=[(5, 20), (10, 30), (20, 50), (50, 200)],
        help="Zu testende SMA-Kombinationen als 'kurz:lang,kurz:lang,...' (Standard: 5:20,10:30,20:50,50:200).",
    )
    _add_strategy_arguments(validate_parser)

    walkforward_parser = subparsers.add_parser(
        "walkforward",
        help="Walk-Forward-Validierung: validate() über mehrere aufeinanderfolgende Zeitfenster wiederholen.",
    )
    walkforward_parser.add_argument(
        "--days", type=_positive_int, default=1500, help="Anzahl historischer Handelstage (Standard: 1500)."
    )
    walkforward_parser.add_argument(
        "--grid",
        type=_parse_grid,
        default=[(5, 20), (10, 30), (20, 50), (50, 200)],
        help="Zu testende SMA-Kombinationen als 'kurz:lang,kurz:lang,...' (Standard: 5:20,10:30,20:50,50:200).",
    )
    walkforward_parser.add_argument(
        "--train-window",
        type=_positive_int,
        default=252,
        help="Größe des Trainingsfensters in Handelstagen (Standard: 252, ca. 1 Jahr).",
    )
    walkforward_parser.add_argument(
        "--test-window",
        type=_positive_int,
        default=63,
        help="Größe des Testfensters in Handelstagen (Standard: 63, ca. 1 Quartal).",
    )
    walkforward_parser.add_argument(
        "--step",
        type=_positive_int,
        default=None,
        help="Schrittweite pro Fenster in Handelstagen (Standard: gleich --test-window, "
        "d.h. nicht überlappende Testfenster).",
    )
    walkforward_parser.add_argument(
        "--expanding",
        action="store_true",
        help="Trainingsfenster wächst ab Tag 0 statt mit fester Größe mitzurutschen (Standard: rolling).",
    )
    _add_strategy_arguments(walkforward_parser)

    momentum_parser = subparsers.add_parser(
        "momentum-backtest",
        help="Historischer Backtest der Warrior-Trading-Momentum-Strategie (Bull Flag/Flat Top) auf Minutendaten.",
    )
    momentum_parser.add_argument(
        "--symbol",
        type=_symbol,
        default=None,
        help="Zu testendes Symbol, überschreibt SYMBOL aus .env nur für diesen Aufruf. Schließt "
        "sich mit --symbols gegenseitig aus.",
    )
    momentum_parser.add_argument(
        "--symbols",
        type=_symbol_list,
        default=None,
        help="Kommagetrennte Liste mehrerer Symbole (z.B. --symbols AAPL,TSLA,MSFT) -- führt den "
        "Backtest für jedes Symbol UNABHÄNGIG mit demselben Startkapital aus (siehe "
        "--starting-cash) und fasst die Ergebnisse zusammen. Simuliert KEIN gemeinsames Konto mit "
        "begrenztem Gesamtkapital oder einer Obergrenze gleichzeitiger Positionen (das macht live "
        "`momentum-run`). Schließt sich mit --symbol gegenseitig aus.",
    )
    momentum_parser.add_argument(
        "--starting-cash",
        type=_positive_float,
        default=10_000.0,
        help="Startkapital (Standard: 10000). Bei --symbols gilt dieser Betrag JE Symbol "
        "unabhängig, nicht als geteiltes Gesamtkapital.",
    )
    momentum_parser.add_argument(
        "--days",
        type=_positive_int,
        default=90,
        dest="calendar_days",
        help="Kalendertage (nicht Handelstage!) historischer Minutendaten, die geladen werden "
        "(Standard: 90). Alpacas kostenloser Plan liefert typischerweise nur einige Monate "
        "Minutenhistorie zurück.",
    )
    momentum_parser.add_argument(
        "--feed",
        choices=["sip", "iex"],
        default="sip",
        help="Datenfeed für den Backtest. 'sip' (Standard) fragt Alpacas Standard-/SIP-Feed ab -- "
        "vollen Marktüberblick, aber ohne Zusatzabo nur für Daten älter als ~20 Minuten. 'iex' "
        "fragt stattdessen genau den Feed ab, den `momentum-run` live tatsächlich nutzt (nur ~2-3%% "
        "des Marktvolumens) -- testet damit realistischer, was der Live-Bot sehen würde, statt "
        "gegen den volleren SIP-Feed zu optimistische Ergebnisse zu liefern.",
    )
    momentum_parser.add_argument(
        "--max-risk-dollars",
        type=_positive_float,
        default=500.0,
        help="Maximal riskierter Betrag pro Trade in Dollar, bestimmt die Positionsgröße "
        "(Stückzahl = max_risk_dollars / Risiko pro Aktie). Standard: 500 (Artikel-Beispiel).",
    )
    momentum_parser.add_argument(
        "--reward-risk-ratio",
        type=_positive_float,
        default=2.0,
        help="Chance-Risiko-Verhältnis für das erste Kursziel (Artikel: 2:1). Standard: 2.0.",
    )
    momentum_parser.add_argument(
        "--min-relative-volume",
        type=_positive_float,
        default=2.0,
        help="Mindest-Relativvolumen (Vielfaches des Durchschnitts zur gleichen Tageszeit) für ein "
        "gültiges Setup (Artikel-Kriterium 3). Standard: 2.0.",
    )
    momentum_parser.add_argument(
        "--lookback-days",
        type=_positive_int,
        default=20,
        help="Anzahl vorangehender Handelstage für den Relativvolumen-Vergleich. Standard: 20.",
    )
    momentum_parser.add_argument(
        "--daily-trend-window",
        type=_positive_int,
        default=50,
        help="Fenster (Handelstage) für den Tages-SMA-Trendfilter (Artikel-Kriterium 2). Standard: 50.",
    )
    momentum_parser.add_argument(
        "--flagpole-min-gain-pct",
        type=_positive_float,
        default=0.03,
        help="Mindestanstieg für eine gültige Flagpole (im Artikel nicht numerisch spezifiziert, "
        "eigene Annäherung). Standard: 0.03 (3%%).",
    )
    momentum_parser.add_argument(
        "--flagpole-max-bars",
        type=_positive_int,
        default=15,
        help="Maximale Anzahl 1-Min-Bars, innerhalb derer der Flagpole-Anstieg stattfinden muss. Standard: 15.",
    )
    momentum_parser.add_argument(
        "--min-pullback-bars",
        type=_positive_int,
        default=2,
        help="Mindestanzahl Pullback-Bars vor einem gültigen Breakout-Einstieg (Artikel: '2-3 rote Kerzen'). "
        "Standard: 2.",
    )
    momentum_parser.add_argument(
        "--max-pullback-bars",
        type=_positive_int,
        default=5,
        help="Nach so vielen Pullback-Bars ohne Breakout gilt das Setup als ungültig. Standard: 5.",
    )
    momentum_parser.add_argument(
        "--max-pullback-retrace-pct",
        type=_fraction_below_one,
        default=0.5,
        help="Zieht sich der Pullback um mehr als diesen Anteil des Flagpole-Anstiegs zurück, gilt das "
        "Setup als ungültig (eigene Annäherung, im Artikel nicht spezifiziert). Standard: 0.5 (50%%).",
    )
    momentum_parser.add_argument(
        "--extension-multiplier",
        type=_positive_float,
        default=4.0,
        help="Ein Balken mit Handelsspanne >= diesem Vielfachen der durchschnittlichen Pullback-"
        "Balkenspanne gilt als 'Extension Bar' (Artikel-Exit-Indikator #3, Schwelle eigene "
        "Annäherung). Standard: 4.0.",
    )
    momentum_parser.add_argument(
        "--weakness-exit", choices=WEAKNESS_EXITS, default="red_candle",
        help="Schwäche-Ausstieg vor dem Ziel-Teilverkauf: red_candle = erste rot schließende Kerze, "
        "new_low = erste Kerze mit Tief unter dem der Vorkerze, none = keiner (nur Stop/Ziel/Extension) "
        "(Standard: red_candle).",
    )
    momentum_parser.add_argument(
        "--commission-pct",
        type=_fraction_below_one,
        default=0.0,
        help="Provision pro Order als Anteil des Ordervolumens. Standard: 0.0 (Alpaca ist provisionsfrei).",
    )
    momentum_parser.add_argument(
        "--slippage-pct",
        type=_fraction_below_one,
        default=0.0005,
        help="Erwartete Slippage pro Order gegenüber dem Balkenpreis. Standard: 0.05%%.",
    )

    scan_parser = subparsers.add_parser(
        "scan",
        help="Marktweiter Scanner nach Warrior-Trading-Aktienauswahl-Kriterien (nur aktueller Marktzustand).",
    )
    scan_parser.add_argument(
        "--min-price", type=_positive_float, default=1.0,
        help="Untere Preisgrenze in Dollar (Standard: 1.0).",
    )
    scan_parser.add_argument(
        "--max-price", type=_positive_float, default=20.0,
        help="Obere Preisgrenze in Dollar (Standard: 20.0, Ross Camerons genereller Bereich; "
        "fürs Small-Account-Beispiel aus dem Sample Trading Plan z.B. --min-price 5 --max-price 10).",
    )
    scan_parser.add_argument(
        "--min-percent-change", type=_non_negative_finite, default=10.0,
        help="Mindest-Tagesgewinn in Prozent (Standard: 10.0).",
    )
    scan_parser.add_argument(
        "--min-relative-volume", type=_positive_float, default=5.0,
        help="Mindest-Relativvolumen ggü. Tagesdurchschnitt der letzten N Tage (Standard: 5.0).",
    )
    scan_parser.add_argument(
        "--relative-volume-lookback-days", type=_positive_int, default=30,
        help="Anzahl Vortage für den Volumendurchschnitt (Standard: 30).",
    )
    scan_parser.add_argument(
        "--require-news", action="store_true",
        help="Nur Kandidaten mit aktueller News (siehe --news-lookback-hours) behalten "
        "(Standard: aus -- News ist laut Strategie bevorzugt, nicht zwingend).",
    )
    scan_parser.add_argument(
        "--news-lookback-hours", type=_positive_int, default=24,
        help="Zeitfenster in Stunden für die News-Prüfung (Standard: 24).",
    )
    scan_parser.add_argument(
        "--top-movers", type=_positive_int, default=30,
        help="Wie viele Top-Tagesgewinner von Alpacas Screener-API abgefragt werden (Standard: 30).",
    )
    scan_parser.add_argument(
        "--top-actives", type=_positive_int, default=30,
        help="Wie viele Top-Symbole nach Handelsvolumen abgefragt werden (Standard: 30).",
    )

    momentum_run_parser = subparsers.add_parser(
        "momentum-run",
        help="Live-Momentum-Bot: kombiniert den Scanner mit der Bull-Flag/Flat-Top-Engine und platziert "
        "echte (Paper-)Orders. Läuft bis Strg+C (siehe README für Einschränkungen).",
    )
    momentum_run_parser.add_argument(
        "--state-file", default="momentum_state.json",
        help="Zustandsdatei für Neustarts (Standard: momentum_state.json).",
    )
    momentum_run_parser.add_argument(
        "--no-state-file", action="store_const", const=None, dest="state_file",
        help="Zustand nicht speichern; offene Positionen beim Neustart wie bisher glattstellen.",
    )
    momentum_run_parser.add_argument(
        "--min-price", type=_positive_float, default=1.0, help="Untere Preisgrenze in Dollar (Standard: 1.0).",
    )
    momentum_run_parser.add_argument(
        "--max-price", type=_positive_float, default=20.0, help="Obere Preisgrenze in Dollar (Standard: 20.0).",
    )
    momentum_run_parser.add_argument(
        "--min-percent-change", type=_non_negative_finite, default=10.0,
        help="Mindest-Tagesgewinn in Prozent, den ein Scan-Kandidat haben muss (Standard: 10.0).",
    )
    momentum_run_parser.add_argument(
        "--scan-min-relative-volume", type=_positive_float, default=5.0,
        help="Mindest-Relativvolumen, das ein Scan-Kandidat haben muss (Standard: 5.0). Getrennt von "
        "--min-relative-volume (Schwelle für die Bull-Flag/Flat-Top-Erkennung selbst).",
    )
    momentum_run_parser.add_argument(
        "--relative-volume-lookback-days", type=_positive_int, default=30,
        help="Anzahl Vortage für den Scanner-Volumendurchschnitt (Standard: 30).",
    )
    momentum_run_parser.add_argument(
        "--require-news", action="store_true",
        help="Nur Kandidaten mit aktueller News als Symbol aufnehmen (Standard: aus).",
    )
    momentum_run_parser.add_argument(
        "--news-lookback-hours", type=_positive_int, default=24,
        help="Zeitfenster in Stunden für die News-Prüfung (Standard: 24).",
    )
    momentum_run_parser.add_argument(
        "--top-movers", type=_positive_int, default=30,
        help="Wie viele Top-Tagesgewinner pro Scan abgefragt werden (Standard: 30).",
    )
    momentum_run_parser.add_argument(
        "--top-actives", type=_positive_int, default=30,
        help="Wie viele Top-Symbole nach Handelsvolumen pro Scan abgefragt werden (Standard: 30).",
    )
    momentum_run_parser.add_argument(
        "--max-risk-dollars", type=_positive_float, default=500.0,
        help="Maximal riskierter Betrag pro Trade in Dollar (Standard: 500).",
    )
    momentum_run_parser.add_argument(
        "--reward-risk-ratio", type=_positive_float, default=2.0,
        help="Chance-Risiko-Verhältnis für das erste Kursziel (Standard: 2.0).",
    )
    momentum_run_parser.add_argument(
        "--min-relative-volume", type=_positive_float, default=2.0,
        help="Mindest-Relativvolumen für ein gültiges Bull-Flag/Flat-Top-Setup (Standard: 2.0).",
    )
    momentum_run_parser.add_argument(
        "--lookback-days", type=_positive_int, default=20,
        help="Anzahl vorangehender Handelstage für den Relativvolumen-Vergleich je Symbol (Standard: 20).",
    )
    momentum_run_parser.add_argument(
        "--daily-trend-window", type=_positive_int, default=50,
        help="Fenster (Handelstage) für den Tages-SMA-Trendfilter (Standard: 50).",
    )
    momentum_run_parser.add_argument(
        "--flagpole-min-gain-pct", type=_positive_float, default=0.03,
        help="Mindestanstieg für eine gültige Flagpole (Standard: 0.03).",
    )
    momentum_run_parser.add_argument(
        "--flagpole-max-bars", type=_positive_int, default=15,
        help="Maximale Anzahl 1-Min-Bars für den Flagpole-Anstieg (Standard: 15).",
    )
    momentum_run_parser.add_argument(
        "--min-pullback-bars", type=_positive_int, default=2,
        help="Mindestanzahl Pullback-Bars vor einem gültigen Breakout (Standard: 2).",
    )
    momentum_run_parser.add_argument(
        "--max-pullback-bars", type=_positive_int, default=5,
        help="Nach so vielen Pullback-Bars ohne Breakout gilt das Setup als ungültig (Standard: 5).",
    )
    momentum_run_parser.add_argument(
        "--max-pullback-retrace-pct", type=_fraction_below_one, default=0.5,
        help="Maximaler Rückzug des Pullbacks relativ zum Flagpole-Anstieg (Standard: 0.5).",
    )
    momentum_run_parser.add_argument(
        "--extension-multiplier", type=_positive_float, default=4.0,
        help="Vielfaches der durchschnittlichen Pullback-Balkenspanne für einen 'Extension Bar'-Ausstieg "
        "(Standard: 4.0).",
    )
    momentum_run_parser.add_argument(
        "--weakness-exit", choices=WEAKNESS_EXITS, default="red_candle",
        help="Schwäche-Ausstieg vor dem Ziel-Teilverkauf: red_candle = erste rot schließende Kerze, "
        "new_low = erste Kerze mit Tief unter dem der Vorkerze, none = keiner (nur Stop/Ziel/Extension) "
        "(Standard: red_candle).",
    )
    momentum_run_parser.add_argument(
        "--news-intel", action="store_true",
        help="Je neuem Kandidaten News + SEC-Meldungen per LLM einschätzen (ANTHROPIC_API_KEY oder "
        "OPENAI_API_KEY in .env); "
        "Ergebnis in news_intel.csv. Ohne --news-filter nur Schattenmodus (Handel unverändert).",
    )
    momentum_run_parser.add_argument(
        "--news-filter", choices=["off", "block-dilution"], default="off",
        help="block-dilution: Einstieg ablehnen, wenn die Einschätzung Verwässerung/Emission meldet "
        "(erst nach Auswertung des Schattenmodus nutzen; Standard: off).",
    )
    momentum_run_parser.add_argument(
        "--news-model", default=None,
        help="Modell für die Einschätzung (Standard je Anbieter: claude-haiku-4-5-20251001 bzw. gpt-5-mini).",
    )
    momentum_run_parser.add_argument(
        "--news-provider", choices=["auto", "anthropic", "openai"], default="auto",
        help="LLM-Anbieter; auto = Anthropic, wenn ANTHROPIC_API_KEY gesetzt ist, sonst OpenAI "
        "(OPENAI_API_KEY) (Standard: auto).",
    )
    momentum_run_parser.add_argument(
        "--max-concurrent-positions", type=_positive_int, default=3,
        help="Obergrenze gleichzeitig offener Positionen (Standard: 3).",
    )
    momentum_run_parser.add_argument(
        "--max-tracked-symbols", type=_positive_int, default=20,
        help="Obergrenze gleichzeitig beobachteter Symbole (Standard: 20).",
    )
    momentum_run_parser.add_argument(
        "--daily-max-loss-pct", type=_fraction_below_one, default=0.10,
        help="Anteil des Tages-Start-Eigenkapitals, bei dessen Verlust der Bot für den Rest des Tages "
        "pausiert und alle Positionen schließt (Standard: 0.10 = 10%%, muss > 0 sein).",
    )
    momentum_run_parser.add_argument(
        "--scan-interval-seconds", type=_positive_int, default=300,
        help="Wie oft (Sekunden) erneut nach neuen Kandidaten-Symbolen gescannt wird (Standard: 300).",
    )
    momentum_run_parser.add_argument(
        "--poll-interval-seconds", type=_positive_int, default=60,
        help="Wie oft (Sekunden) neue Kursdaten für bereits beobachtete Symbole abgerufen werden "
        "(Standard: 60).",
    )
    momentum_run_parser.add_argument(
        "--order-fill-timeout-seconds", type=_positive_int, default=30,
        help="Wie lange (Sekunden) auf die Ausführung einer Order gewartet wird, bevor reagiert wird "
        "(Kauf: stornieren; Verkauf: erneut versuchen). Standard: 30.",
    )
    momentum_run_parser.add_argument(
        "--order-poll-interval-seconds", type=_positive_float, default=1.0,
        help="Wie oft (Sekunden) der Order-Status während des Wartens auf eine Fill-Bestätigung "
        "abgefragt wird (Standard: 1.0).",
    )
    momentum_run_parser.add_argument(
        "--flatten-minutes-before-close", type=_positive_int, default=5,
        help="Wie viele Minuten vor Sitzungsende alle offenen Positionen zwangsweise geschlossen werden "
        "(Standard: 5).",
    )
    momentum_run_parser.add_argument(
        "--no-broker-stop", dest="broker_stop_orders", action="store_false",
        help="Keine zusätzliche Stop-Order bei Alpaca hinterlegen (nur Software-Stop). Standard: "
        "Stop-Order wird hinterlegt und greift auch, wenn der Bot ausfällt.",
    )
    momentum_run_parser.add_argument(
        "--min-stop-pct", type=float, default=0.02,
        help="Mindest-Stop-Abstand (Anteil vom Kurs) für die Stückzahl-Berechnung. Ein engerer Stop "
        "führt nicht mehr zu einer größeren Position. Standard: 0.02 (2%%).",
    )
    momentum_run_parser.add_argument(
        "--max-position-dollars", type=float, default=25_000.0,
        help="Maximaler Positionswert pro Trade in $. Standard: 25000.",
    )
    momentum_run_parser.add_argument(
        "--max-entry-slippage-pct", type=float, default=0.01,
        help="Kauf als Limit-Order höchstens so weit über dem Signalkurs (Anteil). Stückzahl und "
        "Risiko werden mit diesem Limit gerechnet. Standard: 0.01 (1%%).",
    )

    report_parser = subparsers.add_parser(
        "momentum-report",
        help="Wertet Alpacas Order-Historie des Live-Bots (momentum-run) zu einem P&L-Report pro "
        "Handelstag aus -- ruft nur Daten ab, platziert keine Orders.",
    )
    report_parser.add_argument(
        "--days", type=_positive_int, default=1,
        help="Wie viele Kalendertage rückwirkend die Order-Historie abgefragt wird (Standard: 1).",
    )

    overnight_parser = subparsers.add_parser(
        "overnight-run",
        help="Overnight-Portfolio (Paper): Kauf zum Schluss bei Kurs > SMA200, Verkauf zum nächsten Open. "
        "Braucht ein EIGENES Alpaca-Konto (Keys in --env-file).",
    )
    overnight_parser.add_argument("--env-file", default="overnight.env",
                                  help="Datei mit den Keys des eigenen Overnight-Kontos (Standard: overnight.env).")
    overnight_parser.add_argument("--dry-run", action="store_true",
                                  help="Nur Entscheidungen loggen, keine Orders platzieren.")
    subparsers.add_parser("overnight-report", help="Auswertung von overnight_trades.csv.")

    copilot_parser = subparsers.add_parser(
        "copilot",
        help="Trading-Copilot (eigenes Paper-Konto): du entscheidest, er erzwingt Regeln, setzt den Stop "
        "bei Alpaca und führt ein Journal. Unterbefehle: scan, buy, status, close, watch, report.",
    )
    copilot_parser.add_argument("--env-file", default="copilot.env",
                                help="Keys des eigenen Copilot-Kontos (Standard: copilot.env).")
    copilot_parser.add_argument("--journal", default="copilot_journal.jsonl", help="Journal-Datei.")
    copilot_parser.add_argument("--risk", type=float, default=50.0, help="$-Risiko je Trade = 1 R (Standard 50).")
    copilot_parser.add_argument("--max-daily-loss", type=float, default=150.0,
                                help="Tagesverlustgrenze in $ (Standard 150).")
    copilot_parser.add_argument("--max-trades", type=_positive_int, default=6, help="Einstiege pro Tag (Standard 6).")
    copilot_sub = copilot_parser.add_subparsers(dest="copilot_command", required=True)
    cp_scan = copilot_sub.add_parser("scan", help="Kandidaten (Aktien im Spiel) für den Nachmittag.")
    cp_scan.add_argument("--min-change", type=float, default=5.0, help="Mindest-Tagesplus in %% (Standard 5).")
    cp_scan.add_argument("--min-price", type=float, default=2.0)
    cp_scan.add_argument("--max-price", type=float, default=200.0)
    cp_scan.add_argument("--min-relvol", type=float, default=2.0, help="Mindest-Relativvolumen (Standard 2).")
    cp_buy = copilot_sub.add_parser("buy", help="Kauf mit Stop bei Alpaca; Stückzahl aus dem Risiko.")
    cp_buy.add_argument("symbol")
    cp_buy.add_argument("--stop", type=float, required=True, help="Stop-Kurs (unter dem aktuellen Kurs).")
    cp_buy.add_argument("--setup", required=True, help="Name des Setups, z.B. vwap-pullback, power-hour.")
    cp_buy.add_argument("--target", type=float, default=None, help="Optionales Kursziel (Limit-Verkauf).")
    cp_buy.add_argument("--note", default="", help="Warum dieser Trade? (fürs Journal)")
    cp_buy.add_argument("--breakeven", action="store_true",
                        help="Stop bei +1 R auf den Einstiegskurs nachziehen (erledigt `copilot watch`).")
    copilot_sub.add_parser("status", help="Offene Positionen, Tages-P&L, verbleibendes Verlustbudget.")
    cp_close = copilot_sub.add_parser("close", help="Position schließen (Stop-Order wird storniert).")
    cp_close.add_argument("symbol", help="Symbol oder 'all'.")
    copilot_sub.add_parser("watch", help="Läuft im Hintergrund: stellt bei Tagesverlustgrenze und um 15:55 ET glatt.")
    copilot_sub.add_parser("notify-test", help="Testnachricht ans Handy (ntfy, NTFY_TOPIC in copilot.env).")
    copilot_sub.add_parser("weekly", help="Wochenbericht der letzten 7 Tage (kommt freitags auch per ntfy).")
    cp_report = copilot_sub.add_parser("report", help="Auswertung je Setup in R-Vielfachen.")
    cp_report.add_argument("--days", type=_positive_int, default=90)

    forward_parser = subparsers.add_parser(
        "forward-run",
        help="Vorwärtstest ohne Broker: Nikkei-Nachteffekt und Gotobi (USD/JPY) aus Dukascopy-Minutendaten "
        "(braucht Node.js/npx). Schreibt forward_trades.csv, sendet keine Orders.",
    )
    forward_parser.add_argument("--start", type=date.fromisoformat, default=date(2026, 9, 28),
                                help="Erster Tag des Vorwärtstests (Standard: 2026-09-28); frühere Trades zählen nicht.")
    forward_parser.add_argument("--ledger", default="forward_trades.csv", help="CSV mit den Trades.")
    forward_parser.add_argument("--lookback-days", type=_positive_int, default=10,
                                help="Wie viele Tage je Lauf neu geladen werden (Standard: 10).")
    forward_report = subparsers.add_parser("forward-report", help="Auswertung von forward_trades.csv.")
    forward_report.add_argument("--ledger", default="forward_trades.csv", help="CSV mit den Trades.")
    fwd_stocks = subparsers.add_parser(
        "forward-stocks",
        help="Vorwärtstest Aktien (Papier, keine Orders): ORB Top 5 täglich und Qualitäts-Top-50 monatlich. "
        "Nutzt Alpaca-Marktdaten (nur Lesen) und SEC-Daten; schreibt forward_orb.csv und forward_quality.csv.",
    )
    fwd_stocks.add_argument("--start", type=date.fromisoformat, default=date(2026, 10, 1),
                            help="Erster Tag (Standard: 2026-10-01); frühere Tage zählen nicht.")
    fwd_stocks.add_argument("--env-file", default=".env", help="Datei mit Alpaca-Schlüsseln (nur Marktdaten).")
    fwd_stocks.add_argument("--last-day", type=date.fromisoformat, default=None,
                            help="Letzter zu verarbeitender Handelstag (Standard: gestern).")
    subparsers.add_parser("forward-stocks-report", help="Auswertung von forward_orb.csv und forward_quality.csv.")
    health_parser = subparsers.add_parser(
        "health", help="Wächter (VPS): Dienste, Platte, Speicher, Recorder prüfen; Probleme und Tagesstatus per ntfy.")
    health_parser.add_argument("--env-file", default="copilot.env", help="Datei mit NTFY_TOPIC.")
    fstatus = subparsers.add_parser(
        "forward-status", help="Alle Vorwärtstests nach der gemeinsamen Auswertungsregel (nur Information).")
    fstatus.add_argument("--notify", action="store_true", help="Zusätzlich per ntfy senden.")
    fstatus.add_argument("--env-file", default="copilot.env", help="Datei mit NTFY_TOPIC.")
    gl_p = subparsers.add_parser("gold-live", help="Gold-Ausbruch-Bot mit OANDA-DEMO-Orders (Runde 134, nur Papier).")
    gl_p.add_argument("--env-file", default="gold.env", help="OANDA_TOKEN, OANDA_ACCOUNT_ID, OANDA_PRACTICE=true.")
    gl_p.add_argument("--notify-env", default="copilot.env", help="Datei mit NTFY_TOPIC (optional).")
    gl_p.add_argument("--check", action="store_true", help="Nur Verbindung prüfen (Konto, Kerzen), nichts handeln.")
    subparsers.add_parser("forward-gold", help="Vorwärtstest gold_breakout (Nachbau Gold Reaper, Runde 134; Papier).")
    pbot = subparsers.add_parser("pelosi-bot", help="Pelosi-Käufe kopieren, 12 Monate halten (Alpaca-PAPER, Runde 141).")
    pbot.add_argument("--env-file", default="overnight.env", help="Alpaca-Papierkonto (Standard: Overnight-Konto).")
    pbot.add_argument("--notify-env", default="copilot.env", help="Datei mit NTFY_TOPIC.")
    pbot.add_argument("--check", action="store_true", help="Nur Konto und Stand anzeigen, nichts handeln.")
    fpel = subparsers.add_parser("forward-pelosi", help="Vorwärtstest pelosi_copy (Kongress-Meldungen, Runde 141; Papier).")
    fpel.add_argument("--notify-env", default="", help="Datei mit NTFY_TOPIC: neue Pelosi-Käufe aufs Handy.")
    mcheck = subparsers.add_parser(
        "momentum-checkpoint", help="Prüfpunkte 100/150 Trades des Momentum-Vorwärtstests (Meldung je einmal).")
    mcheck.add_argument("--env-file", default=".env", help="Konto des Momentum-Bots (nur lesend).")
    mcheck.add_argument("--notify-env", default="copilot.env", help="Datei mit NTFY_TOPIC.")
    mcheck.add_argument("--notify", action="store_true", help="Fällige Prüfpunkte per ntfy senden.")

    compare_parser = subparsers.add_parser(
        "momentum-compare",
        help="Vergleicht mehrere Bot-Konten (je ein Alpaca-Paper-Konto mit eigener .env-Datei) "
        "nebeneinander -- ruft nur Daten ab, platziert keine Orders.",
    )
    compare_parser.add_argument(
        "--account", type=_account_spec, action="append", required=True, metavar="NAME=PFAD",
        help="Kontoname und Pfad zu dessen .env-Datei, mehrfach angeben, z.B. "
        "--account red=.env --account none=~/bot2.env",
    )
    compare_parser.add_argument(
        "--days", type=_positive_int, default=1,
        help="Wie viele Kalendertage rückwirkend die Order-Historien abgefragt werden (Standard: 1).",
    )
    compare_parser.add_argument(
        "--tolerance-minutes", type=_positive_int, default=3,
        help="Einstiege desselben Symbols innerhalb dieser Minuten gelten als dasselbe Setup (Standard: 3).",
    )
    return parser

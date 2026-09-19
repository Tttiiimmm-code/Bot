"""CLI-Einstiegspunkt für den Tradingbot.

Nutzung:
    python main.py run         # Live-/Paper-Trading-Loop starten
    python main.py backtest    # Strategie gegen historische Daten testen
"""

from __future__ import annotations

import argparse
import logging
import sys

from alpaca.common.exceptions import APIError

from tradingbot.bot import TradingBot
from tradingbot.broker import Broker
from tradingbot.config import Config


def _positive_int(value: str) -> int:
    """Für --days: eine großzügige Obergrenze verhindert einen
    OverflowError beim Aufbau des Anfragezeitraums (timedelta) bei einem
    zu langen Tippfehler -- 50000 Tage sind bereits ~200 Jahre."""
    n = int(value)
    if not 0 < n <= 50_000:
        raise argparse.ArgumentTypeError(f"muss zwischen 1 und 50000 liegen, nicht {n}")
    return n


def _train_ratio(value: str) -> float:
    ratio = float(value)
    if not 0 < ratio < 1:
        raise argparse.ArgumentTypeError(f"muss zwischen 0 und 1 liegen (exklusiv), nicht {ratio}")
    return ratio


def _fraction_below_one(value: str) -> float:
    """Für commission-pct/slippage-pct/stop-loss-pct: alle drei fließen in
    run_backtest als Multiplikator auf einen Preis/Kapitalbetrag ein.
    Ab 1 (100%) kippen die Vorzeichen (z.B. negative shares bei
    commission_pct>=1, negativer Verkaufspreis bei slippage_pct>=1) und
    korrumpieren den Backtest-Zustand dauerhaft -- daher hier hart auf
    [0, 1) begrenzt statt nur "nicht negativ"."""
    x = float(value)
    if not 0 <= x < 1:
        raise argparse.ArgumentTypeError(f"muss zwischen 0 und kleiner 1 (100%) liegen, nicht {x}")
    return x


def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


def cmd_run(config: Config):
    bot = TradingBot(config)
    bot.run_forever()


def cmd_backtest(
    config: Config, days: int, commission_pct: float, slippage_pct: float, stop_loss_pct: float
):
    from tradingbot.backtest import run_backtest

    broker = Broker(config)
    closes = broker.get_recent_closes(limit=days)
    if closes.empty:
        print(f"Keine historischen Daten für {config.symbol} erhalten.")
        return

    result = run_backtest(
        closes,
        config.short_window,
        config.long_window,
        commission_pct=commission_pct,
        slippage_pct=slippage_pct,
        stop_loss_pct=stop_loss_pct,
    )
    num_stops = sum(1 for t in result.trades if t.side == "STOP")

    print(f"Symbol:          {config.symbol}")
    print(f"Zeitraum:        {closes.index[0].date()} - {closes.index[-1].date()} ({len(closes)} Tage)")
    print(f"Trades:          {result.num_trades} (davon {num_stops} Stop-Loss-Ausstiege)")
    print(f"Stop-Loss:       {stop_loss_pct:.1%} unter Einstiegspreis" if stop_loss_pct > 0 else "Stop-Loss:       deaktiviert")
    print(f"Kosten (Provision+Slippage): {result.total_costs:,.2f} ({commission_pct:.2%} + {slippage_pct:.2%}/Order)")
    print(f"Endkapital:      {result.final_equity:,.2f}")
    print(f"Gesamtrendite:   {result.total_return_pct:+.2f}%")


def _parse_grid(grid_str: str) -> list[tuple[int, int]]:
    combos = []
    try:
        for pair in grid_str.split(","):
            short_str, long_str = pair.split(":")
            short_w, long_w = int(short_str), int(long_str)
            if short_w < 1:
                raise ValueError(f"{short_w}:{long_w} -- kurzes Fenster muss mindestens 1 sein")
            if short_w >= long_w:
                raise ValueError(f"{short_w}:{long_w} -- kurzes Fenster muss kleiner als langes sein")
            if long_w > 100_000:
                raise ValueError(f"{short_w}:{long_w} -- langes Fenster darf höchstens 100000 sein")
            combos.append((short_w, long_w))
    except ValueError as e:
        raise argparse.ArgumentTypeError(
            f"Ungültiges --grid-Format {grid_str!r}, erwartet 'kurz:lang,kurz:lang,...' "
            f"(z.B. '5:20,10:30'): {e}"
        )
    return combos


def cmd_validate(
    config: Config,
    days: int,
    train_ratio: float,
    grid: list[tuple[int, int]],
    commission_pct: float,
    slippage_pct: float,
    stop_loss_pct: float,
):
    from tradingbot.validation import validate

    broker = Broker(config)
    closes = broker.get_recent_closes(limit=days)
    if closes.empty:
        print(f"Keine historischen Daten für {config.symbol} erhalten.")
        return

    result = validate(
        closes,
        grid,
        train_ratio=train_ratio,
        commission_pct=commission_pct,
        slippage_pct=slippage_pct,
        stop_loss_pct=stop_loss_pct,
    )

    evaluated = {(c.short_window, c.long_window) for c in result.all_candidates}
    skipped = [combo for combo in grid if combo not in evaluated]
    if skipped:
        skipped_str = ", ".join(f"{s}/{l}" for s, l in skipped)
        print(
            f"Hinweis: {skipped_str} übersprungen -- zu wenig Handelstage im "
            f"Trainingsabschnitt für diese Fenstergröße (mehr --days oder kleineres "
            f"--train-ratio verwenden).\n"
        )

    print(f"Symbol:          {config.symbol}")
    print(
        f"Zeitraum:        {closes.index[0].date()} - {closes.index[-1].date()} "
        f"({len(closes)} Tage, Split am {result.split_date.date()}, train_ratio={train_ratio})"
    )
    print()
    print(f"{'SMA':<8} {'Train Rendite':>14} {'Train Trades':>13} {'Test Rendite':>13} {'Test Trades':>12}")
    print("-" * 65)
    for c in result.all_candidates:
        sma = f"{c.short_window}/{c.long_window}"
        marker = " *" if c is result.best else ""
        print(
            f"{sma:<8} {c.train.return_pct:>+13.2f}% {c.train.num_trades:>13} "
            f"{c.test.return_pct:>+12.2f}% {c.test.num_trades:>12}{marker}"
        )

    print()
    best = result.best
    print(f"Beste Parameter (nach Trainingsdaten ausgewählt): SMA {best.short_window}/{best.long_window}")
    print(f"  Training  ({best.train.start.date()} - {best.train.end.date()}): {best.train.return_pct:+.2f}% ({best.train.num_trades} Trades)")
    print(f"  Test      ({best.test.start.date()} - {best.test.end.date()}): {best.test.return_pct:+.2f}% ({best.test.num_trades} Trades)")
    gap = best.test.return_pct - best.train.return_pct
    print(f"  Differenz Test-Train: {gap:+.2f} Prozentpunkte {'(Overfitting-Warnsignal)' if gap < -10 else ''}")


def _add_cost_and_risk_arguments(subparser: argparse.ArgumentParser):
    """Fügt die für backtest und validate identischen Kosten-/Risiko-Flags
    hinzu -- an einer Stelle definiert, damit beide Subcommands garantiert
    dieselben Wertebereiche/Defaults akzeptieren."""
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
        help="Stop-Loss als Anteil unter dem Einstiegspreis, z.B. 0.08 = 8%%. 0 deaktiviert den Stop (Standard: 0.08).",
    )


def main():
    parser = argparse.ArgumentParser(description="Moving-Average-Crossover Tradingbot (Alpaca)")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("run", help="Startet die Live-/Paper-Trading-Loop.")

    backtest_parser = subparsers.add_parser("backtest", help="Backtest gegen historische Kurse.")
    backtest_parser.add_argument(
        "--days", type=_positive_int, default=250, help="Anzahl historischer Handelstage (Standard: 250)."
    )
    _add_cost_and_risk_arguments(backtest_parser)

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
    _add_cost_and_risk_arguments(validate_parser)

    args = parser.parse_args()

    setup_logging()

    try:
        config = Config.from_env()

        if args.command == "run":
            cmd_run(config)
        elif args.command == "backtest":
            cmd_backtest(config, args.days, args.commission_pct, args.slippage_pct, args.stop_loss_pct)
        elif args.command == "validate":
            cmd_validate(
                config,
                args.days,
                args.train_ratio,
                args.grid,
                args.commission_pct,
                args.slippage_pct,
                args.stop_loss_pct,
            )
    except (RuntimeError, ValueError) as e:
        print(f"Fehler: {e}", file=sys.stderr)
        sys.exit(1)
    except APIError as e:
        print(f"Fehler bei der Alpaca-API (Keys/Netzwerk prüfen): {e}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nAbgebrochen.", file=sys.stderr)
        sys.exit(130)


if __name__ == "__main__":
    main()

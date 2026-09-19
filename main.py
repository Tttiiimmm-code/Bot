"""CLI-Einstiegspunkt für den Tradingbot.

Nutzung:
    python main.py run         # Live-/Paper-Trading-Loop starten
    python main.py backtest    # Strategie gegen historische Daten testen
"""

from __future__ import annotations

import argparse
import logging

from tradingbot.bot import TradingBot
from tradingbot.broker import Broker
from tradingbot.config import Config


def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


def cmd_run(config: Config):
    bot = TradingBot(config)
    bot.run_forever()


def cmd_backtest(config: Config, days: int, commission_pct: float, slippage_pct: float):
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
    )
    print(f"Symbol:          {config.symbol}")
    print(f"Zeitraum:        {closes.index[0].date()} - {closes.index[-1].date()} ({len(closes)} Tage)")
    print(f"Trades:          {result.num_trades}")
    print(f"Kosten (Provision+Slippage): {result.total_costs:,.2f} ({commission_pct:.2%} + {slippage_pct:.2%}/Order)")
    print(f"Endkapital:      {result.final_equity:,.2f}")
    print(f"Gesamtrendite:   {result.total_return_pct:+.2f}%")


def _parse_grid(grid_str: str) -> list[tuple[int, int]]:
    combos = []
    for pair in grid_str.split(","):
        short_str, long_str = pair.split(":")
        combos.append((int(short_str), int(long_str)))
    return combos


def cmd_validate(
    config: Config,
    days: int,
    train_ratio: float,
    grid_str: str,
    commission_pct: float,
    slippage_pct: float,
):
    from tradingbot.validation import validate

    grid = _parse_grid(grid_str)

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


def main():
    parser = argparse.ArgumentParser(description="Moving-Average-Crossover Tradingbot (Alpaca)")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("run", help="Startet die Live-/Paper-Trading-Loop.")

    backtest_parser = subparsers.add_parser("backtest", help="Backtest gegen historische Kurse.")
    backtest_parser.add_argument(
        "--days", type=int, default=250, help="Anzahl historischer Handelstage (Standard: 250)."
    )
    backtest_parser.add_argument(
        "--commission-pct",
        type=float,
        default=0.0,
        help="Provision pro Order als Anteil des Ordervolumens, z.B. 0.001 = 0.1%% (Standard: 0.0, Alpaca ist provisionsfrei).",
    )
    backtest_parser.add_argument(
        "--slippage-pct",
        type=float,
        default=0.0005,
        help="Erwartete Slippage pro Order gegenüber dem Schlusskurs, z.B. 0.0005 = 0.05%% (Standard: 0.05%%).",
    )

    validate_parser = subparsers.add_parser(
        "validate", help="Out-of-Sample-Validierung: Parameter auf Trainingsdaten wählen, auf Testdaten prüfen."
    )
    validate_parser.add_argument(
        "--days", type=int, default=600, help="Anzahl historischer Handelstage (Standard: 600)."
    )
    validate_parser.add_argument(
        "--train-ratio",
        type=float,
        default=0.7,
        help="Anteil der Daten für die Parametersuche, Rest ist Out-of-Sample-Test (Standard: 0.7).",
    )
    validate_parser.add_argument(
        "--grid",
        type=str,
        default="5:20,10:30,20:50,50:200",
        help="Zu testende SMA-Kombinationen als 'kurz:lang,kurz:lang,...' (Standard: 5:20,10:30,20:50,50:200).",
    )
    validate_parser.add_argument("--commission-pct", type=float, default=0.0)
    validate_parser.add_argument("--slippage-pct", type=float, default=0.0005)

    args = parser.parse_args()

    setup_logging()
    config = Config.from_env()

    if args.command == "run":
        cmd_run(config)
    elif args.command == "backtest":
        cmd_backtest(config, args.days, args.commission_pct, args.slippage_pct)
    elif args.command == "validate":
        cmd_validate(
            config, args.days, args.train_ratio, args.grid, args.commission_pct, args.slippage_pct
        )


if __name__ == "__main__":
    main()

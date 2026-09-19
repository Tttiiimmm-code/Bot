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

    args = parser.parse_args()

    setup_logging()
    config = Config.from_env()

    if args.command == "run":
        cmd_run(config)
    elif args.command == "backtest":
        cmd_backtest(config, args.days, args.commission_pct, args.slippage_pct)


if __name__ == "__main__":
    main()

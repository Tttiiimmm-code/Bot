"""CLI-Einstiegspunkt für den Tradingbot.

Nutzung:
    python main.py run                # Live-/Paper-Trading-Loop starten
    python main.py backtest           # Strategie gegen historische Daten testen
    python main.py validate           # Out-of-Sample-Validierung (ein Train-/Test-Split)
    python main.py walkforward        # Out-of-Sample-Validierung über mehrere Zeitfenster
    python main.py momentum-backtest  # Momentum-Day-Trading-Backtest auf Minutendaten
    python main.py scan               # Marktweiter Scanner (aktueller Marktzustand)
    python main.py momentum-run       # Live-Momentum-Bot: Scanner + Bull-Flag/Flat-Top-Engine + echte Orders
    python main.py momentum-report    # P&L-Report aus Alpacas Order-Historie (momentum-run auswerten)
    python main.py momentum-compare   # mehrere Bot-Konten nebeneinander vergleichen

Alle Befehle: python main.py --help. Der Parser steht in tradingbot/cli/parser.py, die Befehle je Gruppe
in tradingbot/cli/ (sma, momentum, overnight, copilot, forward).
"""
from __future__ import annotations

import dataclasses
import logging
import sys

from alpaca.common.exceptions import APIError

from tradingbot.cli import forward
from tradingbot.cli.copilot import cmd_copilot
from tradingbot.cli.momentum import (  # noqa: F401 -- _format_duration wird von tests/test_main.py importiert
    _format_duration,
    cmd_momentum_backtest,
    cmd_momentum_backtest_multi,
    cmd_momentum_compare,
    cmd_momentum_report,
    cmd_momentum_run,
    cmd_scan,
)
from tradingbot.cli.overnight import cmd_overnight_run
from tradingbot.cli.parser import (  # noqa: F401 -- Prüffunktionen werden von tests/test_main.py importiert
    _fraction_below_one,
    _positive_int,
    _symbol,
    _train_ratio,
    build_parser,
)
from tradingbot.cli.sma import _parse_grid, cmd_backtest, cmd_run, cmd_validate, cmd_walkforward  # noqa: F401
from tradingbot.config import Config


def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


def main():
    parser = build_parser()
    args = parser.parse_args()

    setup_logging()

    # Vorwärtstests, Papier-Bots mit eigenem Konto und der Wächter brauchen die .env des Momentum-Bots nicht.
    handler = forward.COMMANDS.get(args.command)
    if handler is not None:
        handler(args)
        return

    # Copilot und Overnight-Bot nutzen eigene Konten und brauchen die .env des
    # Momentum-Bots nicht -- daher vor Config.from_env() behandeln.
    if args.command == "copilot":
        try:
            cmd_copilot(args)
        except (RuntimeError, ValueError) as e:
            print(f"Fehler: {e}", file=sys.stderr)
            sys.exit(1)
        return
    if args.command in ("overnight-run", "overnight-report"):
        try:
            if args.command == "overnight-run":
                cmd_overnight_run(args.env_file, args.dry_run, args.allow_live_trading)
            else:
                from pathlib import Path

                from tradingbot.overnight_live import summarize_trade_log

                print(summarize_trade_log(Path("overnight_trades.csv")))
        except (RuntimeError, ValueError) as e:
            print(f"Fehler: {e}", file=sys.stderr)
            sys.exit(1)
        except APIError as e:
            print(f"Fehler bei der Alpaca-API (Keys/Netzwerk prüfen): {e}", file=sys.stderr)
            sys.exit(1)
        return

    try:
        if args.command == "momentum-compare":
            # Eigene Keys je Konto (--account), unabhängig von der .env.
            cmd_momentum_compare(args.account, args.days, args.tolerance_minutes)
            return
        config = Config.from_env()
        if args.command not in ("run", "scan", "momentum-run", "momentum-report") and args.symbol is not None:
            # Nur die Analyse-Subcommands mit fest EINEM Symbol (backtest/
            # validate/walkforward/momentum-backtest) erlauben ein Ad-hoc-
            # Symbol. run kennt --symbol gar nicht und bleibt bewusst strikt
            # an .env gebunden, damit der Live-/Paper-Trading-Loop nie
            # versehentlich per CLI-Flag ein anderes Symbol handelt. scan
            # kennt --symbol ebenfalls nicht -- es durchsucht den ganzen
            # Markt, nicht ein einzelnes Symbol.
            config = dataclasses.replace(config, symbol=args.symbol)

        if args.command == "momentum-backtest" and args.symbol is not None and args.symbols is not None:
            raise ValueError("--symbol und --symbols schließen sich gegenseitig aus (nur eins von beiden angeben).")

        if args.command == "run":
            cmd_run(config)
        elif args.command == "backtest":
            cmd_backtest(
                config,
                args.days,
                args.commission_pct,
                args.slippage_pct,
                args.stop_loss_pct,
                args.take_profit_pct,
                args.risk_per_trade_pct,
                args.trend_window,
                args.rsi_window,
            )
        elif args.command == "validate":
            cmd_validate(
                config,
                args.days,
                args.train_ratio,
                args.grid,
                args.commission_pct,
                args.slippage_pct,
                args.stop_loss_pct,
                args.take_profit_pct,
                args.risk_per_trade_pct,
                args.trend_window,
                args.rsi_window,
            )
        elif args.command == "walkforward":
            cmd_walkforward(
                config,
                args.days,
                args.grid,
                args.train_window,
                args.test_window,
                args.step,
                args.expanding,
                args.commission_pct,
                args.slippage_pct,
                args.stop_loss_pct,
                args.take_profit_pct,
                args.risk_per_trade_pct,
                args.trend_window,
                args.rsi_window,
            )
        elif args.command == "momentum-backtest":
            if args.symbols is not None:
                cmd_momentum_backtest_multi(
                    config,
                    args.symbols,
                    args.calendar_days,
                    args.feed,
                    args.starting_cash,
                    args.max_risk_dollars,
                    args.reward_risk_ratio,
                    args.min_relative_volume,
                    args.lookback_days,
                    args.daily_trend_window,
                    args.flagpole_min_gain_pct,
                    args.flagpole_max_bars,
                    args.min_pullback_bars,
                    args.max_pullback_bars,
                    args.max_pullback_retrace_pct,
                    args.extension_multiplier,
                    args.commission_pct,
                    args.slippage_pct,
                    weakness_exit=args.weakness_exit,
                )
            else:
                cmd_momentum_backtest(
                    config,
                    args.calendar_days,
                    args.feed,
                    args.starting_cash,
                    args.max_risk_dollars,
                    args.reward_risk_ratio,
                    args.min_relative_volume,
                    args.lookback_days,
                    args.daily_trend_window,
                    args.flagpole_min_gain_pct,
                    args.flagpole_max_bars,
                    args.min_pullback_bars,
                    args.max_pullback_bars,
                    args.max_pullback_retrace_pct,
                    args.extension_multiplier,
                    args.commission_pct,
                    args.slippage_pct,
                    weakness_exit=args.weakness_exit,
                )
        elif args.command == "scan":
            cmd_scan(
                config,
                args.min_price,
                args.max_price,
                args.min_percent_change,
                args.min_relative_volume,
                args.relative_volume_lookback_days,
                args.require_news,
                args.news_lookback_hours,
                args.top_movers,
                args.top_actives,
            )
        elif args.command == "momentum-run":
            cmd_momentum_run(
                config,
                args.min_price,
                args.max_price,
                args.min_percent_change,
                args.scan_min_relative_volume,
                args.relative_volume_lookback_days,
                args.require_news,
                args.news_lookback_hours,
                args.top_movers,
                args.top_actives,
                args.max_risk_dollars,
                args.reward_risk_ratio,
                args.min_relative_volume,
                args.lookback_days,
                args.daily_trend_window,
                args.flagpole_min_gain_pct,
                args.flagpole_max_bars,
                args.min_pullback_bars,
                args.max_pullback_bars,
                args.max_pullback_retrace_pct,
                args.extension_multiplier,
                args.max_concurrent_positions,
                args.max_tracked_symbols,
                args.daily_max_loss_pct,
                args.scan_interval_seconds,
                args.poll_interval_seconds,
                args.order_fill_timeout_seconds,
                args.order_poll_interval_seconds,
                args.flatten_minutes_before_close,
                args.allow_live_trading,
                args.broker_stop_orders,
                args.min_stop_pct,
                args.max_position_dollars,
                args.max_entry_slippage_pct,
                weakness_exit=args.weakness_exit,
                news_intel=args.news_intel,
                news_filter=args.news_filter,
                news_model=args.news_model,
                news_provider=args.news_provider,
            )
        elif args.command == "momentum-report":
            cmd_momentum_report(config, args.days)
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

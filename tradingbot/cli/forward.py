"""Befehle der Vorwärtstests, Papier-Bots und des Wächters (eigene Konten bzw. ganz ohne Alpaca-Keys)."""
from __future__ import annotations

import subprocess
import sys
from datetime import date


def cmd_forward_test(args):
    from pathlib import Path

    from tradingbot import forward_test

    try:
        if args.command == "forward-run":
            cfg = forward_test.ForwardConfig(first_day=args.start, ledger=Path(args.ledger),
                                             lookback_days=args.lookback_days)
            print(forward_test.run(cfg))
        else:
            print(forward_test.summarize(Path(args.ledger)))
    except (RuntimeError, OSError, subprocess.SubprocessError) as e:
        print(f"Fehler: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_health(args):
    from tradingbot import health
    from tradingbot.notify import notifier_from_env

    for m in health.step(notifier_from_env(args.env_file)):
        print(f"gesendet: {m}")


def cmd_gold_live(args):
    from tradingbot import gold_live
    from tradingbot.notify import notifier_from_env

    client = gold_live.client_from_env(args.env_file)
    if args.check:
        cs = client.candles(60)
        lv = gold_live.signal_levels(client.candles(500), gold_live.GoldLiveConfig())
        print(f"OANDA Practice OK: Kontowert {client.nav():,.2f}, {len(cs)} H1-Kerzen, letzte {cs[-1]['time'][:16]} "
              f"Geld {float(cs[-1]['bid']['c']):.2f}; nächster Buy-Stop wäre {lv[0]:.2f} (ATR {lv[1]:.2f})")
        print(f"Offene Trades {len(client.open_trades())}, eigene Orders {len(client.pending_orders())}")
        return
    from pathlib import Path as _P

    notifier = notifier_from_env(args.notify_env) if _P(args.notify_env).exists() else None
    gold_live.GoldLiveBot(client, notifier=notifier).run_forever()


def cmd_forward_gold(args):
    from tradingbot import forward_gold

    print(forward_gold.run(forward_gold.GoldConfig()))


def cmd_pelosi_bot(args):
    from alpaca.data.enums import DataFeed
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockLatestTradeRequest
    from alpaca.trading.client import TradingClient

    from tradingbot import pelosi_bot
    from tradingbot.notify import notifier_from_env
    from tradingbot.report import read_account_env

    key, secret, paper = read_account_env(args.env_file)
    if not paper:
        raise RuntimeError(f"{args.env_file}: ALPACA_PAPER=false -- der Pelosi-Bot handelt nur auf Papierkonten.")
    tc, dc = TradingClient(key, secret, paper=True), StockHistoricalDataClient(key, secret)

    def last_price(sym):
        t = dc.get_stock_latest_trade(StockLatestTradeRequest(symbol_or_symbols=sym, feed=DataFeed.IEX))
        return float(t[sym].price) if sym in t else None

    cfg = pelosi_bot.PelosiBotConfig()
    if args.check:
        acct = tc.get_account()
        print(f"Konto paper, Wert {float(acct.equity):.2f} $, Bargeld {float(acct.cash):.2f} $, "
              f"Positionen {len(tc.get_all_positions())}; NVDA {last_price('NVDA')}")
        print(pelosi_bot.summarize(cfg.state_file, cfg.trade_log))
        return
    notifier = notifier_from_env(args.notify_env) if args.notify_env else None
    pelosi_bot.PelosiBot(cfg, tc, last_price, notifier=notifier).run_forever()


def cmd_forward_pelosi(args):
    from tradingbot import forward_pelosi
    from tradingbot.notify import notifier_from_env

    notifier = notifier_from_env(args.notify_env) if args.notify_env else None
    print(forward_pelosi.run(notifier=notifier))


def cmd_momentum_checkpoint(args):
    from datetime import datetime as _dt, timezone as _tz

    from alpaca.trading.client import TradingClient

    from tradingbot import momentum_checkpoint as mcp
    from tradingbot.notify import notifier_from_env
    from tradingbot.report import fetch_closed_orders, match_trades, read_account_env

    key, secret, paper = read_account_env(args.env_file)
    orders = fetch_closed_orders(TradingClient(key, secret, paper=paper), _dt(2026, 9, 20, tzinfo=_tz.utc),
                                 _dt.now(_tz.utc))
    trades, _, _ = match_trades(orders)
    print(mcp.progress(trades))
    if args.notify:
        for text in mcp.step(trades, notifier_from_env(args.notify_env)):
            print(f"gesendet: {text}")


def cmd_forward_status(args):
    from tradingbot import forward_status
    from tradingbot.notify import notifier_from_env

    text = forward_status.format_text(forward_status.status(forward_status.Path("."), date.today()))
    print(text)
    if args.notify:
        notifier_from_env(args.env_file).send("Vorwaertstests Monatsstand", text, tags="bar_chart")


def cmd_forward_stocks(args):
    from tradingbot import forward_stocks

    if args.command == "forward-stocks":
        cfg = forward_stocks.StockForwardConfig(first_day=args.start)
        print(forward_stocks.run(cfg, args.env_file, args.last_day))
    else:
        print(forward_stocks.summarize(forward_stocks.StockForwardConfig(first_day=date(2026, 10, 1))))


# Befehle, die ohne die .env des Momentum-Bots auskommen (Name -> Funktion).
COMMANDS = {
    "forward-run": cmd_forward_test,
    "forward-report": cmd_forward_test,
    "health": cmd_health,
    "gold-live": cmd_gold_live,
    "forward-gold": cmd_forward_gold,
    "pelosi-bot": cmd_pelosi_bot,
    "forward-pelosi": cmd_forward_pelosi,
    "momentum-checkpoint": cmd_momentum_checkpoint,
    "forward-status": cmd_forward_status,
    "forward-stocks": cmd_forward_stocks,
    "forward-stocks-report": cmd_forward_stocks,
}

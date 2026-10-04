"""Momentum-Befehle: momentum-backtest, scan, momentum-run, momentum-report, momentum-compare."""
from __future__ import annotations

import dataclasses

from tradingbot.broker import Broker
from tradingbot.config import Config


def cmd_momentum_backtest(
    config: Config,
    calendar_days: int,
    feed,
    starting_cash: float,
    max_risk_dollars: float,
    reward_risk_ratio: float,
    min_relative_volume: float,
    lookback_days: int,
    daily_trend_window: int,
    flagpole_min_gain_pct: float,
    flagpole_max_bars: int,
    min_pullback_bars: int,
    max_pullback_bars: int,
    max_pullback_retrace_pct: float,
    extension_multiplier: float,
    commission_pct: float,
    slippage_pct: float,
    weakness_exit: str = "red_candle",
):
    from alpaca.data.enums import DataFeed

    from tradingbot.momentum import run_momentum_backtest

    data_feed = DataFeed.IEX if feed == "iex" else None
    broker = Broker(config)
    bars = broker.get_minute_bars(calendar_days, feed=data_feed)
    if bars.empty:
        print(f"Keine Minuten-Kursdaten für {config.symbol} erhalten.")
        return

    result = run_momentum_backtest(
        bars,
        starting_cash=starting_cash,
        max_risk_dollars=max_risk_dollars,
        reward_risk_ratio=reward_risk_ratio,
        min_relative_volume=min_relative_volume,
        lookback_days=lookback_days,
        daily_trend_window=daily_trend_window,
        flagpole_min_gain_pct=flagpole_min_gain_pct,
        flagpole_max_bars=flagpole_max_bars,
        min_pullback_bars=min_pullback_bars,
        max_pullback_bars=max_pullback_bars,
        max_pullback_retrace_pct=max_pullback_retrace_pct,
        extension_multiplier=extension_multiplier,
        commission_pct=commission_pct,
        slippage_pct=slippage_pct,
        weakness_exit=weakness_exit,
    )

    print(f"Symbol:                {config.symbol}")
    print(
        "Datenfeed:             "
        + (
            "IEX (echtzeitfähig, deckt aber nur ~2-3% des Marktvolumens ab -- entspricht dem, "
            "was momentum-run live tatsächlich sieht)"
            if data_feed is not None
            else "Standard/SIP (voller Marktüberblick, ohne Zusatzabo >15 Min. verzögert -- "
            "momentum-run live sieht das NICHT, siehe --feed iex)"
        )
    )
    print(f"Zeitraum:              {bars.index[0]} - {bars.index[-1]} ({calendar_days} Kalendertage angefragt)")
    print(
        f"Tage ausgewertet:      {result.days_evaluated} "
        f"({result.days_skipped_insufficient_lookback} übersprungen: zu wenig Vortage für Relativvolumen, "
        f"{result.days_skipped_insufficient_trend_history} übersprungen: zu wenig Vortage für Trend-SMA)"
    )
    print(
        f"Parameter:             Risiko/Trade=${max_risk_dollars:.0f}, Ziel={reward_risk_ratio:.1f}:1, "
        f"Rel.Volumen>={min_relative_volume:.1f}x, Trend-SMA={daily_trend_window}T"
    )
    print()
    if not result.trades:
        print("Keine Setups erkannt (siehe README für die Einschränkungen dieser Näherung).")
        return

    print(f"{'Datum':<12} {'Muster':<10} {'Einstieg':>12} {'Stop':>10} {'Stück':>7} {'PnL':>10}")
    print("-" * 65)
    for t in result.trades:
        marker = "+" if t.gross_pnl > 0 else ("-" if t.gross_pnl < 0 else " ")
        print(
            f"{str(t.day):<12} {t.pattern:<10} {t.entry_price:>11.2f} {t.initial_stop_price:>10.2f} "
            f"{t.shares:>7} {marker}{abs(t.gross_pnl):>8.2f}"
        )

    print()
    print(f"Trades:                {result.num_trades}")
    print(f"Trefferquote:          {result.win_rate:.0%}")
    print(f"Kosten (Provision+Slippage): {result.total_costs:,.2f}")
    print(f"Endkapital:            {result.final_equity:,.2f}")
    print(f"Gesamtrendite:         {result.total_return_pct:+.2f}%")
    print(
        "\nHinweis: Näherung der Warrior-Trading-Momentum-Strategie ohne Float-Filter (siehe README). "
        "Dieser Befehl selbst platziert nie Orders -- für den Live-Handel siehe `python main.py "
        "momentum-run` (nutzt intern immer den IEX-Feed). Mit --feed iex lässt sich hier vorab "
        "testen, wie sich die Strategie auf genau den (eingeschränkten) Daten verhalten hätte, die "
        "der Live-Bot tatsächlich sieht -- ohne --feed iex testet dieser Befehl gegen den volleren "
        "Standard-/SIP-Feed, was die Ergebnisse optimistischer als die Live-Realität wirken lassen "
        "kann. Kandidaten-Symbole findet `python main.py scan`."
    )


def cmd_momentum_backtest_multi(
    config: Config,
    symbols: list[str],
    calendar_days: int,
    feed,
    starting_cash: float,
    max_risk_dollars: float,
    reward_risk_ratio: float,
    min_relative_volume: float,
    lookback_days: int,
    daily_trend_window: int,
    flagpole_min_gain_pct: float,
    flagpole_max_bars: int,
    min_pullback_bars: int,
    max_pullback_bars: int,
    max_pullback_retrace_pct: float,
    extension_multiplier: float,
    commission_pct: float,
    slippage_pct: float,
    weakness_exit: str = "red_candle",
):
    from alpaca.data.enums import DataFeed

    from tradingbot.momentum import run_momentum_backtest_multi

    data_feed = DataFeed.IEX if feed == "iex" else None

    bars_by_symbol = {}
    for symbol in symbols:
        symbol_broker = Broker(dataclasses.replace(config, symbol=symbol))
        bars = symbol_broker.get_minute_bars(calendar_days, feed=data_feed)
        if bars.empty:
            print(f"Keine Minuten-Kursdaten für {symbol} erhalten -- übersprungen.")
            continue
        bars_by_symbol[symbol] = bars

    if not bars_by_symbol:
        print("Für keines der angegebenen Symbole konnten Daten geladen werden.")
        return

    result = run_momentum_backtest_multi(
        bars_by_symbol,
        starting_cash_per_symbol=starting_cash,
        max_risk_dollars=max_risk_dollars,
        reward_risk_ratio=reward_risk_ratio,
        min_relative_volume=min_relative_volume,
        lookback_days=lookback_days,
        daily_trend_window=daily_trend_window,
        flagpole_min_gain_pct=flagpole_min_gain_pct,
        flagpole_max_bars=flagpole_max_bars,
        min_pullback_bars=min_pullback_bars,
        max_pullback_bars=max_pullback_bars,
        max_pullback_retrace_pct=max_pullback_retrace_pct,
        extension_multiplier=extension_multiplier,
        commission_pct=commission_pct,
        slippage_pct=slippage_pct,
        weakness_exit=weakness_exit,
    )

    print(f"Symbole:               {', '.join(bars_by_symbol)} ({len(bars_by_symbol)} von {len(symbols)} mit Daten)")
    print(
        "Datenfeed:             "
        + (
            "IEX (echtzeitfähig, deckt aber nur ~2-3% des Marktvolumens ab -- entspricht dem, "
            "was momentum-run live tatsächlich sieht)"
            if data_feed is not None
            else "Standard/SIP (voller Marktüberblick, ohne Zusatzabo >15 Min. verzögert -- "
            "momentum-run live sieht das NICHT, siehe --feed iex)"
        )
    )
    print(f"Startkapital/Symbol:   {starting_cash:,.2f} (siehe Hinweis unten)")
    print(
        f"Parameter:             Risiko/Trade=${max_risk_dollars:.0f}, Ziel={reward_risk_ratio:.1f}:1, "
        f"Rel.Volumen>={min_relative_volume:.1f}x, Trend-SMA={daily_trend_window}T"
    )
    print()
    print(
        f"{'Symbol':<8} {'Tage ausgew.':>12} {'Trades':>7} {'Trefferquote':>13} "
        f"{'Endkapital':>14} {'Rendite':>10}"
    )
    print("-" * 72)
    for s in result.per_symbol:
        r = s.result
        print(
            f"{s.symbol:<8} {r.days_evaluated:>12} {r.num_trades:>7} {r.win_rate:>12.0%} "
            f"{r.final_equity:>14,.2f} {r.total_return_pct:>+9.2f}%"
        )

    print()
    print(f"Trades gesamt:         {result.total_trades}")
    print(f"Trefferquote gesamt:   {result.overall_win_rate:.0%}")
    print(f"Bruttogewinn/-verlust gesamt: {result.total_gross_pnl:+,.2f}")
    print(f"Kosten gesamt:         {result.total_costs:,.2f}")
    print(
        "\nHinweis: jedes Symbol wird UNABHÄNGIG mit demselben Startkapital simuliert, NICHT als "
        "ein gemeinsames Konto mit begrenztem Gesamtkapital oder einer Obergrenze gleichzeitiger "
        "Positionen (das macht live `momentum-run` über --max-concurrent-positions). Für eine "
        "schnelle Einschätzung über mehrere selbst gewählte Kandidaten hinweg gedacht -- KEINE "
        "Simulation, welche Aktien der Scanner an einem vergangenen Tag gefunden hätte (Alpacas "
        "Screener-API kennt kein historisches Datum, siehe README)."
    )


def _format_duration(td) -> str:
    total_seconds = int(td.total_seconds())
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def cmd_momentum_report(config: Config, days: int):
    from datetime import datetime, timedelta, timezone
    from zoneinfo import ZoneInfo

    from alpaca.trading.client import TradingClient

    from tradingbot.report import fetch_closed_orders, group_by_trading_day, match_trades

    berlin = ZoneInfo("Europe/Berlin")
    trading_client = TradingClient(config.api_key, config.secret_key, paper=config.paper)
    until = datetime.now(timezone.utc)
    after = until - timedelta(days=days)

    orders = fetch_closed_orders(trading_client, after, until)
    trades, open_positions, unmatched_sells = match_trades(orders)

    if not trades and not open_positions and not unmatched_sells:
        print(f"Keine ausgeführten Orders in den letzten {days} Tag(en) gefunden.")
        return

    by_day = group_by_trading_day(trades)

    print(f"=== Trading-Report: letzte {days} Tag(e) ===\n")

    if by_day:
        print(f"{'Datum':<12} {'Trades':>7} {'Trefferquote':>13} {'Netto-P&L':>12}")
        print("-" * 47)
        for day, summary in by_day.items():
            print(
                f"{day.isoformat():<12} {summary.num_trades:>7} {summary.win_rate:>12.0%} "
                f"{summary.net_pnl:>+11.2f}"
            )
        print("-" * 47)
        total_trades = len(trades)
        total_wins = sum(1 for t in trades if t.pnl > 0)
        total_pnl = sum(t.pnl for t in trades)
        print(
            f"{'Gesamt':<12} {total_trades:>7} {total_wins / total_trades:>12.0%} "
            f"{total_pnl:>+11.2f}"
        )

        print("\nEinzeltrades (Zeiten in deutscher Ortszeit):")
        header = (
            f"{'Datum':<12} {'Ein':>8} {'Aus':>8} {'Dauer':>8} {'Symbol':<8} "
            f"{'Einstieg':>10} {'Ausstieg':>10} {'Stück':>10} {'P&L':>12} {'P&L%':>8}"
        )
        print(header)
        print("-" * len(header))
        for t in trades:
            entry_local = t.entry_time.astimezone(berlin)
            exit_local = t.exit_time.astimezone(berlin)
            print(
                f"{t.trading_day.isoformat():<12} {entry_local.strftime('%H:%M:%S'):>8} "
                f"{exit_local.strftime('%H:%M:%S'):>8} {_format_duration(t.duration):>8} {t.symbol:<8} "
                f"{t.entry_price:>10.4f} {t.exit_price:>10.4f} "
                f"{t.shares:>10.0f} {t.pnl:>+12.2f} {t.pnl_pct:>+7.1%}"
            )

        best = max(trades, key=lambda t: t.pnl)
        worst = min(trades, key=lambda t: t.pnl)
        print(f"\nBester Trade:  {best.symbol:<6} {best.pnl:>+10.2f} $ ({best.trading_day.isoformat()})")
        print(f"Schlechtester: {worst.symbol:<6} {worst.pnl:>+10.2f} $ ({worst.trading_day.isoformat()})")
    else:
        print("Keine abgeschlossenen Trades im Zeitraum (nur noch offene Positionen).")

    print("\nOffene Positionen (noch nicht geschlossen):")
    if open_positions:
        for p in open_positions:
            entry_local = p.entry_time.astimezone(berlin)
            print(
                f"  {p.symbol:<8} {p.shares:>10.0f} Stück, Einstieg {p.entry_price:>8.4f} "
                f"({entry_local.strftime('%Y-%m-%d %H:%M:%S')} deutsche Zeit)"
            )
    else:
        print("  (keine)")

    if unmatched_sells:
        print("\nVerkäufe ohne Kauf im Zeitraum (Position vor Zeitraumbeginn eröffnet, nicht im P&L enthalten):")
        for s in unmatched_sells:
            sell_local = s.time.astimezone(berlin)
            print(
                f"  {s.symbol:<8} {s.shares:>10.0f} Stück @ {s.price:>8.4f} "
                f"({sell_local.strftime('%Y-%m-%d %H:%M:%S')} deutsche Zeit) -- ggf. mit größerem --days auswerten"
            )

    print(
        "\nHinweis: P&L ist brutto (Kommissionen/Slippage nicht berücksichtigt -- im Paper-Modus "
        "ohnehin 0). Handelstag richtet sich nach dem Ausstiegszeitpunkt in America/New_York, "
        "unabhängig von der Server-Zeitzone."
    )


def _signed(value: float | None) -> str:
    return "-" if value is None else f"{value:+.2f}"


def cmd_momentum_compare(accounts: list[tuple[str, str]], days: int, tolerance_minutes: int = 3):
    """Vergleicht die Order-Historie mehrerer Paper-Konten (je ein Bot)
    nebeneinander -- ruft nur Daten ab, platziert keine Orders."""
    from datetime import datetime, timedelta, timezone
    from zoneinfo import ZoneInfo

    from alpaca.trading.client import TradingClient

    from tradingbot.report import (
        account_stats,
        fetch_closed_orders,
        group_by_trading_day,
        group_parallel_trades,
        match_trades,
        read_account_env,
    )

    if len(accounts) < 2:
        raise ValueError("Für einen Vergleich mindestens zwei Konten angeben (--account NAME=PFAD, mehrfach).")
    names = [name for name, _ in accounts]
    if len(set(names)) != len(names):
        raise ValueError(f"Kontonamen müssen eindeutig sein, waren {names}.")

    credentials = {name: read_account_env(path) for name, path in accounts}
    seen_keys: dict[str, str] = {}
    for name, (api_key, _, _) in credentials.items():
        if api_key in seen_keys:
            raise ValueError(
                f"{seen_keys[api_key]} und {name} nutzen dieselben API-Keys, also dasselbe Konto -- "
                "jeder Bot braucht ein eigenes Paper-Konto."
            )
        seen_keys[api_key] = name

    berlin = ZoneInfo("Europe/Berlin")
    until = datetime.now(timezone.utc)
    after = until - timedelta(days=days)

    trades_by_account = {}
    open_by_account = {}
    equity_by_account = {}
    for name, (api_key, secret_key, paper) in credentials.items():
        client = TradingClient(api_key, secret_key, paper=paper)
        trades, open_positions, _ = match_trades(fetch_closed_orders(client, after, until))
        trades_by_account[name] = trades
        open_by_account[name] = open_positions
        equity_by_account[name] = float(client.get_account().equity)

    stats = {name: account_stats(trades) for name, trades in trades_by_account.items()}
    width = max(12, *(len(n) for n in names))

    def row(label: str, values) -> str:
        return f"{label:<18}" + "".join(f"{v:>{width + 2}}" for v in values)

    print(f"=== Konto-Vergleich: letzte {days} Tag(e) ===\n")
    print(row("", names))
    print("-" * (18 + (width + 2) * len(names)))
    print(row("Konto-Equity", [f"{equity_by_account[n]:,.2f}" for n in names]))
    print(row("Trades", [stats[n].num_trades for n in names]))
    print(row("Trefferquote", [f"{stats[n].win_rate:.0%}" for n in names]))
    print(row("Netto-P&L", [f"{stats[n].net_pnl:+.2f}" for n in names]))
    print(row("Ø Gewinn", [_signed(stats[n].avg_win) for n in names]))
    print(row("Ø Verlust", [_signed(stats[n].avg_loss) for n in names]))
    print(row(
        "Profit-Faktor",
        ["-" if stats[n].num_trades == 0 else ("∞" if stats[n].profit_factor is None else f"{stats[n].profit_factor:.2f}")
         for n in names],
    ))
    print(row(
        "Ø Haltedauer",
        ["-" if stats[n].avg_duration is None else _format_duration(stats[n].avg_duration) for n in names],
    ))
    print(row("Offene Positionen", [len(open_by_account[n]) for n in names]))

    by_day = {name: group_by_trading_day(trades) for name, trades in trades_by_account.items()}
    all_days = sorted({d for days_ in by_day.values() for d in days_})
    if all_days:
        print("\nNetto-P&L pro Handelstag (Anzahl Trades):")
        print(row("Datum", names))
        for day in all_days:
            print(row(
                day.isoformat(),
                [f"{by_day[n][day].net_pnl:+.2f} ({by_day[n][day].num_trades})" if day in by_day[n] else "-"
                 for n in names],
            ))

    groups = group_parallel_trades(trades_by_account, timedelta(minutes=tolerance_minutes))
    if groups:
        print(
            f"\nSetups im Vergleich (gleiches Symbol, Einstieg innerhalb {tolerance_minutes} Min; "
            "P&L und Haltedauer, deutsche Zeit):"
        )
        print(f"{'Datum':<11} {'Ein':>5} {'Symbol':<7}" + "".join(f"{n:>{width + 8}}" for n in names))
        for group in groups:
            first = min(group.values(), key=lambda t: t.entry_time)
            entry_local = first.entry_time.astimezone(berlin)
            cells = [
                f"{group[n].pnl:+.2f} ({_format_duration(group[n].duration)})" if n in group else "-"
                for n in names
            ]
            print(
                f"{first.trading_day.isoformat():<11} {entry_local.strftime('%H:%M'):>5} {first.symbol:<7}"
                + "".join(f"{c:>{width + 8}}" for c in cells)
            )
        shared = sum(1 for g in groups if len(g) == len(names))
        print(
            f"\n{shared} Setup(s) von allen Konten gehandelt, {len(groups) - shared} nur von einem Teil "
            "(z.B. Kauf-Order nicht gefüllt, Positionslimit erreicht oder noch in einer Position)."
        )
    else:
        print("\nKeine abgeschlossenen Trades im Zeitraum.")

    print(
        "\nHinweis: Nur ausgeführte Orders; P&L brutto. Ein Unterschied an einzelnen Tagen ist Zufall "
        "-- erst über mehrere Handelstage aussagekräftig."
    )


def cmd_scan(
    config: Config,
    min_price: float,
    max_price: float,
    min_percent_change: float,
    min_relative_volume: float,
    relative_volume_lookback_days: int,
    require_news: bool,
    news_lookback_hours: int,
    top_movers: int,
    top_actives: int,
):
    from tradingbot.scanner import Scanner, ScanCriteria

    scanner = Scanner(config)
    criteria = ScanCriteria(
        min_price=min_price,
        max_price=max_price,
        min_percent_change=min_percent_change,
        min_relative_volume=min_relative_volume,
        relative_volume_lookback_days=relative_volume_lookback_days,
        require_news=require_news,
        news_lookback_hours=news_lookback_hours,
        top_movers=top_movers,
        top_actives=top_actives,
    )
    candidates = scanner.scan(criteria)

    print(
        f"Kriterien: Preis ${min_price:.2f}-${max_price:.2f}, "
        f"Tagesgewinn>={min_percent_change:.1f}%, Rel.Volumen>={min_relative_volume:.1f}x, "
        f"News-Pflicht={'ja' if require_news else 'nein'}"
    )
    print()
    if not candidates:
        print("Keine Kandidaten gefunden.")
        return

    print(f"{'Symbol':<8} {'Preis':>9} {'Tagesgewinn':>12} {'Rel.Vol':>9} {'News':>6} {'Quelle':<14}")
    print("-" * 62)
    for c in candidates:
        news = "?" if c.has_recent_news is None else ("ja" if c.has_recent_news else "nein")
        print(
            f"{c.symbol:<8} {c.price:>9.2f} {c.percent_change:>11.1f}% "
            f"{c.relative_volume:>8.1f}x {news:>6} {','.join(c.sources):<14}"
        )
    print(
        "\nHinweis: liefert nur den AKTUELLEN Marktzustand (Alpacas Screener-API kennt kein "
        "historisches Datum), rein lesend -- keine Order wird ausgelöst. Kein Float-Filter "
        "(siehe README). Symbol manuell in `momentum-backtest --symbol X` einsetzen, um es "
        "historisch zu prüfen."
    )


def cmd_momentum_run(
    config: Config,
    min_price: float,
    max_price: float,
    min_percent_change: float,
    scan_min_relative_volume: float,
    relative_volume_lookback_days: int,
    require_news: bool,
    news_lookback_hours: int,
    top_movers: int,
    top_actives: int,
    max_risk_dollars: float,
    reward_risk_ratio: float,
    min_relative_volume: float,
    lookback_days: int,
    daily_trend_window: int,
    flagpole_min_gain_pct: float,
    flagpole_max_bars: int,
    min_pullback_bars: int,
    max_pullback_bars: int,
    max_pullback_retrace_pct: float,
    extension_multiplier: float,
    max_concurrent_positions: int,
    max_tracked_symbols: int,
    daily_max_loss_pct: float,
    scan_interval_seconds: int,
    poll_interval_seconds: int,
    order_fill_timeout_seconds: int,
    order_poll_interval_seconds: float,
    flatten_minutes_before_close: int,
    allow_live_trading: bool = False,
    broker_stop_orders: bool = True,
    min_stop_pct: float = 0.02,
    max_position_dollars: float = 25_000.0,
    max_entry_slippage_pct: float = 0.01,
    weakness_exit: str = "red_candle",
    news_intel: bool = False,
    news_filter: str = "off",
    news_model: str | None = None,
    news_provider: str = "auto",
):
    from tradingbot.momentum_live import LiveMomentumBot, LiveMomentumConfig
    from tradingbot.scanner import ScanCriteria

    # Der Live-Momentum-Bot ist nur im Paper-Modus erprobt -- ein
    # versehentliches ALPACA_PAPER=false (z.B. eine .env eines anderen
    # Projekts) darf nicht unbemerkt mit echtem Geld handeln.
    if not config.paper and not allow_live_trading:
        raise RuntimeError(
            "momentum-run ist nur für Paper-Trading gedacht, aber ALPACA_PAPER=false ist gesetzt. "
            "Für echtes Geld zusätzlich --allow-live-trading angeben (auf eigenes Risiko)."
        )

    criteria = ScanCriteria(
        min_price=min_price,
        max_price=max_price,
        min_percent_change=min_percent_change,
        min_relative_volume=scan_min_relative_volume,
        relative_volume_lookback_days=relative_volume_lookback_days,
        require_news=require_news,
        news_lookback_hours=news_lookback_hours,
        top_movers=top_movers,
        top_actives=top_actives,
    )
    live_config = LiveMomentumConfig(
        max_risk_dollars=max_risk_dollars,
        reward_risk_ratio=reward_risk_ratio,
        min_relative_volume=min_relative_volume,
        lookback_days=lookback_days,
        daily_trend_window=daily_trend_window,
        flagpole_min_gain_pct=flagpole_min_gain_pct,
        flagpole_max_bars=flagpole_max_bars,
        min_pullback_bars=min_pullback_bars,
        max_pullback_bars=max_pullback_bars,
        max_pullback_retrace_pct=max_pullback_retrace_pct,
        extension_multiplier=extension_multiplier,
        max_concurrent_positions=max_concurrent_positions,
        max_tracked_symbols=max_tracked_symbols,
        daily_max_loss_pct=daily_max_loss_pct,
        scan_interval_seconds=scan_interval_seconds,
        poll_interval_seconds=poll_interval_seconds,
        order_fill_timeout_seconds=order_fill_timeout_seconds,
        order_poll_interval_seconds=order_poll_interval_seconds,
        flatten_minutes_before_close=flatten_minutes_before_close,
        broker_stop_orders=broker_stop_orders,
        min_stop_pct=min_stop_pct,
        max_position_dollars=max_position_dollars,
        max_entry_slippage_pct=max_entry_slippage_pct,
        weakness_exit=weakness_exit,
    )

    trading_mode_warning = (
        "nur für Paper-Trading gedacht."
        if config.paper
        else "!!! ECHTES GELD (--allow-live-trading gesetzt) !!! Nur im Paper-Modus erprobt."
    )
    print(
        f"Starte Live-Momentum-Bot (paper={config.paper}) -- Scanner alle {scan_interval_seconds}s, "
        f"Balken-Polling alle {poll_interval_seconds}s, max. {max_concurrent_positions} gleichzeitige "
        f"Positionen, Tages-Maximalverlust {daily_max_loss_pct:.1%}.\n"
        "ACHTUNG: siehe README für die Einschränkungen (IEX-Feed statt voller Marktabdeckung, kein "
        f"Zustand übersteht einen Neustart, kein Float-Filter) -- {trading_mode_warning} "
        "Mit Strg+C beenden.\n"
    )
    intel = None
    if news_intel:
        from alpaca.data.historical.news import NewsClient

        from tradingbot.news_intel import NewsIntel, NewsIntelConfig

        intel = NewsIntel(
            NewsIntelConfig(enabled=True, filter_mode=news_filter.replace("-", "_"), model=news_model,
                            provider=news_provider,
                            news_lookback_hours=news_lookback_hours),
            NewsClient(config.api_key, config.secret_key),
        )
        mode = "Filter: Verwässerung blockiert Einstiege" if news_filter != "off" else "Schatten: nur protokollieren"
        print(f"News-Intel aktiv ({intel.provider}, Modell {intel.model}, {mode}) -> news_intel.csv")
    bot = LiveMomentumBot(config, criteria, live_config, news_intel=intel)
    bot.run_forever()

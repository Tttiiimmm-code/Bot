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
"""

from __future__ import annotations

import argparse
import dataclasses
import logging
import math
import sys

from alpaca.common.exceptions import APIError

from tradingbot.bot import TradingBot
from tradingbot.broker import Broker
from tradingbot.config import Config
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


def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


def cmd_run(config: Config):
    bot = TradingBot(config)
    bot.run_forever()


def cmd_backtest(
    config: Config,
    days: int,
    commission_pct: float,
    slippage_pct: float,
    stop_loss_pct: float,
    take_profit_pct: float,
    risk_per_trade_pct: float,
    trend_window: int,
    rsi_window: int,
):
    from tradingbot.backtest import run_backtest

    broker = Broker(config)
    closes = broker.get_recent_closes(limit=days)
    if closes.empty:
        print(f"Keine historischen Daten für {config.symbol} erhalten.")
        return

    required_history = max(config.long_window, trend_window, rsi_window)
    if len(closes) < required_history + 1:
        print(
            f"Hinweis: {len(closes)} Handelstage geladen, aber long_window/trend_window/"
            f"rsi_window benötigen mindestens {required_history + 1} -- der Trendfilter/"
            f"RSI-Filter liefert dann nie einen gültigen Wert und es werden keine BUY-Signale "
            f"erzeugt (mehr --days verwenden oder --trend-window/--rsi-window verkleinern).\n"
        )

    result = run_backtest(
        closes,
        config.short_window,
        config.long_window,
        commission_pct=commission_pct,
        slippage_pct=slippage_pct,
        stop_loss_pct=stop_loss_pct,
        take_profit_pct=take_profit_pct,
        risk_per_trade_pct=risk_per_trade_pct,
        trend_window=trend_window,
        rsi_window=rsi_window,
    )
    num_stops = sum(1 for t in result.trades if t.side == "STOP")
    num_tp = sum(1 for t in result.trades if t.side == "TP")

    print(f"Symbol:          {config.symbol}")
    print(f"Zeitraum:        {closes.index[0].date()} - {closes.index[-1].date()} ({len(closes)} Tage)")
    print(f"Trades:          {result.num_trades} (davon {num_stops} Trailing-Stop, {num_tp} Take-Profit)")
    print(
        f"Stop-Loss:       {stop_loss_pct:.1%} unter Höchststand seit Einstieg (Trailing)"
        if stop_loss_pct > 0 else "Stop-Loss:       deaktiviert"
    )
    print(
        f"Take-Profit:     {take_profit_pct:.1%} über Einstiegspreis"
        if take_profit_pct > 0 else "Take-Profit:     deaktiviert"
    )
    if risk_per_trade_pct > 0 and stop_loss_pct > 0:
        print(f"Positionsgröße:  {risk_per_trade_pct:.1%} Kapitalrisiko pro Trade")
    elif risk_per_trade_pct > 0:
        # risk_per_trade_pct ohne stop_loss_pct ist nicht definiert
        # (kein Bezugspunkt für "Risiko") -- run_backtest fällt dann
        # still auf volles Kapital zurück, das muss hier auch so stehen.
        print("Positionsgröße:  volles Kapital pro Trade (RISK_PER_TRADE_PCT ohne STOP_LOSS_PCT ist wirkungslos)")
    else:
        print("Positionsgröße:  volles Kapital pro Trade")
    print(f"Trendfilter:     {trend_window}-Tage-SMA" if trend_window > 0 else "Trendfilter:     deaktiviert")
    print(f"RSI-Filter:      {rsi_window}-Tage-RSI > 50" if rsi_window > 0 else "RSI-Filter:      deaktiviert")
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
            if long_w > MAX_WINDOW:
                raise ValueError(f"{short_w}:{long_w} -- langes Fenster darf höchstens {MAX_WINDOW} sein")
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
    take_profit_pct: float,
    risk_per_trade_pct: float,
    trend_window: int,
    rsi_window: int,
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
        take_profit_pct=take_profit_pct,
        risk_per_trade_pct=risk_per_trade_pct,
        trend_window=trend_window,
        rsi_window=rsi_window,
    )

    evaluated = {(c.short_window, c.long_window) for c in result.all_candidates}
    skipped = [combo for combo in grid if combo not in evaluated]
    if skipped:
        skipped_str = ", ".join(f"{s}/{l}" for s, l in skipped)
        print(
            f"Hinweis: {skipped_str} übersprungen -- zu wenig Handelstage im "
            f"Trainingsabschnitt für diese Fenstergröße bzw. den Trend-/RSI-Filter "
            f"(mehr --days oder kleineres --train-ratio verwenden).\n"
        )

    print(f"Symbol:          {config.symbol}")
    print(
        f"Zeitraum:        {closes.index[0].date()} - {closes.index[-1].date()} "
        f"({len(closes)} Tage, Split am {result.split_date.date()}, train_ratio={train_ratio})"
    )
    print(
        f"Filter/Exits:    Trend={trend_window if trend_window else 'aus'}, "
        f"RSI={rsi_window if rsi_window else 'aus'}, "
        f"Stop={stop_loss_pct:.1%}, Take-Profit={take_profit_pct:.1%}, "
        f"Risiko/Trade={risk_per_trade_pct:.1%}"
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


def cmd_walkforward(
    config: Config,
    days: int,
    grid: list[tuple[int, int]],
    train_window: int,
    test_window: int,
    step: int | None,
    expanding: bool,
    commission_pct: float,
    slippage_pct: float,
    stop_loss_pct: float,
    take_profit_pct: float,
    risk_per_trade_pct: float,
    trend_window: int,
    rsi_window: int,
):
    from tradingbot.walkforward import walk_forward_validate

    broker = Broker(config)
    closes = broker.get_recent_closes(limit=days)
    if closes.empty:
        print(f"Keine historischen Daten für {config.symbol} erhalten.")
        return

    # validate() prüft jede Grid-Kombination einzeln und überspringt nur die,
    # die zu wenig Historie hat (siehe validation.py) -- der Lauf schlägt also
    # erst fehl, wenn SELBST die kleinste Kombination im Grid nicht genug
    # Trainingshistorie bekommt. min() statt max() über das Grid, sonst würde
    # dieser Hinweis fälschlich "der Lauf schlägt fehl" melden, obwohl eine
    # kleinere SMA-Kombination im selben Grid noch erfolgreich liefe.
    best_case_required_history = max(min(l for _, l in grid), trend_window, rsi_window)
    if train_window < best_case_required_history + 1:
        if expanding:
            # Bei --expanding wächst das Trainingsfenster mit jedem Schritt
            # (train_window + i*step) -- ein zu kleines ANFANGS-Fenster lässt
            # nur die ersten Fenster scheitern, spätere (größere) können
            # trotzdem funktionieren. Anders als bei rolling (feste
            # Fenstergröße über den ganzen Lauf) ist das kein Totalausfall.
            print(
                f"Hinweis: Das anfängliche --train-window {train_window} liegt unter den "
                f"benötigten {best_case_required_history + 1} Handelstagen (selbst für die "
                f"kleinste SMA-Kombination im Grid bzw. den Trend-/RSI-Filter) -- bei "
                f"--expanding werden deshalb nur die ersten Fenster übersprungen, bis das "
                f"wachsende Trainingsfenster groß genug ist.\n"
            )
        else:
            print(
                f"Hinweis: --train-window {train_window} liegt unter den benötigten "
                f"{best_case_required_history + 1} Handelstagen (selbst für die kleinste "
                f"SMA-Kombination im Grid bzw. den Trend-/RSI-Filter) -- jedes Zeitfenster wird "
                f"deshalb übersprungen und der Lauf schlägt fehl (--train-window vergrößern, "
                f"--trend-window/--rsi-window verkleinern oder eine kleinere SMA-Kombination "
                f"ins Grid aufnehmen).\n"
            )

    result = walk_forward_validate(
        closes,
        grid,
        train_window=train_window,
        test_window=test_window,
        step=step,
        expanding=expanding,
        commission_pct=commission_pct,
        slippage_pct=slippage_pct,
        stop_loss_pct=stop_loss_pct,
        take_profit_pct=take_profit_pct,
        risk_per_trade_pct=risk_per_trade_pct,
        trend_window=trend_window,
        rsi_window=rsi_window,
    )

    print(f"Symbol:          {config.symbol}")
    print(f"Zeitraum:        {closes.index[0].date()} - {closes.index[-1].date()} ({len(closes)} Tage)")
    print(
        f"Fenster:         Training={train_window}, Test={test_window}, "
        f"Schritt={step if step else test_window}, Modus={'expanding' if expanding else 'rolling'}"
    )
    print(
        f"Filter/Exits:    Trend={trend_window if trend_window else 'aus'}, "
        f"RSI={rsi_window if rsi_window else 'aus'}, "
        f"Stop={stop_loss_pct:.1%}, Take-Profit={take_profit_pct:.1%}, "
        f"Risiko/Trade={risk_per_trade_pct:.1%}"
    )
    print()
    print(f"{'#':>3} {'Training':^23} {'Test':^23} {'SMA':<8} {'Train':>9} {'Test':>9} {'Gap':>8}")
    print("-" * 92)
    for w in result.windows:
        best = w.result.best
        gap = best.test.return_pct - best.train.return_pct
        flag = " *" if gap < -10 else ""
        sma = f"{best.short_window}/{best.long_window}"
        print(
            f"{w.window_index:>3} "
            f"{best.train.start.date()!s:>10} - {best.train.end.date()!s:<10} "
            f"{best.test.start.date()!s:>10} - {best.test.end.date()!s:<10} "
            f"{sma:<8} "
            f"{best.train.return_pct:>+8.2f}% {best.test.return_pct:>+8.2f}% {gap:>+7.2f}{flag}"
        )

    print()
    print(f"Fenster gesamt:              {len(result.windows)}")
    print(f"Positive Testfenster:        {result.win_rate:.0%}")
    print(f"Mittelwert Testrendite:      {result.mean_test_return_pct:+.2f}%")
    print(f"Median Testrendite:          {result.median_test_return_pct:+.2f}%")
    if result.compounded_test_return_pct is not None:
        print(f"Verkettete Testrendite:      {result.compounded_test_return_pct:+.2f}% "
              f"(simuliert fortlaufendes Neu-Optimieren + Handeln nur im jeweils folgenden Testfenster)")
    else:
        print(
            "Verkettete Testrendite:      nicht verfügbar (Testfenster überlappen sich bei "
            "--step < --test-window -- Mittelwert/Median oben verwenden)"
        )
    print(
        "\nHinweis: '*' markiert Fenster mit Test-Train-Differenz < -10 Prozentpunkte "
        "(Overfitting-Warnsignal für dieses einzelne Fenster). Einzelne markierte Fenster sind "
        "normal; viele markierte Fenster oder eine stark negative verkettete Testrendite "
        "deuten darauf hin, dass die Parametersuche der Strategie nicht robust über "
        "verschiedene Marktphasen hinweg funktioniert."
    )


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
    bot = LiveMomentumBot(config, criteria, live_config)
    bot.run_forever()


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


def main():
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
        "--allow-live-trading", action="store_true",
        help="Erlaubt den Start mit ALPACA_PAPER=false (ECHTES Geld). Ohne dieses Flag bricht "
        "momentum-run im Live-Modus ab.",
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

    args = parser.parse_args()

    setup_logging()

    try:
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

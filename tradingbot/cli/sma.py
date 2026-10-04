"""Befehle des Referenz-Bots SMA-Crossover: run, backtest, validate, walkforward."""
from __future__ import annotations

import argparse

from tradingbot.bot import TradingBot
from tradingbot.broker import Broker
from tradingbot.config import Config
from tradingbot.strategy import MAX_WINDOW


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

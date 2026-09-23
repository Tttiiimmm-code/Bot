from __future__ import annotations

from datetime import date, datetime

import numpy as np
import pandas as pd
import pytest

from tradingbot.momentum import (
    BreakoutEvent,
    ExitReason,
    MomentumEngine,
    run_momentum_backtest,
    run_momentum_backtest_multi,
)


def _minute_index(day: date, n: int) -> pd.DatetimeIndex:
    start = datetime(day.year, day.month, day.day, 9, 30)
    idx = pd.date_range(start, periods=n, freq="1min", tz="America/New_York")
    return idx


def make_day(day: date, bars: list[dict]) -> pd.DataFrame:
    """bars: Liste von dicts mit open/high/low/close/volume, eine pro Minute
    ab 9:30 NY-Zeit."""
    idx = _minute_index(day, len(bars))
    return pd.DataFrame(bars, index=idx)


def flat_day(day: date, n: int, price: float, volume: float) -> pd.DataFrame:
    bars = [
        {"open": price, "high": price + 0.01, "low": price - 0.01, "close": price, "volume": volume}
        for _ in range(n)
    ]
    return make_day(day, bars)


def build_bars(days: dict[date, pd.DataFrame]) -> pd.DataFrame:
    return pd.concat([days[d] for d in sorted(days)]).sort_index()


# Zwei ruhige Vortage als Referenz für Relativvolumen (niedrig) und
# Trendfilter (Schlusskurs 10.00) -- von den meisten Tests wiederverwendet.
DAY_MINUS_2 = date(2024, 1, 8)
DAY_MINUS_1 = date(2024, 1, 9)
TODAY = date(2024, 1, 10)

COMMON_KWARGS = dict(
    lookback_days=2,
    daily_trend_window=2,
    flagpole_min_gain_pct=0.05,
    flagpole_max_bars=5,
    min_pullback_bars=2,
    max_pullback_bars=5,
    max_pullback_retrace_pct=0.5,
    min_relative_volume=2.0,
    reward_risk_ratio=2.0,
    max_risk_dollars=70.0,
    commission_pct=0.0,
    slippage_pct=0.0,
)


def bull_flag_setup_bars() -> list[dict]:
    """Klarer Bull-Flag: Swing-Tief 10.00 (Bar1) -> Flagpole auf 12.00 (Bar2,
    +20% auf hohem Volumen) -> 3 Pullback-Bars (Tief 11.30) -> Breakout-Bar
    (Bar5, Schluss 12.20 > Flagpole-Hoch) -> löst Entry aus.
    Stop = Pullback-Tief 11.30, Risiko/Aktie = 12.20-11.30 = 0.90.
    """
    return [
        {"open": 10.00, "high": 10.05, "low": 9.98, "close": 10.05, "volume": 50},  # bar0 (klar ueber Trend-SMA 10.00)
        {"open": 10.05, "high": 10.05, "low": 9.95, "close": 10.00, "volume": 50},  # bar1 (swing low)
        {"open": 10.00, "high": 12.05, "low": 9.99, "close": 12.00, "volume": 600},  # bar2 (flagpole)
        {"open": 12.00, "high": 12.00, "low": 11.60, "close": 11.70, "volume": 100},  # bar3 (pullback 1)
        {"open": 11.70, "high": 11.75, "low": 11.30, "close": 11.40, "volume": 100},  # bar4 (pullback 2)
        {"open": 11.40, "high": 12.25, "low": 11.35, "close": 12.20, "volume": 300},  # bar5 (breakout/entry)
    ]


def test_detects_bull_flag_and_enters_on_breakout():
    days = {
        DAY_MINUS_2: flat_day(DAY_MINUS_2, 10, 10.00, 50),
        DAY_MINUS_1: flat_day(DAY_MINUS_1, 10, 10.00, 50),
        TODAY: make_day(TODAY, bull_flag_setup_bars() + [
            {"open": 12.20, "high": 12.30, "low": 12.15, "close": 12.25, "volume": 50},  # bar6, hold
        ]),
    }
    bars = build_bars(days)

    result = run_momentum_backtest(bars, starting_cash=100_000.0, **COMMON_KWARGS)

    assert result.num_trades == 1
    trade = result.trades[0]
    assert trade.pattern == "BULL_FLAG"
    assert trade.entry_price == pytest.approx(12.20)
    assert trade.initial_stop_price == pytest.approx(11.30)
    # risk/share = 12.20 - 11.30 = 0.90; shares = floor(70 / 0.90) = 77
    assert trade.shares == 77


def test_relative_volume_below_threshold_blocks_entry():
    """Ohne das hohe Volumen in der Flagpole-Kerze (Kriterium 3: >= 2x
    relatives Volumen) darf kein Setup erkannt werden, selbst wenn der
    Kursanstieg für sich genommen groß genug wäre."""
    low_volume_setup = bull_flag_setup_bars()
    low_volume_setup[2]["volume"] = 60  # statt 600 -- kein erhöhtes Volumen
    days = {
        DAY_MINUS_2: flat_day(DAY_MINUS_2, 10, 10.00, 50),
        DAY_MINUS_1: flat_day(DAY_MINUS_1, 10, 10.00, 50),
        TODAY: make_day(TODAY, low_volume_setup),
    }
    bars = build_bars(days)

    result = run_momentum_backtest(bars, starting_cash=100_000.0, **COMMON_KWARGS)

    assert result.num_trades == 0


def test_daily_trend_filter_blocks_entries_when_below_sma():
    """Kriterium 2 (Tageschart über dem gleitenden Durchschnitt): startet
    die heutige Sitzung UNTER dem Schnitt der Vortage, darf kein Setup
    dieses Tages gehandelt werden, selbst wenn Muster+Volumen passen."""
    setup = bull_flag_setup_bars()
    days = {
        # Vortage mit deutlich höherem Schlusskurs als der heutige Start (10.00).
        DAY_MINUS_2: flat_day(DAY_MINUS_2, 10, 15.00, 50),
        DAY_MINUS_1: flat_day(DAY_MINUS_1, 10, 15.00, 50),
        TODAY: make_day(TODAY, setup),
    }
    bars = build_bars(days)

    result = run_momentum_backtest(bars, starting_cash=100_000.0, **COMMON_KWARGS)

    assert result.num_trades == 0


def test_insufficient_lookback_skips_early_days():
    """Mit lookback_days=2 braucht es 2 vorangehende Tage für den
    Relativvolumen-Vergleich -- der allererste Tag im Datensatz hat keine
    Vortage und muss übersprungen werden (kein Absturz, keine Trades)."""
    days = {
        TODAY: make_day(TODAY, bull_flag_setup_bars()),
    }
    bars = build_bars(days)

    result = run_momentum_backtest(bars, starting_cash=100_000.0, **COMMON_KWARGS)

    assert result.num_trades == 0
    assert result.days_skipped_insufficient_lookback == 1
    assert result.days_evaluated == 0


def _entered_trade_bars(after_entry: list[dict]) -> pd.DataFrame:
    days = {
        DAY_MINUS_2: flat_day(DAY_MINUS_2, 10, 10.00, 50),
        DAY_MINUS_1: flat_day(DAY_MINUS_1, 10, 10.00, 50),
        TODAY: make_day(TODAY, bull_flag_setup_bars() + after_entry),
    }
    return build_bars(days)


def test_stop_loss_exit_closes_full_position():
    """Fällt der Kurs nach Einstieg unter den Pullback-Tief-Stop, wird die
    GESAMTE Position zum Stop-Preis verkauft."""
    bars = _entered_trade_bars([
        {"open": 12.20, "high": 12.20, "low": 11.20, "close": 11.25, "volume": 100},  # unter Stop 11.30
    ])

    result = run_momentum_backtest(bars, starting_cash=100_000.0, **COMMON_KWARGS)

    assert result.num_trades == 1
    trade = result.trades[0]
    assert len(trade.exits) == 1
    exit_ = trade.exits[0]
    assert exit_.reason == ExitReason.STOP
    assert exit_.price == pytest.approx(11.30)
    assert exit_.shares == trade.shares


def test_stop_loss_on_gap_below_stop_fills_at_open_not_stop():
    """Regression: eröffnet der Balken bereits UNTER dem Stop (Kurslücke),
    war der Stop-Preis nie handelbar -- der Backtest verbuchte trotzdem den
    Stop-Preis und schönte so den Verlust. Realistischer Fill: Eröffnung."""
    bars = _entered_trade_bars([
        {"open": 11.00, "high": 11.05, "low": 10.90, "close": 11.00, "volume": 100},  # Gap unter Stop 11.30
    ])

    result = run_momentum_backtest(bars, starting_cash=100_000.0, **COMMON_KWARGS)

    assert result.num_trades == 1
    exit_ = result.trades[0].exits[0]
    assert exit_.reason == ExitReason.STOP
    assert exit_.price == pytest.approx(11.00)


def test_red_candle_exit_before_target_closes_full_position():
    """Erste rote Kerze VOR Erreichen des 2:1-Ziels ist ein
    Voll-Ausstiegssignal (Exit Indicator #2 im Artikel)."""
    bars = _entered_trade_bars([
        {"open": 12.20, "high": 12.22, "low": 12.05, "close": 12.10, "volume": 100},  # rote Kerze, kein Stop
    ])

    result = run_momentum_backtest(bars, starting_cash=100_000.0, **COMMON_KWARGS)

    assert result.num_trades == 1
    trade = result.trades[0]
    assert len(trade.exits) == 1
    assert trade.exits[0].reason == ExitReason.RED_CANDLE
    assert trade.exits[0].price == pytest.approx(12.10)
    assert trade.exits[0].shares == trade.shares


def test_target_hit_sells_half_and_moves_stop_to_breakeven():
    """Ziel = Einstieg + 2*Risiko = 12.20 + 2*0.90 = 14.00. Bei Erreichen
    wird die Hälfte verkauft und der Stop auf den Einstiegspreis gezogen."""
    bars = _entered_trade_bars([
        {"open": 12.20, "high": 14.10, "low": 12.15, "close": 14.00, "volume": 200},  # Ziel erreicht
        {"open": 14.00, "high": 14.20, "low": 13.90, "close": 14.10, "volume": 100},  # danach kein Trigger
    ])

    result = run_momentum_backtest(bars, starting_cash=100_000.0, **COMMON_KWARGS)

    assert result.num_trades == 1
    trade = result.trades[0]
    target_exits = [e for e in trade.exits if e.reason == ExitReason.TARGET]
    assert len(target_exits) == 1
    assert target_exits[0].price == pytest.approx(14.00)
    assert target_exits[0].shares == trade.shares // 2
    # Rest wird am Sitzungsende zwangsgeschlossen (letzte Bar des Tages).
    eod_exits = [e for e in trade.exits if e.reason == ExitReason.END_OF_DAY]
    assert len(eod_exits) == 1
    assert eod_exits[0].shares == trade.shares - trade.shares // 2


def test_target_and_extension_can_both_fire_on_the_same_bar():
    """Regressionstest (beim Umbau auf MomentumEngine gefunden): Ziel-
    Teilverkauf UND ein Extension-Bar-Ausstieg des Rests können auf
    DEMSELBEN Balken zutreffen (ein extrem starker Balken kann sowohl das
    Ziel reißen als auch selbst als Extension Bar gelten). avg_bar_range
    der 3 Pullback-Bars (0.40, 0.45, 0.90) ist 0.5833; mit
    extension_multiplier=4.0 braucht es eine Balkenspanne >= 2.333.
    Konstruiert: high=14.60 (Ziel 14.00 klar erreicht), low=12.20
    (Spanne 2.40 >= 2.333), close=14.50 (> Einstieg 12.20)."""
    bars = _entered_trade_bars([
        {"open": 12.20, "high": 14.60, "low": 12.20, "close": 14.50, "volume": 500},
    ])

    result = run_momentum_backtest(bars, starting_cash=100_000.0, **COMMON_KWARGS)

    assert result.num_trades == 1
    trade = result.trades[0]
    assert len(trade.exits) == 2
    target_exit, extension_exit = trade.exits
    assert target_exit.reason == ExitReason.TARGET
    assert target_exit.price == pytest.approx(14.00)
    assert target_exit.shares == trade.shares // 2
    assert extension_exit.reason == ExitReason.EXTENSION
    assert extension_exit.price == pytest.approx(14.50)
    assert extension_exit.shares == trade.shares - trade.shares // 2
    assert trade.shares_closed == trade.shares


def test_holds_through_red_candle_after_breakeven_stop_set():
    """Nach Teilverkauf (Breakeven-Stop gesetzt) hält die Position durch
    rote Kerzen hindurch, solange der Breakeven-Stop nicht ausgelöst wird
    (Exit Indicator #2: 'hold through red candles as long as breakeven
    stop doesn't hit')."""
    bars = _entered_trade_bars([
        {"open": 12.20, "high": 14.10, "low": 12.15, "close": 14.00, "volume": 200},  # Ziel, Teilverkauf
        {"open": 14.00, "high": 14.05, "low": 13.50, "close": 13.60, "volume": 100},  # rote Kerze, aber ueber Breakeven
    ])

    result = run_momentum_backtest(bars, starting_cash=100_000.0, **COMMON_KWARGS)

    trade = result.trades[0]
    # Keine RED_CANDLE-Exits -- nur TARGET (Teilverkauf) und END_OF_DAY (Rest).
    reasons = [e.reason for e in trade.exits]
    assert ExitReason.RED_CANDLE not in reasons
    assert ExitReason.TARGET in reasons
    assert ExitReason.END_OF_DAY in reasons


def test_end_of_day_forces_close_of_open_position():
    bars = _entered_trade_bars([
        {"open": 12.20, "high": 12.30, "low": 12.10, "close": 12.25, "volume": 100},  # letzte Bar, kein Trigger
    ])

    result = run_momentum_backtest(bars, starting_cash=100_000.0, **COMMON_KWARGS)

    trade = result.trades[0]
    assert len(trade.exits) == 1
    assert trade.exits[0].reason == ExitReason.END_OF_DAY
    assert trade.exits[0].price == pytest.approx(12.25)
    assert trade.exits[0].shares == trade.shares


def test_entry_on_final_bar_of_day_is_still_recorded_and_closed():
    """Regressionstest: löst der Breakout-Einstieg selbst auf dem LETZTEN
    Balken des Tages aus, greift die reguläre END_OF_DAY-Zwangsschließung
    innerhalb der Schleife nicht mehr (die prüft nur bereits offene
    Positionen BEIM BETRETEN eines Balkens). Ohne das Sicherheitsnetz nach
    der Schleife verschwindet die Position lautlos aus dem Trade-Log,
    obwohl das Kapital dafür bereits abgebucht wurde ('Phantom'-Position,
    final_equity wäre um den Einstiegsbetrag zu niedrig ohne zugehörigen
    Trade-Eintrag)."""
    days = {
        DAY_MINUS_2: flat_day(DAY_MINUS_2, 10, 10.00, 50),
        DAY_MINUS_1: flat_day(DAY_MINUS_1, 10, 10.00, 50),
        # bull_flag_setup_bars() hat 6 Balken (Index 0-5), der Breakout/
        # Einstieg löst exakt auf dem letzten (Index 5) aus.
        TODAY: make_day(TODAY, bull_flag_setup_bars()),
    }
    bars = build_bars(days)

    result = run_momentum_backtest(bars, starting_cash=100_000.0, **COMMON_KWARGS)

    assert result.num_trades == 1
    trade = result.trades[0]
    assert len(trade.exits) == 1
    assert trade.exits[0].reason == ExitReason.END_OF_DAY
    assert trade.exits[0].shares == trade.shares
    # Cash-Konsistenz: Endkapital muss den vollständigen Rundtrip (Einstieg
    # UND sofortiger Zwangsausstieg zum selben Kurs) widerspiegeln, nicht
    # nur den Kapitalabfluss des Einstiegs ohne Gegenbuchung.
    assert result.final_equity == pytest.approx(100_000.0 + trade.gross_pnl, rel=1e-9)


def test_risk_cap_is_not_bypassed_when_risk_per_share_exceeds_max_risk_dollars():
    """Regressionstest: wenn schon das Risiko EINER Aktie max_risk_dollars
    übersteigt, muss das Setup übersprungen werden -- NICHT stattdessen mit
    dem gesamten verfügbaren Kapital gekauft werden (das würde die
    Risikobegrenzung faktisch aushebeln). risk/share hier = 12.20-11.30 =
    0.90; mit max_risk_dollars=0.50 ist risk_based_shares = 0."""
    days = {
        DAY_MINUS_2: flat_day(DAY_MINUS_2, 10, 10.00, 50),
        DAY_MINUS_1: flat_day(DAY_MINUS_1, 10, 10.00, 50),
        TODAY: make_day(TODAY, bull_flag_setup_bars()),
    }
    bars = build_bars(days)
    kwargs = dict(COMMON_KWARGS)
    kwargs["max_risk_dollars"] = 0.50

    result = run_momentum_backtest(bars, starting_cash=100_000.0, **kwargs)

    assert result.num_trades == 0


def test_second_trade_same_day_sizes_against_remaining_not_stale_cash():
    """Regressionstest: available_cash für die Positionsgrößen-Berechnung
    darf sich nicht auf das Kapital zu TAGESBEGINN beziehen, sondern muss
    den Cash-Verbrauch/-Zufluss vorheriger Trades DESSELBEN Tages
    berücksichtigen. Szenario: Trade 1 (77 Stück @ 12.20) verliert am Stop
    (-69.30 zzgl. Kosten), Trade 2 (risikobasiert würden 82 Stück @ 13.65
    verlangt) muss bei knappem Startkapital auf das tatsächlich noch
    verfügbare Cash gedeckelt werden -- verifiziert per Reproduktion: bei
    starting_cash=1000 wird Trade 2 korrekt auf 68 statt 82 Stück gedeckelt
    (68*13.65=928.20, innerhalb des nach Trade 1 verbleibenden Caps),
    während bei reichlich Kapital (100000) Trade 2 die vollen 82 Stück
    bekommt."""
    seg_a = bull_flag_setup_bars() + [
        {"open": 12.20, "high": 12.20, "low": 11.20, "close": 11.25, "volume": 100},  # STOP
    ]
    seg_b = [
        {"open": 11.25, "high": 13.55, "low": 11.24, "close": 13.50, "volume": 900},  # Flagpole
        {"open": 13.50, "high": 13.50, "low": 13.00, "close": 13.10, "volume": 150},  # Pullback 1
        {"open": 13.10, "high": 13.15, "low": 12.80, "close": 12.90, "volume": 150},  # Pullback 2
        {"open": 12.90, "high": 13.70, "low": 12.85, "close": 13.65, "volume": 400},  # Breakout/Entry
        {"open": 13.65, "high": 13.70, "low": 13.60, "close": 13.68, "volume": 100},  # EOD
    ]
    days = {
        DAY_MINUS_2: flat_day(DAY_MINUS_2, 12, 10.00, 50),
        DAY_MINUS_1: flat_day(DAY_MINUS_1, 12, 10.00, 50),
        TODAY: make_day(TODAY, seg_a + seg_b),
    }
    bars = build_bars(days)

    plenty = run_momentum_backtest(bars, starting_cash=100_000.0, **COMMON_KWARGS)
    assert plenty.num_trades == 2
    assert plenty.trades[1].shares == 82

    constrained = run_momentum_backtest(bars, starting_cash=1000.0, **COMMON_KWARGS)
    assert constrained.num_trades == 2
    assert constrained.trades[1].shares == 68
    # Kerninvariante: nie mehr ausgeben, als tatsächlich verfügbar ist.
    assert constrained.final_equity >= 0


def test_flat_top_classification_excludes_breakout_bar_own_high():
    """Regressionstest: die Flat-Top/Bull-Flag-Klassifizierung verglich
    bisher auch das Hoch des BREAKOUT-Balkens selbst in der Pullback-
    Flachheitsprüfung -- der ist per Definition höher als das Pullback-
    Plateau (sonst wäre es kein Breakout), was eine echte Flat-Top-
    Formation fälschlich als Bull Flag eingestuft hätte. Szenario: zwei
    Pullback-Bars mit fast identischem Hoch (flaches Plateau bei ~11.70),
    danach Breakout deutlich darüber."""
    setup = bull_flag_setup_bars()
    # Pullback-Hochs eng beieinander (flaches Plateau ~11.70/11.71).
    setup[3] = {"open": 12.00, "high": 11.70, "low": 11.60, "close": 11.65, "volume": 100}
    setup[4] = {"open": 11.65, "high": 11.71, "low": 11.50, "close": 11.60, "volume": 100}
    setup[5] = {"open": 11.60, "high": 12.25, "low": 11.55, "close": 12.20, "volume": 300}
    days = {
        DAY_MINUS_2: flat_day(DAY_MINUS_2, 10, 10.00, 50),
        DAY_MINUS_1: flat_day(DAY_MINUS_1, 10, 10.00, 50),
        TODAY: make_day(TODAY, setup),
    }
    bars = build_bars(days)

    result = run_momentum_backtest(bars, starting_cash=100_000.0, **COMMON_KWARGS)

    assert result.num_trades == 1
    assert result.trades[0].pattern == "FLAT_TOP"


def test_single_bar_pullback_defaults_to_bull_flag_not_flat_top():
    """Regressionstest: mit min_pullback_bars=1 kann ein Breakout schon
    nach genau einem Pullback-Bar auslösen -- dann bleibt nach Ausschluss
    des Breakout-Balkens KEIN Vergleichs-Bar für die Flach-Prüfung übrig.
    Der alte `... or pullback_highs`-Fallback griff dann auf das
    Breakout-Hoch selbst zurück (Differenz zu sich selbst immer 0), was
    JEDEN Ein-Bar-Pullback fälschlich als FLAT_TOP eingestuft hätte. Mit
    < 2 Vergleichs-Bars ist 'flach' nicht beurteilbar -- Standard BULL_FLAG."""
    setup = bull_flag_setup_bars()
    # Nur EIN Pullback-Bar (Index 3), danach direkter Breakout (Index 4).
    setup = setup[:3] + [
        {"open": 12.00, "high": 12.00, "low": 11.30, "close": 11.70, "volume": 100},  # einziger Pullback-Bar
        {"open": 11.70, "high": 12.25, "low": 11.65, "close": 12.20, "volume": 300},  # Breakout/Entry
    ]
    days = {
        DAY_MINUS_2: flat_day(DAY_MINUS_2, 10, 10.00, 50),
        DAY_MINUS_1: flat_day(DAY_MINUS_1, 10, 10.00, 50),
        TODAY: make_day(TODAY, setup),
    }
    bars = build_bars(days)
    kwargs = dict(COMMON_KWARGS)
    kwargs["min_pullback_bars"] = 1

    result = run_momentum_backtest(bars, starting_cash=100_000.0, **kwargs)

    assert result.num_trades == 1
    assert result.trades[0].pattern == "BULL_FLAG"


def test_total_costs_includes_entry_side_slippage_not_only_commission():
    """Regressionstest: total_costs zählte beim EINSTIEG nur die Provision,
    nicht die Slippage-Komponente -- obwohl der Verkaufspfad (über
    _execute_sell) beides korrekt einrechnet. Mit commission_pct=0 und
    slippage_pct>0 muss total_costs trotzdem > 0 sein (allein aus der
    Einstiegs-Slippage)."""
    days = {
        DAY_MINUS_2: flat_day(DAY_MINUS_2, 10, 10.00, 50),
        DAY_MINUS_1: flat_day(DAY_MINUS_1, 10, 10.00, 50),
        TODAY: make_day(TODAY, bull_flag_setup_bars()),
    }
    bars = build_bars(days)
    kwargs = dict(COMMON_KWARGS)
    kwargs["commission_pct"] = 0.0
    kwargs["slippage_pct"] = 0.001

    result = run_momentum_backtest(bars, starting_cash=100_000.0, **kwargs)

    assert result.num_trades == 1
    trade = result.trades[0]
    expected_entry_slippage = (trade.entry_price - 12.20) * trade.shares
    assert expected_entry_slippage > 0
    assert result.total_costs >= expected_entry_slippage


def test_rejects_reversed_trading_window():
    from datetime import time as dt_time

    days = {TODAY: flat_day(TODAY, 5, 10.0, 50)}
    bars = build_bars(days)
    with pytest.raises(ValueError, match="trading_window"):
        run_momentum_backtest(
            bars, trading_window_start=dt_time(15, 0), trading_window_end=dt_time(9, 30)
        )


def test_days_evaluated_excludes_days_with_insufficient_trend_history():
    """Regressionstest: days_evaluated zählte bisher Tage mit, die zwar
    genug Vortage für das Relativvolumen hatten, aber noch nicht für den
    daily_trend_window-SMA (NaN) -- solche Tage können _daily_trend_ok nie
    erfüllen und liefern garantiert 0 Trades, dürfen also nicht als
    'ausgewertet' gezählt werden. lookback_days=2 < daily_trend_window=5
    erzwingt genau diese Lücke."""
    days = {}
    for offset in range(6):
        d = date(2024, 1, 8 + offset)
        days[d] = flat_day(d, 5, 10.00, 50)
    bars = build_bars(days)

    result = run_momentum_backtest(
        bars, starting_cash=100_000.0, lookback_days=2, daily_trend_window=5
    )

    # Tage 0-1: lookback fehlt. Tage 2-4: lookback ok, aber SMA(5) via
    # shift(1) braucht 5 Vortage -> erst ab Tag 5 (Index 5) erfuellt.
    assert result.days_skipped_insufficient_lookback == 2
    assert result.days_skipped_insufficient_trend_history == 3
    assert result.days_evaluated == 1


@pytest.mark.parametrize(
    "override,message_substr",
    [
        ({"reward_risk_ratio": 0.0}, "reward_risk_ratio"),
        ({"min_relative_volume": -1.0}, "min_relative_volume"),
        ({"daily_trend_window": 0}, "daily_trend_window"),
        ({"flagpole_min_gain_pct": 0.0}, "flagpole_min_gain_pct"),
        ({"flagpole_max_bars": 0}, "flagpole_max_bars"),
        ({"min_pullback_bars": 0}, "min_pullback_bars"),
        ({"min_pullback_bars": 5, "max_pullback_bars": 2}, "min_pullback_bars"),
        ({"max_pullback_retrace_pct": 1.0}, "max_pullback_retrace_pct"),
        ({"extension_multiplier": 0.0}, "extension_multiplier"),
    ],
)
def test_rejects_invalid_strategy_parameters(override, message_substr):
    days = {TODAY: flat_day(TODAY, 5, 10.0, 50)}
    bars = build_bars(days)
    with pytest.raises(ValueError, match=message_substr):
        run_momentum_backtest(bars, **override)


def test_rejects_invalid_bars_missing_columns():
    bad_bars = pd.DataFrame(
        {"close": [1.0, 2.0]}, index=pd.date_range("2024-01-01 09:30", periods=2, freq="1min", tz="America/New_York")
    )
    with pytest.raises(ValueError):
        run_momentum_backtest(bad_bars)


def test_rejects_non_positive_max_risk_dollars():
    days = {TODAY: flat_day(TODAY, 5, 10.0, 50)}
    bars = build_bars(days)
    with pytest.raises(ValueError):
        run_momentum_backtest(bars, max_risk_dollars=0.0)


def test_end_to_end_smoke_on_realistic_random_walk_minute_data():
    """Integrations-Smoke-Test ohne konstruiertes Setup: realistische
    (random-walk) Minutendaten über mehrere Tage -- stellt sicher, dass
    der Zustandsautomat nicht abstürzt und ein plausibles Ergebnis liefert,
    unabhängig davon ob zufällig ein Muster erkannt wird."""
    rng = np.random.default_rng(7)
    days_data = {}
    base_price = 20.0
    for offset in range(15):
        day = date(2024, 2, 1 + offset) if offset < 27 else date(2024, 2, 28)
        n = 60
        returns = rng.normal(0, 0.004, size=n)
        closes = base_price * np.cumprod(1 + returns)
        opens = np.roll(closes, 1)
        opens[0] = base_price
        highs = np.maximum(opens, closes) * (1 + np.abs(rng.normal(0, 0.001, size=n)))
        lows = np.minimum(opens, closes) * (1 - np.abs(rng.normal(0, 0.001, size=n)))
        volumes = rng.uniform(50, 5000, size=n)
        bars = [
            {"open": opens[j], "high": highs[j], "low": lows[j], "close": closes[j], "volume": volumes[j]}
            for j in range(n)
        ]
        days_data[day] = make_day(day, bars)
        base_price = closes[-1]

    bars = build_bars(days_data)

    result = run_momentum_backtest(
        bars,
        starting_cash=100_000.0,
        lookback_days=5,
        daily_trend_window=5,
    )

    assert np.isfinite(result.final_equity)
    assert np.isfinite(result.total_return_pct)
    assert result.days_evaluated + result.days_skipped_insufficient_lookback == 15
    for trade in result.trades:
        assert trade.shares_closed == trade.shares
        assert trade.entry_price > 0


def _make_engine() -> MomentumEngine:
    return MomentumEngine(
        flagpole_min_gain_pct=0.05,
        flagpole_max_bars=5,
        min_pullback_bars=2,
        max_pullback_bars=5,
        max_pullback_retrace_pct=0.5,
        reward_risk_ratio=2.0,
        extension_multiplier=4.0,
        min_relative_volume=2.0,
    )


def _feed(engine: MomentumEngine, bars: list[tuple[float, float, float, float]]) -> list:
    """Speist (open, high, low, close)-Kerzen im Minutentakt ab 9:30 ein
    (im Handelsfenster, Trend ok, hohes Rel.Volumen) und gibt alle
    Ereignisse zurück. Ein BreakoutEvent wird abgelehnt, damit die Engine
    weiterlaufen kann."""
    events = []
    base = pd.Timestamp("2024-01-10 09:30")
    for i, (o, h, lo, c) in enumerate(bars):
        for event in engine.process_bar(
            base + pd.Timedelta(minutes=i), o, h, lo, c, 1000,
            in_window=True, relative_volume=5.0, daily_trend_ok=True,
        ):
            events.append(event)
            if isinstance(event, BreakoutEvent):
                engine.decline_entry()
    return events


def _live_like_engine(**overrides) -> MomentumEngine:
    params = dict(
        flagpole_min_gain_pct=0.03, flagpole_max_bars=15, min_pullback_bars=2, max_pullback_bars=5,
        max_pullback_retrace_pct=0.5, reward_risk_ratio=2.0, extension_multiplier=4.0, min_relative_volume=2.0,
    )
    params.update(overrides)
    return MomentumEngine(**params)


def test_no_breakout_on_first_weak_candle_after_pole_high_grml_2026_09_23():
    """Regressionstest mit den echten GRML-Kerzen vom 23.09. (IEX): die
    alte Logik kaufte 15:45 bei 16.03 -- eine Kerze mit TIEFEREM Hoch und
    Schluss als die Vorkerze (16.25), also die erste Schwäche nach dem
    Hoch. 15:44 lief über die Flaggenstange hinaus und wurde trotzdem als
    "Pullback-Kerze" gezählt."""
    bars = [
        (15.335, 15.565, 15.29, 15.40),
        (15.46, 15.46, 15.25, 15.25),   # Swing-Tief
        (15.74, 15.83, 15.74, 15.76),   # Flaggenstange (+3.3%)
        (15.83, 16.25, 15.82, 16.25),   # Fortsetzung -- kein Rücksetzer
        (16.09, 16.09, 15.96, 16.03),   # erste Schwächekerze -- kein Breakout
    ]
    assert _feed(_live_like_engine(), bars) == []


def test_no_breakout_on_sideways_bars_without_pullback_mss_2026_09_23():
    """Regressionstest mit den echten MSS-Kerzen vom 23.09. (IEX): die
    "Pullback-Kerzen" 2.17/2.16/2.18 liefen seitwärts, ohne je unter die
    Flaggenstange zurückzugehen -- alte Logik kaufte bei 2.18 mit Stop 2.16
    (1% unter Einstieg, im Rauschen)."""
    bars = [
        (2.19, 2.19, 2.03, 2.06),   # Swing-Tief
        (2.11, 2.16, 2.11, 2.16),   # Flaggenstange (+4.9%)
        (2.17, 2.18, 2.17, 2.17),   # neues Hoch -- Stange läuft weiter
        (2.16, 2.16, 2.16, 2.16),
        (2.18, 2.18, 2.18, 2.18),
    ]
    assert _feed(_live_like_engine(), bars) == []


def test_breakout_requires_close_above_previous_candle_high():
    """Nach 2 echten Rücksetzer-Kerzen löst erst die Kerze aus, die über dem
    Hoch der VORKERZE schließt -- ein Schluss nur über dem Flaggenstangen-
    Schluss (alte Regel) reicht nicht."""
    engine = _make_engine()
    bars = [
        (10.00, 10.05, 9.98, 10.05),
        (10.05, 10.05, 9.95, 10.00),    # Swing-Tief
        (10.00, 12.05, 9.99, 12.00),    # Flaggenstange, Hoch 12.05
        (12.00, 12.00, 11.60, 11.70),   # Rücksetzer 1
        (11.70, 11.90, 11.30, 11.40),   # Rücksetzer 2, Hoch 11.90
        (11.40, 11.95, 11.35, 11.85),   # Schluss 11.85 < Vorkerzenhoch 11.90
    ]
    assert _feed(engine, bars) == []

    events = _feed(engine, [(11.85, 12.10, 11.80, 12.05)])  # Schluss > Vorkerzenhoch 11.95
    assert len(events) == 1
    assert isinstance(events[0], BreakoutEvent)
    assert events[0].stop_price == pytest.approx(11.30)
    assert events[0].pullback_bars == 3


def test_new_high_during_pullback_extends_pole_and_restarts_pullback():
    """Eine Kerze mit neuem Hoch über der Flaggenstange (ohne Breakout-
    Bestätigung) ist die Fortsetzung der Stange: der Rücksetzer beginnt von
    vorn, der Stop kommt nur aus den Rücksetzer-Kerzen DANACH."""
    engine = _make_engine()
    bars = [
        (10.05, 10.05, 9.95, 10.00),    # Swing-Tief
        (10.00, 12.05, 9.99, 12.00),    # Flaggenstange
        (12.00, 12.00, 11.50, 11.60),   # Rücksetzer 1 (Tief 11.50)
        (11.60, 12.40, 11.60, 11.65),   # neues Stangen-Hoch 12.40, Schluss < Vorkerzenhoch -> Neustart
        (11.65, 12.30, 11.70, 12.10),   # Rücksetzer 1 (neu)
        (12.10, 12.20, 11.90, 12.00),   # Rücksetzer 2 (neu)
        (12.00, 12.35, 11.95, 12.30),   # Schluss 12.30 > Vorkerzenhoch 12.20 -> Breakout
    ]
    events = _feed(engine, bars)
    assert len(events) == 1
    assert events[0].stop_price == pytest.approx(11.70)  # nicht 11.50 aus dem ersten Rücksetzer


def _entered_engine(weakness_exit: str) -> MomentumEngine:
    engine = _live_like_engine(weakness_exit=weakness_exit)
    t = pd.Timestamp("2024-01-10 09:35")
    engine._pending_breakout = BreakoutEvent("BULL_FLAG", t, 10.00, 9.50, 0.50)
    engine.record_entry(100, 10.00, t)
    engine.process_bar(t, 9.90, 10.10, 9.90, 10.05, 1000, in_window=True, relative_volume=5.0, daily_trend_ok=True)
    return engine


def test_new_low_exit_ignores_red_candle_without_lower_low():
    engine = _entered_engine("new_low")
    events = engine.process_bar(
        pd.Timestamp("2024-01-10 09:37"), 10.10, 10.15, 9.95, 10.00, 1000,
        in_window=True, relative_volume=5.0, daily_trend_ok=True,
    )
    assert events == []  # rot, aber Tief 9.95 >= Vorkerzentief 9.90


def test_new_low_exit_fires_when_low_breaks_previous_low():
    engine = _entered_engine("new_low")
    events = engine.process_bar(
        pd.Timestamp("2024-01-10 09:37"), 10.00, 10.20, 9.85, 10.15, 1000,
        in_window=True, relative_volume=5.0, daily_trend_ok=True,
    )
    assert len(events) == 1
    assert events[0].reason == ExitReason.NEW_LOW  # grün, aber Tief 9.85 < 9.90
    assert events[0].reference_price == pytest.approx(10.15)


def test_red_candle_exit_remains_default():
    engine = _entered_engine("red_candle")
    events = engine.process_bar(
        pd.Timestamp("2024-01-10 09:37"), 10.10, 10.15, 9.95, 10.00, 1000,
        in_window=True, relative_volume=5.0, daily_trend_ok=True,
    )
    assert [e.reason for e in events] == [ExitReason.RED_CANDLE]


def test_invalid_weakness_exit_is_rejected():
    with pytest.raises(ValueError, match="weakness_exit"):
        _live_like_engine(weakness_exit="green_candle")


def test_record_exit_partial_without_target_does_not_move_stop_to_breakeven():
    """Regressionstest: ein Teil-Fill, der NICHT von einem TARGET-Treffer
    stammt (z.B. eine STOP-Order, die bei dünner Liquidität nur teilweise
    ausgeführt wird, bevor sie storniert wird -- siehe
    momentum_live.py._record_broker_stop_fill/_reconcile_terminal_exit_order),
    darf den Stop NICHT auf Breakeven anheben. Der ursprüngliche (bereits
    verletzte) Stop muss bestehen bleiben, sonst wäre die Restposition bis
    zum nächsten Balken fälschlich als "abgesichert" markiert, obwohl der
    Kurs schon unter dem echten Stop liegt."""
    engine = _make_engine()
    entry_time = pd.Timestamp("2024-01-10 09:35")
    engine._pending_breakout = BreakoutEvent("BULL_FLAG", entry_time, 12.20, 11.30, 0.90)
    engine.record_entry(100, 12.20, entry_time)

    fully_closed = engine.record_exit(40, 11.28, is_target_partial=False)

    assert fully_closed is False
    assert engine.stop_price == pytest.approx(11.30)  # unverändert, NICHT auf Breakeven (12.20)
    assert engine.shares_open == 60


def test_record_exit_target_partial_still_moves_stop_to_breakeven():
    """Gegenprobe: der Standardfall (TARGET-Teilverkauf, is_target_partial
    bleibt beim Default True) muss weiterhin wie zuvor auf Breakeven
    ziehen -- der Fix darf das bestehende Verhalten nicht brechen."""
    engine = _make_engine()
    entry_time = pd.Timestamp("2024-01-10 09:35")
    engine._pending_breakout = BreakoutEvent("BULL_FLAG", entry_time, 12.20, 11.30, 0.90)
    engine.record_entry(100, 12.20, entry_time)

    fully_closed = engine.record_exit(50, 14.00)

    assert fully_closed is False
    assert engine.stop_price == pytest.approx(12.20)  # Breakeven


def test_breakout_event_and_position_diagnostics_after_entry():
    """Regressionstest für die Nachvollziehbarkeits-Felder auf
    BreakoutEvent (swing_low_price/flagpole_gain_pct/pullback_bars/
    relative_volume) sowie die Positions-Properties (entry_price/
    stop_price/target_price/avg_bar_range) -- werden für die Live-Log-
    Anreicherung gebraucht (siehe momentum_live.py._handle_breakout /
    _submit_exit)."""
    engine = _make_engine()
    bars = bull_flag_setup_bars()
    base_time = pd.Timestamp("2024-01-10 09:30")

    event = None
    for i, bar in enumerate(bars):
        time = base_time + pd.Timedelta(minutes=i)
        events = engine.process_bar(
            time, bar["open"], bar["high"], bar["low"], bar["close"], bar["volume"],
            in_window=True, relative_volume=5.0, daily_trend_ok=True,
        )
        for e in events:
            if isinstance(e, BreakoutEvent):
                event = e

    assert event is not None
    assert event.pattern == "BULL_FLAG"
    assert event.swing_low_price == pytest.approx(10.00)
    # Flaggenstange bis zu ihrem HOCH gemessen (12.05), nicht bis zum Schluss.
    assert event.flagpole_gain_pct == pytest.approx(0.205)
    # Nur die echten Rücksetzer-Kerzen (bar3, bar4), nicht der Breakout-Balken.
    assert event.pullback_bars == 2
    assert event.relative_volume == pytest.approx(5.0)

    engine.record_entry(77, event.reference_price, event.time)

    assert engine.entry_price == pytest.approx(12.20)
    assert engine.stop_price == pytest.approx(11.30)
    assert engine.target_price == pytest.approx(12.20 + 2.0 * event.risk_per_share)
    # Pullback-Balken inkl. Breakout-Balken: bar3 (12.00-11.60=0.40),
    # bar4 (11.75-11.30=0.45), bar5 (12.25-11.35=0.90).
    assert engine.avg_bar_range == pytest.approx((0.40 + 0.45 + 0.90) / 3)


def test_record_exit_reseeds_swing_low_with_bar_close_not_fill_price():
    """Regressionstest: nach einer vollständig geschlossenen Position muss
    die Swing-Tief-Referenz mit dem zuletzt beobachteten SCHLUSSKURS neu
    gestartet werden, NICHT mit dem Ausführungspreis (fill_price) des
    Exits -- der weicht z.B. bei einem Stop durch Slippage systematisch
    UNTER der Stop-Schwelle ab und würde (fälschlich als neue Referenz
    verwendet) eine nachfolgende Flagpole künstlich leichter auslösbar
    machen. decline_entry() und der Pullback-Invalidierungspfad
    (_reset_to_searching_after) verwenden beide bereits konsequent einen
    Schlusskurs -- record_exit() war hier die einzige Ausnahme."""
    engine = _make_engine()
    entry_time = pd.Timestamp("2024-01-10 09:35")
    engine._pending_breakout = BreakoutEvent("BULL_FLAG", entry_time, 12.20, 11.30, 0.90)
    engine.record_entry(10, 12.20, entry_time)

    # Docht durch den Stop (low <= 11.30), aber der Balken schließt danach
    # deutlich höher wieder (close=11.55) -- ein realistischer "Spike-down
    # und Erholung"-Balken.
    stop_bar_time = pd.Timestamp("2024-01-10 09:40")
    events = engine.process_bar(
        stop_bar_time, 11.50, 11.60, 11.00, 11.55, 500,
        in_window=True, relative_volume=5.0, daily_trend_ok=True,
    )
    assert len(events) == 1
    assert events[0].reason == ExitReason.STOP

    # Realer Fill (inkl. Slippage) liegt UNTER sowohl der Stop-Schwelle als
    # auch dem Balken-Schlusskurs.
    engine.record_exit(10, 11.25)

    assert engine.state == "SEARCHING"
    assert engine._swing_low_price == pytest.approx(11.55)


# ---------------------------------------------------------------------------
# run_momentum_backtest_multi
# ---------------------------------------------------------------------------


def _quiet_bars(day: date) -> pd.DataFrame:
    """Ein Tag, an dem garantiert kein Setup ausgelöst wird (flacher Kurs,
    kein Anstieg -> keine Flagpole)."""
    return flat_day(day, 10, 10.00, 50)


def test_run_momentum_backtest_multi_aggregates_across_symbols():
    triggering_days = {
        DAY_MINUS_2: flat_day(DAY_MINUS_2, 10, 10.00, 50),
        DAY_MINUS_1: flat_day(DAY_MINUS_1, 10, 10.00, 50),
        TODAY: make_day(TODAY, bull_flag_setup_bars()),
    }
    quiet_days = {
        DAY_MINUS_2: flat_day(DAY_MINUS_2, 10, 10.00, 50),
        DAY_MINUS_1: flat_day(DAY_MINUS_1, 10, 10.00, 50),
        TODAY: _quiet_bars(TODAY),
    }
    bars_by_symbol = {
        "AAA": build_bars(triggering_days),
        "BBB": build_bars(quiet_days),
    }

    result = run_momentum_backtest_multi(bars_by_symbol, starting_cash_per_symbol=100_000.0, **COMMON_KWARGS)

    assert [s.symbol for s in result.per_symbol] == ["AAA", "BBB"]
    aaa_result = result.per_symbol[0].result
    bbb_result = result.per_symbol[1].result
    assert aaa_result.num_trades == 1
    assert bbb_result.num_trades == 0

    assert result.total_trades == aaa_result.num_trades + bbb_result.num_trades
    assert result.total_costs == pytest.approx(aaa_result.total_costs + bbb_result.total_costs)
    expected_gross_pnl = sum(t.gross_pnl for t in aaa_result.trades) + sum(t.gross_pnl for t in bbb_result.trades)
    assert result.total_gross_pnl == pytest.approx(expected_gross_pnl)
    wins = sum(1 for t in aaa_result.trades + bbb_result.trades if t.gross_pnl > 0)
    assert result.overall_win_rate == pytest.approx(wins / result.total_trades)


def test_run_momentum_backtest_multi_uses_independent_starting_cash_per_symbol():
    """Regressionstest: jedes Symbol muss mit DEMSELBEN, aber UNABHÄNGIGEN
    Startkapital simuliert werden -- Trades in einem Symbol dürfen das
    Endkapital eines ANDEREN Symbols nicht beeinflussen (kein geteiltes
    Gesamtkapital, siehe run_momentum_backtest_multi-Docstring)."""
    triggering_days = {
        DAY_MINUS_2: flat_day(DAY_MINUS_2, 10, 10.00, 50),
        DAY_MINUS_1: flat_day(DAY_MINUS_1, 10, 10.00, 50),
        TODAY: make_day(TODAY, bull_flag_setup_bars()),
    }
    quiet_days = {
        DAY_MINUS_2: flat_day(DAY_MINUS_2, 10, 10.00, 50),
        DAY_MINUS_1: flat_day(DAY_MINUS_1, 10, 10.00, 50),
        TODAY: _quiet_bars(TODAY),
    }
    bars_by_symbol = {
        "AAA": build_bars(triggering_days),
        "BBB": build_bars(quiet_days),
    }

    result = run_momentum_backtest_multi(bars_by_symbol, starting_cash_per_symbol=5_000.0, **COMMON_KWARGS)

    bbb_result = result.per_symbol[1].result
    assert bbb_result.num_trades == 0
    assert bbb_result.final_equity == pytest.approx(5_000.0)  # unveraendert, keine Trades


def test_run_momentum_backtest_multi_rejects_empty_dict():
    with pytest.raises(ValueError, match="bars_by_symbol"):
        run_momentum_backtest_multi({}, starting_cash_per_symbol=10_000.0, **COMMON_KWARGS)


def _sparse_day(day: date, minute_volumes: dict[int, float], price: float = 10.00) -> pd.DataFrame:
    """Tag mit Balken NUR in den angegebenen Minuten seit 9:30 (wie IEX bei
    dünn gehandelten Small-Caps: Minuten ohne Trade fehlen komplett)."""
    start = pd.Timestamp(datetime(day.year, day.month, day.day, 9, 30), tz="America/New_York")
    idx = pd.DatetimeIndex([start + pd.Timedelta(minutes=m) for m in minute_volumes])
    rows = [
        {"open": price, "high": price, "low": price, "close": price, "volume": v} for v in minute_volumes.values()
    ]
    return pd.DataFrame(rows, index=idx)


def test_relative_volume_reference_aligns_by_clock_minute_not_bar_position():
    """Regression: die Referenzkurve wurde nach Balken-POSITION aufgebaut
    (i-ter Balken des Tages), abgefragt aber (live) nach UHRZEIT-Minute seit
    Sitzungsbeginn. Bei lückenhaften Daten (IEX, Small-Caps) liefen beide
    auseinander -- Relativvolumen wurde falsch bzw. gar nicht berechnet."""
    from tradingbot.momentum import _relative_volume_reference

    d1, d2, d3 = date(2024, 1, 8), date(2024, 1, 9), date(2024, 1, 10)
    day_bars = {
        d1: _sparse_day(d1, {0: 100, 5: 100}),
        d2: _sparse_day(d2, {0: 100, 5: 100}),
        d3: _sparse_day(d3, {0: 100, 5: 100}),
    }

    reference = _relative_volume_reference([d1, d2, d3], day_bars, lookback_days=2)[d3]

    # 9:33 (Minute 3): bis dahin nur der 9:30-Balken gehandelt.
    assert reference[3] == pytest.approx(100)
    # 9:35 (Minute 5): beide Balken.
    assert reference[5] == pytest.approx(200)

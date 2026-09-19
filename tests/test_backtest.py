import numpy as np
import pandas as pd
import pytest

from tradingbot.backtest import run_backtest


def test_trailing_stop_tracks_peak_not_entry_price():
    """Regressionstest fürs Kernverhalten des Trailing-Stops: steigt der
    Kurs nach dem Einstieg stark und fällt danach nur leicht, darf ein
    fixer (auf Einstieg bezogener) Stop nicht mehr auslösen -- der
    Trailing-Stop (bezogen auf den seit Einstieg höchsten Kurs) hingegen
    schon."""
    values = [10, 9, 8, 7, 6, 7, 9]  # BUY am Ende, Einstieg ~9
    values += [12, 15, 20, 25, 30]  # starker Anstieg -> Peak 30
    values += [28, 27]  # leichter Rückgang, weit über dem fixen 8%-Stop von ~8.3
    close = pd.Series(values, index=pd.date_range("2024-01-01", periods=len(values), freq="D"))

    result = run_backtest(close, short_window=2, long_window=4, stop_loss_pct=0.08, take_profit_pct=0.0)

    sides = [t.side for t in result.trades]
    assert sides == ["BUY", "STOP"]
    stop_trade = result.trades[1]
    # Stop-Schwelle bezogen auf Peak (30): 30*0.92=27.6 -> löst bei Kurs 27 aus.
    # Bezogen auf Einstieg (~9): 9*0.92=8.28 -> hätte hier nie ausgelöst.
    assert stop_trade.price == pytest.approx(27 * 0.9995)


def test_trailing_stop_behaves_like_fixed_stop_without_prior_rise():
    """Steigt der Kurs nach dem Einstieg nie, ist Peak == Einstiegspreis
    und der Trailing-Stop verhält sich identisch zu einem fixen (auf den
    Einstieg bezogenen) Stop -- stellt sicher, dass die Umstellung
    bestehendes Verhalten nicht verändert hat."""
    values = [10, 9, 8, 7, 6, 7, 9, 8, 7, 6, 5]
    close = pd.Series(values, index=pd.date_range("2024-01-01", periods=len(values), freq="D"))

    result = run_backtest(close, short_window=2, long_window=4, stop_loss_pct=0.08, take_profit_pct=0.0)

    stop = result.trades[1]
    assert stop.side == "STOP"
    # Erster Tag nach dem Einstieg, an dem der rohe Kurs (8) die auf den
    # Einstiegspreis bezogene Schwelle (9.0045*0.92≈8.28) unterschreitet.
    assert stop.price == pytest.approx(8 * (1 - 0.0005))


def test_take_profit_exits_when_target_reached():
    values = [10, 9, 8, 7, 6, 7, 9, 10, 11, 12]  # BUY ~9, dann +33%
    close = pd.Series(values, index=pd.date_range("2024-01-01", periods=len(values), freq="D"))

    result = run_backtest(close, short_window=2, long_window=4, stop_loss_pct=0.0, take_profit_pct=0.15)

    sides = [t.side for t in result.trades]
    assert sides == ["BUY", "TP"]
    buy, tp = result.trades
    assert tp.price >= buy.price * 1.15 * (1 - 0.0005) - 1e-9


def test_take_profit_disabled_by_default():
    values = [10, 9, 8, 7, 6, 7, 9, 20, 30, 40]
    close = pd.Series(values, index=pd.date_range("2024-01-01", periods=len(values), freq="D"))

    result = run_backtest(close, short_window=2, long_window=4, stop_loss_pct=0.0)

    assert "TP" not in [t.side for t in result.trades]


def test_take_profit_rejects_negative_and_non_finite():
    close = pd.Series([10, 9, 8, 7, 6, 7, 9], index=pd.date_range("2024-01-01", periods=7, freq="D"))
    with pytest.raises(ValueError):
        run_backtest(close, 2, 4, take_profit_pct=-0.1)
    with pytest.raises(ValueError):
        run_backtest(close, 2, 4, take_profit_pct=float("nan"))


def test_risk_based_position_sizing_uses_less_than_full_capital():
    values = [10, 9, 8, 7, 6, 7, 9, 12, 16]
    close = pd.Series(values, index=pd.date_range("2024-01-01", periods=len(values), freq="D"))

    full = run_backtest(close, 2, 4, starting_cash=10_000.0, stop_loss_pct=0.08, risk_per_trade_pct=0.0)
    risked = run_backtest(close, 2, 4, starting_cash=10_000.0, stop_loss_pct=0.08, risk_per_trade_pct=0.02)

    full_notional = full.trades[0].shares * full.trades[0].price
    risked_notional = risked.trades[0].shares * risked.trades[0].price

    assert full_notional == pytest.approx(10_000.0, rel=1e-3)
    # notional = (equity * risk_pct) / stop_loss_pct = (10000*0.02)/0.08 = 2500
    assert risked_notional == pytest.approx(2_500.0, rel=1e-3)


def test_risk_based_sizing_does_not_lose_uninvested_cash_on_exit():
    """Regressionstest für einen kritischen Bug: bei risikobasierter
    Positionsgröße bleibt Kapital uninvestiert (cash > 0 während die
    Position offen ist). Ein Exit (STOP/TP/SELL), der cash mit dem
    Verkaufserlös ÜBERSCHREIBT statt ihn zu ADDIEREN, vernichtet dieses
    uninvestierte Kapital stillschweigend -- verifiziert am exakten
    Reproduktionsfall: Einstieg ~9, Ausstieg (Trailing-Stop) ~18 (also mit
    GEWINN verkauft), aber die Equity brach vorher von ~13052 auf ~4995
    ein, weil ~7500 uninvestiertes Kapital beim Verkauf verloren gingen."""
    values = [10, 9, 8, 7, 6, 7, 9, 12, 16, 21, 20, 18, 15, 12, 9]
    close = pd.Series(values, index=pd.date_range("2024-01-01", periods=len(values), freq="D"))

    result = run_backtest(
        close, 2, 4, starting_cash=10_000.0, stop_loss_pct=0.08, risk_per_trade_pct=0.02
    )

    sides = [t.side for t in result.trades]
    assert sides == ["BUY", "STOP"]
    # Mit dem Bug wurden die ~75% nie investierten Kapitals beim Verkauf
    # gelöscht -> final_equity wäre auf ~4995 (nur der Verkaufserlös)
    # eingebrochen, obwohl die Position mit deutlichem Gewinn verkauft
    # wurde (Einstieg ~9, Ausstieg ~18). Korrekt bleibt das uninvestierte
    # Kapital (10000-2500=7500) vollständig erhalten und addiert sich zum
    # Verkaufserlös -> Endkapital deutlich über dem Startkapital.
    assert result.final_equity > 12_000.0


def test_risk_based_position_sizing_caps_at_available_cash():
    """Wenn die risikobasierte Notional-Größe das verfügbare Kapital
    übersteigen würde (z.B. sehr hoher Risiko-Prozentsatz relativ zum
    Stop), darf trotzdem nicht mehr als das vorhandene Kapital investiert
    werden -- kein Hebel."""
    values = [10, 9, 8, 7, 6, 7, 9]
    close = pd.Series(values, index=pd.date_range("2024-01-01", periods=len(values), freq="D"))

    result = run_backtest(close, 2, 4, starting_cash=10_000.0, stop_loss_pct=0.01, risk_per_trade_pct=0.5)

    notional = result.trades[0].shares * result.trades[0].price
    assert notional <= 10_000.0 * 1.0005  # kleine Toleranz für Slippage-Aufschlag im BUY-Preis


def test_risk_based_position_sizing_disabled_without_stop_loss():
    """risk_per_trade_pct ist ohne stop_loss_pct nicht definiert (kein
    Bezugspunkt für 'Risiko pro Trade') -- muss dann auf volles Kapital
    zurückfallen statt zu crashen oder eine Bedeutungslose Größe zu
    berechnen."""
    values = [10, 9, 8, 7, 6, 7, 9]
    close = pd.Series(values, index=pd.date_range("2024-01-01", periods=len(values), freq="D"))

    result = run_backtest(close, 2, 4, starting_cash=10_000.0, stop_loss_pct=0.0, risk_per_trade_pct=0.02)

    notional = result.trades[0].shares * result.trades[0].price
    assert notional == pytest.approx(10_000.0, rel=1e-3)


def test_zero_price_day_does_not_crash_and_skips_trade():
    """Regressionstest: ein Kurs von exakt 0 (z.B. Delisting, defekter
    Datenpunkt) an einem Golden-Cross-Tag würde beim Teilen durch
    fill_price einen ZeroDivisionError auslösen. Solche Tage werden jetzt
    als nicht handelbar übersprungen statt zu crashen."""
    values = [41.78, 48.87, 31.91, 35.06, 23.09, 26.67, 2.5, 34.07, 0.0, 33.33]
    close = pd.Series(values, index=pd.date_range("2024-01-01", periods=len(values), freq="D"))

    result = run_backtest(close, short_window=2, long_window=4, stop_loss_pct=0.0)

    assert not result.equity_curve.isna().any()
    assert not pd.isna(result.final_equity)


def test_negative_price_day_does_not_crash():
    values = [10, 9, 8, 7, 6, 7, 9, -5, 12, 16]
    close = pd.Series(values, index=pd.date_range("2024-01-01", periods=len(values), freq="D"))

    result = run_backtest(close, short_window=2, long_window=4, stop_loss_pct=0.0)

    assert not result.equity_curve.isna().any()


def test_cost_and_risk_params_must_be_below_one():
    """Regressionstest: commission_pct/slippage_pct >= 1 (100%) lässt
    Vorzeichen kippen (z.B. negative shares) und korrumpiert den
    Backtest-Zustand dauerhaft -- muss abgelehnt werden statt still
    falsche Ergebnisse zu produzieren."""
    close = pd.Series(
        [10, 9, 8, 7, 6, 7, 9, 12, 16],
        index=pd.date_range("2024-01-01", periods=9, freq="D"),
    )

    with pytest.raises(ValueError):
        run_backtest(close, 2, 4, commission_pct=1.5)
    with pytest.raises(ValueError):
        run_backtest(close, 2, 4, slippage_pct=1.0)
    with pytest.raises(ValueError):
        run_backtest(close, 2, 4, stop_loss_pct=1.0)
    with pytest.raises(ValueError):
        run_backtest(close, 2, 4, commission_pct=-0.01)


def test_starting_cash_must_be_positive_and_finite():
    """Regressionstest: starting_cash ist Divisor bei der Rendite-
    berechnung -- 0 hätte einen ZeroDivisionError (leere Serie) oder
    still NaN (nicht-leere Serie) erzeugt statt eines klaren Fehlers."""
    close = pd.Series(
        [10, 9, 8, 7, 6, 7, 9, 12, 16],
        index=pd.date_range("2024-01-01", periods=9, freq="D"),
    )

    for bad_value in (0.0, -100.0, np.nan, np.inf):
        try:
            run_backtest(close, 2, 4, starting_cash=bad_value)
            raise AssertionError(f"starting_cash={bad_value} hätte ValueError auslösen müssen")
        except ValueError:
            pass


def test_nan_gap_while_holding_position_does_not_poison_equity_curve():
    """Regressionstest: 0 * NaN und x * NaN sind beide NaN -- ein fehlender
    Kurs (Datenlücke) darf die Equity-Kurve nicht mit NaN verunreinigen,
    weder für den Lücken-Tag selbst noch (über final_equity) für alle
    folgenden Tage."""
    values = [10, 9, 8, 7, 6, 7, 9, 12, 16, np.nan, 21, 27]
    close = pd.Series(values, index=pd.date_range("2024-01-01", periods=len(values), freq="D"))

    result = run_backtest(close, short_window=2, long_window=4, starting_cash=1000.0, stop_loss_pct=0.0)

    assert not result.equity_curve.isna().any()
    assert not pd.isna(result.final_equity)
    assert not pd.isna(result.total_return_pct)


def test_nan_gap_before_any_position_does_not_poison_equity_curve():
    """0 * NaN ist ebenfalls NaN -- auch ohne offene Position (shares=0)
    darf ein fehlender Kurs am Anfang der Serie die Equity-Kurve nicht
    verunreinigen."""
    values = [np.nan, 10, 9, 8, 7, 6, 7, 9, 12, 16]
    close = pd.Series(values, index=pd.date_range("2024-01-01", periods=len(values), freq="D"))

    result = run_backtest(close, short_window=2, long_window=4, starting_cash=1000.0, stop_loss_pct=0.0)

    assert not result.equity_curve.isna().any()
    assert result.equity_curve.iloc[0] == 1000.0


def test_buy_cost_matches_shares_times_price_shortfall():
    """trade.cost muss exakt der Differenz zwischen eingesetztem Kapital und
    dem fairen Wert (Anzahl Aktien * unbeeinflusster Kurs) entsprechen --
    das deckt sowohl Provision als auch Slippage in einer Formel ab."""
    values = [10, 9, 8, 7, 6, 7, 9]
    close = pd.Series(values, index=pd.date_range("2024-01-01", periods=len(values), freq="D"))

    result = run_backtest(
        close, short_window=2, long_window=4, starting_cash=1000.0,
        commission_pct=0.01, slippage_pct=0.01, stop_loss_pct=0.0,
    )

    buy = result.trades[0]
    assert buy.side == "BUY"
    raw_price = close.loc[buy.date]
    expected_cost = 1000.0 - buy.shares * raw_price
    assert buy.cost == pytest.approx(expected_cost)


def test_sell_cost_matches_shares_times_price_shortfall():
    values = [10, 9, 8, 7, 6, 7, 9, 8, 6, 4]
    close = pd.Series(values, index=pd.date_range("2024-01-01", periods=len(values), freq="D"))

    result = run_backtest(
        close, short_window=2, long_window=4, starting_cash=1000.0,
        commission_pct=0.01, slippage_pct=0.01, stop_loss_pct=0.0,
    )

    sell = next(t for t in result.trades if t.side in ("SELL", "STOP"))
    raw_price = close.loc[sell.date]
    expected_cost = sell.shares * raw_price - (sell.shares * sell.price * (1 - 0.01))
    assert sell.cost == pytest.approx(expected_cost)


def test_backtest_profits_on_clean_uptrend_with_dip():
    values = [10, 9, 8, 7, 6] + [7, 9, 12, 16, 21, 27, 34, 42, 51]
    close = pd.Series(values, index=pd.date_range("2024-01-01", periods=len(values), freq="D"))

    result = run_backtest(close, short_window=2, long_window=4, starting_cash=1000.0)

    assert result.num_trades >= 1
    assert result.final_equity > 0
    assert len(result.equity_curve) == len(close)


def test_backtest_no_signal_keeps_cash_flat():
    close = pd.Series([100] * 15, index=pd.date_range("2024-01-01", periods=15, freq="D"))

    result = run_backtest(close, short_window=3, long_window=6, starting_cash=1000.0)

    assert result.num_trades == 0
    assert result.final_equity == 1000.0
    assert result.total_return_pct == 0.0
    assert result.total_costs == 0.0


def test_zero_costs_produce_zero_total_costs():
    values = [10, 9, 8, 7, 6, 7, 9, 12, 16, 21, 27, 34, 30, 25, 18, 10]
    close = pd.Series(values, index=pd.date_range("2024-01-01", periods=len(values), freq="D"))

    result = run_backtest(
        close, short_window=2, long_window=4, starting_cash=1000.0,
        commission_pct=0.0, slippage_pct=0.0,
    )

    assert result.num_trades >= 1
    assert result.total_costs == 0.0


def test_stop_loss_exits_before_crossover_on_sharp_drop():
    # BUY-Signal (Golden Cross) bei Index 6, danach fällt der Kurs sofort
    # stark -- weit vor einem regulären Death-Cross-Signal.
    values = [10, 9, 8, 7, 6, 7, 9, 8, 7, 6, 5, 4, 3]
    close = pd.Series(values, index=pd.date_range("2024-01-01", periods=len(values), freq="D"))

    result = run_backtest(
        close, short_window=2, long_window=4, starting_cash=1000.0,
        stop_loss_pct=0.08,
    )

    sides = [t.side for t in result.trades]
    assert sides == ["BUY", "STOP"]
    # Der Stop muss unmittelbar nach dem starken Einbruch greifen, nicht erst
    # am Ende der Zeitreihe wie es ein reines Crossover-Signal täte.
    assert result.trades[1].date < close.index[-1]


def test_stop_loss_disabled_rides_out_the_drawdown():
    values = [10, 9, 8, 7, 6, 7, 9, 8, 7, 6, 5, 4, 3]
    close = pd.Series(values, index=pd.date_range("2024-01-01", periods=len(values), freq="D"))

    with_stop = run_backtest(
        close, short_window=2, long_window=4, starting_cash=1000.0, stop_loss_pct=0.08
    )
    without_stop = run_backtest(
        close, short_window=2, long_window=4, starting_cash=1000.0, stop_loss_pct=0.0
    )

    assert "STOP" in [t.side for t in with_stop.trades]
    assert "STOP" not in [t.side for t in without_stop.trades]
    # Ohne Stop reitet die Position den weiteren Absturz voll mit --
    # das Endkapital muss entsprechend niedriger sein als mit Stop.
    assert without_stop.final_equity < with_stop.final_equity


def test_stop_loss_uses_slippage_adjusted_entry_price():
    values = [10, 9, 8, 7, 6, 7, 9, 8, 7, 6, 5, 4, 3]
    close = pd.Series(values, index=pd.date_range("2024-01-01", periods=len(values), freq="D"))

    result = run_backtest(
        close, short_window=2, long_window=4, starting_cash=1000.0,
        slippage_pct=0.001, stop_loss_pct=0.08,
    )

    buy_trade, stop_trade = result.trades
    stop_threshold = buy_trade.price * (1 - 0.08)
    assert stop_trade.price <= stop_threshold * (1 + 1e-9)


def test_higher_costs_reduce_final_equity():
    values = [10, 9, 8, 7, 6, 7, 9, 12, 16, 21, 27, 34, 30, 25, 18, 10]
    close = pd.Series(values, index=pd.date_range("2024-01-01", periods=len(values), freq="D"))

    cheap = run_backtest(
        close, short_window=2, long_window=4, starting_cash=1000.0,
        commission_pct=0.0, slippage_pct=0.0,
    )
    expensive = run_backtest(
        close, short_window=2, long_window=4, starting_cash=1000.0,
        commission_pct=0.01, slippage_pct=0.01,
    )

    assert cheap.num_trades == expensive.num_trades
    assert expensive.total_costs > cheap.total_costs
    assert expensive.final_equity < cheap.final_equity

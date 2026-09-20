from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from tradingbot import walkforward as walkforward_module
from tradingbot.validation import ParamCandidate, SegmentMetrics, ValidationResult
from tradingbot.walkforward import walk_forward_validate


def make_series(n: int) -> pd.Series:
    return pd.Series(
        np.arange(n, dtype=float), index=pd.date_range("2024-01-01", periods=n, freq="D")
    )


def install_fake_validate(monkeypatch, test_returns: list[float]):
    """Ersetzt validate() durch eine Fake-Implementierung, die für jeden
    Aufruf (in Reihenfolge) die vorgegebene Testrendite liefert -- so lässt
    sich die Orchestrierung/Aggregation von walk_forward_validate isoliert
    von der eigentlichen Backtest-Simulation testen."""
    calls: list[tuple[pd.Series, float]] = []

    def fake_validate(close, param_grid, train_ratio, **kwargs):
        calls.append((close, train_ratio))
        idx = len(calls) - 1
        split_idx = round(len(close) * train_ratio)
        candidate = ParamCandidate(
            short_window=5,
            long_window=20,
            train=SegmentMetrics(close.index[0], close.index[split_idx - 1], 1.0, 3, 0.0),
            test=SegmentMetrics(close.index[split_idx], close.index[-1], test_returns[idx], 2, 0.0),
        )
        return ValidationResult(
            split_date=close.index[split_idx],
            train_ratio=train_ratio,
            best=candidate,
            all_candidates=[candidate],
        )

    monkeypatch.setattr(walkforward_module, "validate", fake_validate)
    return calls


def test_rolling_windows_have_fixed_size_train_slice_that_slides(monkeypatch):
    """Rolling (expanding=False): das Trainingsfenster hat über alle
    Schritte dieselbe Größe und rutscht mit train_window+step vorwärts,
    statt bei Tag 0 zu beginnen."""
    close = make_series(300)
    calls = install_fake_validate(monkeypatch, test_returns=[1.0, 2.0, 3.0, 4.0])

    result = walk_forward_validate(close, [(5, 20)], train_window=100, test_window=50)

    assert len(result.windows) == 4
    assert [len(c) for c, _ in calls] == [150, 150, 150, 150]
    assert result.windows[0].train_start == close.index[0]
    assert result.windows[1].train_start == close.index[50]
    assert result.windows[2].train_start == close.index[100]
    assert result.windows[3].train_start == close.index[150]
    assert result.windows[3].test_end == close.index[299]


def test_expanding_windows_always_start_training_at_day_zero(monkeypatch):
    """Expanding: train_start bleibt immer der erste Tag der Serie, nur
    train_end wächst mit jedem Schritt."""
    close = make_series(300)
    calls = install_fake_validate(monkeypatch, test_returns=[1.0, 2.0, 3.0, 4.0])

    result = walk_forward_validate(
        close, [(5, 20)], train_window=100, test_window=50, expanding=True
    )

    assert len(result.windows) == 4
    assert all(w.train_start == close.index[0] for w in result.windows)
    assert [len(c) for c, _ in calls] == [150, 200, 250, 300]


def test_custom_step_smaller_than_test_window_creates_overlapping_test_periods(monkeypatch):
    """Ein step < test_window lässt aufeinanderfolgende Testfenster
    überlappen -- z.B. für ein feineres Sampling der Robustheit. Muss
    trotzdem korrekt terminieren und die richtige Fensteranzahl liefern."""
    close = make_series(200)
    install_fake_validate(monkeypatch, test_returns=[1.0] * 10)

    result = walk_forward_validate(
        close, [(5, 20)], train_window=100, test_window=50, step=25
    )

    # i=0: train[0:100) test[100:150); i=1: train[25:125) test[125:175);
    # i=2: train[50:150) test[150:200); i=3: train[75:175) test[175:225) > 200 -> stop
    assert len(result.windows) == 3


def test_compounded_return_is_none_when_test_windows_overlap(monkeypatch):
    """Regressionstest: bei step < test_window überlappen sich die
    Testfenster, dieselben Kalendertage würden bei einer naiven Verkettung
    mehrfach gezählt und die Rendite künstlich aufblähen. Verifiziert per
    Reproduktion: mit konstant 10% Testrendite pro Fenster ergäbe eine
    fehlerhafte Verkettung ueber 7 ueberlappende Fenster ~94.87% statt der
    korrekten, nicht ueberlappenden ~46.41% bei gleicher Rendite -- daher
    muss compounded_test_return_pct bei Ueberlappung None sein, nicht ein
    verfaelschter Wert."""
    close = make_series(200)
    install_fake_validate(monkeypatch, test_returns=[10.0] * 10)

    overlapping = walk_forward_validate(
        close, [(5, 20)], train_window=100, test_window=50, step=25
    )
    assert overlapping.compounded_test_return_pct is None

    non_overlapping = walk_forward_validate(
        close, [(5, 20)], train_window=100, test_window=50, step=50
    )
    assert non_overlapping.compounded_test_return_pct is not None
    assert non_overlapping.compounded_test_return_pct == pytest.approx(1.10**2 * 100 - 100)


def test_aggregation_matches_manual_computation(monkeypatch):
    close = make_series(300)
    test_returns = [10.0, -5.0, 20.0, -2.0]
    install_fake_validate(monkeypatch, test_returns=test_returns)

    result = walk_forward_validate(close, [(5, 20)], train_window=100, test_window=50)

    assert result.mean_test_return_pct == pytest.approx(sum(test_returns) / 4)
    assert result.median_test_return_pct == pytest.approx(4.0)  # sorted: -5,-2,10,20 -> (-2+10)/2
    assert result.win_rate == pytest.approx(2 / 4)  # nur 10.0 und 20.0 sind positiv

    expected_compounded = 1.0
    for r in test_returns:
        expected_compounded *= 1 + r / 100
    expected_compounded_pct = (expected_compounded - 1) * 100
    assert result.compounded_test_return_pct == pytest.approx(expected_compounded_pct)


def test_rejects_non_positive_train_or_test_window():
    close = make_series(300)
    with pytest.raises(ValueError):
        walk_forward_validate(close, [(5, 20)], train_window=0, test_window=50)
    with pytest.raises(ValueError):
        walk_forward_validate(close, [(5, 20)], train_window=100, test_window=0)
    with pytest.raises(ValueError):
        walk_forward_validate(close, [(5, 20)], train_window=100, test_window=50, step=0)


def test_raises_when_not_a_single_window_fits():
    close = make_series(50)
    with pytest.raises(ValueError):
        walk_forward_validate(close, [(5, 20)], train_window=100, test_window=50)


def test_window_skipped_when_grid_has_insufficient_history_but_later_window_succeeds(monkeypatch):
    """Ein zu kurzes Trainingsfenster für ALLE Grid-Kombinationen lässt
    validate() ValueError werfen -- dieses Fenster muss übersprungen
    werden, ohne den gesamten Lauf abzubrechen, solange ein anderes
    (z.B. bei expanding: späteres, größeres) Fenster genug Daten hat."""
    close = make_series(300)

    call_count = 0

    def flaky_validate(close_slice, param_grid, train_ratio, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise ValueError("zu wenig Daten in diesem Fenster")
        split_idx = round(len(close_slice) * train_ratio)
        candidate = ParamCandidate(
            short_window=5,
            long_window=20,
            train=SegmentMetrics(close_slice.index[0], close_slice.index[split_idx - 1], 1.0, 1, 0.0),
            test=SegmentMetrics(close_slice.index[split_idx], close_slice.index[-1], 5.0, 1, 0.0),
        )
        return ValidationResult(
            split_date=close_slice.index[split_idx],
            train_ratio=train_ratio,
            best=candidate,
            all_candidates=[candidate],
        )

    monkeypatch.setattr(walkforward_module, "validate", flaky_validate)

    result = walk_forward_validate(close, [(5, 20)], train_window=100, test_window=50)

    # 4 Fenster insgesamt moeglich, das erste schlaegt fehl -> 3 uebrig.
    assert len(result.windows) == 3
    assert result.windows[0].window_index == 1


def test_end_to_end_with_real_validate_on_realistic_random_walk_prices():
    """Integrations-Smoke-Test ohne Mock: echte validate()/run_backtest()-
    Pipeline über mehrere Fenster auf einer realistischen (random-walk)
    Kursreihe -- stellt sicher, dass das Zusammenspiel der echten
    Funktionen nicht crasht und plausible Werte liefert."""
    rng = np.random.default_rng(42)
    returns = rng.normal(0, 0.015, size=600)
    prices = 100 * np.cumprod(1 + returns)
    close = pd.Series(prices, index=pd.date_range("2023-01-01", periods=600, freq="D"))

    result = walk_forward_validate(
        close,
        [(5, 20), (10, 30), (20, 50)],
        train_window=200,
        test_window=100,
        stop_loss_pct=0.08,
        take_profit_pct=0.15,
        trend_window=0,
        rsi_window=0,
    )

    assert len(result.windows) == 4
    for w in result.windows:
        assert w.train_start < w.train_end < w.test_start <= w.test_end
        assert np.isfinite(w.result.best.test.return_pct)
    assert np.isfinite(result.mean_test_return_pct)
    assert np.isfinite(result.compounded_test_return_pct)
    assert 0.0 <= result.win_rate <= 1.0

"""Out-of-Sample-Validierung für die Moving-Average-Crossover-Parameter.

Methodik: Für jede Parameterkombination wird EIN Backtest über die
gesamte Zeitreihe gerechnet (der gleitende Durchschnitt schaut nur
zurück, nie nach vorne — ein Trainings-/Test-Split verändert also die
Werte im Trainingsabschnitt nicht). Aus der resultierenden Equity-Kurve
wird anschließend am Split-Datum in Trainings- und Testabschnitt
zerlegt. Die beste Parameterkombination wird ausschließlich anhand des
Trainingsabschnitts ausgewählt ("in-sample"); der Testabschnitt fließt
in die Auswahl nicht ein und zeigt, wie die gewählten Parameter sich
auf ungesehenen Daten verhalten ("out-of-sample").
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from tradingbot.backtest import BacktestResult, run_backtest


@dataclass
class SegmentMetrics:
    start: pd.Timestamp
    end: pd.Timestamp
    return_pct: float
    num_trades: int
    total_costs: float


@dataclass
class ParamCandidate:
    short_window: int
    long_window: int
    train: SegmentMetrics
    test: SegmentMetrics


@dataclass
class ValidationResult:
    split_date: pd.Timestamp
    train_ratio: float
    best: ParamCandidate
    all_candidates: list[ParamCandidate]


def _segment_metrics(
    result: BacktestResult,
    close: pd.Series,
    starting_cash: float,
    start_idx: int,
    end_idx: int,
) -> SegmentMetrics:
    """Berechnet Rendite/Trades/Kosten für den Indexbereich [start_idx, end_idx)
    der Equity-Kurve, wobei die Rendite auf dem Kapitalstand zu Beginn des
    Abschnitts basiert (also die Fortführung eines durchgehenden Portfolios
    simuliert statt bei jedem Abschnitt künstlich neu zu starten)."""
    start_date = close.index[start_idx]
    end_date = close.index[end_idx - 1]

    baseline_equity = starting_cash if start_idx == 0 else result.equity_curve.iloc[start_idx - 1]
    end_equity = result.equity_curve.iloc[end_idx - 1]
    return_pct = (end_equity / baseline_equity - 1) * 100

    segment_trades = [t for t in result.trades if start_date <= t.date <= end_date]

    return SegmentMetrics(
        start=start_date,
        end=end_date,
        return_pct=return_pct,
        num_trades=len(segment_trades),
        total_costs=sum(t.cost for t in segment_trades),
    )


def validate(
    close: pd.Series,
    param_grid: list[tuple[int, int]],
    train_ratio: float = 0.7,
    commission_pct: float = 0.0,
    slippage_pct: float = 0.0005,
    stop_loss_pct: float = 0.08,
    take_profit_pct: float = 0.0,
    risk_per_trade_pct: float = 0.0,
    trend_window: int = 0,
    rsi_window: int = 0,
    starting_cash: float = 10_000.0,
) -> ValidationResult:
    if not 0 < train_ratio < 1:
        raise ValueError("train_ratio muss zwischen 0 und 1 liegen.")

    # round() statt int(): int() würde bei Gleitkomma-Ungenauigkeiten
    # (z.B. 650*0.7 == 454.99999999999994 statt 455) den Split fälschlich
    # einen Tag zu früh setzen.
    split_idx = round(len(close) * train_ratio)
    if split_idx < 2 or split_idx >= len(close):
        raise ValueError("Zu wenig Daten für den gewählten train_ratio.")

    candidates: list[ParamCandidate] = []
    for short_w, long_w in param_grid:
        required_history = max(long_w, trend_window, rsi_window)
        if len(close) < required_history + 1 or split_idx < required_history + 1:
            # Zu wenig Historie im Trainingsabschnitt, um diese Fenstergröße
            # (bzw. Trend-/RSI-Filter) fair zu bewerten -> überspringen
            # statt verzerrte Ergebnisse.
            continue

        result = run_backtest(
            close,
            short_w,
            long_w,
            starting_cash=starting_cash,
            commission_pct=commission_pct,
            slippage_pct=slippage_pct,
            stop_loss_pct=stop_loss_pct,
            take_profit_pct=take_profit_pct,
            risk_per_trade_pct=risk_per_trade_pct,
            trend_window=trend_window,
            rsi_window=rsi_window,
        )

        train_metrics = _segment_metrics(result, close, starting_cash, 0, split_idx)
        test_metrics = _segment_metrics(result, close, starting_cash, split_idx, len(close))
        candidates.append(ParamCandidate(short_w, long_w, train_metrics, test_metrics))

    if not candidates:
        raise ValueError(
            "Keine Parameterkombination hat genug Daten im Trainingsabschnitt "
            "(mehr Handelstage laden oder train_ratio erhöhen)."
        )

    candidates.sort(key=lambda c: c.train.return_pct, reverse=True)
    best = candidates[0]

    return ValidationResult(
        split_date=close.index[split_idx],
        train_ratio=train_ratio,
        best=best,
        all_candidates=candidates,
    )

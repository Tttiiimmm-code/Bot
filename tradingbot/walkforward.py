"""Walk-Forward-Validierung: wiederholt validate() über mehrere
aufeinanderfolgende Zeitfenster statt eines einzelnen Trainings-/
Testsplits.

Ein einzelner Train-/Test-Split (validation.py) beantwortet nur "hätten
die auf den ersten X% der Daten gewählten Parameter auf den letzten Y%
funktioniert?" -- ein einziger Testzeitraum kann zufällig günstig oder
ungünstig ausfallen. Walk-Forward wiederholt dieselbe Frage über mehrere
Fenster hinweg (z.B. quartalsweise) und aggregiert die Ergebnisse: eine
Strategie, die nur in einem einzelnen Testfenster gut abschneidet, fällt
hier durch Inkonsistenz auf, eine Strategie, die über viele verschiedene
Marktphasen hinweg funktioniert, zeigt eine stabile Testrendite.

Nur die SMA-Fenster (param_grid) werden pro Zeitfenster neu ausgewählt --
wie schon bei validate() selbst. Kosten/Stop-Loss/Take-Profit/Trend-/
RSI-Filter bleiben über alle Fenster fest (dieselbe Fläche zusätzlich
"walk-forward" zu optimieren würde die Kombinatorik und damit das
Overfitting-Risiko explodieren lassen, siehe README).
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field

import pandas as pd

from tradingbot.validation import ValidationResult, validate


@dataclass
class WalkForwardWindow:
    window_index: int
    train_start: pd.Timestamp
    train_end: pd.Timestamp
    test_start: pd.Timestamp
    test_end: pd.Timestamp
    result: ValidationResult


@dataclass
class WalkForwardResult:
    windows: list[WalkForwardWindow] = field(default_factory=list)
    mean_test_return_pct: float = 0.0
    median_test_return_pct: float = 0.0
    win_rate: float = 0.0
    # Verkettete (compounded) Testrendite: simuliert, was tatsächlich
    # passiert wäre, wenn man die Parameter am Ende jedes Trainingsfensters
    # neu gewählt und dann nur im jeweils folgenden Testfenster gehandelt
    # hätte -- eine realistischere Gesamtschätzung als der einfache
    # Durchschnitt der Einzelfenster-Renditen. Nur definiert, wenn sich die
    # Testfenster nicht überlappen (step >= test_window): bei Überlappung
    # würden dieselben Kalendertage mehrfach verkettet und die Rendite
    # künstlich aufblähen -- dann None.
    compounded_test_return_pct: float | None = None


def walk_forward_validate(
    close: pd.Series,
    param_grid: list[tuple[int, int]],
    train_window: int,
    test_window: int,
    step: int | None = None,
    expanding: bool = False,
    commission_pct: float = 0.0,
    slippage_pct: float = 0.0005,
    stop_loss_pct: float = 0.08,
    take_profit_pct: float = 0.0,
    risk_per_trade_pct: float = 0.0,
    trend_window: int = 0,
    rsi_window: int = 0,
    starting_cash: float = 10_000.0,
) -> WalkForwardResult:
    """Wiederholt validate() über mehrere Zeitfenster.

    - `train_window`/`test_window`: Größe von Trainings-/Testabschnitt in
      Handelstagen pro Fenster.
    - `step`: um wie viele Handelstage das Fenster pro Schritt vorrückt.
      Standard (None) = test_window, d.h. nicht überlappende Testfenster
      (jeder Handelstag fließt in genau ein Testfenster ein).
    - `expanding`: False (Standard) = "rolling", das Trainingsfenster hat
      über alle Schritte dieselbe feste Größe und rutscht mit; True =
      "expanding", das Trainingsfenster beginnt immer bei Tag 0 und wächst
      mit jedem Schritt -- nutzt mit der Zeit mehr Historie, reagiert aber
      langsamer auf Regimewechsel als "rolling".

    Jedes Fenster ruft validate() auf dem jeweiligen Ausschnitt auf (der
    exakt bei `train_start` beginnt), sodass Indikatoren dort ganz normal
    mit NaN/Warmup beginnen -- identisch zum Verhalten von validate() auf
    der Gesamtserie, nur auf einen Ausschnitt begrenzt.
    """
    if train_window <= 0 or test_window <= 0:
        raise ValueError(
            f"train_window und test_window müssen positiv sein, waren {train_window}/{test_window}."
        )
    step_size = step if step is not None else test_window
    if step_size <= 0:
        raise ValueError(f"step muss positiv sein, war {step_size}.")

    n = len(close)
    windows: list[WalkForwardWindow] = []
    i = 0
    while True:
        if expanding:
            train_start_idx = 0
            train_end_idx = train_window + i * step_size
        else:
            train_start_idx = i * step_size
            train_end_idx = train_start_idx + train_window
        test_start_idx = train_end_idx
        test_end_idx = test_start_idx + test_window

        if test_end_idx > n:
            break

        window_close = close.iloc[train_start_idx:test_end_idx]
        window_train_ratio = (train_end_idx - train_start_idx) / len(window_close)

        try:
            result = validate(
                window_close,
                param_grid,
                train_ratio=window_train_ratio,
                commission_pct=commission_pct,
                slippage_pct=slippage_pct,
                stop_loss_pct=stop_loss_pct,
                take_profit_pct=take_profit_pct,
                risk_per_trade_pct=risk_per_trade_pct,
                trend_window=trend_window,
                rsi_window=rsi_window,
                starting_cash=starting_cash,
            )
        except ValueError:
            # Keine Grid-Kombination hatte genug Historie in DIESEM Fenster
            # (z.B. ein sehr kurzes Trainingsfenster) -- Fenster überspringen
            # statt den gesamten Walk-Forward-Lauf abzubrechen, ein späteres
            # (bei "expanding" größeres) Fenster kann trotzdem auswertbar sein.
            i += 1
            continue

        windows.append(
            WalkForwardWindow(
                window_index=i,
                train_start=window_close.index[0],
                train_end=window_close.index[train_end_idx - train_start_idx - 1],
                test_start=window_close.index[test_start_idx - train_start_idx],
                test_end=window_close.index[-1],
                result=result,
            )
        )
        i += 1

    if not windows:
        raise ValueError(
            "Kein Zeitfenster hatte genug Daten für die gewählte Grid-/Fenstergröße "
            "(mehr --days, kleinere Fenster oder ein kleineres Grid verwenden)."
        )

    test_returns = [w.result.best.test.return_pct for w in windows]

    compounded_pct: float | None = None
    if step_size >= test_window:
        # Nur bei step >= test_window ueberlappen sich die Testfenster
        # nicht -- jeder Kalendertag zaehlt dann in hoechstens ein
        # Testfenster, Verketten simuliert also eine echte fortlaufende
        # Handelsperiode. Bei ueberlappenden Fenstern (step < test_window,
        # z.B. fuer feineres Robustheits-Sampling) wuerden dieselben Tage
        # mehrfach gezaehlt und die verkettete Rendite verfaelschen.
        compounded = 1.0
        for r in test_returns:
            compounded *= 1 + r / 100
        compounded_pct = (compounded - 1) * 100

    return WalkForwardResult(
        windows=windows,
        mean_test_return_pct=statistics.mean(test_returns),
        median_test_return_pct=statistics.median(test_returns),
        win_rate=sum(1 for r in test_returns if r > 0) / len(test_returns),
        compounded_test_return_pct=compounded_pct,
    )

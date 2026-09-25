"""Strategie-Forschung: Datencache, Intraday-Backtest-Engine, Kennzahlen
und Kandidaten-Strategien. Rein historische Analyse, löst nie Orders aus.

Protokoll (siehe README, Abschnitt "Strategie-Forschung"): alles ab
HOLDOUT_START ist gesperrt und wird für den finalen Kandidaten genau
einmal geöffnet.
"""

from datetime import date

# Beginn des gesperrten Holdout-Zeitraums (die letzten ~12 Monate vor
# Beginn der Forschung am 2026-09-24).
HOLDOUT_START = date(2025, 9, 22)

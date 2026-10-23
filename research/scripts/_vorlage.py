"""Runde {NR}: {TITEL} -- Vorab: PROTOCOL.md Runde {NR}.

Aufruf aus dem Haupt-Repo: python tools/runde.py rechnen {NR}
"""
from __future__ import annotations

import numpy as np  # noqa: F401
import pandas as pd  # noqa: F401

from rlib import judge, random_arm, spy_daily, switch_costs, verdict  # noqa: F401

A, B = "2016-01-01", "2025-09-30"            # Hauptzeitraum laut Vorab-Eintrag


def strategy(spy: pd.Series) -> pd.Series:
    """Tagesrenditen der Regel nach Kosten (Signal nur aus Daten bis zum Vortag)."""
    raise NotImplementedError


def main():
    spy = spy_daily()
    print("Runde {NR} -- {TITEL}\n")
    print("Hauptkriterium:")
    res = [judge(strategy(spy), spy, A, B, label="Regel", k=1)]   # ggf. ohne_besten_monat=True
    # Trade-Regeln mit Trendfilter: random_arm(sim, signale, filter, label="Regel vs Zufall") (vorab festlegen)
    print("\nInfo (nicht gewertet):")
    verdict(res)


if __name__ == "__main__":
    main()

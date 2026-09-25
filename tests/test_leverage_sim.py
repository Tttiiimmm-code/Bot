from __future__ import annotations

import numpy as np
import pytest

from tradingbot.research.leverage_sim import SPREAD, grid_martingale, scalper


def bars(close, spread_hl=0.0):
    c = np.asarray(close, dtype=float)
    o = np.concatenate([[c[0]], c[:-1]])
    return o, np.maximum(o, c) * (1 + spread_hl), np.minimum(o, c) * (1 - spread_hl), c


def test_scalper_compounds_on_take_profit_and_stops_at_target():
    # Aufwärtskerze, danach jede Minute +0,03 % -> jedes Mal Ziel (+2 bp) erreicht
    o, h, l, c = bars(100 * 1.0003 ** np.arange(50))
    r = scalper(o, h, l, c, 1, 10.0, 100, target=1e9)
    per_trade = 1 + 100 * (2e-4 - SPREAD)
    assert not r.blown_up and r.final_equity == pytest.approx(10 * per_trade ** r.trades)


def test_scalper_blows_up_on_small_adverse_move_with_extreme_leverage():
    # Long nach Aufwärtskerze, dann -0,05 %: bei 3000x Hebel sind -1,5 x Kapital weg
    o, h, l, c = bars([100, 100.1, 100.05, 100.0])
    r = scalper(o, h, l, c, 1, 10.0, 3000, target=1e9)
    assert r.blown_up and r.final_equity == 0.0


def test_grid_doubles_and_closes_at_average_plus_tp():
    # Long, Kurs fällt um 1 Stufe (Verdopplung), erholt sich dann
    o, h, l, c = bars([100, 100.01, 99.98, 99.99, 100.02])
    r = grid_martingale(o, h, l, c, 1, 10.0, 10, target=1e9, step=3e-4, take_profit=2e-4)
    assert not r.blown_up and r.trades >= 1 and r.final_equity > 10.0

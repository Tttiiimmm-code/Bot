from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from tradingbot.research.crypto import (
    _to_frame,
    is_tradable_asset,
    momentum_weights,
    run_weights,
    trend_weights,
    universe_mask,
)


def test_asset_filter_excludes_stables_wrapped_and_leveraged_tokens():
    bases = {"BTC", "ETH", "JUP", "SYRUP", "BTCUP", "ETHBEAR", "USDC", "WBTC"}
    ok = [s for s in ("BTCUSDT", "JUPUSDT", "SYRUPUSDT", "BTCUPUSDT", "ETHBEARUSDT", "USDCUSDT", "WBTCUSDT")
          if is_tradable_asset(s, bases)]
    assert ok == ["BTCUSDT", "JUPUSDT", "SYRUPUSDT"]
    assert not any(is_tradable_asset(s, bases) for s in ("BULLUSDT", "BEARUSDT", "USDSBUSDT"))


def test_to_frame_handles_ms_and_microsecond_timestamps():
    ms = int(pd.Timestamp("2024-12-31", tz="UTC").timestamp() * 1000)
    us = int(pd.Timestamp("2025-01-01", tz="UTC").timestamp() * 1_000_000)
    rows = [[ms, "1", "2", "0.5", "1.5", "10", 0, "15"], [us, "1.5", "3", "1", "2.5", "20", 0, "50"]]
    df = _to_frame(rows)
    assert list(df.index) == [date(2024, 12, 31), date(2025, 1, 1)]
    assert df["close"].tolist() == [1.5, 2.5] and df["quote_volume"].tolist() == [15.0, 50.0]


def _panel(n=100):
    idx = pd.date_range("2021-01-01", periods=n).date
    close = pd.DataFrame({"BTCUSDT": np.linspace(100, 200, n), "AAAUSDT": np.linspace(10, 5, n),
                          "BBBUSDT": 10 * 1.01 ** np.arange(n)}, index=idx)
    vol = pd.DataFrame({"BTCUSDT": 1e9, "AAAUSDT": 1e6, "BBBUSDT": 1e7}, index=idx)
    return close, vol


def test_universe_uses_prior_volume_and_min_history():
    close, vol = _panel()
    close.iloc[:50, 2] = np.nan  # BBB erst ab Tag 50 gelistet
    u = universe_mask(close, vol, top_n=2, min_history=30)
    assert not u.iloc[10].any()  # noch keine 20 Vortage Volumen
    assert u.iloc[40].tolist() == [True, True, False]
    assert u.iloc[99].tolist() == [True, False, True]  # BBB nach 30 Tagen Historie vor AAA


def test_run_weights_applies_next_day_return_and_costs():
    idx = pd.date_range("2021-01-01", periods=4).date
    close = pd.DataFrame({"X": [100.0, 110.0, 121.0, 121.0]}, index=idx)
    w = pd.DataFrame({"X": [1.0, 1.0, 0.0, 0.0]}, index=idx)
    res = run_weights(w, close, cost_per_side=0.01, name="t")
    # Tag 2: +10 % abzüglich Einstiegskosten, Tag 3: +10 %, Tag 4: 0 abzgl. Ausstiegskosten
    assert res.daily_returns.tolist() == pytest.approx([0.10 - 0.01, 0.10, -0.01])


def test_trend_weights_only_above_sma():
    close = pd.Series([1, 2, 3, 2, 1, 2, 3], dtype=float)
    w = trend_weights(close, 3)
    assert w.tolist() == [0, 0, 1, 0, 0, 1, 1]


def test_momentum_weights_picks_top_k_weekly_and_respects_btc_filter():
    close, vol = _panel()
    u = pd.DataFrame(True, index=close.index, columns=close.columns)
    w = momentum_weights(close, u, lookback=7, k=1, btc_filter=False)
    # BBB wächst am stärksten (1 %/Tag vs. BTC ~0,7 %/Tag am Ende)
    assert w.iloc[98].idxmax() == "BBBUSDT" and w.iloc[98].sum() == pytest.approx(1.0)
    falling = close.copy()
    falling["BTCUSDT"] = np.linspace(200, 100, len(close))
    wf = momentum_weights(falling, u, lookback=7, k=1, btc_filter=True)
    assert wf.iloc[60:].to_numpy().sum() == 0  # BTC unter SMA50 -> Cash


def test_momentum_weights_hold_between_rebalances_and_drop_delisted():
    close, vol = _panel(30)
    close["BTCUSDT"] = 100.0  # BTC seitwärts -> BBB ist der stärkste Coin
    u = pd.DataFrame(True, index=close.index, columns=close.columns)
    close.iloc[25:, 2] = np.nan  # BBB delistet
    w = momentum_weights(close, u, lookback=7, k=1, btc_filter=False)
    assert w.iloc[21:25]["BBBUSDT"].tolist() == [1.0] * 4
    assert w.iloc[26]["BBBUSDT"] == 0.0

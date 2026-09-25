from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from tradingbot.research.orb import OrbParams, simulate_symbol_day
from tradingbot.research.universe import (
    _data_symbols,
    daily_features,
    opening_needs,
    select_candidates,
)

DAY = date(2021, 3, 1)


def day_bars(path_close, open0=None):
    """Minuten-Bars eines Tages aus einer Schlusskurs-Folge."""
    close = np.asarray(path_close, dtype=float)
    open_ = np.concatenate([[open0 if open0 is not None else close[0]], close[:-1]])
    idx = pd.date_range("2021-03-01 09:30", periods=len(close), freq="min", tz="America/New_York")
    return pd.DataFrame({"open": open_, "high": np.maximum(open_, close),
                         "low": np.minimum(open_, close), "close": close, "volume": 1000}, index=idx)


def test_long_breakout_held_to_close():
    # OR (5 Min) steigt 10 -> 10.5, danach Ausbruch und weiter hoch
    path = list(np.linspace(10.1, 10.5, 5)) + list(np.linspace(10.6, 12, 385))
    t = simulate_symbol_day(DAY, "X", day_bars(path, 10.0), atr=1.0, params=OrbParams(), position_cap=1.0)
    assert t.side == 1 and t.reason == "close"
    assert t.entry_price == pytest.approx(10.5)  # max(open 10.5, level 10.5)
    assert t.exit_price == pytest.approx(12.0)
    # Risiko 1 % / (0,1 ATR / 10,5) = 1,05 -> auf position_cap gedeckelt
    assert t.exposure == pytest.approx(1.0)


def test_short_breakout_stopped_out():
    path = list(np.linspace(9.9, 9.5, 5)) + [9.45, 9.4, 9.6] + [9.6] * 382
    t = simulate_symbol_day(DAY, "X", day_bars(path, 10.0), atr=1.0, params=OrbParams(), position_cap=0.05)
    assert t.side == -1 and t.reason == "stop"
    assert t.entry_price == pytest.approx(9.5)
    assert t.exit_price == pytest.approx(9.6)  # Stop 9.5 + 0.1 ATR, Bar-Open 9.4 < Stop
    assert t.exposure == pytest.approx(0.05)


def test_long_only_skips_bearish_range_and_doji():
    bearish = list(np.linspace(9.9, 9.5, 5)) + [9.0] * 385
    assert simulate_symbol_day(DAY, "X", day_bars(bearish, 10.0), 1.0, OrbParams(long_only=True), 1.0) is None
    doji = [10.0] * 390
    assert simulate_symbol_day(DAY, "X", day_bars(doji, 10.0), 1.0, OrbParams(), 1.0) is None


def test_no_trade_without_breakout():
    path = list(np.linspace(10.1, 10.5, 5)) + [10.4] * 385
    assert simulate_symbol_day(DAY, "X", day_bars(path, 10.0), 1.0, OrbParams(), 1.0) is None


def test_stop_in_entry_bar_fills_at_stop():
    path = list(np.linspace(10.1, 10.5, 5)) + [10.6] + [11] * 384
    bars = day_bars(path, 10.0)
    bars.iloc[5, bars.columns.get_loc("low")] = 10.0  # Einstiegs-Bar fällt unter Stop 10.4
    t = simulate_symbol_day(DAY, "X", bars, 1.0, OrbParams(), 1.0)
    assert t.reason == "stop" and t.exit_price == pytest.approx(10.4)


def test_orb_no_look_ahead():
    rng = np.random.default_rng(4)
    for seed in range(20):
        path = 10 * np.cumprod(1 + np.random.default_rng(seed).normal(0, 0.002, 390))
        bars = day_bars(path, 10 * (1 + rng.normal(0, 0.003)))
        for cut in (20, 120, 300):
            ts = bars.index[cut]
            corrupted = bars.copy()
            corrupted.loc[corrupted.index >= ts, ["open", "high", "low", "close"]] *= 1.3
            for p in (OrbParams(), OrbParams(or_minutes=15)):
                a = simulate_symbol_day(DAY, "X", bars, 0.5, p, 1.0)
                b = simulate_symbol_day(DAY, "X", corrupted, 0.5, p, 1.0)
                if a is not None and a.exit_time < ts:
                    assert a == b
                if a is not None and a.entry_time < ts:
                    assert b is not None and (a.side, a.entry_price) == (b.side, b.entry_price)


def _panel():
    dates = pd.bdate_range("2021-01-04", periods=20).date
    rows = []
    for sym, vol, price in (("AAA", 2_000_000, 20.0), ("BBB", 500_000, 20.0), ("CCC", 2_000_000, 3.0)):
        for i, d in enumerate(dates):
            rows.append({"symbol": sym, "date": d, "open": price, "high": price + 1, "low": price - 1,
                         "close": price, "volume": vol})
    return pd.DataFrame(rows).set_index(["symbol", "date"]), dates


def test_daily_features_use_only_prior_days():
    panel, dates = _panel()
    panel.loc[("AAA", dates[14]), "volume"] = 1e12  # nur Tag 14 extrem
    f = daily_features(panel)
    assert f.loc[("AAA", dates[14]), "avg_volume"] == pytest.approx(2_000_000)
    assert f.loc[("AAA", dates[15]), "avg_volume"] > 1e10
    assert f.loc[("AAA", dates[14]), "atr"] == pytest.approx(2.0)
    assert bool(f.loc[("AAA", dates[14]), "eligible"])
    assert not f.loc[("BBB", dates[14]), "eligible"]  # zu wenig Volumen
    assert not f.loc[("CCC", dates[14]), "eligible"]  # Kurs < 5 $


def test_opening_needs_include_history_window():
    panel, dates = _panel()
    needs = opening_needs(daily_features(panel))
    # AAA ist ab Tag 14 zulässig -> Eröffnungs-Bars schon ab Tag 0 nötig
    assert "AAA" in needs[dates[0]] and "AAA" in needs[dates[19]]
    assert all("BBB" not in s for s in needs.values())


def test_select_candidates_ranks_by_relative_volume():
    panel, dates = _panel()
    panel = panel.reset_index()
    panel = pd.concat([panel, panel[panel.symbol == "AAA"].assign(symbol="DDD")])
    panel = panel.set_index(["symbol", "date"]).sort_index()
    feats = daily_features(panel)
    rows = []
    for i, d in enumerate(dates):
        rows.append({"date": d, "symbol": "AAA", "open": 20, "high": 21, "low": 19, "close": 20.5,
                     "volume": 1000 if i < 19 else 3000})
        rows.append({"date": d, "symbol": "DDD", "open": 20, "high": 21, "low": 19, "close": 20.5,
                     "volume": 1000 if i < 19 else 1500})
    opening = pd.DataFrame(rows).set_index(["date", "symbol"])
    cands = select_candidates(feats, opening, top_n=1)
    last = cands.loc[dates[19]]
    assert list(last.index) == ["AAA"] and last["relvol"].iloc[0] == pytest.approx(3.0)
    # vor Tag 14 nicht zulässig, ab Tag 14 mit >= 10 Tagen Historie
    assert dates[13] not in cands.index.get_level_values("date")


def test_data_symbols_maps_delisted_and_drops_cusips():
    assets = pd.DataFrame({"symbol": ["AAPL", "PBSK_DELISTED", "097ESC065", "AAPL_DELISTED", "BRK"]})
    assert _data_symbols(assets) == ["AAPL", "BRK", "PBSK"]


def test_run_orb_reads_months_and_respects_holdout(tmp_path):
    from tradingbot.research import HOLDOUT_START
    from tradingbot.research.engine import CostModel
    from tradingbot.research.orb import run_orb

    path = list(np.linspace(10.1, 10.5, 5)) + list(np.linspace(10.6, 11, 385))
    frames, cand_rows = [], []
    for d in (DAY, HOLDOUT_START):
        bars = day_bars(path, 10.0)
        bars.index = pd.date_range(f"{d} 09:30", periods=390, freq="min", tz="America/New_York")
        bars.index = pd.MultiIndex.from_arrays([["X"] * 390, bars.index.tz_convert("UTC")],
                                               names=["symbol", "timestamp"])
        (tmp_path / "intraday").mkdir(exist_ok=True)
        bars.to_pickle(tmp_path / "intraday" / f"{d.year}-{d.month:02d}.pkl")
        cand_rows.append({"date": d, "symbol": "X", "atr": 1.0, "relvol": 2.0})
    candidates = pd.DataFrame(cand_rows).set_index(["date", "symbol"])
    res = run_orb({"v": OrbParams()}, candidates, CostModel(0, 0, 0), max_exposure=1.0,
                  top_n=20, base=tmp_path)["v"]
    assert list(res.daily_returns.index) == [DAY]
    assert res.daily_returns.iloc[0] == pytest.approx(0.05 * (11 / 10.5 - 1))
    opened = run_orb({"v": OrbParams()}, candidates, CostModel(0, 0, 0), base=tmp_path,
                     allow_holdout=True)["v"]
    assert len(opened.daily_returns) == 2


def _ambiguous_long_bars():
    # OR 10.1..10.5, Einstiegs-Bar (9:35) reicht bis 10.3 hinunter -> berührt Stop 10.4
    path = list(np.linspace(10.1, 10.5, 5)) + [10.6] + [11] * 384
    bars = day_bars(path, 10.0)
    bars.iloc[5, bars.columns.get_loc("low")] = 10.3
    return bars


def test_ticks_resolve_entry_minute_in_favour():
    bars = _ambiguous_long_bars()
    # Tief kommt VOR dem Ausbruch über 10.5, danach kein Stop mehr
    ticks = np.array([10.45, 10.30, 10.48, 10.52, 10.60])
    t = simulate_symbol_day(DAY, "X", bars, 1.0, OrbParams(), 1.0,
                            lambda sym, ts: ticks if ts == bars.index[5] else None)
    assert t.reason == "close" and t.entry_price == pytest.approx(10.52)
    assert t.exit_price == pytest.approx(11)


def test_ticks_confirm_stop_after_entry():
    bars = _ambiguous_long_bars()
    ticks = np.array([10.49, 10.55, 10.50, 10.44, 10.60])
    t = simulate_symbol_day(DAY, "X", bars, 1.0, OrbParams(), 1.0, lambda sym, ts: ticks)
    assert t.reason == "stop" and t.entry_price == pytest.approx(10.55)
    assert t.exit_price == pytest.approx(10.44) and t.exit_time == bars.index[5]
    assert t.symbol == "X"


def test_raw_ticks_are_rescaled_to_split_adjusted_bars():
    bars = _ambiguous_long_bars()
    # Gleicher Verlauf wie oben, aber Rohkurse vor einem 1:4-Split
    ticks = np.array([10.49, 10.55, 10.50, 10.44, 10.60]) * 4
    t = simulate_symbol_day(DAY, "X", bars, 1.0, OrbParams(), 1.0, lambda sym, ts: ticks)
    assert t.reason == "stop" and t.entry_price == pytest.approx(10.55, rel=0.02)
    assert t.exit_price == pytest.approx(10.44, rel=0.02)


def test_without_ticks_entry_minute_stays_conservative():
    bars = _ambiguous_long_bars()
    t = simulate_symbol_day(DAY, "X", bars, 1.0, OrbParams(), 1.0, lambda sym, ts: None)
    assert t.reason == "stop" and t.exit_price == pytest.approx(10.4)


def test_clean_ticks_drops_odd_lots():
    from tradingbot.research.universe import _clean_ticks

    df = pd.DataFrame({"price": [1.0, 2.0, 3.0], "conditions": [[" "], ["I"], ["@", "F"]]})
    assert _clean_ticks(df)["price"].tolist() == [1.0, 3.0]

from __future__ import annotations

import math
from datetime import date

import numpy as np
import pandas as pd
import pytest

from tradingbot.research import HOLDOUT_START
from tradingbot.research.data import load_minute_bars, split_sessions
from tradingbot.research.engine import CostModel, Trade, run_backtest
from tradingbot.research.metrics import (
    compute_metrics,
    deflated_sharpe,
    expected_max_sharpe,
    max_drawdown,
    sharpe_ratio,
)
from tradingbot.research.strategies import GapFade, LastHalfHourMomentum, NoiseAreaBreakout


def make_sessions(n_days: int, seed: int = 0, start: str = "2020-01-02", drift: float = 0.0):
    """Zufallspfad-Minuten-Bars, 390 Bars je Tag, Index America/New_York."""
    rng = np.random.default_rng(seed)
    days = pd.bdate_range(start, periods=n_days)
    frames, price = [], 100.0
    for d in days:
        idx = pd.date_range(d + pd.Timedelta(hours=9, minutes=30), periods=390, freq="min", tz="America/New_York")
        rets = rng.normal(drift, 0.0008, 390)
        close = price * np.cumprod(1 + rets)
        open_ = np.concatenate([[price * (1 + rng.normal(0, 0.003))], close[:-1]])
        high = np.maximum(open_, close) * 1.0002
        low = np.minimum(open_, close) * 0.9998
        frames.append(pd.DataFrame(
            {"open": open_, "high": high, "low": low, "close": close, "volume": rng.integers(1000, 5000, 390)},
            index=idx,
        ))
        price = close[-1]
    return split_sessions(pd.concat(frames))


def test_split_sessions_groups_by_trading_day():
    sessions = make_sessions(3)
    assert [len(b) for _, b in sessions] == [390, 390, 390]
    assert sessions[0][0] == date(2020, 1, 2)


def test_load_minute_bars_reads_cache_without_client(tmp_path):
    bars = pd.concat([b for _, b in make_sessions(3)])
    bars.to_pickle(tmp_path / "SPY_1min.pkl")
    out = load_minute_bars("spy", start=date(2020, 1, 3), end=date(2020, 1, 3), cache_dir=tmp_path)
    assert len(out) == 390 and out.index[0].date() == date(2020, 1, 3)


def _trade(side=1, entry=100.0, exit_=101.0, exposure=1.0, day=date(2020, 1, 2)):
    ts = pd.Timestamp("2020-01-02 10:00", tz="America/New_York")
    return Trade(day, side, ts, entry, ts, exit_, exposure)


def test_trade_gross_return_long_and_short():
    assert _trade(1, 100, 101).gross_return == pytest.approx(0.01)
    assert _trade(-1, 100, 101).gross_return == pytest.approx(-0.01)


def test_cost_model_round_trip():
    costs = CostModel(slippage_bps=1.0, commission_per_share=0.0, sec_fee_rate=0.0)
    assert costs.round_trip_cost(_trade()) == pytest.approx(0.0002)
    with_comm = CostModel(slippage_bps=0.0, commission_per_share=0.01, sec_fee_rate=0.0)
    assert with_comm.round_trip_cost(_trade(1, 100, 100)) == pytest.approx(0.0002)


class _FixedStrategy:
    name = "fixed"
    warmup_days = 1

    def __init__(self, exposure=2.0):
        self.exposure = exposure

    def trades_for_day(self, sessions, i):
        return [_trade(1, 100, 101, self.exposure, sessions[i][0])]


def test_run_backtest_caps_exposure_and_applies_costs():
    sessions = make_sessions(4)
    res = run_backtest(sessions, _FixedStrategy(exposure=2.0), CostModel(1.0, 0, 0), max_exposure=1.0)
    assert len(res.daily_returns) == 3  # Warmup-Tag übersprungen
    assert res.daily_returns.iloc[0] == pytest.approx(0.01 - 0.0002)


def test_run_backtest_blocks_holdout_unless_allowed():
    sessions = make_sessions(10, start=str(HOLDOUT_START - pd.Timedelta(days=7)))
    blocked = run_backtest(sessions, _FixedStrategy())
    assert all(d < HOLDOUT_START for d in blocked.daily_returns.index)
    opened = run_backtest(sessions, _FixedStrategy(), allow_holdout=True)
    assert any(d >= HOLDOUT_START for d in opened.daily_returns.index)


def test_sharpe_and_drawdown():
    r = pd.Series([0.01, -0.02, 0.01, 0.0])
    assert max_drawdown(r) == pytest.approx(-0.02)
    assert sharpe_ratio(pd.Series([0.0, 0.0])) == 0.0
    assert sharpe_ratio(pd.Series([0.01, 0.02, 0.01, 0.02])) > 0


def test_deflated_sharpe_penalises_many_trials():
    rng = np.random.default_rng(1)
    r = pd.Series(rng.normal(0.0005, 0.01, 1000))
    single = deflated_sharpe(r, 1, 0.0)
    many = deflated_sharpe(r, 100, 0.03**2)
    assert 0 <= many < single <= 1
    assert expected_max_sharpe(1, 1.0) == 0.0


def test_compute_metrics_profit_factor():
    sessions = make_sessions(3)
    res = run_backtest(sessions, _FixedStrategy(1.0), CostModel(0, 0, 0))
    m = compute_metrics(res)
    assert m.n_trades == 2 and m.win_rate == 1.0 and math.isinf(m.profit_factor)


def _corrupt_from(sessions, i, ts):
    """Ersetzt in Tag i alle Bars ab `ts` und alle Folgetage durch Unsinn."""
    out = list(sessions)
    d, bars = out[i]
    bars = bars.copy()
    mask = bars.index >= ts
    bars.loc[mask, ["open", "high", "low", "close"]] *= 1.5
    bars.loc[mask, "volume"] = 1
    out[i] = (d, bars)
    for k in range(i + 1, len(out)):
        dk, bk = out[k]
        out[k] = (dk, bk * 0.5)
    return out


@pytest.mark.parametrize(
    "factory",
    [
        lambda: NoiseAreaBreakout(),
        lambda: NoiseAreaBreakout(long_only=True, check_minutes=15),
        lambda: LastHalfHourMomentum(),
        lambda: GapFade(min_gap=0.0),
        lambda: GapFade(min_gap=0.0, exit_minute=150, long_only=True),
    ],
)
def test_strategies_have_no_look_ahead(factory):
    sessions = make_sessions(40, seed=3, drift=0.00005)
    for i in range(20, 40, 3):
        original = factory().trades_for_day(sessions, i)
        day_idx = sessions[i][1].index
        for cut in (60, 200, 361):
            ts = day_idx[cut]
            changed = factory().trades_for_day(_corrupt_from(sessions, i, ts), i)
            before = [t for t in original if t.exit_time < ts]
            assert [t for t in changed if t.exit_time < ts] == before
            assert [(t.side, t.entry_time, t.entry_price) for t in original if t.entry_time < ts] == [
                (t.side, t.entry_time, t.entry_price) for t in changed if t.entry_time < ts
            ]


def test_noise_breakout_goes_long_on_strong_trend_day():
    sessions = make_sessions(20, seed=5)
    d, bars = sessions[-1]
    bars = bars.copy()
    ramp = np.linspace(1.0, 1.05, 390)
    base = bars["open"].iloc[0]
    for col in ("open", "high", "low", "close"):
        bars[col] = base * ramp
    sessions[-1] = (d, bars)
    trades = NoiseAreaBreakout().trades_for_day(sessions, len(sessions) - 1)
    assert len(trades) == 1 and trades[0].side == 1 and trades[0].reason == "close"
    # Einstieg nur zu einem Halbstunden-Prüfzeitpunkt ab 10:00
    assert trades[0].entry_time.minute in (0, 30) and trades[0].entry_time.hour >= 10


def test_last_half_hour_direction_and_long_only():
    sessions = make_sessions(3, seed=7)
    i = 2
    prev_close = sessions[1][1]["close"].iloc[-1]
    close_10 = sessions[i][1]["close"].iloc[29]
    trades = LastHalfHourMomentum().trades_for_day(sessions, i)
    assert trades[0].side == (1 if close_10 > prev_close else -1)
    assert trades[0].entry_time.strftime("%H:%M") == "15:30"
    if close_10 < prev_close:
        assert LastHalfHourMomentum(long_only=True).trades_for_day(sessions, i) == []


def test_month_chunks_cover_range_without_gaps():
    from tradingbot.research.data import _month_chunks

    chunks = _month_chunks(date(2020, 1, 15), date(2020, 3, 2))
    assert chunks == [
        (date(2020, 1, 15), date(2020, 1, 31)),
        (date(2020, 2, 1), date(2020, 2, 29)),
        (date(2020, 3, 1), date(2020, 3, 2)),
    ]


def _gap_day(sessions, gap, path):
    """Setzt den letzten Tag auf Open = Vortagesschluss*(1+gap) und danach
    einen Kursverlauf `path` (relativ zum Open, 390 Werte)."""
    d, bars = sessions[-1]
    prev_close = sessions[-2][1]["close"].iloc[-1]
    o = prev_close * (1 + gap)
    close = o * np.asarray(path)
    open_ = np.concatenate([[o], close[:-1]])
    bars = pd.DataFrame(
        {"open": open_, "high": np.maximum(open_, close), "low": np.minimum(open_, close),
         "close": close, "volume": 1000},
        index=bars.index,
    )
    sessions[-1] = (d, bars)
    return prev_close, o


def test_gap_fade_hits_target_on_gap_fill():
    sessions = make_sessions(3, seed=2)
    prev_close, o = _gap_day(sessions, -0.01, np.linspace(1.0, 1.02, 390))
    (t,) = GapFade().trades_for_day(sessions, 2)
    assert t.side == 1 and t.reason == "target"
    assert t.exit_price == pytest.approx(prev_close, rel=1e-3)


def test_gap_fade_stops_out_when_gap_extends():
    sessions = make_sessions(3, seed=2)
    prev_close, o = _gap_day(sessions, 0.01, np.linspace(1.0, 1.03, 390))
    (t,) = GapFade().trades_for_day(sessions, 2)
    assert t.side == -1 and t.reason == "stop"
    assert t.exit_price == pytest.approx(o * 1.01, rel=1e-3)
    assert GapFade(long_only=True).trades_for_day(sessions, 2) == []


def test_gap_fade_skips_small_and_huge_gaps():
    sessions = make_sessions(3, seed=2)
    _gap_day(sessions, 0.001, np.ones(390))
    assert GapFade().trades_for_day(sessions, 2) == []
    _gap_day(sessions, 0.05, np.ones(390))
    assert GapFade().trades_for_day(sessions, 2) == []


def test_gap_fade_time_exit():
    sessions = make_sessions(3, seed=2)
    _gap_day(sessions, -0.01, np.ones(390))
    (t,) = GapFade(exit_minute=150).trades_for_day(sessions, 2)
    assert t.reason == "time" and t.exit_time.strftime("%H:%M") == "11:59"

"""CLI der Strategie-Forschung (braucht nur für `fetch` Alpaca-Keys).

    python -m tradingbot.research fetch --symbols SPY,QQQ
    python -m tradingbot.research grid --family noise_breakout --symbols SPY,QQQ
    python -m tradingbot.research run --family noise_breakout --symbol SPY --params band_mult=1.0
    python -m tradingbot.research holdout --family ... --symbol ... --params ...   (EINMALIG)

Jeder ausgewertete Variantenlauf (außer `holdout`) wird in
research/trials.csv protokolliert; die Deflated Sharpe Ratio rechnet mit
der Gesamtzahl aller je protokollierten Versuche.
"""

from __future__ import annotations

import argparse
import csv
import itertools
import json
import logging
import math
import os
import sys
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from tradingbot.research import HOLDOUT_START
from tradingbot.research.data import EARLIEST_DATE, load_minute_bars, split_sessions
from tradingbot.research.engine import BacktestResult, CostModel, run_backtest
from tradingbot.research.metrics import (
    TRADING_DAYS,
    compute_metrics,
    deflated_sharpe,
    sharpe_ratio,
    yearly_returns,
)
from tradingbot.research.strategies import GapFade, LastHalfHourMomentum, NoiseAreaBreakout

TRIALS_LOG = Path("research") / "trials.csv"

FAMILIES = {
    "noise_breakout": NoiseAreaBreakout,
    "last_half_hour": LastHalfHourMomentum,
    "gap_fade": GapFade,
}

# Vorab festgelegte Varianten (Plan: höchstens ~20 je Familie). Nicht
# nachträglich erweitern, ohne die neuen Versuche mitzuzählen.
GRIDS: dict[str, list[dict]] = {
    "noise_breakout": [
        {"band_mult": b, "check_minutes": c, **mode}
        for b, c, mode in itertools.product(
            (0.8, 1.0, 1.2),
            (15, 30, 60),
            ({"long_only": False}, {"long_only": True, "max_entries": 1}),
        )
    ],
    "last_half_hour": [
        {"min_abs_signal": s, "long_only": lo}
        for s, lo in itertools.product((0.0, 0.0025, 0.005, 0.01), (False, True))
    ],
    "gap_fade": [
        {"min_gap": g, "exit_minute": e, "long_only": lo}
        for g, e, lo in itertools.product((0.0025, 0.005), (150, 390), (False, True))
    ],
}

# Bestehenskriterien (Plan, Phase 3) -- vor dem ersten Test festgelegt.
MIN_OOS_TRADES = 200
MIN_PROFIT_FACTOR = 1.2
MIN_POSITIVE_WINDOWS = 0.6
MIN_DSR = 0.95


def _parse_params(items: list[str]) -> dict:
    out = {}
    for item in items or []:
        k, v = item.split("=", 1)
        out[k] = json.loads(v.lower()) if v.lower() in ("true", "false", "null") else float(v) if "." in v else int(v)
    return out


def _sessions(symbol: str, allow_holdout: bool = False):
    end = None if allow_holdout else HOLDOUT_START - pd.Timedelta(days=1)
    bars = load_minute_bars(symbol, EARLIEST_DATE, end)
    if bars.empty:
        raise RuntimeError(f"Keine gecachten Daten für {symbol} -- zuerst `fetch` ausführen.")
    return split_sessions(bars)


def _log_trial(family, symbol, params, costs, max_exposure, result: BacktestResult,
               periods: int = TRADING_DAYS) -> None:
    m = compute_metrics(result, periods)
    r = result.daily_returns
    daily_sr = float(r.mean() / r.std(ddof=1)) if len(r) > 1 and r.std(ddof=1) > 0 else 0.0
    TRIALS_LOG.parent.mkdir(exist_ok=True)
    new = not TRIALS_LOG.exists()
    with TRIALS_LOG.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["logged_at", "family", "symbol", "params", "slippage_bps", "max_exposure",
                        "start", "end", "days", "sharpe", "daily_sharpe", "cagr", "max_dd",
                        "n_trades", "profit_factor"])
        w.writerow([datetime.now().isoformat(timespec="seconds"), family, symbol,
                    json.dumps(params, sort_keys=True), costs.slippage_bps, max_exposure,
                    r.index[0], r.index[-1], m.days, round(m.sharpe, 4), round(daily_sr, 6),
                    round(m.cagr, 5), round(m.max_drawdown, 5), m.n_trades, round(m.profit_factor, 4)])


def _trial_stats() -> tuple[int, float]:
    """(Anzahl eindeutiger Versuche, Varianz ihrer täglichen Sharpe Ratios)."""
    if not TRIALS_LOG.exists():
        return 1, 0.0
    df = pd.read_csv(TRIALS_LOG)
    df = df.drop_duplicates(["family", "symbol", "params", "slippage_bps", "max_exposure"], keep="last")
    return max(len(df), 1), float(df["daily_sharpe"].var(ddof=1)) if len(df) > 1 else 0.0


def _print_metrics(label: str, result: BacktestResult, periods: int = TRADING_DAYS) -> None:
    m = compute_metrics(result, periods)
    print(f"{label:<58} Sharpe {m.sharpe:5.2f} | CAGR {m.cagr:7.2%} | MaxDD {m.max_drawdown:7.2%} "
          f"| Trades {m.n_trades:5d} | PF {m.profit_factor:4.2f} | Ø {m.avg_trade_bps:5.1f} bp")


def walk_forward(returns: dict[str, pd.Series], train_days: int, test_days: int) -> tuple[pd.Series, list]:
    """Wählt je Fenster die Variante mit der besten Trainings-Sharpe und
    verkettet deren Renditen im folgenden Testfenster. Zulässig, weil die
    Strategien keinen Zustand über Tage hinweg tragen: ein Gesamtlauf,
    in Fenster geschnitten, entspricht Einzelläufen je Fenster."""
    frame = pd.DataFrame(returns).fillna(0.0)
    oos, windows = [], []
    for start in range(0, len(frame) - train_days - test_days + 1, test_days):
        train = frame.iloc[start:start + train_days]
        test = frame.iloc[start + train_days:start + train_days + test_days]
        best = max(train.columns, key=lambda c: sharpe_ratio(train[c]))
        oos.append(test[best])
        windows.append((test.index[0], test.index[-1], best, float(np.prod(1 + test[best]) - 1)))
    return (pd.concat(oos) if oos else pd.Series(dtype=float)), windows


def cmd_fetch(symbols: list[str], env_file: str) -> None:
    from alpaca.data.historical import StockHistoricalDataClient
    from dotenv import load_dotenv

    load_dotenv(env_file)
    key, secret = os.getenv("ALPACA_API_KEY"), os.getenv("ALPACA_SECRET_KEY")
    if not key or not secret:
        raise RuntimeError("ALPACA_API_KEY/ALPACA_SECRET_KEY fehlen (.env).")
    client = StockHistoricalDataClient(key, secret)
    for s in symbols:
        bars = load_minute_bars(s, data_client=client)
        print(f"{s}: {len(bars):,} Minuten-Bars, {bars.index[0].date()} bis {bars.index[-1].date()}")


def _clients(env_file: str):
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.trading.client import TradingClient
    from dotenv import load_dotenv

    load_dotenv(env_file)
    key, secret = os.getenv("ALPACA_API_KEY"), os.getenv("ALPACA_SECRET_KEY")
    if not key or not secret:
        raise RuntimeError(f"ALPACA_API_KEY/ALPACA_SECRET_KEY fehlen ({env_file}).")
    return StockHistoricalDataClient(key, secret), TradingClient(key, secret, paper=True)


def cmd_universe(env_file: str) -> None:
    from datetime import date as _date, timedelta as _td

    from tradingbot.research.universe import build_all

    data_client, trading_client = _clients(env_file)
    end = datetime.now().date() - _td(days=1)
    cands = build_all(data_client, trading_client, EARLIEST_DATE, end)
    per_day = cands.groupby(level="date").size()
    print(f"Kandidaten: {len(cands):,} an {len(per_day)} Tagen (Ø {per_day.mean():.1f}/Tag)")


def cmd_grid(family: str, symbols: list[str], costs: CostModel, max_exposure: float,
             train_days: int, test_days: int) -> None:
    cls = FAMILIES[family]
    all_returns: dict[str, pd.Series] = {}
    for symbol in symbols:
        sessions = _sessions(symbol)
        for params in GRIDS[family]:
            res = run_backtest(sessions, cls(**params), costs, max_exposure)
            _log_trial(family, symbol, params, costs, max_exposure, res)
            label = f"{symbol} {json.dumps(params, sort_keys=True)}"
            _print_metrics(label, res)
            all_returns[label] = res.daily_returns
    evaluate_walk_forward(all_returns, train_days, test_days)


def evaluate_walk_forward(all_returns: dict[str, pd.Series], train_days: int, test_days: int,
                          benchmark: pd.Series | None = None, periods: int = TRADING_DAYS,
                          benchmark_name: str = "SPY") -> bool:
    """Walk-Forward über alle Varianten und Prüfung der Bestehenskriterien.
    Mit `benchmark` (Runde 2) zusätzlich: Alpha gegenüber dem Benchmark mit t >= 2."""
    n_trials, sr_var = _trial_stats()
    print(f"\nWalk-Forward (Training {train_days} / Test {test_days} Handelstage) über alle "
          f"{len(all_returns)} Varianten dieser Familie; insgesamt protokollierte Versuche: {n_trials}")
    oos, windows = walk_forward(all_returns, train_days, test_days)
    for a, b, best, ret in windows:
        print(f"  {a} .. {b}  {ret:7.2%}  {best}")
    if oos.empty:
        print("Zu wenig Daten für Walk-Forward.")
        return False
    pos_share = float(np.mean([w[3] > 0 for w in windows]))
    oos_total = float(np.prod(1 + oos) - 1)
    oos_sharpe = sharpe_ratio(oos, periods)
    dsr = deflated_sharpe(oos, n_trials, sr_var)
    trade_days = oos[oos != 0]
    wins, losses = trade_days[trade_days > 0].sum(), -trade_days[trade_days < 0].sum()
    pf = wins / losses if losses > 0 else math.inf
    years = len(oos) / periods
    print(f"\nOOS verkettet: {oos_total:.2%} ({(1 + oos_total) ** (1 / years) - 1:.2%} p.a.), Sharpe "
          f"{oos_sharpe:.2f}, positive Fenster {pos_share:.0%}, Handelstage mit Trade {len(trade_days)}, "
          f"PF (Tage) {pf:.2f}, Deflated Sharpe {dsr:.3f}")
    print("Jahresrenditen OOS:", {y: f"{v:.1%}" for y, v in yearly_returns(oos).items()})
    checks = {
        "OOS-Rendite > 0": oos_total > 0,
        f"positive Fenster >= {MIN_POSITIVE_WINDOWS:.0%}": pos_share >= MIN_POSITIVE_WINDOWS,
        f"OOS-Handelstage >= {MIN_OOS_TRADES}": len(trade_days) >= MIN_OOS_TRADES,
        f"Profit-Faktor >= {MIN_PROFIT_FACTOR}": pf >= MIN_PROFIT_FACTOR,
        f"Deflated Sharpe >= {MIN_DSR}": dsr >= MIN_DSR,
    }
    if benchmark is not None:
        from tradingbot.research.swing import alpha_vs_benchmark

        alpha, t_alpha, beta = alpha_vs_benchmark(oos, benchmark, periods)
        bench_oos = benchmark.reindex(oos.index).fillna(0.0)
        print(f"Gegenüber {benchmark_name}: Alpha {alpha:.2%} p.a. (t = {t_alpha:.2f}), Beta {beta:.2f}; "
              f"{benchmark_name} im selben Zeitraum: Sharpe {sharpe_ratio(bench_oos, periods):.2f}, "
              f"{float(np.prod(1 + bench_oos) - 1):.1%} gesamt")
        checks[f"Alpha ggü. {benchmark_name} > 0 mit t >= 2"] = alpha > 0 and t_alpha >= 2
    for name, ok in checks.items():
        print(f"  [{'OK' if ok else 'NEIN'}] {name}")
    print("BESTANDEN (vor Robustheits-/Holdout-Prüfung)" if all(checks.values()) else "NICHT BESTANDEN")
    return all(checks.values())


ORB_GRID = {
    f"or{m}_{'long' if lo else 'both'}": {"or_minutes": m, "long_only": lo}
    for m in (5, 15) for lo in (False, True)
}


def cmd_orb_ticks(env_file: str) -> None:
    """Sammelt alle Einstiegs-Minuten, in denen der Minuten-Bar auch den Stop
    berührt (über alle ORB-Varianten), und lädt deren Ticks. Die long-only-
    Varianten sind Teilmengen der long+short-Varianten."""
    from tradingbot.research.orb import OrbParams, run_orb
    from tradingbot.research.universe import UNIVERSE_DIR, fetch_entry_ticks

    candidates = pd.read_pickle(UNIVERSE_DIR / "candidates.pkl")
    variants = {name: OrbParams(**p) for name, p in ORB_GRID.items() if not p["long_only"]}
    results = run_orb(variants, candidates, CostModel(0, 0, 0), allow_holdout=True)
    events = {
        (t.symbol, t.entry_time)
        for res in results.values() for t in res.trades
        if t.reason == "stop" and t.exit_time == t.entry_time
    }
    print(f"{len(events):,} mehrdeutige Einstiegs-Minuten")
    data_client, _ = _clients(env_file)
    fetch_entry_ticks(data_client, events)


def cmd_orb_grid(slippage_bps: float, per_share: float, train_days: int, test_days: int,
                 use_ticks: bool = False) -> None:
    from tradingbot.research.orb import OrbParams, run_orb
    from tradingbot.research.universe import UNIVERSE_DIR, load_tick_lookup

    path = UNIVERSE_DIR / "candidates.pkl"
    if not path.exists():
        raise RuntimeError("Keine Kandidaten -- zuerst `universe` ausführen.")
    candidates = pd.read_pickle(path)
    costs = CostModel(slippage_bps=slippage_bps, commission_per_share=per_share)
    variants = {name: OrbParams(**p) for name, p in ORB_GRID.items()}
    tick_lookup = load_tick_lookup() if use_ticks else None
    main_returns = {}
    for max_exposure in (4.0, 1.0):
        results = run_orb(variants, candidates, costs, max_exposure=max_exposure, tick_lookup=tick_lookup)
        print(f"\n--- max_exposure {max_exposure} ---")
        for name, res in results.items():
            fill = {"fill": "ticks"} if use_ticks else {}
            _log_trial("orb", "stocks_in_play", {**ORB_GRID[name], "per_share": per_share, **fill},
                       costs, max_exposure, res)
            _print_metrics(name, res)
            print("   Jahre:", {y: f"{v:.1%}" for y, v in yearly_returns(res.daily_returns).items()},
                  "| Anteil Stop:", f"{np.mean([t.reason == 'stop' for t in res.trades]):.0%}")
            if max_exposure == 1.0:
                main_returns[name] = res.daily_returns
    print("\nHauptkriterium (max_exposure 1.0, Cash-Konto):")
    evaluate_walk_forward(main_returns, train_days, test_days)


SWING_ETFS = ["SPY", "QQQ", "IWM", "DIA", "XLK", "XLF", "XLE", "SMH"]
SWING_GRIDS = {
    "overnight": [{"trend_filter": f} for f in (False, True)],
    "rsi2": [{"entry_below": e, "exit_rule": x} for e in (5, 10) for x in ("sma5", "rsi70")],
    "reversal": [{"n_stocks": n, "lookback": lb} for n in (10, 25) for lb in (5, 10)],
}


def cmd_swing_grid(family: str, train_days: int, test_days: int) -> None:
    """Runde 2 (research/PROTOCOL.md): vorab registrierte Varianten, Walk-Forward
    und Alpha-Prüfung gegenüber SPY."""
    from tradingbot.research import swing

    spy = swing.etf_daily("SPY")
    benchmark = (spy["close"] / spy["close"].shift(1) - 1).dropna()
    all_returns: dict[str, pd.Series] = {}
    if family in ("overnight", "rsi2"):
        costs = CostModel(slippage_bps=1.0)
        for symbol in SWING_ETFS:
            daily = swing.etf_daily(symbol)
            for params in SWING_GRIDS[family]:
                if family == "overnight":
                    res = swing.overnight(daily, params["trend_filter"], costs, symbol)
                else:
                    res = swing.rsi2_reversion(daily, params["entry_below"], params["exit_rule"], costs, symbol)
                _log_trial(family, symbol, params, costs, 1.0, res)
                label = f"{symbol} {json.dumps(params, sort_keys=True)}"
                _print_metrics(label, res)
                all_returns[label] = res.daily_returns
    else:
        from tradingbot.research.universe import load_daily_panel

        costs = CostModel(slippage_bps=1.0, commission_per_share=0.01)
        opens, closes, mask = swing.reversal_matrices(load_daily_panel())
        for params in SWING_GRIDS[family]:
            res = swing.weekly_reversal(opens, closes, mask, swing.ReversalParams(**params), costs)
            _log_trial(family, "top500", params, costs, 1.0, res)
            label = f"top500 {json.dumps(params, sort_keys=True)}"
            _print_metrics(label, res)
            print("   Jahre:", {y: f"{v:.1%}" for y, v in yearly_returns(res.daily_returns).items()})
            all_returns[label] = res.daily_returns
    evaluate_walk_forward(all_returns, train_days, test_days, benchmark=benchmark)


CRYPTO_GRIDS = {
    "trend": [{"lookback": n, "asset": a} for n in (20, 50, 100) for a in ("BTCUSDT", "ETHUSDT")],
    "xsmom": [{"lookback": lb, "k": k, "btc_filter": f} for lb in (7, 28) for k in (3, 5) for f in (False, True)],
}


def cmd_crypto_grid(family: str, cost_per_side: float, train_days: int, test_days: int) -> None:
    """Runde 3 (research/PROTOCOL.md): Krypto-Spot, Walk-Forward und Alpha ggü. BTC."""
    from tradingbot.research import crypto

    close, vol = crypto.load_panel()
    btc = close["BTCUSDT"].dropna()
    benchmark = (btc / btc.shift(1) - 1).dropna()
    universe = crypto.universe_mask(close, vol) if family == "xsmom" else None
    costs = CostModel(slippage_bps=cost_per_side * 10_000 / 2)  # nur für das Versuchsprotokoll
    all_returns: dict[str, pd.Series] = {}
    for params in CRYPTO_GRIDS[family]:
        if family == "trend":
            px = close[[params["asset"]]].dropna()
            w = crypto.trend_weights(px[params["asset"]], params["lookback"]).to_frame(params["asset"])
            res = crypto.run_weights(w, px, cost_per_side, "crypto_trend")
        else:
            w = crypto.momentum_weights(close, universe, params["lookback"], params["k"], params["btc_filter"])
            res = crypto.run_weights(w, close, cost_per_side, "crypto_xsmom")
        _log_trial(f"crypto_{family}", "binance", {**params, "cost_per_side": cost_per_side}, costs, 1.0,
                   res, crypto.PERIODS)
        label = json.dumps(params, sort_keys=True)
        _print_metrics(label, res, crypto.PERIODS)
        print("   Jahre:", {y: f"{v:.0%}" for y, v in yearly_returns(res.daily_returns).items()})
        all_returns[label] = res.daily_returns
    bench = BacktestResult("btc", benchmark[benchmark.index >= min(r.index[0] for r in all_returns.values())])
    _print_metrics("Vergleich: BTC Buy-and-Hold", bench, crypto.PERIODS)
    evaluate_walk_forward(all_returns, train_days, test_days, benchmark=benchmark,
                          periods=crypto.PERIODS, benchmark_name="BTC")


METALS = ["GLD", "SLV"]
METALS_GRIDS = {
    "overnight": [{"trend_filter": f} for f in (False, True)],
    "trend": [{"lookback": n} for n in (50, 100, 200)],
}


def cmd_metals_grid(family: str, train_days: int, test_days: int) -> None:
    """Runde 4 (research/PROTOCOL.md): Gold/Silber, Benchmark 50/50 GLD/SLV halten."""
    from tradingbot.research import swing

    costs = CostModel(slippage_bps=1.0)
    daily = {s: swing.etf_daily(s) for s in METALS}
    bench_legs = pd.DataFrame({s: d["close"] / d["close"].shift(1) - 1 for s, d in daily.items()})
    benchmark = bench_legs.mean(axis=1).dropna()
    all_returns: dict[str, pd.Series] = {}
    for symbol in METALS:
        for params in METALS_GRIDS[family]:
            if family == "overnight":
                res = swing.overnight(daily[symbol], params["trend_filter"], costs, symbol)
            else:
                res = swing.trend_close_to_close(daily[symbol], params["lookback"], costs, symbol)
            _log_trial(f"metals_{family}", symbol, params, costs, 1.0, res)
            label = f"{symbol} {json.dumps(params, sort_keys=True)}"
            _print_metrics(label, res)
            print("   Jahre:", {y: f"{v:.1%}" for y, v in yearly_returns(res.daily_returns).items()})
            all_returns[label] = res.daily_returns
    for s in METALS:
        leg = bench_legs[s].dropna()
        _print_metrics(f"Vergleich: {s} halten", BacktestResult(s, leg[leg.index >= date(2016, 10, 19)]))
    evaluate_walk_forward(all_returns, train_days, test_days, benchmark=benchmark,
                          benchmark_name="50/50 GLD/SLV")


MULTI_GRID = [{"signal": s, "mode": m} for s in ("sma200", "m12", "m6") for m in ("absolute", "dual")]


def _multi_asset_panel(allow_holdout: bool = False) -> tuple[pd.DataFrame, pd.DataFrame]:
    from tradingbot.research import swing

    dailies = {s: swing.etf_daily(s, allow_holdout=allow_holdout) for s in swing.MULTI_ASSETS}
    close = pd.DataFrame({s: d["close"] for s, d in dailies.items()}).dropna()
    pre = pd.DataFrame({s: d["pre_close"] for s, d in dailies.items()}).reindex(close.index)
    return close, pre


def cmd_multiasset_grid(train_days: int, test_days: int) -> None:
    """Runde 5 (research/PROTOCOL.md): Multi-Asset-Trendfolge, Benchmark 1/9 halten."""
    from tradingbot.research import crypto, swing

    close, pre = _multi_asset_panel()
    cost_side = 1.0 / 10_000 + 27.8e-6 / 2  # 1 bp + SEC-Gebühr (nur Verkäufe, ~halber Umschlag)
    costs = CostModel(slippage_bps=1.0)
    rets = close / close.shift(1) - 1
    benchmark = rets.mean(axis=1).dropna()
    all_returns: dict[str, pd.Series] = {}
    for params in MULTI_GRID:
        w = swing.multi_asset_weights(close, pre, params["signal"], params["mode"])
        res = crypto.run_weights(w, close, cost_side, "multi_asset")
        _log_trial("multi_asset_trend", "+".join(swing.MULTI_ASSETS), params, costs, 1.0, res)
        label = json.dumps(params, sort_keys=True)
        _print_metrics(label, res)
        print("   Jahre:", {y: f"{v:.1%}" for y, v in yearly_returns(res.daily_returns).items()},
              f"| Ø investiert {w.sum(axis=1).loc[res.daily_returns.index].mean():.0%}")
        all_returns[label] = res.daily_returns
    start = min(r.index[0] for r in all_returns.values())
    _print_metrics("Vergleich: 1/9 halten", BacktestResult("bench", benchmark[benchmark.index >= start]))
    _print_metrics("Vergleich: SPY halten", BacktestResult("spy", rets["SPY"][rets.index >= start]))
    evaluate_walk_forward(all_returns, train_days, test_days, benchmark=benchmark,
                          benchmark_name="1/9 halten")


def cmd_tom_grid(train_days: int, test_days: int) -> None:
    """Runde 6, Familie N: Monatswechsel-Effekt, Alpha je ETF und im Walk-Forward ggü. SPY."""
    from tradingbot.research import swing

    costs = CostModel(slippage_bps=1.0)
    all_returns: dict[str, pd.Series] = {}
    spy_bench = None
    for symbol in ("SPY", "QQQ", "IWM"):
        daily = swing.etf_daily(symbol)
        own = (daily["close"] / daily["close"].shift(1) - 1).dropna()
        if symbol == "SPY":
            spy_bench = own
        for w in (1, 2):
            res = swing.turn_of_month(daily, w, costs, symbol=symbol)
            _log_trial("turn_of_month", symbol, {"last_days": w}, costs, 1.0, res)
            label = f"{symbol} {{\"last_days\": {w}}}"
            _print_metrics(label, res)
            alpha, t_a, beta = swing.alpha_vs_benchmark(res.daily_returns, own)
            invested = (res.daily_returns != 0).mean()
            print(f"   Alpha ggü. {symbol} {alpha:.2%} p.a. (t = {t_a:.2f}), investiert an {invested:.0%} der Tage")
            all_returns[label] = res.daily_returns
    evaluate_walk_forward(all_returns, train_days, test_days, benchmark=spy_bench)


def cmd_carry_grid(train_days: int, test_days: int) -> None:
    """Runde 6, Familie O: Funding-Carry BTC/ETH (marktneutral), Alpha ggü. BTC."""
    from tradingbot.research import crypto

    close, _ = crypto.load_panel()
    btc = close["BTCUSDT"].dropna()
    benchmark = (btc / btc.shift(1) - 1).dropna()
    costs = CostModel(slippage_bps=7.5)  # nur fürs Versuchsprotokoll (Ø aus 10 und 5 bp)
    all_returns: dict[str, pd.Series] = {}
    for symbol in ("BTCUSDT", "ETHUSDT"):
        perp = crypto.fetch_perp(symbol)
        perp = perp[perp.index < HOLDOUT_START]
        for filtered in (False, True):
            res = crypto.funding_carry(close[symbol].dropna(), perp, filtered, 0.001, 0.0005)
            _log_trial("funding_carry", symbol, {"filtered": filtered}, costs, 1.0, res, crypto.PERIODS)
            label = f"{symbol} {{\"filtered\": {str(filtered).lower()}}}"
            _print_metrics(label, res, crypto.PERIODS)
            print("   Jahre:", {y: f"{v:.1%}" for y, v in yearly_returns(res.daily_returns).items()},
                  f"| schlechtester Tag {res.daily_returns.min():.2%}")
            all_returns[label] = res.daily_returns
    evaluate_walk_forward(all_returns, train_days, test_days, benchmark=benchmark,
                          periods=crypto.PERIODS, benchmark_name="BTC")


SECTORS = ["XLB", "XLE", "XLF", "XLI", "XLK", "XLP", "XLU", "XLV", "XLY"]
_FUND_NAME = (r"\bETF\b|\bETN\b|Fund|Trust|iShares|SPDR|ProShares|Direxion|Invesco|Vanguard|VanEck|"
              r"Ultra|\b[23]X\b|Bull|Bear|Index")


def cmd_anomalies(train_days: int, test_days: int) -> None:
    """Runde 8 (research/PROTOCOL.md): P, Q, R mit zwei unabhängigen Zeiträumen
    (Yahoo inkl. Dividenden), S, T per Walk-Forward auf dem Aktien-Panel."""
    import re
    from datetime import date as _date

    from tradingbot.research import anomalies, crypto, history, swing
    from tradingbot.research.universe import UNIVERSE_DIR, load_daily_panel

    split, dev_end = _date(2015, 12, 31), _date(2025, 9, 19)
    etf_cost = 1.0 / 10_000 + 27.8e-6 / 2
    costs = CostModel(slippage_bps=1.0)

    def adj(sym: str) -> pd.Series:
        d = history.fetch_yahoo(sym, until=_date(2025, 9, 20))
        return d["adjclose"][d.index <= dev_end]

    spy = adj("SPY")
    spy_ret = spy.pct_change().dropna()
    sectors = pd.DataFrame({s: adj(s) for s in SECTORS}).dropna()
    sector_bench = sectors.pct_change().mean(axis=1).dropna()

    candidates: dict[str, tuple[str, pd.Series, pd.Series]] = {}
    for cap in (1.0, 1.5):
        w = anomalies.vol_managed_weights(spy, cap)
        candidates[f"P cap {cap}"] = ("vol_managed", anomalies.financed_returns(w, spy, etf_cost), spy_ret)
    candidates["Q Halloween"] = ("halloween",
                                 anomalies.financed_returns(anomalies.halloween_weights(spy.index), spy, etf_cost),
                                 spy_ret)
    for sig in ("m6", "m12"):
        w = swing.multi_asset_weights(sectors, sectors, sig, "dual")
        res = crypto.run_weights(w, sectors, etf_cost, "sector_momentum")
        candidates[f"R Sektoren {sig}"] = ("sector_momentum", res.daily_returns, sector_bench)

    print("Variante                 Zeitraum     p.a.    Sharpe  Bench-Sharpe  Alpha p.a.  t-Wert")
    table = {}
    for label, (family, r, bench) in candidates.items():
        row = {}
        for period, mask in (("vor 2016", r.index <= split), ("2016-2025", r.index > split)):
            part = r[mask]
            part = part[part.index >= part.ne(0).idxmax()] if period == "vor 2016" else part
            b = bench.reindex(part.index).fillna(0.0)
            m, mb = compute_metrics(BacktestResult(label, part)), compute_metrics(BacktestResult("b", b))
            alpha, t_a, _ = swing.alpha_vs_benchmark(part, b)
            row[period] = t_a
            print(f"{label:24s} {period:10s} {m.cagr:7.2%}  {m.sharpe:6.2f}  {mb.sharpe:11.2f}  {alpha:9.2%}  {t_a:6.2f}")
            if period == "2016-2025":
                _log_trial(family, "SPY" if family != "sector_momentum" else "SPDR-Sektoren",
                           {"variant": label}, costs, 1.0, BacktestResult(label, part))
        table[label] = row
    for fam in ("P", "Q", "R"):
        labels = [k for k in table if k.startswith(fam)]
        best = max(labels, key=lambda k: table[k]["2016-2025"])
        ok = table[best]["2016-2025"] >= 2 and table[best]["vor 2016"] >= 2
        print(f"Familie {fam}: gewählt {best} (t 2016-2025 = {table[best]['2016-2025']:.2f}, "
              f"vor 2016 = {table[best]['vor 2016']:.2f}) -> {'BESTANDEN' if ok else 'NICHT BESTANDEN'}")

    # S, T: Einzelaktien (ohne Fonds/ETFs), Top-500 nach Liquidität
    assets = pd.read_pickle(UNIVERSE_DIR / "assets.pkl")
    funds = set(assets.loc[assets["name"].fillna("").str.contains(re.compile(_FUND_NAME, re.I)), "symbol"])
    panel = load_daily_panel()
    panel = panel[panel.index.get_level_values("date") < HOLDOUT_START]
    spy_panel = panel.xs("SPY", level="symbol")["close"]
    bench = spy_panel.pct_change().dropna()
    stocks = panel[~panel.index.get_level_values("symbol").isin(funds)]
    _, closes, mask = swing.reversal_matrices(stocks)
    for fam, score, highest, name in (("S", anomalies.momentum_12_1(closes), True, "stock_momentum"),
                                      ("T", anomalies.low_volatility(closes), False, "low_volatility")):
        returns = {}
        for n in (50, 100):
            w = anomalies.cross_section_weights(closes, mask, score, n, highest)
            res = crypto.run_weights(w, closes, 3.0 / 10_000, name)
            _log_trial(name, "top500", {"n": n}, CostModel(slippage_bps=3.0), 1.0, res)
            label = f"{fam} n={n}"
            _print_metrics(label, res)
            print("   Jahre:", {y: f"{v:.1%}" for y, v in yearly_returns(res.daily_returns).items()})
            returns[label] = res.daily_returns
        print(f"\nFamilie {fam}:")
        evaluate_walk_forward(returns, train_days, test_days, benchmark=bench)


def cmd_round9(train_days: int, test_days: int) -> None:
    """Runde 9 (research/PROTOCOL.md): V Pre-FOMC, W Short-Vola (zwei Zeiträume),
    U Paarhandel (Walk-Forward auf dem Aktien-Panel ab 2016)."""
    import re
    from datetime import date as _date

    from tradingbot.research import anomalies, history, swing
    from tradingbot.research.universe import UNIVERSE_DIR, load_daily_panel

    split, dev_end = _date(2015, 12, 31), _date(2025, 9, 19)
    etf_cost = 1.0 / 10_000 + 27.8e-6 / 2
    costs = CostModel(slippage_bps=1.0)

    def adj(sym: str) -> pd.Series:
        d = history.fetch_yahoo(sym, until=_date(2025, 9, 20))
        return d["adjclose"][d.index <= dev_end]

    spy = adj("SPY")
    spy_ret = spy.pct_change().dropna()
    candidates = {}
    fomc = anomalies.fomc_decision_days()
    w = anomalies.event_day_weights(spy.index, fomc)
    candidates["V Pre-FOMC"] = ("pre_fomc", anomalies.financed_returns(w, spy, etf_cost), _date(1994, 1, 1))
    vix, vix3m, svxy = adj("^VIX"), adj("^VIX3M"), adj("SVXY")
    for label, extra in (("W Contango", None), ("W Contango+VIX<20", 20.0)):
        idx = svxy.index
        ok = (vix.reindex(idx) < vix3m.reindex(idx))
        if extra is not None:
            ok &= vix.reindex(idx) < extra
        candidates[label] = ("short_vol", anomalies.financed_returns(ok.astype(float), svxy, etf_cost),
                             _date(2011, 10, 4))
    print("Variante                 Zeitraum     p.a.    Sharpe  SPY-Sharpe  MaxDD   Alpha p.a.  t-Wert  investiert")
    table = {}
    for label, (family, r, start) in candidates.items():
        row = {}
        for period, mask in (("vor 2016", (r.index <= split) & (r.index >= start)), ("2016-2025", r.index > split)):
            part = r[mask]
            b = spy_ret.reindex(part.index).fillna(0.0)
            m, mb = compute_metrics(BacktestResult(label, part)), compute_metrics(BacktestResult("b", b))
            alpha, t_a, _ = swing.alpha_vs_benchmark(part, b)
            row[period] = t_a
            print(f"{label:24s} {period:10s} {m.cagr:7.2%}  {m.sharpe:6.2f}  {mb.sharpe:9.2f}  {m.max_drawdown:6.1%}"
                  f"  {alpha:9.2%}  {t_a:6.2f}  {(part != 0).mean():6.0%}")
            if period == "2016-2025":
                _log_trial(family, "SPY" if family == "pre_fomc" else "SVXY", {"variant": label}, costs, 1.0,
                           BacktestResult(label, part))
        table[label] = row
    for fam in ("V", "W"):
        labels = [k for k in table if k.startswith(fam)]
        best = max(labels, key=lambda k: table[k]["2016-2025"])
        ok = table[best]["2016-2025"] >= 2 and table[best]["vor 2016"] >= 2
        print(f"Familie {fam}: gewählt {best} (t 2016-2025 = {table[best]['2016-2025']:.2f}, "
              f"vor 2016 = {table[best]['vor 2016']:.2f}) -> {'BESTANDEN' if ok else 'NICHT BESTANDEN'}")

    assets = pd.read_pickle(UNIVERSE_DIR / "assets.pkl")
    funds = set(assets.loc[assets["name"].fillna("").str.contains(re.compile(_FUND_NAME, re.I)), "symbol"])
    panel = load_daily_panel()
    panel = panel[panel.index.get_level_values("date") < HOLDOUT_START]
    bench = panel.xs("SPY", level="symbol")["close"].pct_change().dropna()
    stocks = panel[~panel.index.get_level_values("symbol").isin(funds)]
    _, closes, mask = swing.reversal_matrices(stocks)
    r = anomalies.pairs_trading(closes, mask)
    res = BacktestResult("pairs", r, [], r[r != 0].to_numpy())
    _log_trial("pairs_trading", "top500", {"k": 2.0, "n_pairs": 20}, CostModel(slippage_bps=3.0), 1.0, res)
    _print_metrics("U Paarhandel k=2", res)
    print("   Jahre:", {y: f"{v:.1%}" for y, v in yearly_returns(r).items()})
    evaluate_walk_forward({"U Paarhandel k=2": r}, train_days, test_days, benchmark=bench)


def cmd_validate_history() -> None:
    """Runde 7 (research/PROTOCOL.md): die drei auf 2016-2025 festgelegten
    Kandidaten einmalig auf Yahoo-Daten bis 2015 prüfen. Keine Parameterwahl,
    daher keine neuen Versuche im Protokoll."""
    from tradingbot.research import crypto, history, swing

    costs = CostModel(slippage_bps=1.0)
    raw = {s: history.fetch_yahoo(s) for s in set(SWING_ETFS) | set(swing.MULTI_ASSETS)}
    spy_adj = history.as_daily(raw["SPY"])["close"]
    spy_ret = (spy_adj / spy_adj.shift(1) - 1).dropna()
    t_needed = 2.4

    def verdict(name: str, strat: pd.Series, bench: pd.Series, bench_name: str) -> None:
        bench = bench.reindex(strat.index).fillna(0.0)
        ms, mb = compute_metrics(BacktestResult(name, strat)), compute_metrics(BacktestResult(bench_name, bench))
        alpha, t_a, beta = swing.alpha_vs_benchmark(strat, bench)
        print(f"\n=== {name} ({strat.index[0]} .. {strat.index[-1]}) ===")
        print(f"Strategie: {ms.cagr:.2%} p.a., Sharpe {ms.sharpe:.2f}, MaxDD {ms.max_drawdown:.1%}")
        print(f"{bench_name}: {mb.cagr:.2%} p.a., Sharpe {mb.sharpe:.2f}, MaxDD {mb.max_drawdown:.1%}")
        print(f"Alpha {alpha:.2%} p.a. (t = {t_a:.2f}), Beta {beta:.2f}")
        print("Jahre:", {y: f"{v:.1%}" for y, v in yearly_returns(strat).items()})
        checks = {"Rendite > 0": ms.total_return > 0, f"Sharpe > {bench_name}": ms.sharpe > mb.sharpe,
                  f"Alpha > 0 mit t >= {t_needed}": alpha > 0 and t_a >= t_needed}
        for k, ok in checks.items():
            print(f"  [{'OK' if ok else 'NEIN'}] {k}")
        print("BESTANDEN" if all(checks.values()) else "NICHT BESTANDEN")

    # 1. E-Portfolio: Overnight mit Trendfilter, 8 ETFs je 1/8
    legs = {s: swing.overnight(history.as_daily(raw[s], overnight=True), True, costs, s).daily_returns
            for s in SWING_ETFS}
    frame = pd.DataFrame(legs).dropna()
    verdict("E-Portfolio Overnight", frame.mean(axis=1), spy_ret, "SPY halten")

    # 2. Multi-Asset-Trendfolge dual m12
    close = pd.DataFrame({s: history.as_daily(raw[s])["close"] for s in swing.MULTI_ASSETS}).dropna()
    w = swing.multi_asset_weights(close, close, "m12", "dual")
    res = crypto.run_weights(w, close, 1.0 / 10_000 + 27.8e-6 / 2, "multi_asset")
    bench = (close / close.shift(1) - 1).mean(axis=1).dropna()
    verdict("Multi-Asset dual m12", res.daily_returns, bench, "1/9 halten")

    # 3. Monatswechsel SPY, last_days 2
    tom = swing.turn_of_month(history.as_daily(raw["SPY"]), 2, costs, symbol="SPY")
    verdict("Monatswechsel SPY", tom.daily_returns, spy_ret, "SPY halten")


def cmd_overnight_portfolio(holdout: bool) -> bool:
    """E-Portfolio (research/PROTOCOL.md): Overnight mit Trendfilter auf allen
    SWING_ETFS, je 1/n des Kapitals, eine feste Variante ohne Auswahl."""
    from tradingbot.research import swing
    from tradingbot.research.metrics import deflated_sharpe
    from tradingbot.research.swing import alpha_vs_benchmark

    costs = CostModel(slippage_bps=1.0)
    legs, trades = {}, []
    for symbol in SWING_ETFS:
        res = swing.overnight(swing.etf_daily(symbol, allow_holdout=holdout), True, costs, symbol)
        legs[symbol] = res.daily_returns
        trades += res.trades
    frame = pd.DataFrame(legs).fillna(0.0)
    portfolio = frame.mean(axis=1)
    spy = swing.etf_daily("SPY", allow_holdout=holdout)["close"]
    benchmark = (spy / spy.shift(1) - 1).dropna()
    if holdout:
        portfolio = portfolio[portfolio.index >= HOLDOUT_START]
        benchmark = benchmark[benchmark.index >= HOLDOUT_START]
    result = BacktestResult("overnight_portfolio", portfolio, trades)
    if not holdout:
        _log_trial("overnight_portfolio", "+".join(SWING_ETFS), {"trend_filter": True}, costs, 1.0, result)
    m = compute_metrics(result)
    n_trials, sr_var = _trial_stats()
    dsr = deflated_sharpe(portfolio, n_trials, sr_var)
    alpha, t_alpha, beta = alpha_vs_benchmark(portfolio, benchmark)
    active = portfolio[portfolio != 0]
    pf = active[active > 0].sum() / -active[active < 0].sum()
    idx = pd.to_datetime(portfolio.index)
    halves = portfolio.groupby([idx.year, idx.month > 6]).apply(lambda x: float(np.prod(1 + x) - 1))
    bench_total = float(np.prod(1 + benchmark.reindex(portfolio.index).fillna(0)) - 1)
    label = "HOLDOUT" if holdout else "Entwicklungszeitraum"
    print(f"{label} {portfolio.index[0]} .. {portfolio.index[-1]} ({len(portfolio)} Tage)")
    print(f"Rendite {m.total_return:.1%} ({m.cagr:.2%} p.a.), Sharpe {m.sharpe:.2f}, MaxDD {m.max_drawdown:.1%}, "
          f"PF (Tage) {pf:.2f}, Deflated Sharpe {dsr:.3f} (N={n_trials})")
    print(f"Alpha ggü. SPY {alpha:.2%} p.a. (t = {t_alpha:.2f}), Beta {beta:.2f}; SPY im Zeitraum {bench_total:.1%}")
    print(f"Positive Halbjahre: {(halves > 0).mean():.0%} ({(halves > 0).sum()}/{len(halves)})")
    print("Jahresrenditen:", {y: f"{v:.1%}" for y, v in yearly_returns(portfolio).items()})
    if holdout:
        checks = {"Rendite > 0": m.total_return > 0, "Alpha > 0": alpha > 0}
    else:
        checks = {
            f"Deflated Sharpe >= {MIN_DSR}": dsr >= MIN_DSR,
            "Alpha ggü. SPY > 0 mit t >= 2": alpha > 0 and t_alpha >= 2,
            f"Profit-Faktor >= {MIN_PROFIT_FACTOR}": pf >= MIN_PROFIT_FACTOR,
            "positive Halbjahre >= 60 %": (halves > 0).mean() >= 0.6,
        }
    for name, ok in checks.items():
        print(f"  [{'OK' if ok else 'NEIN'}] {name}")
    passed = all(checks.values())
    print("BESTANDEN" if passed else "NICHT BESTANDEN")
    return passed


def cmd_portfolio(family: str, symbols: list[str], params: dict, costs: CostModel,
                  max_exposure: float) -> pd.Series:
    """Eine feste Variante auf mehreren Symbolen, jedes mit 1/n des Kapitals.
    Jeder Symbol-Lauf wird als Versuch protokolliert."""
    returns = {}
    for symbol in symbols:
        res = run_backtest(_sessions(symbol), FAMILIES[family](**params), costs, max_exposure)
        _log_trial(family, symbol, params, costs, max_exposure, res)
        _print_metrics(f"{symbol} {json.dumps(params, sort_keys=True)}", res)
        returns[symbol] = res.daily_returns
    frame = pd.DataFrame(returns).fillna(0.0)
    portfolio = frame.mean(axis=1)
    m = compute_metrics(BacktestResult("portfolio", portfolio))
    positive = sum(sharpe_ratio(frame[c]) > 0 for c in frame.columns)
    print(f"\nGleichgewichtet ({len(symbols)} Symbole): Sharpe {m.sharpe:.2f} | CAGR {m.cagr:.2%} | "
          f"MaxDD {m.max_drawdown:.2%} | Symbole mit positiver Sharpe: {positive}/{len(symbols)}")
    print("Jahresrenditen:", {y: f"{v:.1%}" for y, v in yearly_returns(portfolio).items()})
    print("Korrelation der Tagesrenditen (Mittel):",
          f"{frame.corr().values[np.triu_indices(len(symbols), 1)].mean():.2f}" if len(symbols) > 1 else "-")
    return portfolio


def cmd_run(family: str, symbol: str, params: dict, costs: CostModel, max_exposure: float,
            holdout: bool) -> None:
    sessions = _sessions(symbol, allow_holdout=holdout)
    start = HOLDOUT_START if holdout else None
    res = run_backtest(sessions, FAMILIES[family](**params), costs, max_exposure,
                       start=start, allow_holdout=holdout)
    if not holdout:
        _log_trial(family, symbol, params, costs, max_exposure, res)
    _print_metrics(f"{'HOLDOUT ' if holdout else ''}{symbol} {json.dumps(params, sort_keys=True)}", res)
    print("Jahresrenditen:", {y: f"{v:.1%}" for y, v in yearly_returns(res.daily_returns).items()})
    reasons = pd.Series([t.reason for t in res.trades]).value_counts().to_dict()
    sides = pd.Series([t.side for t in res.trades]).value_counts().to_dict()
    print(f"Ausstiegsgründe {reasons}, Richtungen {sides}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m tradingbot.research")
    sub = parser.add_subparsers(dest="command", required=True)
    f = sub.add_parser("fetch", help="Minuten-Bars (SIP) laden und cachen.")
    f.add_argument("--symbols", required=True)
    f.add_argument("--env-file", default=".env", help="Datei mit ALPACA_API_KEY/ALPACA_SECRET_KEY")
    u = sub.add_parser("universe", help="Stocks-in-Play-Universum (Familie A) laden und cachen.")
    u.add_argument("--env-file", default=".env")
    o = sub.add_parser("orb-grid", help="ORB auf Stocks in Play: vorab registrierte 4 Varianten.")
    o.add_argument("--slippage-bps", type=float, default=1.0)
    o.add_argument("--per-share", type=float, default=0.01, help="Slippage je Aktie und Seite in $")
    o.add_argument("--train-days", type=int, default=504)
    o.add_argument("--test-days", type=int, default=126)
    o.add_argument("--ticks", action="store_true", help="Einstiegs-Minuten Tick-genau auflösen")
    ot = sub.add_parser("orb-ticks", help="Ticks der mehrdeutigen ORB-Einstiegs-Minuten laden.")
    ot.add_argument("--env-file", default=".env")
    sw = sub.add_parser("swing-grid", help="Runde 2: Haltedauer über Nacht bis wenige Tage.")
    sw.add_argument("--family", required=True, choices=["overnight", "rsi2", "reversal"])
    sw.add_argument("--train-days", type=int, default=504)
    sw.add_argument("--test-days", type=int, default=126)
    sub.add_parser("validate-history", help="Runde 7: Kandidaten auf 2003-2015 (Yahoo) prüfen.")
    r9 = sub.add_parser("round9", help="Runde 9: Pre-FOMC, Short-Vola, Paarhandel (Familien U-W).")
    r9.add_argument("--train-days", type=int, default=504)
    r9.add_argument("--test-days", type=int, default=126)
    an = sub.add_parser("anomalies", help="Runde 8: bekannte Anomalien (Familien P-T).")
    an.add_argument("--train-days", type=int, default=504)
    an.add_argument("--test-days", type=int, default=126)
    tg = sub.add_parser("tom-grid", help="Runde 6: Monatswechsel-Effekt (Familie N).")
    tg.add_argument("--train-days", type=int, default=504)
    tg.add_argument("--test-days", type=int, default=126)
    cy = sub.add_parser("carry-grid", help="Runde 6: Krypto-Funding-Carry (Familie O).")
    cy.add_argument("--train-days", type=int, default=730)
    cy.add_argument("--test-days", type=int, default=182)
    ma = sub.add_parser("multiasset-grid", help="Runde 5: Multi-Asset-Trendfolge (Familie M).")
    ma.add_argument("--train-days", type=int, default=504)
    ma.add_argument("--test-days", type=int, default=126)
    mg = sub.add_parser("metals-grid", help="Runde 4: Gold/Silber (Familien K/L).")
    mg.add_argument("--family", required=True, choices=sorted(METALS_GRIDS))
    mg.add_argument("--train-days", type=int, default=504)
    mg.add_argument("--test-days", type=int, default=126)
    cg = sub.add_parser("crypto-grid", help="Runde 3: Krypto-Spot (Familien H/I).")
    cg.add_argument("--family", required=True, choices=sorted(CRYPTO_GRIDS))
    cg.add_argument("--cost", type=float, default=0.0025, help="Kosten je Seite (Standard 0.25 %%)")
    cg.add_argument("--train-days", type=int, default=730)
    cg.add_argument("--test-days", type=int, default=182)
    op = sub.add_parser("overnight-portfolio", help="E-Portfolio: Overnight mit Trendfilter auf allen ETFs.")
    op.add_argument("--holdout", action="store_true", help="Holdout EINMALIG öffnen (nur nach Bestehen)")
    for name in ("grid", "run", "holdout", "portfolio"):
        p = sub.add_parser(name)
        p.add_argument("--family", required=True, choices=sorted(FAMILIES))
        p.add_argument("--slippage-bps", type=float, default=1.0, help="pro Seite (Standard 1 bp)")
        p.add_argument("--max-exposure", type=float, default=1.0,
                       help="Kapital-Obergrenze je Position (1.0 = Cash-Konto ohne Hebel)")
        if name == "grid":
            p.add_argument("--symbols", required=True)
            p.add_argument("--train-days", type=int, default=504)
            p.add_argument("--test-days", type=int, default=126)
        elif name == "portfolio":
            p.add_argument("--symbols", required=True)
            p.add_argument("--params", nargs="*", default=[])
        else:
            p.add_argument("--symbol", required=True)
            p.add_argument("--params", nargs="*", default=[])
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    try:
        if args.command == "fetch":
            cmd_fetch([s.strip().upper() for s in args.symbols.split(",")], args.env_file)
            return
        if args.command == "universe":
            cmd_universe(args.env_file)
            return
        if args.command == "orb-grid":
            cmd_orb_grid(args.slippage_bps, args.per_share, args.train_days, args.test_days, args.ticks)
            return
        if args.command == "orb-ticks":
            cmd_orb_ticks(args.env_file)
            return
        if args.command == "swing-grid":
            cmd_swing_grid(args.family, args.train_days, args.test_days)
            return
        if args.command == "round9":
            cmd_round9(args.train_days, args.test_days)
            return
        if args.command == "anomalies":
            cmd_anomalies(args.train_days, args.test_days)
            return
        if args.command == "validate-history":
            cmd_validate_history()
            return
        if args.command == "tom-grid":
            cmd_tom_grid(args.train_days, args.test_days)
            return
        if args.command == "carry-grid":
            cmd_carry_grid(args.train_days, args.test_days)
            return
        if args.command == "multiasset-grid":
            cmd_multiasset_grid(args.train_days, args.test_days)
            return
        if args.command == "metals-grid":
            cmd_metals_grid(args.family, args.train_days, args.test_days)
            return
        if args.command == "crypto-grid":
            cmd_crypto_grid(args.family, args.cost, args.train_days, args.test_days)
            return
        if args.command == "overnight-portfolio":
            cmd_overnight_portfolio(args.holdout)
            return
        costs = CostModel(slippage_bps=args.slippage_bps)
        if args.command == "grid":
            cmd_grid(args.family, [s.strip().upper() for s in args.symbols.split(",")], costs,
                     args.max_exposure, args.train_days, args.test_days)
        elif args.command == "portfolio":
            cmd_portfolio(args.family, [s.strip().upper() for s in args.symbols.split(",")],
                          _parse_params(args.params), costs, args.max_exposure)
        else:
            if args.command == "holdout":
                print(f"ACHTUNG: öffnet den gesperrten Zeitraum ab {HOLDOUT_START}. Nur EINMAL für den "
                      "finalen Kandidaten verwenden.", file=sys.stderr)
            cmd_run(args.family, args.symbol.upper(), _parse_params(args.params), costs,
                    args.max_exposure, holdout=args.command == "holdout")
    except (RuntimeError, ValueError) as e:
        print(f"Fehler: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

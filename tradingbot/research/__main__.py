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
from datetime import datetime
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


def _log_trial(family, symbol, params, costs, max_exposure, result: BacktestResult) -> None:
    m = compute_metrics(result)
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


def _print_metrics(label: str, result: BacktestResult) -> None:
    m = compute_metrics(result)
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


def evaluate_walk_forward(all_returns: dict[str, pd.Series], train_days: int, test_days: int) -> bool:
    """Walk-Forward über alle Varianten und Prüfung der Bestehenskriterien."""
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
    oos_sharpe = sharpe_ratio(oos)
    dsr = deflated_sharpe(oos, n_trials, sr_var)
    trade_days = oos[oos != 0]
    wins, losses = trade_days[trade_days > 0].sum(), -trade_days[trade_days < 0].sum()
    pf = wins / losses if losses > 0 else math.inf
    years = len(oos) / TRADING_DAYS
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

"""Opening-Range-Breakout auf "Stocks in Play" (Familie A, research/PROTOCOL.md).

Je Tag die vorab (um 9:35) ausgewählten Top-N-Kandidaten aus
universe.select_candidates. Je Kandidat höchstens ein Trade:
Richtung aus der Opening-Range-Kerze, Einstieg per Stop-Order am OR-Hoch/
-Tief, Stop bei 10 % ATR, sonst Ausstieg zum Handelsschluss.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

from tradingbot.research import HOLDOUT_START
from tradingbot.research.engine import BacktestResult, CostModel, Trade
from tradingbot.research.universe import UNIVERSE_DIR, load_intraday_month

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OrbParams:
    or_minutes: int = 5
    long_only: bool = False
    risk_pct: float = 0.01
    stop_atr_frac: float = 0.10


# (symbol, Minuten-Zeitstempel) -> Tick-Preise dieser Minute in zeitlicher
# Reihenfolge, oder None, wenn keine Ticks vorliegen.
TickLookup = Callable[[str, pd.Timestamp], "np.ndarray | None"]


def simulate_symbol_day(day: date, symbol: str, bars: pd.DataFrame, atr: float,
                        params: OrbParams, position_cap: float,
                        tick_lookup: TickLookup | None = None) -> Trade | None:
    """`bars`: Minuten-Bars EINES Symbols an EINEM Tag, Index America/New_York.

    `tick_lookup`: löst Einstiegs-Minuten auf, in denen der Bar auch den
    Stop berührt (Reihenfolge aus Minuten-Bars unbekannt). Ohne Ticks gilt
    der schlechteste Fall: Stop-Kurs in derselben Minute."""
    if bars.empty or not atr > 0:
        return None
    idx = bars.index
    minute = np.asarray(idx.hour * 60 + idx.minute - 570)
    if minute[0] != 0:
        return None
    o, h, l, c = (bars[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    in_or = minute < params.or_minutes
    after = np.flatnonzero(~in_or)
    if len(after) == 0:
        return None
    or_open, or_close = o[0], c[in_or][-1]
    if or_close > or_open:
        side = 1
    elif or_close < or_open and not params.long_only:
        side = -1
    else:
        return None
    level = h[in_or].max() if side > 0 else l[in_or].min()
    stop_dist = params.stop_atr_frac * atr

    entry_k = entry = None
    for k in after:
        if side > 0 and h[k] > level:
            entry_k, entry = k, max(o[k], level)
        elif side < 0 and l[k] < level:
            entry_k, entry = k, min(o[k], level)
        if entry_k is not None:
            break
    if entry_k is None:
        return None
    stop = entry - side * stop_dist
    exit_k, exit_price, reason = len(c) - 1, c[-1], "close"
    first_k = entry_k
    entry_bar_hit = l[entry_k] <= stop if side > 0 else h[entry_k] >= stop
    ticks = tick_lookup(symbol, idx[entry_k]) if entry_bar_hit and tick_lookup else None
    if ticks is not None and len(ticks):
        # Ticks sind Rohkurse, die Bars split-bereinigt: auf das Bar-Niveau
        # skalieren (Split-Faktoren sind diskret, kleine Abweichungen bleiben).
        # Bar-Open/-Close = erster/letzter Trade der Minute.
        factor = (o[entry_k] + c[entry_k]) / float(ticks[0] + ticks[-1])
        if abs(factor - 1) > 0.05:
            ticks = ticks * factor
        crossed = np.flatnonzero(ticks > level if side > 0 else ticks < level)
        if len(crossed):
            i = crossed[0]
            entry = float(ticks[i])
            stop = entry - side * stop_dist
            later = ticks[i + 1:]
            hits = np.flatnonzero(later <= stop if side > 0 else later >= stop)
            if len(hits):
                exit_k, exit_price, reason = entry_k, float(later[hits[0]]), "stop"
            first_k = entry_k + 1  # Einstiegs-Minute per Ticks erledigt
    exposure = min(params.risk_pct / (stop_dist / entry), position_cap)

    for k in range(first_k, len(c)):
        if reason == "stop":
            break
        hit = l[k] <= stop if side > 0 else h[k] >= stop
        if hit:
            # Im Einstiegs-Bar ohne Ticks ist die Reihenfolge unbekannt ->
            # Stop-Kurs (konservativ); danach bei Kurslücke der schlechtere Open.
            if k == entry_k:
                exit_price = stop
            else:
                exit_price = min(o[k], stop) if side > 0 else max(o[k], stop)
            exit_k, reason = k, "stop"
            break
    return Trade(day=day, side=side, entry_time=idx[entry_k], entry_price=float(entry),
                 exit_time=idx[exit_k], exit_price=float(exit_price), exposure=float(exposure),
                 reason=reason, symbol=symbol)


def run_orb(variants: dict[str, OrbParams], candidates: pd.DataFrame, costs: CostModel,
            max_exposure: float = 1.0, top_n: int = 20, allow_holdout: bool = False,
            base=UNIVERSE_DIR, tick_lookup: TickLookup | None = None) -> dict[str, BacktestResult]:
    """Simuliert alle Varianten in einem Durchlauf über die gecachten
    Intraday-Monate. Positionsdeckel je Trade = max_exposure / top_n."""
    position_cap = max_exposure / top_n
    days = sorted(d for d in candidates.index.get_level_values("date").unique()
                  if allow_holdout or d < HOLDOUT_START)
    rets = {name: {} for name in variants}
    trades = {name: [] for name in variants}
    trade_rets = {name: [] for name in variants}
    for y, m in sorted({(d.year, d.month) for d in days}):
        month = load_intraday_month(y, m, base)
        month_syms = set(month.index.get_level_values("symbol")) if len(month) else set()
        for d in [d for d in days if (d.year, d.month) == (y, m)]:
            day_ret = dict.fromkeys(variants, 0.0)
            for symbol, row in candidates.loc[d].iterrows():
                if symbol not in month_syms:
                    continue
                sym_bars = month.loc[symbol]
                bars = sym_bars[sym_bars.index.date == d]
                for name, params in variants.items():
                    t = simulate_symbol_day(d, symbol, bars, float(row["atr"]), params, position_cap,
                                            tick_lookup)
                    if t is None:
                        continue
                    net = t.exposure * (t.gross_return - costs.round_trip_cost(t))
                    day_ret[name] += net
                    trades[name].append(t)
                    trade_rets[name].append(net)
            for name in variants:
                rets[name][d] = day_ret[name]
        logger.info("ORB %d-%02d fertig", y, m)
    return {
        name: BacktestResult(
            strategy=f"orb_{name}",
            daily_returns=pd.Series(rets[name], dtype=float).sort_index(),
            trades=trades[name],
            trade_net_returns=np.array(trade_rets[name], dtype=float),
        )
        for name in variants
    }

"""Runde 2 der Forschung: Haltedauer über Nacht bis wenige Tage
(Familien E, F, G in research/PROTOCOL.md).

Alle Strategien liefern ein BacktestResult mit täglichen Renditen
(Mark-to-Market zum Schlusskurs) und den abgeschlossenen Trades. Kosten
werden am Ausstiegstag abgezogen. Tage ab HOLDOUT_START werden nur mit
allow_holdout ausgewertet.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from tradingbot.research import HOLDOUT_START
from tradingbot.research.data import EARLIEST_DATE, load_minute_bars
from tradingbot.research.engine import BacktestResult, CostModel, Trade

SMA_TREND = 200


def etf_daily(symbol: str, allow_holdout: bool = False) -> pd.DataFrame:
    """Tageswerte aus dem Minuten-Cache: open (erster Bar), close (letzter
    Bar), pre_close (Schluss des Bars 10 Minuten vor dem letzten, also
    15:50 an normalen Tagen) mit den zugehörigen Zeitstempeln."""
    end = None if allow_holdout else HOLDOUT_START - pd.Timedelta(days=1)
    bars = load_minute_bars(symbol, EARLIEST_DATE, end)
    rows = {}
    for d, g in bars.groupby(bars.index.date, sort=True):
        if len(g) < 30 or g.index[0].hour != 9 or g.index[0].minute != 30:
            continue
        pre = g.iloc[-11] if len(g) >= 11 else g.iloc[0]
        rows[d] = {
            "open": g["open"].iloc[0],
            "close": g["close"].iloc[-1],
            "pre_close": pre["close"],
            "open_time": g.index[0],
            "close_time": g.index[-1],
        }
    return pd.DataFrame.from_dict(rows, orient="index")


def _result(name: str, days, rets, trades, trade_rets) -> BacktestResult:
    return BacktestResult(
        strategy=name,
        daily_returns=pd.Series(rets, index=pd.Index(days, name="day"), dtype=float),
        trades=trades,
        trade_net_returns=np.array(trade_rets, dtype=float),
    )


def overnight(daily: pd.DataFrame, trend_filter: bool, costs: CostModel,
              symbol: str = "") -> BacktestResult:
    """Familie E: Kauf zum Schluss von Tag t, Verkauf zum Open von t+1; die
    Rendite zählt für Tag t+1."""
    close, pre, open_ = (daily[c].to_numpy(float) for c in ("close", "pre_close", "open"))
    days = list(daily.index)
    out_days, rets, trades, trade_rets = [], [], [], []
    for t in range(SMA_TREND, len(days) - 1):
        take = not trend_filter or pre[t] > close[t - SMA_TREND:t].mean()
        r = 0.0
        if take:
            tr = Trade(days[t + 1], 1, daily["close_time"].iloc[t], close[t],
                       daily["open_time"].iloc[t + 1], open_[t + 1], 1.0, "open", symbol)
            r = tr.gross_return - costs.round_trip_cost(tr)
            trades.append(tr)
            trade_rets.append(r)
        out_days.append(days[t + 1])
        rets.append(r)
    return _result("overnight", out_days, rets, trades, trade_rets)


def _rsi2_today(avg_gain: float, avg_loss: float, prev_close: float, price: float) -> float:
    """RSI(2) mit Wilder-Glättung, einen Schritt mit `price` fortgeschrieben."""
    change = price - prev_close
    g = (avg_gain + max(change, 0.0)) / 2
    lo = (avg_loss + max(-change, 0.0)) / 2
    if lo == 0:
        return 100.0
    return 100 - 100 / (1 + g / lo)


def rsi2_reversion(daily: pd.DataFrame, entry_below: float, exit_rule: str, costs: CostModel,
                   symbol: str = "") -> BacktestResult:
    """Familie F: Signal aus dem 15:50-Kurs, Ausführung zum Schlusskurs
    desselben Tages. exit_rule: "sma5" (15:50-Kurs > SMA5) oder "rsi70"."""
    close, pre = daily["close"].to_numpy(float), daily["pre_close"].to_numpy(float)
    days = list(daily.index)
    # Wilder-Mittelwerte der Schlusskurs-Veränderungen bis einschließlich Tag t
    avg_gain = np.zeros(len(close))
    avg_loss = np.zeros(len(close))
    for t in range(1, len(close)):
        ch = close[t] - close[t - 1]
        avg_gain[t] = (avg_gain[t - 1] + max(ch, 0.0)) / 2
        avg_loss[t] = (avg_loss[t - 1] + max(-ch, 0.0)) / 2

    out_days, rets, trades, trade_rets = [], [], [], []
    entry_t = None
    for t in range(SMA_TREND, len(days)):
        rsi = _rsi2_today(avg_gain[t - 1], avg_loss[t - 1], close[t - 1], pre[t])
        r = 0.0
        if entry_t is not None:
            r = close[t] / close[t - 1] - 1
            if exit_rule == "sma5":
                leave = pre[t] > (close[t - 4:t].sum() + pre[t]) / 5
            else:
                leave = rsi > 70
            if leave:
                tr = Trade(days[t], 1, daily["close_time"].iloc[entry_t], close[entry_t],
                           daily["close_time"].iloc[t], close[t], 1.0, exit_rule, symbol)
                cost = costs.round_trip_cost(tr)
                r -= cost
                trades.append(tr)
                trade_rets.append(tr.gross_return - cost)
                entry_t = None
        elif pre[t] > close[t - SMA_TREND:t].mean() and rsi < entry_below:
            entry_t = t
        out_days.append(days[t])
        rets.append(r)
    return _result("rsi2", out_days, rets, trades, trade_rets)


# ------------------------------------------------------------ Familie G

@dataclass(frozen=True)
class ReversalParams:
    n_stocks: int = 10
    lookback: int = 5
    hold: int = 5


def reversal_matrices(panel: pd.DataFrame, universe_size: int = 500, min_price: float = 5.0):
    """Wide-Matrizen (Tage x Symbole) für alle Symbole, die irgendwann zum
    Top-`universe_size`-Universum gehören, plus die Universums-Maske.
    Ø-Dollar-Volumen nur aus den 20 Vortagen, Kurs-Filter auf den Vortagesschluss
    (point-in-time zum Signalzeitpunkt, dem Schluss des Stichtags)."""
    dollar = panel["close"] * panel["volume"]
    avg_dv = dollar.groupby(level="symbol").transform(lambda v: v.rolling(20).mean().shift(1))
    ok = panel["close"] > min_price
    ranked = avg_dv.where(ok).groupby(level="date").rank(ascending=False)
    in_uni = ranked <= universe_size
    symbols = in_uni[in_uni].index.get_level_values("symbol").unique()
    sub = panel[panel.index.get_level_values("symbol").isin(symbols)]
    opens = sub["open"].unstack("symbol").sort_index()
    closes = sub["close"].unstack("symbol").sort_index()
    mask = in_uni[in_uni.index.get_level_values("symbol").isin(symbols)].unstack("symbol")
    mask = mask.reindex(index=closes.index, columns=closes.columns).fillna(False).astype(bool)
    return opens, closes, mask


def weekly_reversal(opens: pd.DataFrame, closes: pd.DataFrame, universe: pd.DataFrame,
                    params: ReversalParams, costs: CostModel,
                    allow_holdout: bool = False) -> BacktestResult:
    """Alle `hold` Tage zum Schluss die `n_stocks` Verlierer der letzten
    `lookback` Tage wählen, zum nächsten Open kaufen, `hold` Tage halten und
    zum Open verkaufen. Tagesrendite = gleichgewichtetes Mittel der Positionen."""
    days = list(closes.index)
    O, C, U = opens.to_numpy(float), closes.to_numpy(float), universe.to_numpy(bool)
    cols = list(closes.columns)
    daily_ret = np.zeros(len(days))
    trades, trade_rets = [], []
    first = max(params.lookback, 21)
    t = first
    while t + 1 < len(days):
        if not allow_holdout and days[t + 1] >= HOLDOUT_START:
            break
        with np.errstate(invalid="ignore", divide="ignore"):
            past = C[t] / C[t - params.lookback] - 1
        elig = U[t] & np.isfinite(past) & np.isfinite(O[t + 1])
        if elig.sum() < params.n_stocks:
            t += params.hold
            continue
        picks = np.flatnonzero(elig)[np.argsort(past[elig])[:params.n_stocks]]
        exit_t = min(t + 1 + params.hold, len(days) - 1)
        w = 1.0 / params.n_stocks
        for j in picks:
            entry = O[t + 1, j]
            prev, last_k, exit_price = entry, t + 1, None
            for k in range(t + 1, exit_t + 1):
                if k == exit_t and k > t + 1 and np.isfinite(O[k, j]):
                    daily_ret[k] += w * (O[k, j] / prev - 1)
                    exit_price, last_k = O[k, j], k
                    break
                if not np.isfinite(C[k, j]):
                    break  # Delisting/Datenlücke: Ausstieg zum letzten bekannten Kurs
                daily_ret[k] += w * (C[k, j] / prev - 1)
                prev, last_k = C[k, j], k
            if exit_price is None:
                exit_price = prev
            tr = Trade(days[last_k], 1, pd.Timestamp(days[t + 1]), float(entry),
                       pd.Timestamp(days[last_k]), float(exit_price), w, "time", cols[j])
            cost = costs.round_trip_cost(tr)
            daily_ret[last_k] -= w * cost
            trades.append(tr)
            trade_rets.append(w * (tr.gross_return - cost))
        t += params.hold
    idx = [d for d in days[first + 1:] if allow_holdout or d < HOLDOUT_START]
    series = pd.Series(daily_ret, index=pd.Index(days, name="day")).loc[idx]
    return BacktestResult("weekly_reversal", series, trades, np.array(trade_rets, dtype=float))


def alpha_vs_benchmark(returns: pd.Series, benchmark: pd.Series, periods: int = 252) -> tuple[float, float, float]:
    """OLS r = a + b * bench. Liefert (Alpha p.a., t-Wert Alpha, Beta)."""
    df = pd.concat([returns.rename("r"), benchmark.rename("b")], axis=1, join="inner").dropna()
    if len(df) < 30:
        return 0.0, 0.0, 0.0
    X = np.column_stack([np.ones(len(df)), df["b"].to_numpy()])
    y = df["r"].to_numpy()
    coef, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ coef
    sigma2 = resid @ resid / (len(df) - 2)
    cov = sigma2 * np.linalg.inv(X.T @ X)
    t_alpha = coef[0] / np.sqrt(cov[0, 0]) if cov[0, 0] > 0 else 0.0
    return float(coef[0] * periods), float(t_alpha), float(coef[1])


def trend_close_to_close(daily: pd.DataFrame, lookback: int, costs: CostModel,
                         symbol: str = "") -> BacktestResult:
    """Familie L: investiert von Schluss t bis Schluss t+1, wenn der 15:50-Kurs
    von Tag t über dem SMA(lookback) der Vortages-Schlüsse liegt. Kosten je
    Positionswechsel (Kauf: Slippage, Verkauf: Slippage + SEC-Gebühr)."""
    close, pre = daily["close"].to_numpy(float), daily["pre_close"].to_numpy(float)
    days = list(daily.index)
    side_cost = costs.slippage_bps / 10_000
    out_days, rets, active = [], [], []
    pos_prev = False
    for t in range(lookback, len(days) - 1):
        pos = bool(pre[t] > close[t - lookback:t].mean())
        r = (close[t + 1] / close[t] - 1) if pos else 0.0
        if pos != pos_prev:
            r -= side_cost + (0.0 if pos else costs.sec_fee_rate)
        pos_prev = pos
        out_days.append(days[t + 1])
        rets.append(r)
        if pos:
            active.append(r)
    return BacktestResult("trend", pd.Series(rets, index=pd.Index(out_days, name="day"), dtype=float),
                          [], np.array(active, dtype=float))

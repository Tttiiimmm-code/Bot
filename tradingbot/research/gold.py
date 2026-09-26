"""Runde 20: Gold-Range-Ausbruch nach der Asien-Sitzung (research/PROTOCOL.md).

Daten: Dukascopy XAUUSD-Minutenkerzen (Bid, UTC) aus data_cache/dukascopy/xau.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

DATA_DIR = Path("data_cache") / "dukascopy" / "xau"


def load_minutes(base: Path = DATA_DIR, pattern: str = "xau_*.csv") -> pd.DataFrame:
    frames = [pd.read_csv(p) for p in sorted(base.glob(pattern))]
    df = pd.concat(frames)
    df.index = pd.to_datetime(df.pop("timestamp"), unit="ms", utc=True)
    return df[~df.index.duplicated()].sort_index()


def day_trade(day: pd.DataFrame, tp_mult: float | None, cost_per_side: float = 1e-4,
              range_end_hour: int = 7, close_hour: int = 20) -> float | None:
    """Rendite des ersten Ausbruchs-Trades eines UTC-Tages oder None ohne Trade."""
    hours = day.index.hour
    rng = day[hours < range_end_hour]
    session = day[(hours >= range_end_hour) & (hours < close_hour)]
    if len(rng) < 60 or len(session) < 60:
        return None
    hi, lo = rng["high"].max(), rng["low"].min()
    height = hi - lo
    if not height > 0:
        return None
    o, h, l, c = (session[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    for i in range(len(c)):
        side = 0
        if h[i] > hi:
            side, entry = 1, max(o[i], hi)
        elif l[i] < lo:
            side, entry = -1, min(o[i], lo)
        if side == 0:
            continue
        stop = lo if side > 0 else hi
        target = entry + side * tp_mult * height if tp_mult else None
        for k in range(i, len(c)):
            first = k == i
            hit_stop = l[k] <= stop if side > 0 else h[k] >= stop
            hit_tp = target is not None and (h[k] >= target if side > 0 else l[k] <= target)
            if hit_stop:  # Stop zuerst (konservativ), auch im Einstiegs-Bar
                px = stop if first else (min(o[k], stop) if side > 0 else max(o[k], stop))
                return side * (px / entry - 1) - 2 * cost_per_side
            if hit_tp:
                px = target if first else (max(o[k], target) if side > 0 else min(o[k], target))
                return side * (px / entry - 1) - 2 * cost_per_side
        return side * (c[-1] / entry - 1) - 2 * cost_per_side
    return None


FX_DIR = Path("data_cache") / "dukascopy" / "fx"


def load_fx(pair: str, base: Path = FX_DIR) -> pd.Series:
    """Minuten-Open eines Paares (UTC-Index)."""
    frames = [pd.read_csv(p) for p in sorted(base.glob(f"{pair}_*.csv"))]
    df = pd.concat(frames)
    s = pd.Series(df["open"].to_numpy(float), index=pd.to_datetime(df["timestamp"], unit="ms", utc=True))
    return s[~s.index.duplicated()].sort_index()


def price_at(series: pd.Series, ts: pd.Timestamp, tolerance_min: int = 5) -> float | None:
    """Open der ersten Minute ab ts (höchstens tolerance_min später)."""
    pos = series.index.searchsorted(ts)
    if pos >= len(series) or series.index[pos] - ts > pd.Timedelta(minutes=tolerance_min):
        return None
    return float(series.iloc[pos])


def month_end_fix_returns(pairs: dict[str, pd.Series], usd_quote: dict[str, bool], start_h: int, end_h: int,
                          usd_long: bool, cost_per_side: float = 0.5e-4) -> pd.Series:
    """Je Monat (letzter Werktag): Rendite einer USD-Position von start_h bis end_h
    (Uhrzeit London), gleichgewichtet über die Paare. usd_quote[pair] = True, wenn
    USD die Kurswährung ist (EURUSD), False bei USDJPY."""
    days = sorted({d for s in pairs.values() for d in s.index.tz_convert("Europe/London").date})
    by_month: dict[tuple, object] = {}
    for d in days:
        if pd.Timestamp(d).weekday() < 5:
            by_month[(d.year, d.month)] = d  # letzter Werktag mit Daten
    out = {}
    for (y, m), d in sorted(by_month.items()):
        t0 = pd.Timestamp(f"{d} {start_h:02d}:00", tz="Europe/London").tz_convert("UTC")
        t1 = pd.Timestamp(f"{d} {end_h:02d}:00", tz="Europe/London").tz_convert("UTC")
        rets = []
        for pair, s in pairs.items():
            p0, p1 = price_at(s, t0), price_at(s, t1)
            if p0 is None or p1 is None:
                continue
            r = p1 / p0 - 1  # Wertänderung der Basiswährung
            usd_ret = -r if usd_quote[pair] else r
            rets.append((usd_ret if usd_long else -usd_ret) - 2 * cost_per_side)
        if rets:
            out[d] = sum(rets) / len(rets)
    return pd.Series(out, dtype=float)


def backtest(minutes: pd.DataFrame, tp_mult: float | None, cost_per_side: float = 1e-4) -> pd.Series:
    """Tagesrenditen (UTC-Tag), 0 an Tagen ohne Trade; Wochenenden entfallen."""
    out = {}
    for d, g in minutes.groupby(minutes.index.date):
        if pd.Timestamp(d).weekday() >= 5:
            continue
        r = day_trade(g, tp_mult, cost_per_side)
        out[d] = 0.0 if r is None else r
    return pd.Series(out, dtype=float).sort_index()

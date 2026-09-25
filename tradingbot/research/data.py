"""Lokaler Cache für historische Minuten-Bars (Alpaca SIP-Feed).

Pro Symbol eine Pickle-Datei in `cache_dir`. Bereits geladene Tage werden
nicht erneut abgefragt; ein erneuter Aufruf lädt nur den fehlenden Zeitraum
nach. Split-bereinigt (Adjustment.SPLIT): Dividenden-Bereinigung würde bei
jeder neuen Ausschüttung alle alten Kurse umskalieren und damit
nachgeladene und gecachte Teile inkonsistent machen.
"""

from __future__ import annotations

import logging
import os
import time as _time
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

DEFAULT_CACHE_DIR = Path("data_cache")
# Frühester Tag mit Alpaca-SIP-Historie.
EARLIEST_DATE = date(2016, 1, 4)
_NY = "America/New_York"
_COLUMNS = ["open", "high", "low", "close", "volume"]
# Pause zwischen zwei Monatsabfragen: hält den Download bei höchstens ~60
# Anfragen/Minute, damit ein parallel laufender Live-Bot mit denselben Keys
# nicht ins Rate-Limit (200/Minute) läuft.
REQUEST_PAUSE_SECONDS = float(os.getenv("RESEARCH_FETCH_PAUSE", "1.0"))


def _cache_path(cache_dir: Path, symbol: str) -> Path:
    return cache_dir / f"{symbol.upper()}_1min.pkl"


def regular_session(bars: pd.DataFrame) -> pd.DataFrame:
    """Filtert einen Minuten-DataFrame (Index tz-aware) auf 9:30-16:00 ET
    und rechnet den Index nach America/New_York um."""
    if bars.empty:
        return pd.DataFrame(columns=_COLUMNS)
    ny_index = bars.index.tz_convert(_NY)
    mask = (ny_index.time >= time(9, 30)) & (ny_index.time < time(16, 0))
    out = bars.loc[mask, _COLUMNS].copy()
    out.index = ny_index[mask]
    return out


def _fetch(data_client, symbol: str, start: datetime, end: datetime) -> pd.DataFrame:
    from alpaca.data.enums import Adjustment, DataFeed
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame

    request = StockBarsRequest(
        symbol_or_symbols=symbol,
        timeframe=TimeFrame.Minute,
        start=start,
        end=end,
        adjustment=Adjustment.SPLIT,
        feed=DataFeed.SIP,
    )
    raw = data_client.get_stock_bars(request).df
    if raw.empty:
        return pd.DataFrame(columns=_COLUMNS)
    return regular_session(raw.xs(symbol, level="symbol"))


def _month_chunks(a: date, b: date) -> list[tuple[date, date]]:
    """Teilt [a, b] in Kalendermonate (ein Monat SPY-Minuten-Bars passt in
    eine Seite der Alpaca-API)."""
    chunks = []
    cur = a
    while cur <= b:
        nxt = (cur.replace(day=1) + timedelta(days=32)).replace(day=1)
        chunks.append((cur, min(b, nxt - timedelta(days=1))))
        cur = nxt
    return chunks


def load_minute_bars(
    symbol: str,
    start: date = EARLIEST_DATE,
    end: date | None = None,
    data_client=None,
    cache_dir: Path = DEFAULT_CACHE_DIR,
) -> pd.DataFrame:
    """Liefert reguläre-Sitzung-Minuten-Bars für [start, end] (inklusive),
    Index in America/New_York. Ohne `data_client` wird nur der Cache
    gelesen (kein Netzwerkzugriff)."""
    end = end or (datetime.now(timezone.utc) - timedelta(days=1)).date()
    path = _cache_path(cache_dir, symbol)
    cached = pd.read_pickle(path) if path.exists() else pd.DataFrame(columns=_COLUMNS)

    if data_client is not None:
        pieces = [cached]
        cached_first = cached.index[0].date() if len(cached) else None
        cached_last = cached.index[-1].date() if len(cached) else None
        ranges = []
        if cached_first is None:
            ranges.append((start, end))
        else:
            if start < cached_first:
                ranges.append((start, cached_first - timedelta(days=1)))
            if end > cached_last:
                ranges.append((cached_last + timedelta(days=1), end))
        for a, b in [c for r in ranges for c in _month_chunks(*r)]:
            logger.info("Lade %s Minuten-Bars %s bis %s ...", symbol, a, b)
            fetch_start = datetime.combine(a, time(0), tzinfo=timezone.utc)
            fetch_end = datetime.combine(b + timedelta(days=1), time(0), tzinfo=timezone.utc)
            # SIP-Daten sind im Gratisplan erst nach ~15 Minuten abrufbar.
            fetch_end = min(fetch_end, datetime.now(timezone.utc) - timedelta(minutes=20))
            if fetch_start < fetch_end:
                pieces.append(_fetch(data_client, symbol, fetch_start, fetch_end))
            _time.sleep(REQUEST_PAUSE_SECONDS)
        if ranges:
            merged = pd.concat([p for p in pieces if len(p)])
            cached = merged[~merged.index.duplicated(keep="last")].sort_index()
            cache_dir.mkdir(parents=True, exist_ok=True)
            cached.to_pickle(path)

    if cached.empty:
        return cached
    dates = cached.index.date
    return cached.loc[(dates >= start) & (dates <= end)]


def split_sessions(bars: pd.DataFrame) -> list[tuple[date, pd.DataFrame]]:
    """Teilt Minuten-Bars in (Handelstag, Bars des Tages), chronologisch."""
    if bars.empty:
        return []
    return [(d, g) for d, g in bars.groupby(bars.index.date, sort=True)]

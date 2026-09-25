"""Historisches "Stocks in Play"-Universum für die ORB-Strategie (Familie A,
siehe research/PROTOCOL.md).

Stufen, jede einzeln gecacht und wiederaufnehmbar (data_cache/universe/):
1. assets.pkl        -- alle US-Aktien-Symbole bei Alpaca, aktiv UND inaktiv
2. daily/*.pkl       -- Tages-Bars aller Symbole (SIP, split-bereinigt)
3. opening/*.pkl     -- erster 5-Minuten-Bar (9:30) je Tag für alle Symbole,
                        die in den folgenden 15 Handelstagen die Grundfilter
                        erfüllen (nötig für die 14-Tage-RelVol-Historie)
4. intraday/*.pkl    -- Minuten-Bars der Top-N-Kandidaten je Tag

Alle Filter nutzen nur Informationen bis zum Entscheidungszeitpunkt:
Vortages-Kennzahlen (shift(1)) plus Tages-Open und Volumen der ersten fünf
Minuten, die um 9:35 bekannt sind.

Bekannter Rest-Bias: Alpacas Asset-Liste enthält nicht zwingend jedes vor
Jahren delistete Symbol, und ein später neu vergebenes Kürzel liefert die
Historie des aktuellen Inhabers.
"""

from __future__ import annotations

import logging
import os
import time as _time
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

UNIVERSE_DIR = Path("data_cache") / "universe"
_NY = "America/New_York"
_EXCHANGES = {"NYSE", "NASDAQ", "AMEX", "ARCA", "BATS", "NYSEARCA"}
REQUEST_PAUSE_SECONDS = float(os.getenv("RESEARCH_FETCH_PAUSE", "0.0"))

# Grundfilter nach Zarattini & Aziz (2023)
MIN_OPEN = 5.0
MIN_AVG_VOLUME = 1_000_000
MIN_ATR = 0.50
LOOKBACK = 14
MIN_RELVOL_HISTORY = 10


def _pause() -> None:
    if REQUEST_PAUSE_SECONDS:
        _time.sleep(REQUEST_PAUSE_SECONDS)


def _ny(d: date, hh: int, mm: int) -> datetime:
    return pd.Timestamp(datetime.combine(d, time(hh, mm)), tz=_NY).to_pydatetime()


# ---------------------------------------------------------------- Stufe 1

def _data_symbols(assets: pd.DataFrame) -> list[str]:
    """Symbole für die Daten-API: "XYZ_DELISTED" -> "XYZ" (sofern das Kürzel
    nicht ohnehin schon aktiv gelistet ist), CUSIP-artige Einträge (mit
    Ziffern) und Sonderzeichen entfallen."""
    syms = assets["symbol"].str.replace(r"_DELISTED$", "", regex=True)
    ok = syms.str.fullmatch(r"[A-Z]{1,5}")
    return sorted(set(syms[ok]))


def _get_bars_dropping_invalid(data_client, make_request, symbols: list[str]) -> pd.DataFrame:
    """Wie get_stock_bars, entfernt aber Symbole, die die API als ungültig
    ablehnt ("invalid symbol: X"), und versucht es erneut."""
    from alpaca.common.exceptions import APIError

    symbols = list(symbols)
    while symbols:
        try:
            return data_client.get_stock_bars(make_request(symbols)).df
        except APIError as e:
            msg = str(e)
            if "invalid symbol" not in msg:
                raise
            bad = msg.split("invalid symbol:")[-1].strip().strip('"}').strip()
            if bad not in symbols:
                raise
            logger.warning("Symbol %s von der Daten-API abgelehnt, übersprungen", bad)
            symbols.remove(bad)
    return pd.DataFrame()


def fetch_assets(trading_client, base: Path = UNIVERSE_DIR) -> list[str]:
    path = base / "assets.pkl"
    if path.exists():
        return _data_symbols(pd.read_pickle(path))
    from alpaca.trading.enums import AssetClass
    from alpaca.trading.requests import GetAssetsRequest

    assets = trading_client.get_all_assets(GetAssetsRequest(asset_class=AssetClass.US_EQUITY))
    rows = [
        {"symbol": a.symbol, "exchange": str(getattr(a.exchange, "value", a.exchange)),
         "status": str(getattr(a.status, "value", a.status)), "name": a.name}
        for a in assets
    ]
    df = pd.DataFrame(rows)
    df = df[df["exchange"].isin(_EXCHANGES) & ~df["symbol"].str.contains(r"[./]")]
    base.mkdir(parents=True, exist_ok=True)
    df.to_pickle(path)
    logger.info("%d Symbole (%d inaktiv)", len(df), int((df["status"] == "inactive").sum()))
    return _data_symbols(df)


# ---------------------------------------------------------------- Stufe 2

def fetch_daily(data_client, symbols: list[str], start: date, end: date,
                base: Path = UNIVERSE_DIR, batch_size: int = 200) -> pd.DataFrame:
    from alpaca.data.enums import Adjustment, DataFeed
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame

    out_dir = base / "daily"
    out_dir.mkdir(parents=True, exist_ok=True)
    batches = [symbols[i:i + batch_size] for i in range(0, len(symbols), batch_size)]
    for k, batch in enumerate(batches):
        path = out_dir / f"batch_{k:04d}.pkl"
        if path.exists():
            continue
        logger.info("Tages-Bars Batch %d/%d", k + 1, len(batches))
        df = _get_bars_dropping_invalid(data_client, lambda syms: StockBarsRequest(
            symbol_or_symbols=syms, timeframe=TimeFrame.Day,
            start=datetime.combine(start, time(0), tzinfo=timezone.utc),
            end=datetime.combine(end, time(23, 59), tzinfo=timezone.utc),
            adjustment=Adjustment.SPLIT, feed=DataFeed.SIP,
        ), batch)
        df.to_pickle(path)
        _pause()
    return load_daily_panel(base)


def load_daily_panel(base: Path = UNIVERSE_DIR) -> pd.DataFrame:
    """Index (symbol, date), Spalten open/high/low/close/volume."""
    frames = [pd.read_pickle(p) for p in sorted((base / "daily").glob("batch_*.pkl"))]
    frames = [f for f in frames if len(f)]
    df = pd.concat(frames)[["open", "high", "low", "close", "volume"]]
    ts = df.index.get_level_values("timestamp").tz_convert(_NY)
    df.index = pd.MultiIndex.from_arrays(
        [df.index.get_level_values("symbol"), ts.date], names=["symbol", "date"]
    )
    return df[~df.index.duplicated()].sort_index()


def daily_features(panel: pd.DataFrame) -> pd.DataFrame:
    """Vortages-Kennzahlen je (symbol, date): avg_volume, atr, prev_close
    (alle nur aus Vortagen) plus der Tages-Open und das Grundfilter-Flag."""
    g = panel.groupby(level="symbol", group_keys=False)
    prev_close = g["close"].shift(1)
    tr = pd.concat([
        panel["high"] - panel["low"],
        (panel["high"] - prev_close).abs(),
        (panel["low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    feats = pd.DataFrame(index=panel.index)
    feats["open"] = panel["open"]
    feats["prev_close"] = prev_close
    feats["avg_volume"] = g["volume"].transform(lambda v: v.rolling(LOOKBACK).mean().shift(1))
    feats["atr"] = tr.groupby(level="symbol").transform(lambda v: v.rolling(LOOKBACK).mean().shift(1))
    feats["eligible"] = (
        (feats["open"] > MIN_OPEN) & (feats["avg_volume"] > MIN_AVG_VOLUME) & (feats["atr"] > MIN_ATR)
    )
    return feats


def opening_needs(feats: pd.DataFrame) -> dict[date, list[str]]:
    """Symbole, deren erster 5-Minuten-Bar je Tag gebraucht wird: am Tag
    selbst oder in den nächsten LOOKBACK+1 Handelstagen des Symbols
    zulässig (Historie für das relative Volumen)."""
    elig = feats["eligible"].astype(float)
    ahead = elig.groupby(level="symbol", group_keys=False).transform(
        lambda s: s[::-1].rolling(LOOKBACK + 1, min_periods=1).max()[::-1]
    )
    need = ahead[ahead > 0].index
    out: dict[date, list[str]] = {}
    for sym, d in need:
        out.setdefault(d, []).append(sym)
    return out


# ---------------------------------------------------------------- Stufe 3

def fetch_opening_bars(data_client, needs: dict[date, list[str]], base: Path = UNIVERSE_DIR,
                       batch_size: int = 500) -> None:
    from alpaca.data.enums import Adjustment, DataFeed
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

    out_dir = base / "opening"
    out_dir.mkdir(parents=True, exist_ok=True)
    days = sorted(needs)
    months = sorted({(d.year, d.month) for d in days})
    for y, m in months:
        path = out_dir / f"{y}-{m:02d}.pkl"
        if path.exists():
            continue
        rows = []
        for d in [d for d in days if (d.year, d.month) == (y, m)]:
            syms = sorted(needs[d])
            for i in range(0, len(syms), batch_size):
                df = _get_bars_dropping_invalid(data_client, lambda batch, d=d: StockBarsRequest(
                    symbol_or_symbols=batch,
                    timeframe=TimeFrame(5, TimeFrameUnit.Minute),
                    start=_ny(d, 9, 30), end=_ny(d, 9, 34),
                    adjustment=Adjustment.SPLIT, feed=DataFeed.SIP,
                ), syms[i:i + batch_size])
                _pause()
                if df.empty:
                    continue
                df = df.reset_index()
                ts = df["timestamp"].dt.tz_convert(_NY)
                df = df[(ts.dt.hour == 9) & (ts.dt.minute == 30)]
                df["date"] = d
                rows.append(df[["date", "symbol", "open", "high", "low", "close", "volume"]])
        month = pd.concat(rows) if rows else pd.DataFrame(
            columns=["date", "symbol", "open", "high", "low", "close", "volume"])
        month.to_pickle(path)
        logger.info("Eröffnungs-Bars %d-%02d: %d Zeilen", y, m, len(month))


def load_opening(base: Path = UNIVERSE_DIR) -> pd.DataFrame:
    frames = [pd.read_pickle(p) for p in sorted((base / "opening").glob("*.pkl"))]
    return pd.concat([f for f in frames if len(f)]).set_index(["date", "symbol"]).sort_index()


def select_candidates(feats: pd.DataFrame, opening: pd.DataFrame, top_n: int = 20,
                      min_relvol: float = 1.0) -> pd.DataFrame:
    """Top-N je Tag nach relativem Volumen der ersten 5 Minuten. Liefert
    Zeilen (date, symbol) mit relvol, atr, or5_open/high/low/close."""
    vol = opening["volume"].unstack("symbol").sort_index()
    ref = vol.rolling(LOOKBACK, min_periods=MIN_RELVOL_HISTORY).mean().shift(1)
    relvol = (vol / ref).stack().rename("relvol")
    f = feats.swaplevel().sort_index()  # (date, symbol)
    df = opening.join(relvol, how="inner").join(f[["atr", "eligible"]], how="inner")
    df = df[df["eligible"] & (df["relvol"] >= min_relvol)]
    df = df.sort_values("relvol", ascending=False).groupby(level="date", group_keys=False).head(top_n)
    return df.sort_index()


# ---------------------------------------------------------------- Stufe 4

def fetch_intraday(data_client, candidates: pd.DataFrame, base: Path = UNIVERSE_DIR) -> None:
    from alpaca.data.enums import Adjustment, DataFeed
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame

    out_dir = base / "intraday"
    out_dir.mkdir(parents=True, exist_ok=True)
    days = sorted(candidates.index.get_level_values("date").unique())
    months = sorted({(d.year, d.month) for d in days})
    for y, m in months:
        path = out_dir / f"{y}-{m:02d}.pkl"
        if path.exists():
            continue
        frames = []
        for d in [d for d in days if (d.year, d.month) == (y, m)]:
            syms = candidates.loc[d].index.tolist()
            df = _get_bars_dropping_invalid(data_client, lambda batch, d=d: StockBarsRequest(
                symbol_or_symbols=batch, timeframe=TimeFrame.Minute,
                start=_ny(d, 9, 30), end=_ny(d, 15, 59),
                adjustment=Adjustment.SPLIT, feed=DataFeed.SIP,
            ), syms)
            _pause()
            if len(df):
                frames.append(df[["open", "high", "low", "close", "volume"]])
        month = pd.concat(frames) if frames else pd.DataFrame()
        month.to_pickle(path)
        logger.info("Intraday %d-%02d: %d Bars", y, m, len(month))


def load_intraday_month(y: int, m: int, base: Path = UNIVERSE_DIR) -> pd.DataFrame:
    path = base / "intraday" / f"{y}-{m:02d}.pkl"
    df = pd.read_pickle(path)
    if df.empty:
        return df
    ts = df.index.get_level_values("timestamp").tz_convert(_NY)
    df.index = pd.MultiIndex.from_arrays([df.index.get_level_values("symbol"), ts],
                                         names=["symbol", "timestamp"])
    return df


def build_all(data_client, trading_client, start: date, end: date, base: Path = UNIVERSE_DIR,
              top_n: int = 20) -> pd.DataFrame:
    symbols = fetch_assets(trading_client, base)
    # 30 Kalendertage Vorlauf für die 14-Tage-Kennzahlen
    panel = fetch_daily(data_client, symbols, start - timedelta(days=30), end, base)
    feats = daily_features(panel)
    feats.to_pickle(base / "features.pkl")
    needs = opening_needs(feats)
    needs = {d: s for d, s in needs.items() if start <= d <= end}
    logger.info("Eröffnungs-Bars: %d Tage, Ø %.0f Symbole/Tag", len(needs),
                np.mean([len(s) for s in needs.values()]))
    fetch_opening_bars(data_client, needs, base)
    candidates = select_candidates(feats, load_opening(base), top_n)
    candidates.to_pickle(base / "candidates.pkl")
    fetch_intraday(data_client, candidates, base)
    return candidates


# ---------------------------------------------------------------- Stufe 5 (Ticks)

# Trade-Bedingungen, die keinen regulären Kurs setzen und live keine Stop-Order
# auslösen würden: Odd Lot, Durchschnittspreis, verspätet/außerhalb der Reihenfolge,
# außerbörslich/Extended Hours, abgeleitete Preise, Korrekturen.
_EXCLUDED_CONDITIONS = {"I", "W", "Z", "T", "U", "4", "7", "9", "C", "N", "R", "V", "H", "P", "B", "G",
                        "L", "M", "Q"}


def _clean_ticks(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    bad = df["conditions"].apply(
        lambda cs: any(str(c).strip() in _EXCLUDED_CONDITIONS for c in (cs or []))
    )
    return df[~bad]


def fetch_entry_ticks(data_client, events: set[tuple[str, pd.Timestamp]], base: Path = UNIVERSE_DIR,
                      batch_size: int = 50) -> None:
    """Lädt SIP-Ticks für die Minuten (symbol, Minuten-Start), gecacht je Monat."""
    from alpaca.data.enums import DataFeed
    from alpaca.data.requests import StockTradesRequest

    out_dir = base / "ticks"
    out_dir.mkdir(parents=True, exist_ok=True)
    by_month: dict[tuple[int, int], dict[pd.Timestamp, list[str]]] = {}
    for sym, ts in events:
        by_month.setdefault((ts.year, ts.month), {}).setdefault(ts, []).append(sym)
    for (y, m), minutes in sorted(by_month.items()):
        path = out_dir / f"{y}-{m:02d}.pkl"
        if path.exists():
            continue
        rows = []
        for ts, syms in sorted(minutes.items()):
            syms = sorted(set(syms))
            end = ts + pd.Timedelta(minutes=1)
            for i in range(0, len(syms), batch_size):
                df = data_client.get_stock_trades(StockTradesRequest(
                    symbol_or_symbols=syms[i:i + batch_size], start=ts.to_pydatetime(),
                    end=end.to_pydatetime(), feed=DataFeed.SIP,
                )).df
                _pause()
                df = _clean_ticks(df)
                if df.empty:
                    continue
                df = df.reset_index()[["symbol", "timestamp", "price"]]
                df = df[df["timestamp"] < end.tz_convert("UTC")]
                df["minute"] = ts
                rows.append(df)
        month = pd.concat(rows) if rows else pd.DataFrame(columns=["symbol", "timestamp", "price", "minute"])
        month.to_pickle(path)
        logger.info("Ticks %d-%02d: %d Minuten, %d Ticks", y, m, len(minutes), len(month))


def load_tick_lookup(base: Path = UNIVERSE_DIR):
    """Liefert tick_lookup(symbol, minute) -> Preis-Array (zeitlich sortiert) oder None."""
    frames = [pd.read_pickle(p) for p in sorted((base / "ticks").glob("*.pkl"))]
    frames = [f for f in frames if len(f)]
    if not frames:
        return lambda symbol, ts: None
    df = pd.concat(frames).sort_values(["symbol", "minute", "timestamp"], kind="stable")
    table = {
        (sym, pd.Timestamp(minute).tz_convert(_NY)): g["price"].to_numpy(float)
        for (sym, minute), g in df.groupby(["symbol", "minute"], sort=False)
    }
    return lambda symbol, ts: table.get((symbol, ts))

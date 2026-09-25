"""Runde 3 der Forschung: Krypto-Spot (Familien H, I in research/PROTOCOL.md).

Daten: öffentliche Binance-Daten ohne API-Key. Aktive USDT-Paare über die
REST-Schnittstelle (data-api.binance.vision), delistete über die Monats-
archive (data.binance.vision) -- sonst sähe der Backtest nur die Überlebenden.
Gecacht je Symbol in data_cache/crypto/<SYMBOL>.pkl (Index: UTC-Datum).

Engine: gewichtsbasiert. Gewichte werden zum Tagesschluss t festgelegt und
gelten für die Rendite von t nach t+1; Kosten fallen auf den Umschlag an.
"""

from __future__ import annotations

import io
import json
import logging
import re
import urllib.error
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from tradingbot.research import HOLDOUT_START
from tradingbot.research.engine import BacktestResult

logger = logging.getLogger(__name__)

CRYPTO_DIR = Path("data_cache") / "crypto"
REST = "https://data-api.binance.vision/api/v3/klines"
S3_LIST = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
ARCHIVE = "https://data.binance.vision/"
START_MS = int(datetime(2017, 8, 1, tzinfo=timezone.utc).timestamp() * 1000)
PERIODS = 365

STABLE_OR_FIAT = {
    "USDC", "BUSD", "TUSD", "USDP", "PAX", "DAI", "FDUSD", "USDS", "UST", "USTC", "SUSD", "EUR", "GBP",
    "AUD", "TRY", "BRL", "RUB", "UAH", "NGN", "ZAR", "BIDR", "IDRT", "BVND", "AEUR", "EURI", "XUSD",
    "USD1", "PYUSD", "RLUSD", "USDE", "BFUSD", "PAXG", "JPY", "ARS", "PLN", "RON", "MXN", "COP", "CZK",
    "USDSB",
}
# Gehebelte Tokens ohne Basis-Präfix (3x BTC long/short, 2019-2020)
LEVERAGED_STANDALONE = {"BULL", "BEAR", "UP", "DOWN"}
WRAPPED = {"WBTC", "WBETH", "BETH", "STETH", "WETH"}
_COLS = ["open_time", "open", "high", "low", "close", "volume", "close_time", "quote_volume"]


def _get(url: str, timeout: int = 60) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "tradingbot-research"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _s3_prefixes(prefix: str) -> tuple[list[str], list[str]]:
    """(Unterordner, Dateien) eines S3-Präfixes, über alle Seiten."""
    dirs, files, marker = [], [], ""
    while True:
        xml = _get(f"{S3_LIST}?delimiter=/&prefix={prefix}&marker={marker}").decode()
        page_dirs = re.findall(r"<Prefix>([^<]+/)</Prefix>", xml)
        keys = re.findall(r"<Key>([^<]+)</Key>", xml)
        dirs += page_dirs
        files += keys
        if "<IsTruncated>true</IsTruncated>" not in xml:
            break
        nxt = re.search(r"<NextMarker>([^<]+)</NextMarker>", xml)
        marker = nxt.group(1) if nxt else max(keys + [d for d in page_dirs if d != prefix])
    return [d for d in dict.fromkeys(dirs) if d != prefix], files


def all_usdt_symbols() -> list[str]:
    dirs, _ = _s3_prefixes("data/spot/monthly/klines/")
    syms = [d.rstrip("/").split("/")[-1] for d in dirs]
    return sorted(s for s in syms if s.endswith("USDT"))


def is_tradable_asset(symbol: str, all_bases: set[str]) -> bool:
    """Ohne Stablecoins/Fiat, Wrapped-Tokens und gehebelte Tokens (BTCUP,
    ETHBEAR ...). "UP" nur dann als Hebel-Token werten, wenn der Rest ein
    eigenes Paar hat (JUP, SYRUP bleiben)."""
    base = symbol[:-4]
    if not base or base in STABLE_OR_FIAT or base in WRAPPED or base in LEVERAGED_STANDALONE:
        return False
    for suffix in ("DOWN", "BULL", "BEAR", "UP"):
        if base.endswith(suffix) and base[: -len(suffix)] in all_bases:
            return False
    return True


def _to_frame(rows: list[list]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume", "quote_volume"])
    df = pd.DataFrame([r[:8] for r in rows], columns=_COLS)
    t = df["open_time"].astype("int64").to_numpy()
    t = np.where(t > 10**14, t // 1000, t)  # Archive ab 2025 in Mikrosekunden
    df.index = pd.to_datetime(t, unit="ms", utc=True).date
    out = df[["open", "high", "low", "close", "volume", "quote_volume"]].astype(float)
    return out[~out.index.duplicated(keep="last")].sort_index()


def _fetch_rest(symbol: str) -> pd.DataFrame | None:
    rows, start = [], START_MS
    while True:
        try:
            batch = json.loads(_get(f"{REST}?symbol={symbol}&interval=1d&startTime={start}&limit=1000"))
        except urllib.error.HTTPError as e:
            if e.code == 400:
                return None  # nicht (mehr) gelistet -> Archiv
            raise
        rows += batch
        if len(batch) < 1000:
            return _to_frame(rows)
        start = batch[-1][0] + 1


def _fetch_archive(symbol: str) -> pd.DataFrame:
    _, files = _s3_prefixes(f"data/spot/monthly/klines/{symbol}/1d/")
    rows = []
    for key in sorted(k for k in files if k.endswith(".zip")):
        with zipfile.ZipFile(io.BytesIO(_get(ARCHIVE + key))) as z:
            text = z.read(z.namelist()[0]).decode()
        for line in text.splitlines():
            parts = line.split(",")
            if parts and parts[0].isdigit():
                rows.append(parts)
    return _to_frame(rows)


def fetch_symbol(symbol: str, base: Path = CRYPTO_DIR) -> str:
    path = base / f"{symbol}.pkl"
    if path.exists():
        return "cache"
    df = _fetch_rest(symbol)
    source = "rest"
    if df is None or df.empty:
        df, source = _fetch_archive(symbol), "archiv"
    df.to_pickle(path)
    return source


def fetch_all(base: Path = CRYPTO_DIR, workers: int = 8) -> None:
    base.mkdir(parents=True, exist_ok=True)
    symbols = all_usdt_symbols()
    bases = {s[:-4] for s in symbols}
    symbols = [s for s in symbols if is_tradable_asset(s, bases)]
    logger.info("%d USDT-Paare (nach Ausschluss von Stablecoins/Hebel-/Wrapped-Tokens)", len(symbols))
    counts: dict[str, int] = {}

    def safe(sym: str) -> str:
        try:
            return fetch_symbol(sym, base)
        except Exception as e:  # einzelnes Symbol darf den Lauf nicht abbrechen
            logger.warning("%s: %s", sym, e)
            return "fehler"

    with ThreadPoolExecutor(workers) as pool:
        for i, src in enumerate(pool.map(safe, symbols), 1):
            counts[src] = counts.get(src, 0) + 1
            if i % 100 == 0:
                logger.info("%d/%d Symbole (%s)", i, len(symbols), counts)
    logger.info("Fertig: %s", counts)


def load_panel(base: Path = CRYPTO_DIR, allow_holdout: bool = False) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(Schlusskurse, Quote-Volumen) als Tage x Symbole."""
    closes, vols = {}, {}
    paths = sorted(base.glob("*.pkl"))
    bases = {p.stem[:-4] for p in paths}
    for p in (p for p in paths if is_tradable_asset(p.stem, bases)):
        df = pd.read_pickle(p)
        if len(df):
            closes[p.stem], vols[p.stem] = df["close"], df["quote_volume"]
    close = pd.DataFrame(closes).sort_index()
    vol = pd.DataFrame(vols).reindex_like(close)
    if not allow_holdout:
        keep = close.index < HOLDOUT_START
        close, vol = close[keep], vol[keep]
    return close, vol


def universe_mask(close: pd.DataFrame, vol: pd.DataFrame, top_n: int = 20,
                  min_history: int = 60) -> pd.DataFrame:
    """Top-N nach Ø-Quote-Volumen der 30 VORtage, mit mind. `min_history` Tagen Kursen."""
    avg = vol.rolling(30, min_periods=20).mean().shift(1)
    history = close.notna().cumsum()
    avg = avg.where(history >= min_history)
    rank = avg.rank(axis=1, ascending=False)
    return (rank <= top_n) & close.notna()


# ------------------------------------------------------------ Engine

def run_weights(weights: pd.DataFrame, close: pd.DataFrame, cost_per_side: float,
                name: str) -> BacktestResult:
    """Gewichte zum Schluss von t -> Rendite t..t+1. Fehlende Folgekurse
    (Delisting) zählen als 0 % (Ausstieg zum letzten Kurs). Kosten =
    cost_per_side * Umschlag, am Tag nach der Umschichtung abgezogen.
    trade_net_returns = Tagesrenditen der investierten Tage."""
    w = weights.reindex(index=close.index, columns=close.columns).fillna(0.0)
    rets = (close / close.shift(1) - 1).fillna(0.0)
    held = w.shift(1).fillna(0.0)
    gross = (held * rets).sum(axis=1)
    turnover = (w - held).abs().sum(axis=1)
    net = gross - cost_per_side * turnover.shift(1).fillna(0.0)
    invested = w.abs().sum(axis=1) > 0
    if invested.any():
        net = net[net.index > invested.idxmax()]
    active = net[held.abs().sum(axis=1).reindex(net.index) > 0]
    return BacktestResult(name, net, [], active.to_numpy())


def trend_weights(close: pd.Series, lookback: int) -> pd.Series:
    """Familie H: 1, solange Schluss > SMA(lookback), sonst 0."""
    sma = close.rolling(lookback).mean()
    return (close > sma).astype(float).where(sma.notna(), 0.0)


def momentum_weights(close: pd.DataFrame, universe: pd.DataFrame, lookback: int, k: int,
                     btc_filter: bool, rebalance_days: int = 7) -> pd.DataFrame:
    """Familie I: alle `rebalance_days` die k Coins mit der höchsten
    L-Tage-Rendite (nur im Universum), gleichgewichtet, bis zur nächsten
    Umschichtung gehalten (tägliche Rückgewichtung auf 1/k als Näherung).
    Fehlt ein Kurs (Delisting), fällt die Position weg."""
    past = close / close.shift(lookback) - 1
    btc = close["BTCUSDT"]
    btc_ok = (btc > btc.rolling(50).mean()) if btc_filter else None
    rows = np.zeros(close.shape)
    current = np.zeros(close.shape[1])
    avail = close.notna().to_numpy()
    for i, d in enumerate(close.index):
        if i % rebalance_days == 0:
            current = np.zeros(close.shape[1])
            cand = past.loc[d].where(universe.loc[d]).dropna()
            if len(cand) >= k and (btc_ok is None or bool(btc_ok.loc[d])):
                current[close.columns.get_indexer(cand.nlargest(k).index)] = 1.0 / k
        rows[i] = np.where(avail[i], current, 0.0)
    return pd.DataFrame(rows, index=close.index, columns=close.columns)


# ------------------------------------------------------------ Familie O: Funding-Carry

FAPI = "https://fapi.binance.com/fapi/v1"
FUNDING_START_MS = int(datetime(2019, 9, 1, tzinfo=timezone.utc).timestamp() * 1000)


def fetch_perp(symbol: str, base: Path = CRYPTO_DIR) -> pd.DataFrame:
    """Perp-Tageskerzen und Funding je UTC-Tag. Funding eines Haltetags D
    (00:00 D bis 00:00 D+1) = Zahlungen um 08:00 D, 16:00 D und 00:00 D+1."""
    path = base / "perp" / f"{symbol}.pkl"
    if path.exists():
        return pd.read_pickle(path)
    rows, start = [], FUNDING_START_MS
    while True:
        batch = json.loads(_get(f"{FAPI}/klines?symbol={symbol}&interval=1d&startTime={start}&limit=1000"))
        rows += batch
        if len(batch) < 1000:
            break
        start = batch[-1][0] + 1
    perp = _to_frame(rows)["close"].rename("perp_close")
    fund, start = [], FUNDING_START_MS
    while True:
        batch = json.loads(_get(f"{FAPI}/fundingRate?symbol={symbol}&startTime={start}&limit=1000"))
        fund += batch
        if len(batch) < 1000:
            break
        start = batch[-1]["fundingTime"] + 1
    ft = pd.DataFrame(fund)
    day = pd.to_datetime(ft["fundingTime"].astype("int64") - 1, unit="ms", utc=True).dt.date
    funding = ft["fundingRate"].astype(float).groupby(day.to_numpy()).sum().rename("funding")
    out = pd.concat([perp, funding], axis=1).sort_index()
    path.parent.mkdir(parents=True, exist_ok=True)
    out.to_pickle(path)
    return out


def funding_carry(spot_close: pd.Series, perp: pd.DataFrame, filtered: bool, cost_spot: float,
                  cost_perp: float, name: str = "funding_carry") -> BacktestResult:
    """50 % Spot long + 50 % Perp short (gleiche Nominale). Position zum
    Tagesschluss D-1 festgelegt, gilt für Tag D. filtered: nur investiert,
    wenn das Ø-Funding der letzten 7 Tage bis einschließlich D-1 > 0."""
    df = pd.concat([spot_close.rename("spot"), perp], axis=1).dropna(subset=["spot", "perp_close"])
    df["funding"] = df["funding"].fillna(0.0)
    spot_r = df["spot"].pct_change()
    perp_r = df["perp_close"].pct_change()
    if filtered:
        pos = (df["funding"].rolling(7).mean() > 0).astype(float)
    else:
        pos = pd.Series(1.0, index=df.index)
    held = pos.shift(1).fillna(0.0)
    gross = 0.5 * (spot_r - perp_r + df["funding"]) * held
    switch = (pos - held).abs().shift(1).fillna(0.0)  # Umschichtung zum Schluss D-1
    net = (gross - 0.5 * (cost_spot + cost_perp) * switch).iloc[1:]
    if not filtered:
        net.iloc[0] -= 0.5 * (cost_spot + cost_perp)  # einmaliger Einstieg
    active = net[held.iloc[1:] > 0]
    return BacktestResult(name, net.fillna(0.0), [], active.to_numpy())

"""Zeichnet Zwangsliquidationen von Krypto-Perpetuals auf (keine Orders).

Historische Liquidationsdaten gibt es nicht kostenlos, deshalb sammeln wir sie
ab jetzt selbst, um später Liquidationskaskaden testen zu können.

Quellen (öffentliche Websockets, keine API-Keys):
- Binance USDⓈ-M ``!forceOrder@arr``: alle Symbole, aber je Symbol höchstens
  die größte Liquidation pro Sekunde (Binance-Snapshot) -- also unvollständig.
- Bybit ``allLiquidation.<SYMBOL>``: jede Liquidation, aber nur für die
  abonnierten Symbole (``BYBIT_SYMBOLS``).

Pro Börse und UTC-Tag entsteht ``<exchange>_<YYYY-MM-DD>.csv`` mit
``recv_ms,trade_ms,symbol,liquidated,price,qty``; ``liquidated`` ist die Seite
der zwangsgeschlossenen Position (``long``/``short``). Verbindungsabbrüche
landen in ``gaps.csv``, damit die Auswertung Datenlücken kennt.
"""
from __future__ import annotations

import asyncio
import csv
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

import websockets

log = logging.getLogger(__name__)

# Seit 2026-04 liefert Binance Marktdaten-Streams nur noch unter /market.
BINANCE_URL = "wss://fstream.binance.com/market/ws/!forceOrder@arr"
BYBIT_URL = "wss://stream.bybit.com/v5/public/linear"
BYBIT_SYMBOLS = (
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "BNBUSDT", "ADAUSDT",
    "LINKUSDT", "AVAXUSDT", "SUIUSDT", "LTCUSDT", "BCHUSDT", "DOTUSDT", "TRXUSDT",
    "HYPEUSDT", "1000PEPEUSDT", "WIFUSDT", "ENAUSDT", "AAVEUSDT", "NEARUSDT",
)
COLUMNS = ("recv_ms", "trade_ms", "symbol", "liquidated", "price", "qty")
FLUSH_SECONDS = 30


def parse_binance(msg: dict) -> list[tuple]:
    """Binance-forceOrder-Event -> Zeilen. SELL-Order = Long wurde liquidiert."""
    o = msg.get("o")
    if msg.get("e") != "forceOrder" or not o:
        return []
    side = "long" if o["S"] == "SELL" else "short"
    price = o.get("ap") or o["p"]
    return [(int(o["T"]), o["s"], side, price, o.get("z") or o["q"])]


def parse_bybit(msg: dict) -> list[tuple]:
    """Bybit-allLiquidation-Nachricht -> Zeilen. S=Buy heißt laut Doku: Long liquidiert."""
    if not str(msg.get("topic", "")).startswith("allLiquidation."):
        return []
    return [(int(d["T"]), d["s"], "long" if d["S"] == "Buy" else "short", d["p"], d["v"])
            for d in msg.get("data", [])]


class DailyCsvWriter:
    """Puffert Zeilen und hängt sie gesammelt an die Tagesdatei der Börse an."""

    def __init__(self, out_dir: Path, exchange: str):
        self.out_dir, self.exchange = out_dir, exchange
        self.buffer: list[tuple] = []

    def add(self, recv_ms: int, rows: list[tuple]) -> None:
        self.buffer.extend((recv_ms, *r) for r in rows)

    def flush(self) -> None:
        if not self.buffer:
            return
        rows, self.buffer = self.buffer, []
        by_day: dict[str, list[tuple]] = {}
        for r in rows:
            day = datetime.fromtimestamp(r[0] / 1000, timezone.utc).strftime("%Y-%m-%d")
            by_day.setdefault(day, []).append(r)
        for day, day_rows in by_day.items():
            path = self.out_dir / f"{self.exchange}_{day}.csv"
            new = not path.exists()
            with path.open("a", newline="") as f:
                w = csv.writer(f)
                if new:
                    w.writerow(COLUMNS)
                w.writerows(day_rows)


def log_gap(out_dir: Path, exchange: str, start_ms: int, end_ms: int, reason: str) -> None:
    path = out_dir / "gaps.csv"
    new = not path.exists()
    with path.open("a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(("exchange", "from_ms", "to_ms", "reason"))
        w.writerow((exchange, start_ms, end_ms, reason))


def _now_ms() -> int:
    return int(time.time() * 1000)


async def _stream(exchange: str, url: str, parse, out_dir: Path, subscribe=None, ping=None) -> None:
    """Hält eine Verbindung mit Reconnect-Backoff; schreibt Lücken nach gaps.csv."""
    writer = DailyCsvWriter(out_dir, exchange)
    backoff, down_since, reason = 1, _now_ms(), "start"
    while True:
        try:
            async with websockets.connect(url, ping_interval=20, max_size=2**20) as ws:
                if subscribe:
                    await subscribe(ws)
                log_gap(out_dir, exchange, down_since, _now_ms(), reason)
                log.info("%s verbunden", exchange)
                backoff, last_flush, last_ping = 1, time.monotonic(), time.monotonic()
                while True:
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=5)
                        writer.add(_now_ms(), parse(json.loads(raw)))
                    except asyncio.TimeoutError:
                        pass
                    now = time.monotonic()
                    if ping and now - last_ping >= 20:
                        await ping(ws)
                        last_ping = now
                    if now - last_flush >= FLUSH_SECONDS:
                        writer.flush()
                        last_flush = now
        except asyncio.CancelledError:
            writer.flush()
            raise
        except Exception as e:  # Netzfehler, Geoblocking (HTTP 451), Server-Close ...
            writer.flush()
            down_since, reason = _now_ms(), f"{type(e).__name__}: {e}"[:200]
            log.warning("%s getrennt (%s), neuer Versuch in %ss", exchange, reason, backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 300)


async def _bybit_subscribe(ws) -> None:
    for i in range(0, len(BYBIT_SYMBOLS), 10):
        args = [f"allLiquidation.{s}" for s in BYBIT_SYMBOLS[i:i + 10]]
        await ws.send(json.dumps({"op": "subscribe", "args": args}))


async def _bybit_ping(ws) -> None:
    await ws.send(json.dumps({"op": "ping"}))


async def record(out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    await asyncio.gather(
        _stream("binance", BINANCE_URL, parse_binance, out_dir),
        _stream("bybit", BYBIT_URL, parse_bybit, out_dir, _bybit_subscribe, _bybit_ping),
    )


if __name__ == "__main__":
    # Direkt als Modul starten (python -m tradingbot.liquidations [ZIELORDNER]):
    # lädt weder pandas noch alpaca und bleibt so bei wenigen MB RAM.
    import sys

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    try:
        asyncio.run(record(Path(sys.argv[1] if len(sys.argv) > 1 else "data_cache/liquidations")))
    except KeyboardInterrupt:
        pass

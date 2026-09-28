"""Runde 92, Schritt 1+2: Alpaca-News über Nacht (16:00 ET Vortag .. 09:20 ET) und Tageskerzen.

Aufruf: PYTHONPATH=. python research/scripts/r92_fetch.py [env-datei]  (Standard: bottest.env)
"""
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
from dotenv import load_dotenv

load_dotenv(sys.argv[1] if len(sys.argv) > 1 else "bottest.env")
from alpaca.data.enums import Adjustment, DataFeed  # noqa: E402
from alpaca.data.historical import StockHistoricalDataClient  # noqa: E402
from alpaca.data.historical.news import NewsClient  # noqa: E402
from alpaca.data.requests import NewsRequest, StockBarsRequest  # noqa: E402
from alpaca.data.timeframe import TimeFrame  # noqa: E402

from tradingbot.config import Config  # noqa: E402

NY = ZoneInfo("America/New_York")
OUT = Path("data_cache/r92"); (OUT / "news").mkdir(parents=True, exist_ok=True)
cfg = Config.from_env()
news_client = NewsClient(cfg.api_key, cfg.secret_key)
bars_client = StockHistoricalDataClient(cfg.api_key, cfg.secret_key)

days = pd.bdate_range("2025-10-01", "2026-09-25")
for d in days:
    p = OUT / "news" / f"{d:%Y-%m-%d}.json"
    if p.exists():
        continue
    prev = (d - pd.offsets.BDay(1)).date()
    start = datetime(prev.year, prev.month, prev.day, 16, 0, tzinfo=NY)
    end = datetime(d.year, d.month, d.day, 9, 20, tzinfo=NY)
    items = None
    for attempt in range(5):
        try:
            res = news_client.get_news(NewsRequest(start=start, end=end, limit=10000, include_content=False))
            items = res.data.get("news", [])
            break
        except Exception as e:
            print("Fehler", d.date(), e, flush=True)
            time.sleep(10 * (attempt + 1))
    if items is None:
        continue
    rows = [{"t": it.created_at.isoformat(), "h": it.headline, "s": (it.summary or "")[:500],
             "sym": [s.strip() for s in it.symbols]} for it in items]
    p.write_text(json.dumps(rows))
    print(d.date(), len(rows), flush=True)
    time.sleep(0.4)

syms = set()
for p in (OUT / "news").glob("*.json"):
    for r in json.loads(p.read_text()):
        syms.update(s for s in r["sym"] if s and s.isalpha() and len(s) <= 5)
syms = sorted(syms)
print("Symbole mit Nachrichten:", len(syms), flush=True)
bars_path = OUT / "bars.pkl"
if not bars_path.exists():
    frames = []
    for i in range(0, len(syms), 200):
        chunk = syms[i:i + 200]
        for attempt in range(5):
            try:
                df = bars_client.get_stock_bars(StockBarsRequest(
                    symbol_or_symbols=chunk, timeframe=TimeFrame.Day, start=datetime(2025, 8, 15, tzinfo=NY),
                    end=datetime(2026, 9, 26, tzinfo=NY), adjustment=Adjustment.RAW, feed=DataFeed.SIP)).df
                frames.append(df[["open", "close", "volume"]])
                break
            except Exception as e:
                print("Kerzen-Fehler", i, e, flush=True)
                time.sleep(10 * (attempt + 1))
        print("Kerzen", min(i + 200, len(syms)), "/", len(syms), flush=True)
        time.sleep(0.4)
    pd.concat(frames).to_pickle(bars_path)
print("fertig", flush=True)

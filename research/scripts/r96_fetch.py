"""Runde 96: Alpaca-News über Nacht 2016-01..2025-09 nachladen (gleiches Format wie Runde 92).

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

days = pd.bdate_range("2016-01-04", "2025-09-30")
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


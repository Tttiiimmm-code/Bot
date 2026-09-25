"""Runde 7: historische Validierung 2003-2015 mit kostenlosen Yahoo-Tagesdaten
(research/PROTOCOL.md). Liefert Tages-DataFrames im Format von
swing.etf_daily, damit die bestehenden Strategiefunktionen unverändert
laufen.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

YAHOO_DIR = Path("data_cache") / "yahoo"
VALIDATION_END = date(2015, 12, 31)
_URL = ("https://query1.finance.yahoo.com/v8/finance/chart/{sym}?period1={p1}&period2={p2}"
        "&interval=1d&events=div%2Csplit")


def fetch_yahoo(symbol: str, base: Path = YAHOO_DIR, until: date = date(2016, 1, 1)) -> pd.DataFrame:
    """Rohdaten 1993 bis `until` (exklusiv): open, close (split-bereinigt),
    adjclose (zusätzlich dividendenbereinigt), dividend (am Ex-Tag, sonst 0).
    Index: Handelstag. Standard bis 2016 (Runde 7); Runde 8 lädt bis heute
    in einen eigenen Cache (Suffix _full)."""
    suffix = "" if until == date(2016, 1, 1) else "_full"
    path = base / f"{symbol}{suffix}.pkl"
    if path.exists():
        return pd.read_pickle(path)
    p1 = int(datetime(1993, 1, 1, tzinfo=timezone.utc).timestamp())
    p2 = int(datetime(until.year, until.month, until.day, tzinfo=timezone.utc).timestamp())
    req = urllib.request.Request(_URL.format(sym=urllib.parse.quote(symbol), p1=p1, p2=p2), headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        res = json.load(r)["chart"]["result"][0]
    q = res["indicators"]["quote"][0]
    idx = pd.to_datetime(res["timestamp"], unit="s", utc=True).tz_convert("America/New_York").date
    df = pd.DataFrame({"open": q["open"], "close": q["close"],
                       "adjclose": res["indicators"]["adjclose"][0]["adjclose"]}, index=idx)
    divs = res.get("events", {}).get("dividends", {})
    div = pd.Series({pd.Timestamp(v["date"], unit="s", tz="UTC").tz_convert("America/New_York").date(): v["amount"]
                     for v in divs.values()}, dtype=float)
    df["dividend"] = div.reindex(df.index).fillna(0.0)
    df = df.dropna(subset=["open", "close", "adjclose"])
    df = df[~df.index.duplicated(keep="last")]
    base.mkdir(parents=True, exist_ok=True)
    df.to_pickle(path)
    return df


def as_daily(df: pd.DataFrame, overnight: bool = False) -> pd.DataFrame:
    """Format wie swing.etf_daily bis VALIDATION_END. overnight=True: Open um
    die Dividende am Ex-Tag erhöht (der Kursabschlag über Nacht ist kein
    Verlust) und Rohschlusskurs; sonst dividendenbereinigter Schlusskurs.
    pre_close = Schlusskurs (keine Intraday-Daten)."""
    df = df[df.index <= VALIDATION_END]
    ts = pd.DatetimeIndex([pd.Timestamp(d) for d in df.index])
    if overnight:
        open_, close = df["open"] + df["dividend"], df["close"]
    else:
        open_, close = df["open"], df["adjclose"]
    return pd.DataFrame({
        "open": open_.to_numpy(float), "close": close.to_numpy(float), "pre_close": close.to_numpy(float),
        "open_time": ts + pd.Timedelta(hours=9, minutes=30),
        "close_time": ts + pd.Timedelta(hours=16),
    }, index=df.index)

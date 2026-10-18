"""Ersatz-Aufzeichnung von Intraday-Kursen (Yahoo) während der Dukascopy-Sperre -- nur Datensicherung.

Dukascopy blockt seit 2026-10-09 automatisierte Abrufe; die bindenden Vorwärtstests nikkei_night, gotobi,
gotobi_eurjpy und gold_breakout stehen. Yahoo liefert 1-Minuten-Kerzen nur ~7 Tage und 5-Minuten-Kerzen nur ~60 Tage
rückwirkend -- ohne laufende Aufzeichnung wären die Kurse der Sperrzeit später nicht mehr zu bekommen.

Ändert keine Auswertung: Ob diese Daten (Mittelkurse, Nikkei/Gold als Futures statt CFD) für die bindenden Tests
verwendet werden, entscheidet der Nutzer (Protokolleintrag nötig). Ablage je Symbol und Intervall als CSV
`data_cache/yahoo_intraday/<name>_<intervall>.csv` mit ts (Unix-Sekunden, UTC), open, high, low, close, volume.
"""
from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path

import pandas as pd

BASE = Path("data_cache") / "yahoo_intraday"
SYMBOLS = {"USDJPY=X": "usdjpy", "EURJPY=X": "eurjpy", "NIY=F": "niy", "GC=F": "gc"}   # Nikkei/Gold: CME-Futures
INTERVALS = (("1m", "7d"), ("5m", "60d"))
COLUMNS = ["ts", "open", "high", "low", "close", "volume"]


def fetch(symbol: str, interval: str, rng: str, opener=urllib.request.urlopen) -> pd.DataFrame:
    """Kerzen von Yahoo (chart-API); Kerzen ohne Schlusskurs werden verworfen."""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval={interval}&range={rng}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with opener(req, timeout=60) as r:
        chart = json.load(r)["chart"]
    if not chart.get("result"):
        raise RuntimeError(f"Yahoo lieferte keine Daten für {symbol} {interval}: {chart.get('error')}")
    res = chart["result"][0]
    q = res["indicators"]["quote"][0]
    df = pd.DataFrame({"ts": res.get("timestamp") or [], **{c: q.get(c) or [] for c in COLUMNS[1:]}})
    return df.dropna(subset=["close"]).reset_index(drop=True)


def merge(path: Path, new: pd.DataFrame) -> tuple[int, int]:
    """Neue Kerzen anhängen (gleicher Zeitstempel: neuer Wert gilt), atomar schreiben. -> (neu, gesamt)."""
    old = pd.read_csv(path) if path.exists() else pd.DataFrame(columns=COLUMNS)
    before = set(old["ts"].astype("int64")) if len(old) else set()
    both = pd.concat([old, new[COLUMNS]], ignore_index=True)
    both["ts"] = both["ts"].astype("int64")
    both = both.drop_duplicates("ts", keep="last").sort_values("ts")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".csv.tmp")
    both.to_csv(tmp, index=False)
    os.replace(tmp, path)
    return len(set(both["ts"]) - before), len(both)


def run(base: Path = BASE, fetcher=fetch) -> str:
    """Alle Symbole und Intervalle sichern; ein Fehler bricht die übrigen nicht ab, endet aber mit Fehler."""
    lines, errors = [], []
    for symbol, name in SYMBOLS.items():
        for interval, rng in INTERVALS:
            try:
                added, total = merge(base / f"{name}_{interval}.csv", fetcher(symbol, interval, rng))
                lines.append(f"{symbol} {interval}: +{added} Kerzen (gesamt {total})")
            except Exception as exc:                       # noqa: BLE001 -- jede Quelle einzeln
                errors.append(f"{symbol} {interval}: {exc}")
    text = "Intraday-Sicherung (Yahoo): " + "; ".join(lines)
    if errors:
        raise RuntimeError(text + " | Fehler: " + "; ".join(errors))
    return text

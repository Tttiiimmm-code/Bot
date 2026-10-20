"""Intraday-Kurse von Yahoo: Datenquelle der Vorwärtstests nikkei_night, gotobi, gotobi_eurjpy (ab 2026-10-09) und
gold_breakout, seit Dukascopy automatisierte Abrufe blockt (2026-10-09; Nutzer 2026-10-20: nicht weiter versuchen).

Yahoo liefert 1-Minuten-Kerzen nur ~7 Tage und 5-Minuten-Kerzen nur ~60 Tage rückwirkend -> tägliche Aufzeichnung.
Mittelkurse (kein Geld/Brief); Nikkei und Gold als CME-Futures, zusätzlich je Einzelkontrakt (laufender + nächster),
damit `continuous` die Kontrakte zu festen Terminen ohne Kurssprung verketten kann. Ablage je Symbol und Intervall
als CSV `data_cache/yahoo_intraday/<name>_<intervall>.csv` mit ts (Unix-Sekunden, UTC), open, high, low, close, volume.
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


# ------------------------------------------------------------ Einzelkontrakte und Verkettung

MONTH_CODES = "FGHJKMNQUVXZ"
# Wurzel -> (Yahoo-Präfix, Börsenzusatz, Liefermonate). Wechsel auf den nächsten Kontrakt (fest, 2026-10-20):
# Gold am 20. des Vormonats der Lieferung 00:00 UTC (vor dem First Notice Day), Nikkei am 1. des Verfallsmonats.
ROOTS = {"gc": ("GC", ".CMX", (2, 4, 6, 8, 12)), "niy": ("NIY", ".CME", (3, 6, 9, 12))}


def roll_time(root: str, y: int, m: int) -> pd.Timestamp:
    """Zeitpunkt, ab dem Kontrakt (y, m) nicht mehr der laufende ist."""
    if root == "gc":
        y, m = (y, m - 1) if m > 1 else (y - 1, 12)
        return pd.Timestamp(year=y, month=m, day=20, tz="UTC")
    return pd.Timestamp(year=y, month=m, day=1, tz="UTC")


def contract_code(root: str, y: int, m: int) -> str:
    return f"{ROOTS[root][0]}{MONTH_CODES[m - 1]}{y % 100:02d}"


def segments(root: str, start: pd.Timestamp, end: pd.Timestamp) -> list[tuple[int, int, pd.Timestamp, pd.Timestamp]]:
    """Laufende Kontrakte (Jahr, Monat, von, bis) für [start, end), aufsteigend."""
    months = ROOTS[root][2]
    cs = sorted((y, m) for y in range(start.year - 1, end.year + 2) for m in months)
    out = []
    for (py, pm), (y, m) in zip(cs[:-1], cs[1:]):
        a, b = roll_time(root, py, pm), roll_time(root, y, m)
        if a < end and b > start:
            out.append((y, m, max(a, start), min(b, end)))
    return out


def contracts_to_record(root: str, now: pd.Timestamp) -> list[str]:
    """Laufender und nächster Kontrakt (der nächste muss vor dem Wechsel schon aufgezeichnet sein)."""
    segs = segments(root, now, now + pd.Timedelta(days=200))
    return [contract_code(root, y, m) for y, m, _, _ in segs[:2]]


def _read(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=["open", "high", "low", "close"], index=pd.DatetimeIndex([], tz="UTC"), dtype=float)
    df = pd.read_csv(path)
    df.index = pd.to_datetime(df.pop("ts"), unit="s", utc=True)
    df = df[["open", "high", "low", "close"]].astype(float)
    return df[~df.index.duplicated(keep="last")].sort_index()


def load_bars(name: str, base: Path = BASE) -> pd.DataFrame:
    """1-Minuten-Kerzen, Lücken (älter als ~7 Tage, Sicherungsausfall) mit 5-Minuten-Kerzen gefüllt: eine 5-Minuten-
    Kerze zählt nur, wenn in ihren 5 Minuten keine einzige 1-Minuten-Kerze liegt."""
    m1, m5 = _read(base / f"{name}_1m.csv"), _read(base / f"{name}_5m.csv")
    covered = set(m1.index.floor("5min"))
    m5 = m5[[t not in covered for t in m5.index]]
    out = pd.concat([m1, m5]).sort_index()
    return out[~out.index.duplicated()]


def continuous(root: str, start: pd.Timestamp, end: pd.Timestamp, base: Path = BASE) -> pd.DataFrame:
    """Verkettete Kerzen der laufenden Kontrakte in [start, end), ältere Kontrakte per Kursverhältnis am Wechsel
    angepasst (Renditen und Verhältnisse wie R bleiben unverändert). Fehlt ein gemeinsamer Kurs am Wechsel: Fehler."""
    parts = []
    for y, m, a, b in segments(root, start, end):
        bars = load_bars(f"{root}_{contract_code(root, y, m)}", base)
        parts.append((y, m, bars, bars[(bars.index >= a) & (bars.index < b)]))
    factor, out = 1.0, []
    for i in range(len(parts) - 1, -1, -1):
        y, m, full, seg = parts[i]
        out.append(seg * factor)
        if i > 0:
            py, pm, prev_full, _ = parts[i - 1]
            t = roll_time(root, py, pm)
            common = prev_full.index.intersection(full.index)
            common = common[(common <= t) & (common > t - pd.Timedelta(days=4))]
            if not len(common):
                raise RuntimeError(f"{root}: kein gemeinsamer Kurs von {contract_code(root, py, pm)} und "
                                   f"{contract_code(root, y, m)} vor dem Wechsel {t:%Y-%m-%d}")
            factor *= float(full.loc[common[-1], "close"]) / float(prev_full.loc[common[-1], "close"])
    res = pd.concat(out[::-1]).sort_index() if out else _read(base / "-")
    return res[~res.index.duplicated()]


def run(base: Path = BASE, fetcher=fetch, now: pd.Timestamp | None = None) -> str:
    """Alle Symbole und Intervalle sichern; ein Fehler bricht die übrigen nicht ab, endet aber mit Fehler."""
    now = now or pd.Timestamp.now(tz="UTC")
    lines, errors = [], []
    symbols = dict(SYMBOLS)
    for root, (_, suffix, _) in ROOTS.items():
        for code in contracts_to_record(root, now):
            symbols[code + suffix] = f"{root}_{code}"
    for symbol, name in symbols.items():
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

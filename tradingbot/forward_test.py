"""Vorwärtstest (Papier, ohne Broker) der zwei robusten Forschungsbefunde,
siehe research/PROTOCOL.md (Branch research/ideas) Runden 46-49 und 53:

- nikkei_night: Nikkei 225 long vom Schluss der OSE-Tagessitzung (15:45 JST,
  vor 2024-11-05 15:15) bis zur Eröffnung am nächsten Handelstag (08:45 JST).
  Kurse: Dukascopy-CFD jpnidxjpy (Bid). Kosten 0,5 bp je Seite (Handel in den
  Auktionen) + JPY-Zins/360 je Kalendernacht (Future-Carry).
- gotobi: USD/JPY long von 05:00 bis 09:55 JST an Gotobi-Tagen (5., 10., 15.,
  20., 25. und Monatsletzter; Wochenende -> vorheriger Freitag). Kauf zum
  Dukascopy-ASK, Verkauf zum BID, zusätzlich 0,35 bp Kommission je Seite.

Es werden keine Orders gesendet. Jeder Lauf lädt die letzten Tage Minutendaten
per `npx dukascopy-node`, berechnet die Trades und schreibt sie in eine
CSV (idempotent: gleiche Strategie + Datum wird ersetzt). Trades vor
`first_day` werden nicht erfasst, damit die Auswertung ein echter Vorwärtstest
bleibt.
"""

from __future__ import annotations

import calendar
import csv
import logging
import math
import shutil
import subprocess
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

TOKYO = "Asia/Tokyo"
LEDGER_FIELDS = ["strategy", "date", "entry_time", "entry_price", "exit_time", "exit_price", "net_bp"]
# Erwartung aus dem Backtest (Ø netto je Trade in bp, 2013-2025 bzw. 2017-2025)
EXPECTED_BP = {"nikkei_night": 4.21, "gotobi": 1.00}
OSE_CLOSE_CHANGE = date(2024, 11, 5)
# Börsenfreie Tage in Japan (Nationalfeiertage + Jahreswechsel). Der Dukascopy-CFD
# notiert auch an diesen Tagen, die OSE-Futures nicht -> für nikkei_night
# übersprungen (Position läuft über den Feiertag). Jährlich ergänzen
# (Quelle: JPX-Handelskalender).
JP_MARKET_HOLIDAYS = {
    date(2026, 1, 1), date(2026, 1, 2), date(2026, 1, 12), date(2026, 2, 11), date(2026, 2, 23),
    date(2026, 3, 20), date(2026, 4, 29), date(2026, 5, 4), date(2026, 5, 5), date(2026, 5, 6),
    date(2026, 7, 20), date(2026, 8, 11), date(2026, 9, 21), date(2026, 9, 22), date(2026, 9, 23),
    date(2026, 10, 12), date(2026, 11, 3), date(2026, 11, 23), date(2026, 12, 31),
    date(2027, 1, 1), date(2027, 1, 11), date(2027, 2, 11), date(2027, 2, 23), date(2027, 3, 22),
    date(2027, 4, 29), date(2027, 5, 3), date(2027, 5, 4), date(2027, 5, 5), date(2027, 7, 19),
    date(2027, 8, 11), date(2027, 9, 20), date(2027, 9, 23), date(2027, 10, 11), date(2027, 11, 3),
    date(2027, 11, 23), date(2027, 12, 31),
}


@dataclass(frozen=True)
class ForwardConfig:
    first_day: date
    ledger: Path = Path("forward_trades.csv")
    data_dir: Path = Path("data_cache") / "forward"
    lookback_days: int = 10
    nikkei_cost_per_side: float = 0.5e-4
    jpy_rate: float = 0.0075  # p.a., für den Future-Carry
    gotobi_commission: float = 0.35e-4


# ------------------------------------------------------------ Daten

def fetch_minutes(instrument: str, side: str, start: date, end: date, base: Path) -> Path:
    """Lädt Dukascopy-Minutenkerzen [start, end) als CSV und gibt den Pfad zurück."""
    npx = shutil.which("npx")
    if npx is None:
        raise RuntimeError("npx nicht gefunden -- Node.js installieren (für dukascopy-node).")
    base.mkdir(parents=True, exist_ok=True)
    name = f"{instrument}_{side}_{start}_{end}"
    cmd = [npx, "--yes", "dukascopy-node", "-i", instrument, "-from", str(start), "-to", str(end),
           "-t", "m1", "-p", side, "-f", "csv", "-dir", str(base), "-fn", name]
    subprocess.run(cmd, check=True, capture_output=True, timeout=1800)
    path = base / f"{name}.csv"
    if not path.exists():
        raise RuntimeError(f"dukascopy-node hat keine Datei erzeugt: {path}")
    return path


def load_open_prices(path: Path) -> pd.Series:
    """Minuten-Open als Serie mit UTC-Zeitindex."""
    df = pd.read_csv(path)
    s = pd.Series(df["open"].to_numpy(float), index=pd.to_datetime(df["timestamp"], unit="ms", utc=True))
    return s[~s.index.duplicated()].sort_index()


def price_at(series: pd.Series, ts: pd.Timestamp, tolerance_min: int = 5) -> float | None:
    """Open der ersten Minute ab ts (höchstens tolerance_min später)."""
    pos = series.index.searchsorted(ts)
    if pos >= len(series) or series.index[pos] - ts > pd.Timedelta(minutes=tolerance_min):
        return None
    return float(series.iloc[pos])


def _tokyo(d: date, hh: int, mm: int) -> pd.Timestamp:
    return pd.Timestamp(f"{d} {hh:02d}:{mm:02d}", tz=TOKYO)


# ------------------------------------------------------------ Regeln

def gotobi_days(first_year: int, last_year: int) -> set[date]:
    out = set()
    for y in range(first_year, last_year + 1):
        for m in range(1, 13):
            last = calendar.monthrange(y, m)[1]
            for d in (5, 10, 15, 20, 25, last):
                x = date(y, m, d)
                while x.weekday() >= 5:
                    x -= timedelta(days=1)
                out.add(x)
    return out


def ose_close(d: date) -> tuple[int, int]:
    return (15, 45) if d >= OSE_CLOSE_CHANGE else (15, 15)


def nikkei_trades(bid: pd.Series, start: date, end: date, cost_per_side: float, jpy_rate: float,
                  now: pd.Timestamp) -> list[dict]:
    """Nächte mit Ausstiegstag in [start, end]; nur abgeschlossene (Ausstieg vor `now`).
    Handelstage = Werktage ohne japanischen Börsenfeiertag mit Kurs zur Schluss-
    UND Eröffnungszeit."""
    days = sorted({d for d in bid.index.tz_convert(TOKYO).date
                   if d.weekday() < 5 and d not in JP_MARKET_HOLIDAYS})
    trading = []
    for d in days:
        c, o = price_at(bid, _tokyo(d, *ose_close(d))), price_at(bid, _tokyo(d, 8, 45))
        if c is not None and o is not None:
            trading.append((d, c, o))
    rows = []
    for (a, close_a, _), (b, _, open_b) in zip(trading[:-1], trading[1:]):
        exit_ts = _tokyo(b, 8, 45)
        if not (start <= b <= end) or exit_ts >= now:
            continue
        net = open_b / close_a - 1 - 2 * cost_per_side - max(jpy_rate, 0.0) / 360 * (b - a).days
        rows.append({"strategy": "nikkei_night", "date": b.isoformat(),
                     "entry_time": _tokyo(a, *ose_close(a)).isoformat(), "entry_price": close_a,
                     "exit_time": exit_ts.isoformat(), "exit_price": open_b, "net_bp": round(net * 1e4, 3)})
    return rows


def gotobi_trades(bid: pd.Series, ask: pd.Series, start: date, end: date, commission: float,
                  now: pd.Timestamp) -> list[dict]:
    rows = []
    for d in sorted(gotobi_days(start.year, end.year)):
        exit_ts = _tokyo(d, 9, 55)
        if not (start <= d <= end) or exit_ts >= now:
            continue
        entry_ts = _tokyo(d, 5, 0)
        buy, sell = price_at(ask, entry_ts), price_at(bid, exit_ts)
        if buy is None or sell is None:
            logger.warning("Gotobi %s: keine Kurse um 05:00/09:55 JST (Feiertag/Datenlücke).", d)
            continue
        net = sell / buy - 1 - 2 * commission
        rows.append({"strategy": "gotobi", "date": d.isoformat(), "entry_time": entry_ts.isoformat(),
                     "entry_price": buy, "exit_time": exit_ts.isoformat(), "exit_price": sell,
                     "net_bp": round(net * 1e4, 3)})
    return rows


# ------------------------------------------------------------ Ledger

def read_ledger(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def update_ledger(path: Path, rows: list[dict]) -> int:
    """Fügt Trades ein bzw. ersetzt gleiche (Strategie, Datum). Gibt die Zahl neuer Zeilen zurück."""
    existing = {(r["strategy"], r["date"]): r for r in read_ledger(path)}
    new = sum((r["strategy"], r["date"]) not in existing for r in rows)
    for r in rows:
        existing[(r["strategy"], r["date"])] = {k: r[k] for k in LEDGER_FIELDS}
    ordered = sorted(existing.values(), key=lambda r: (r["date"], r["strategy"]))
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=LEDGER_FIELDS)
        w.writeheader()
        w.writerows(ordered)
    tmp.replace(path)
    return new


def summarize(path: Path) -> str:
    rows = read_ledger(path)
    if not rows:
        return f"Noch keine Trades in {path}."
    lines = [f"Vorwärtstest ({path})", ""]
    for strat in ("nikkei_night", "gotobi"):
        bp = [float(r["net_bp"]) for r in rows if r["strategy"] == strat]
        if not bp:
            lines.append(f"{strat}: noch keine Trades")
            continue
        n = len(bp)
        mean = sum(bp) / n
        sd = math.sqrt(sum((x - mean) ** 2 for x in bp) / (n - 1)) if n > 1 else float("nan")
        t = mean / sd * math.sqrt(n) if n > 1 and sd > 0 else float("nan")
        total = math.prod(1 + x / 1e4 for x in bp) - 1
        dates = [r["date"] for r in rows if r["strategy"] == strat]
        lines.append(f"{strat}: {n} Trades ({min(dates)} bis {max(dates)}), Ø {mean:+.2f} bp "
                     f"(Backtest {EXPECTED_BP[strat]:+.2f} bp), Treffer {sum(x > 0 for x in bp) / n:.0%}, "
                     f"t {t:.2f}, kumuliert {total:+.2%} (1x)")
    lines += ["", "Hinweis: Ein Jahr Nikkei-Nacht (~245 Trades) ergibt bei Ø 4 bp und ~40 bp Streuung "
              "nur t ~1,6; Gotobi (~70 Trades/Jahr) braucht mehrere Jahre für Signifikanz."]
    return "\n".join(lines)


# ------------------------------------------------------------ Lauf

def run(cfg: ForwardConfig, today: date | None = None, now: pd.Timestamp | None = None) -> str:
    today = today or datetime.now(timezone.utc).date()
    now = now or pd.Timestamp.now(tz="UTC")
    start = max(cfg.first_day - timedelta(days=5), today - timedelta(days=cfg.lookback_days))
    end = today + timedelta(days=1)
    nk = load_open_prices(fetch_minutes("jpnidxjpy", "bid", start, end, cfg.data_dir))
    fx_bid = load_open_prices(fetch_minutes("usdjpy", "bid", start, end, cfg.data_dir))
    fx_ask = load_open_prices(fetch_minutes("usdjpy", "ask", start, end, cfg.data_dir))
    rows = nikkei_trades(nk, cfg.first_day, today, cfg.nikkei_cost_per_side, cfg.jpy_rate, now)
    rows += gotobi_trades(fx_bid, fx_ask, cfg.first_day, today, cfg.gotobi_commission, now)
    new = update_ledger(cfg.ledger, rows)
    logger.info("Vorwärtstest: %d Trades berechnet, %d neu.", len(rows), new)
    return summarize(cfg.ledger)

"""Vorwärtstest pelosi_copy (Runde 141): Aktienkäufe von Nancy Pelosi ab Meldedatum nachhandeln -- nur Papier.

Regeln (eingefroren 2026-10-04, wie Backtest research/scripts/r141.py):
- Quelle: amtliche House-Clerk-Meldungen (Periodic Transaction Reports, nur elektronische, DocID beginnt mit 2),
  Meldedatum >= first_day.
- Signal: jede Kaufzeile ("P") mit Wertpapierart [ST] Aktie oder [OP] Option (dann Basiswert als Aktie), je Meldung
  und Ticker einmal. Verkäufe werden ignoriert.
- Einstieg Schlusskurs des 2. Handelstags nach dem Meldedatum, Ausstieg 252 Handelstage später; 0,1 % Kosten je Seite.
- Bindende Auswertung (2029-10-01): Depot gleichgewichtet über offene Signale (ohne Signal SPY), monatliche
  Überrendite ggü. SPY ab first_day: Rendite > SPY und t >= 2 (eigene Familie, eine Hypothese).
"""

from __future__ import annotations

import csv
import io
import logging
import math
import re
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

BASE = "https://disclosures-clerk.house.gov/public_disc"
FIELDS = ["doc", "filing_date", "ticker", "entry_date", "entry", "exit_date", "exit", "status", "ret", "spy_ret",
          "excess"]
EXPECTED_EXCESS_PCT = 11.1        # Backtest 2015-2025: Ø 12-Monats-Überrendite je Trade ggü. SPY nach Kosten
HOLD = 252
COST = 0.001
PAT = re.compile(
    r"\(\s*([A-Za-z][A-Za-z.\- ]{0,8}?)\s*\)\s*(?:\[\s*([A-Za-z]{2})\s*\])?\s*"
    r"(P|S|E|p|s|e)(?:\s*\(\s*partial\s*\))?\s*"
    r"(\d{1,2}/\d{1,2}\s*/\s*\d{4})\s*(\d{1,2}/\d{1,2}\s*/\s*\d{4})\s*\$\s*([\d,]+)", re.S)


@dataclass(frozen=True)
class PelosiConfig:
    first_day: date = date(2026, 10, 5)
    last: str = "Pelosi"
    first: str = "Nancy"
    ledger: Path = Path("forward_pelosi.csv")
    cache: Path = Path("data_cache/forward/pelosi")


def parse_buys(text: str) -> list[str]:
    """Ticker aller Kaufzeilen (Aktie oder Option) einer Meldung, Yahoo-Schreibweise, ohne Doppelte."""
    out = []
    for m in PAT.finditer(re.sub(r"\s+", " ", text)):
        tick, tag, typ = m.group(1), (m.group(2) or "").upper(), m.group(3).upper()
        if typ != "P" or (tag and tag not in ("ST", "OP")):
            continue
        t = tick.replace(" ", "").upper().replace(".", "-")
        if t not in out:
            out.append(t)
    return out


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def filings(cfg: PelosiConfig, today: date, fetch=_get) -> list[dict]:
    """Elektronische PTR-Meldungen der Person ab first_day (Index des laufenden und ggf. Vorjahres)."""
    cfg.cache.mkdir(parents=True, exist_ok=True)
    out = []
    for y in range(max(cfg.first_day.year, today.year - 1), today.year + 1):
        raw = fetch(f"{BASE}/financial-pdfs/{y}FD.zip")
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            txt = z.read(f"{y}FD.txt").decode("utf-8", "replace")
        for r in csv.DictReader(io.StringIO(txt), delimiter="\t"):
            if (r["Last"] == cfg.last and cfg.first in r["First"] and r["FilingType"] == "P"
                    and r["DocID"].startswith("2")):
                fd = datetime.strptime(r["FilingDate"], "%m/%d/%Y").date()
                if fd >= cfg.first_day:
                    out.append({"doc": r["DocID"], "year": y, "filing_date": fd})
    return out


def filing_text(cfg: PelosiConfig, f: dict, fetch=_get) -> str:
    path = cfg.cache / f"{f['doc']}.txt"
    if path.exists():
        return path.read_text(encoding="utf-8")
    import pypdf

    raw = fetch(f"{BASE}/ptr-pdfs/{f['year']}/{f['doc']}.pdf")
    text = "\n".join(p.extract_text() or "" for p in pypdf.PdfReader(io.BytesIO(raw)).pages)
    path.write_text(text, encoding="utf-8")
    return text


def build_rows(signals: list[dict], spy: pd.Series, price) -> list[dict]:
    """Ledger-Zeilen aus Signalen; price(ticker) -> Serie (Tagesschluss, DatetimeIndex) oder None."""
    days = spy.index
    rows = []
    for s in signals:
        row = dict.fromkeys(FIELDS, "") | {"doc": s["doc"], "filing_date": s["filing_date"].isoformat(),
                                           "ticker": s["ticker"], "status": "wartet"}
        i = days.searchsorted(pd.Timestamp(s["filing_date"]), side="right") + 1
        if pd.Timestamp(s["filing_date"]) < days[0]:
            row["status"] = "kein Kurs"
        elif i < len(days):
            p = price(s["ticker"])
            if p is None or p.index[0] > days[i] or p.index[-1] < days[i]:
                row["status"] = "kein Kurs"
            else:
                p = p.reindex(days).ffill()
                j = min(i + HOLD, len(days) - 1)
                closed = i + HOLD <= len(days) - 1
                ret = p.iloc[j] / p.iloc[i] * (1 - COST) ** (2 if closed else 1) - 1
                row.update(entry_date=days[i].date().isoformat(), entry=round(float(p.iloc[i]), 4),
                           exit_date=days[j].date().isoformat(), exit=round(float(p.iloc[j]), 4),
                           status="abgeschlossen" if closed else "offen", ret=round(float(ret), 6),
                           spy_ret=round(float(spy.iloc[j] / spy.iloc[i] - 1), 6))
                row["excess"] = round(row["ret"] - row["spy_ret"], 6)
        rows.append(row)
    return rows


def portfolio_excess(rows: list[dict], spy: pd.Series, price, start: date) -> tuple[pd.Series, float]:
    """Bindende Kennzahl: monatliche Überrendite des gleichgewichteten Depots ggü. SPY ab start, und ihr t-Wert."""
    days = spy.index
    num = pd.Series(0.0, index=days)
    den = pd.Series(0.0, index=days)
    for r in rows:
        if r["entry_date"] == "":
            continue
        a, b = days.searchsorted(pd.Timestamp(r["entry_date"])), days.searchsorted(pd.Timestamp(r["exit_date"]))
        ret = price(r["ticker"]).reindex(days[a:b + 1]).ffill().pct_change().iloc[1:].fillna(0.0)
        if ret.empty:
            continue
        ret.iloc[0] -= COST
        if r["status"] == "abgeschlossen":
            ret.iloc[-1] -= COST
        num[ret.index] += ret.values
        den[ret.index] += 1
    spy_r = spy.pct_change().fillna(0.0)
    port = (num / den.where(den > 0)).fillna(spy_r)
    port, spy_r = port[port.index >= pd.Timestamp(start)], spy_r[spy_r.index >= pd.Timestamp(start)]
    ex = ((1 + port).resample("ME").prod() - (1 + spy_r).resample("ME").prod()).dropna()
    sd = ex.std(ddof=1) if len(ex) > 1 else 0.0
    t = ex.mean() / sd * math.sqrt(len(ex)) if sd > 0 else float("nan")
    return ex, t


def write_ledger(path: Path, rows: list[dict]) -> None:
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    tmp.replace(path)


def read_ledger(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def summarize(rows: list[dict]) -> str:
    if not rows:
        return "pelosi_copy: noch keine Meldung seit Start"
    done = [float(r["excess"]) * 100 for r in rows if r["status"] == "abgeschlossen"]
    live = [float(r["excess"]) * 100 for r in rows if r["status"] == "offen"]
    txt = f"pelosi_copy: {len(rows)} Signale, {len(live)} offen"
    if live:
        txt += f" (Ø bisher {sum(live) / len(live):+.1f} % ggü. SPY)"
    if done:
        txt += f", {len(done)} abgeschlossen Ø {sum(done) / len(done):+.1f} % ggü. SPY (Erw. {EXPECTED_EXCESS_PCT:+.1f})"
    return txt


def _yahoo(ticker: str, start: date) -> pd.Series | None:
    from tradingbot.forward_test import fetch_daily_yahoo

    try:
        s = fetch_daily_yahoo(ticker, start, date.today())
    except Exception:  # noqa: BLE001 -- unbekannter/delisteter Ticker
        return None
    s.index = pd.to_datetime(s.index)
    return s


def run(cfg: PelosiConfig = PelosiConfig(), today: date | None = None, notifier=None) -> str:
    today = today or datetime.now(timezone.utc).date()
    known = {(r["doc"], r["ticker"]) for r in read_ledger(cfg.ledger)}
    sigs = [{"doc": f["doc"], "filing_date": f["filing_date"], "ticker": t}
            for f in filings(cfg, today) for t in parse_buys(filing_text(cfg, f))]
    cache: dict[str, pd.Series | None] = {}

    def price(t):
        if t not in cache:
            cache[t] = _yahoo(t, cfg.first_day - timedelta(days=30))
        return cache[t]

    rows = build_rows(sigs, price("SPY"), price)
    write_ledger(cfg.ledger, rows)
    new = [r for r in rows if (r["doc"], r["ticker"]) not in known]
    if new and notifier:
        notifier.send("Pelosi-Kauf gemeldet", "\n".join(
            f"{r['ticker']} (Meldung {r['filing_date']}): Papier-Einstieg zum Schlusskurs am 2. Handelstag danach, "
            f"12 Monate halten" for r in new), tags="classical_building")
    logger.info("pelosi_copy: %d Meldungen seit %s, %d Signale, %d neu.", len({s['doc'] for s in sigs}),
                cfg.first_day, len(rows), len(new))
    return summarize(rows)

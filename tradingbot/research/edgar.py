"""Runde 11: SEC EDGAR -- Insiderkäufe (X) und Earnings-Drift (Y), siehe
research/PROTOCOL.md.

Daten (kostenlos, ohne Schlüssel):
- Insider Transactions Data Sets (Formulare 3/4/5, quartalsweise ZIP-Dateien)
- data.sec.gov/submissions/CIK##########.json (8-K-Meldungen mit Items)
SEC-Vorgabe: höchstens 10 Anfragen je Sekunde -- hier max. ~8.
"""

from __future__ import annotations

import io
import json
import logging
import time
import urllib.error
import urllib.request
import zipfile
from datetime import date, time as dtime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

EDGAR_DIR = Path("data_cache") / "edgar"
_UA = {"User-Agent": "tradingbot-research-script"}
_INSIDER_URL = "https://www.sec.gov/files/structureddata/data/insider-transactions-data-sets/{q}_form345.zip"
_NY = ZoneInfo("America/New_York")
MIN_VALUE = 25_000


def _get(url: str, timeout: int = 120) -> bytes:
    for attempt in range(5):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=_UA), timeout=timeout) as r:
                data = r.read()
            time.sleep(0.13)
            return data
        except urllib.error.HTTPError as e:
            if e.code in (429, 503) and attempt < 4:
                time.sleep(2 ** attempt)
                continue
            raise
    raise RuntimeError(url)


def quarters(start: str = "2015q4", end: str = "2025q3") -> list[str]:
    y, q = int(start[:4]), int(start[-1])
    out = []
    while f"{y}q{q}" <= end:
        out.append(f"{y}q{q}")
        y, q = (y + 1, 1) if q == 4 else (y, q + 1)
    return out


def _parse_quarter(raw: bytes) -> pd.DataFrame:
    z = zipfile.ZipFile(io.BytesIO(raw))

    def tsv(name, cols):
        return pd.read_csv(z.open(name), sep="\t", usecols=cols, dtype=str, on_bad_lines="skip")

    sub = tsv("SUBMISSION.tsv", ["ACCESSION_NUMBER", "FILING_DATE", "DOCUMENT_TYPE", "ISSUERCIK",
                                 "ISSUERTRADINGSYMBOL"])
    own = tsv("REPORTINGOWNER.tsv", ["ACCESSION_NUMBER", "RPTOWNERCIK", "RPTOWNER_RELATIONSHIP"])
    tr = tsv("NONDERIV_TRANS.tsv", ["ACCESSION_NUMBER", "TRANS_CODE", "TRANS_SHARES", "TRANS_PRICEPERSHARE",
                                    "TRANS_ACQUIRED_DISP_CD"])
    sub = sub[sub["DOCUMENT_TYPE"] == "4"]
    tr = tr[(tr["TRANS_CODE"] == "P") & (tr["TRANS_ACQUIRED_DISP_CD"] == "A")].copy()
    tr["value"] = pd.to_numeric(tr["TRANS_SHARES"], errors="coerce") * pd.to_numeric(
        tr["TRANS_PRICEPERSHARE"], errors="coerce")
    val = tr.groupby("ACCESSION_NUMBER")["value"].sum().rename("value")
    rel = own["RPTOWNER_RELATIONSHIP"].fillna("")
    own = own[rel.str.contains("Director|Officer", case=False)].drop_duplicates("ACCESSION_NUMBER")
    df = sub.merge(val, on="ACCESSION_NUMBER").merge(own, on="ACCESSION_NUMBER")
    df["filing_date"] = pd.to_datetime(df["FILING_DATE"], format="%d-%b-%Y", errors="coerce").dt.date
    df["symbol"] = df["ISSUERTRADINGSYMBOL"].fillna("").str.upper().str.strip()
    df = df[(df["value"] >= MIN_VALUE) & df["filing_date"].notna() & (df["symbol"] != "")]
    return df.rename(columns={"ISSUERCIK": "issuer_cik", "RPTOWNERCIK": "owner_cik"})[
        ["filing_date", "symbol", "issuer_cik", "owner_cik", "value"]]


def insider_purchases(base: Path = EDGAR_DIR) -> pd.DataFrame:
    """Alle offenen Marktkäufe von Officers/Directors >= MIN_VALUE, gecacht."""
    out = base / "insider_purchases.pkl"
    if out.exists():
        return pd.read_pickle(out)
    base.mkdir(parents=True, exist_ok=True)
    frames = []
    for q in quarters():
        path = base / f"{q}_form345.zip"
        if not path.exists():
            logger.info("Lade Insider-Daten %s ...", q)
            path.write_bytes(_get(_INSIDER_URL.format(q=q)))
        frames.append(_parse_quarter(path.read_bytes()))
    df = pd.concat(frames).drop_duplicates().sort_values("filing_date").reset_index(drop=True)
    df.to_pickle(out)
    return df


def symbol_to_cik(purchases: pd.DataFrame) -> dict[str, str]:
    """Ticker -> CIK: aktuelle SEC-Tickerliste, überschrieben durch die
    historischen Kürzel aus den Insider-Daten (auch delistete Firmen)."""
    mapping = {}
    cur = json.loads(_get("https://www.sec.gov/files/company_tickers.json"))
    for v in cur.values():
        mapping[v["ticker"].upper()] = str(v["cik_str"]).zfill(10)
    for sym, cik in purchases.sort_values("filing_date")[["symbol", "issuer_cik"]].itertuples(index=False):
        mapping[sym] = str(cik).zfill(10)
    return mapping


def earnings_8k(cik: str, base: Path = EDGAR_DIR) -> pd.DataFrame:
    """8-K-Meldungen mit Item 2.02: acceptance (NY-Zeit) je CIK, gecacht."""
    path = base / "8k" / f"{cik}.pkl"
    if path.exists():
        return pd.read_pickle(path)
    rows = []
    try:
        sub = json.loads(_get(f"https://data.sec.gov/submissions/CIK{cik}.json"))
    except urllib.error.HTTPError:
        sub = None
    if sub:
        pages = [sub["filings"]["recent"]]
        for f in sub["filings"].get("files", []):
            if f.get("filingTo", "9999") >= "2015-12-01":
                pages.append(json.loads(_get(f"https://data.sec.gov/submissions/{f['name']}")))
        for p in pages:
            for form, acc, items in zip(p["form"], p["acceptanceDateTime"], p["items"]):
                if form == "8-K" and "2.02" in (items or ""):
                    ts = pd.Timestamp(acc)
                    ts = ts.tz_localize("UTC") if ts.tzinfo is None else ts
                    rows.append(ts.tz_convert(_NY))
    df = pd.DataFrame({"accepted": sorted(set(rows))})
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_pickle(path)
    return df


def event_day(accepted: pd.Timestamp, trading_days) -> date | None:
    """Vor 9:30 ET gemeldet -> Handelstag der Meldung, sonst nächster Handelstag."""
    days = pd.Index(trading_days)
    d = accepted.date()
    side = "right" if accepted.time() >= dtime(9, 30) else "left"
    pos = days.searchsorted(d, side=side)
    return days[pos] if pos < len(days) else None


# ------------------------------------------------------------ Ereignis-Portfolio

def event_weights(close: pd.DataFrame, events: list[tuple[str, date]], hold: int) -> pd.DataFrame:
    """Kauf zum Schluss des Einstiegstags, `hold` Handelstage halten; alle
    aktiven Positionen gleichgewichtet. Ein neues Ereignis für ein Symbol mit
    aktiver Position wird ignoriert. Ohne Kurs (Delisting) fällt die Position weg."""
    days = pd.Index(close.index)
    col = {s: i for i, s in enumerate(close.columns)}
    active = np.zeros(close.shape, dtype=bool)
    last_entry: dict[str, int] = {}
    for sym, entry in sorted(events, key=lambda e: e[1]):
        if sym not in col:
            continue
        t = days.searchsorted(entry)
        if t >= len(days) or days[t] != entry:
            continue
        if sym in last_entry and t < last_entry[sym] + hold:
            continue
        last_entry[sym] = t
        active[t:t + hold, col[sym]] = True
    active &= close.notna().to_numpy()
    n = active.sum(axis=1, keepdims=True)
    W = np.where(n > 0, active / np.maximum(n, 1), 0.0)
    return pd.DataFrame(W, index=close.index, columns=close.columns)


def insider_events(purchases: pd.DataFrame, trading_days, cluster: bool) -> list[tuple[str, date]]:
    """Einstieg = Handelstag NACH dem Meldetag. cluster: Ereignis erst, wenn
    innerhalb von 30 Kalendertagen ein zweiter, anderer Insider kauft."""
    days = pd.Index(trading_days)
    out = []
    for sym, g in purchases.sort_values("filing_date").groupby("symbol"):
        rows = list(g[["filing_date", "owner_cik"]].itertuples(index=False))
        for i, (fd, owner) in enumerate(rows):
            if cluster and not any(o != owner and 0 <= (fd - d2).days <= 30 for d2, o in rows[:i]):
                continue
            pos = days.searchsorted(fd, side="right")
            if pos < len(days):
                out.append((sym, days[pos]))
    return out


def earnings_events(close: pd.DataFrame, spy: pd.Series, announcements: dict[str, list],
                    threshold: float) -> list[tuple[str, date]]:
    """Überrendite am Ereignistag > threshold -> Einstieg zum Schluss des Folgetags."""
    days = pd.Index(close.index)
    spy_ret = spy.reindex(close.index).pct_change()
    out = []
    for sym, event_days in announcements.items():
        if sym not in close.columns:
            continue
        ret = close[sym].pct_change(fill_method=None)
        for d in event_days:
            t = days.searchsorted(d)
            if t == 0 or t + 1 >= len(days) or days[t] != d:
                continue
            ar = ret.iloc[t] - spy_ret.iloc[t]
            if np.isfinite(ar) and ar > threshold:
                out.append((sym, days[t + 1]))
    return out

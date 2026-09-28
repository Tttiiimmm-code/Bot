"""Nachrichten-Einschätzung per LLM für den Momentum-Bot (zunächst nur Schattenmodus).

Für jedes neue Kandidaten-Symbol wird EINMAL pro Handelstag gesammelt:
- Alpaca-News (Überschrift + Zusammenfassung) der letzten `news_lookback_hours`,
- SEC-Meldungen der letzten 14 Tage (8-K, Emissionsformulare S-1/S-3/424B*, 13D/G, ...),
und ein LLM (Anthropic Messages API) um eine strikte JSON-Einschätzung gebeten:
Katalysator, Richtung, Verwässerungsrisiko, Konfidenz, Kurzbegründung.

Schattenmodus (Standard): Die Einschätzung wird nur protokolliert (news_intel.csv und Log),
der Bot handelt unverändert. Erst wenn die Auswertung zeigt, dass die Einschätzung den
Tradeausgang vorhersagt, soll sie als Filter dienen (`filter_mode="block_dilution"`).

Fehler (fehlender Key, Netz, Parserfehler) werden nur geloggt und blockieren nie den Handel.
Der API-Key kommt aus ANTHROPIC_API_KEY (.env) und wird nie geloggt.
"""

from __future__ import annotations

import csv
import json
import logging
import os
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

CATALYSTS = (
    "earnings", "guidance", "fda_clinical", "contract_partnership", "m_and_a", "offering_dilution",
    "reverse_split", "legal_regulatory", "analyst", "sector_sympathy", "social_meme", "no_news", "other",
)
DIRECTIONS = ("positive", "negative", "mixed", "unclear")
DILUTION = ("low", "medium", "high")
FIELDS = ["date", "time_utc", "symbol", "price", "pct_change", "rel_volume", "n_news", "n_filings",
          "catalyst", "direction", "dilution_risk", "confidence", "summary", "model", "error"]
_SEC_FORMS = ("8-K", "6-K", "S-1", "S-1/A", "S-3", "S-3/A", "F-1", "F-3", "424B1", "424B2", "424B3",
              "424B4", "424B5", "SC 13D", "SC 13G", "10-Q", "10-K")
_PROMPT = """You are a research assistant for an intraday momentum trader of US small caps.
The stock {symbol} is up {pct:.1f}% today at ${price:.2f} on {rvol:.1f}x relative volume.
Classify WHY it is moving, using only the material below. If nothing explains the move, use "no_news".

NEWS (newest first):
{news}

SEC FILINGS (last 14 days):
{filings}

Answer with ONE JSON object and nothing else:
{{"catalyst": one of {catalysts},
 "direction": one of {directions} (is the news fundamentally good or bad for shareholders),
 "dilution_risk": one of {dilution} (share offering, ATM program, warrants, S-1/S-3/424B filings -> medium/high),
 "confidence": number 0..1,
 "summary": "max 200 characters"}}"""


@dataclass
class NewsIntelConfig:
    enabled: bool = False
    filter_mode: str = "off"  # "off" (Schattenmodus) | "block_dilution"
    model: str = "claude-haiku-4-5-20251001"
    news_lookback_hours: int = 24
    max_news: int = 8
    log_path: Path = Path("news_intel.csv")
    timeout_seconds: float = 30.0
    max_calls_per_day: int = 200  # Kostenbremse


@dataclass
class Assessment:
    symbol: str
    catalyst: str = "other"
    direction: str = "unclear"
    dilution_risk: str = "low"
    confidence: float = 0.0
    summary: str = ""
    n_news: int = 0
    n_filings: int = 0
    error: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def blocks_entry_under_dilution_filter(self) -> bool:
        return self.catalyst == "offering_dilution" or self.dilution_risk == "high"


def parse_assessment(symbol: str, text: str) -> Assessment:
    """LLM-Antwort -> Assessment; unbekannte Werte werden auf sichere Standardwerte gesetzt."""
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return Assessment(symbol, error="keine JSON-Antwort")
    try:
        raw = json.loads(text[start:end + 1])
    except json.JSONDecodeError as e:
        return Assessment(symbol, error=f"JSON-Fehler: {e.msg}")
    cat = str(raw.get("catalyst", "other")).strip().lower()
    dirn = str(raw.get("direction", "unclear")).strip().lower()
    dil = str(raw.get("dilution_risk", "low")).strip().lower()
    try:
        conf = min(max(float(raw.get("confidence", 0.0)), 0.0), 1.0)
    except (TypeError, ValueError):
        conf = 0.0
    return Assessment(
        symbol,
        catalyst=cat if cat in CATALYSTS else "other",
        direction=dirn if dirn in DIRECTIONS else "unclear",
        dilution_risk=dil if dil in DILUTION else "low",
        confidence=conf,
        summary=str(raw.get("summary", ""))[:200].replace("\n", " "),
    )


def call_anthropic(prompt: str, model: str, api_key: str, timeout: float) -> str:
    body = json.dumps({"model": model, "max_tokens": 300,
                       "messages": [{"role": "user", "content": prompt}]}).encode()
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages", data=body, method="POST",
        headers={"x-api-key": api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        res = json.load(r)
    return "".join(part.get("text", "") for part in res.get("content", []) if part.get("type") == "text")


class NewsIntel:
    """Sammelt und bewertet Nachrichten je Symbol; Aufrufe laufen in einem Hintergrund-Thread."""

    def __init__(self, config: NewsIntelConfig, news_client=None, *, llm=call_anthropic,
                 sec_user_agent: str = "tradingbot-research-script"):
        self.config = config
        self.news_client = news_client
        self._llm = llm
        self._ua = sec_user_agent
        self._api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
        self._cache: dict[tuple[date, str], Assessment] = {}
        self._pending: set[tuple[date, str]] = set()
        self._calls: dict[date, int] = {}
        self._lock = threading.Lock()
        self._pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="news-intel")
        self._cik: dict[str, str] | None = None
        if config.enabled and not self._api_key:
            logger.warning("News-Intel aktiviert, aber ANTHROPIC_API_KEY fehlt in .env -- es werden keine "
                           "LLM-Einschätzungen erstellt (der Bot handelt normal weiter).")

    # ---------------------------------------------------------- öffentlich
    def request(self, symbol: str, price: float, pct_change: float, rel_volume: float,
                now: datetime | None = None) -> None:
        """Einschätzung im Hintergrund anstoßen (einmal je Symbol und Tag)."""
        if not self.config.enabled or not self._api_key:
            return
        now = now or datetime.now(timezone.utc)
        key = (now.date(), symbol)
        with self._lock:
            if key in self._cache or key in self._pending:
                return
            if self._calls.get(key[0], 0) >= self.config.max_calls_per_day:
                return
            self._calls[key[0]] = self._calls.get(key[0], 0) + 1
            self._pending.add(key)
        self._pool.submit(self._run, key, price, pct_change, rel_volume, now)

    def get(self, symbol: str, now: datetime | None = None) -> Assessment | None:
        now = now or datetime.now(timezone.utc)
        with self._lock:
            return self._cache.get((now.date(), symbol))

    def should_block_entry(self, symbol: str, now: datetime | None = None) -> bool:
        """Nur im Filtermodus: Einstieg ablehnen, wenn eine Einschätzung Verwässerung meldet.
        Ohne (fertige) Einschätzung wird nie blockiert."""
        if self.config.filter_mode != "block_dilution":
            return False
        a = self.get(symbol, now)
        return bool(a and not a.error and a.blocks_entry_under_dilution_filter)

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)

    # ---------------------------------------------------------- intern
    def _run(self, key, price, pct_change, rel_volume, now) -> None:
        symbol = key[1]
        try:
            news = self._fetch_news(symbol, now)
            filings = self._fetch_filings(symbol, now)
            prompt = _PROMPT.format(
                symbol=symbol, pct=pct_change, price=price, rvol=rel_volume or 0.0,
                news="\n".join(news) or "(none)", filings="\n".join(filings) or "(none)",
                catalysts=list(CATALYSTS), directions=list(DIRECTIONS), dilution=list(DILUTION),
            )
            text = self._llm(prompt, self.config.model, self._api_key, self.config.timeout_seconds)
            a = parse_assessment(symbol, text)
            a.n_news, a.n_filings = len(news), len(filings)
        except Exception as e:  # nie den Handel stören
            a = Assessment(symbol, error=f"{type(e).__name__}: {e}"[:200])
        with self._lock:
            self._cache[key] = a
            self._pending.discard(key)
        logger.info("News-Intel %s: Katalysator=%s, Richtung=%s, Verwässerung=%s, Konfidenz=%.2f, %s%s",
                    symbol, a.catalyst, a.direction, a.dilution_risk, a.confidence, a.summary,
                    f" [Fehler: {a.error}]" if a.error else "")
        self._append_log(now, symbol, price, pct_change, rel_volume, a)

    def _fetch_news(self, symbol: str, now: datetime) -> list[str]:
        if self.news_client is None:
            return []
        from alpaca.data.requests import NewsRequest
        req = NewsRequest(symbols=symbol, start=now - timedelta(hours=self.config.news_lookback_hours),
                          limit=self.config.max_news)
        items = self.news_client.get_news(req).data.get("news", [])
        out = []
        for it in items[: self.config.max_news]:
            ts = getattr(it, "created_at", None)
            summary = (getattr(it, "summary", "") or "").strip().replace("\n", " ")[:400]
            line = f"- [{ts:%Y-%m-%d %H:%M} UTC] {it.headline}" if ts else f"- {it.headline}"
            out.append(line + (f" -- {summary}" if summary else ""))
        return out

    def _sec_get(self, url: str) -> dict:
        req = urllib.request.Request(url, headers={"User-Agent": self._ua})
        with urllib.request.urlopen(req, timeout=self.config.timeout_seconds) as r:
            return json.load(r)

    def _fetch_filings(self, symbol: str, now: datetime) -> list[str]:
        if self._cik is None:
            try:
                raw = self._sec_get("https://www.sec.gov/files/company_tickers.json")
                self._cik = {v["ticker"].upper(): str(v["cik_str"]).zfill(10) for v in raw.values()}
            except Exception:
                self._cik = {}
        cik = self._cik.get(symbol.upper())
        if not cik:
            return []
        time.sleep(0.15)  # SEC: max. 10 Anfragen/s
        rec = self._sec_get(f"https://data.sec.gov/submissions/CIK{cik}.json")["filings"]["recent"]
        cutoff = (now - timedelta(days=14)).date().isoformat()
        n = len(rec["form"])
        descs = rec.get("primaryDocDescription") or [""] * n
        items_all = rec.get("items") or [""] * n
        out = []
        for form, fd, desc, items in zip(rec["form"], rec["filingDate"], descs, items_all):
            if fd < cutoff:
                break
            if form in _SEC_FORMS:
                out.append(f"- {fd} {form}" + (f" items {items}" if items else "") + (f" ({desc})" if desc else ""))
        return out[:15]

    def _append_log(self, now, symbol, price, pct_change, rel_volume, a: Assessment) -> None:
        path = self.config.log_path
        try:
            with self._lock:
                new = not path.exists()
                with path.open("a", newline="", encoding="utf-8") as f:
                    w = csv.writer(f)
                    if new:
                        w.writerow(FIELDS)
                    w.writerow([now.date().isoformat(), now.strftime("%H:%M:%S"), symbol, f"{price:.4f}",
                                f"{pct_change:.2f}", f"{(rel_volume or 0):.2f}", a.n_news, a.n_filings, a.catalyst,
                                a.direction, a.dilution_risk, f"{a.confidence:.2f}", a.summary, self.config.model,
                                a.error])
        except OSError:
            logger.exception("news_intel.csv konnte nicht geschrieben werden.")

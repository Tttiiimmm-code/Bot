"""Übersicht aller Vorwärtstests nach der gemeinsamen Auswertungsregel (research/PROTOCOL.md, 2026-10-02):
K = 11 Hypothesen, einseitiger t-Test p < 0,05 / 11, Ø >= 50 % der Backtest-Erwartung, EIN bindender Blick
zum festen Termin. Alles hier ist Zwischenstand und NUR Information -- keine Entscheidung vor dem Termin
(Ausnahme: Abbruch wegen Aussichtslosigkeit nach der Hälfte der Laufzeit, Ø < 0 und t <= -1,5).
"""

from __future__ import annotations

import csv
import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path

K = 11
ALPHA = 0.05 / K


@dataclass(frozen=True)
class Tracker:
    name: str
    start: date
    min_n: int
    eval_date: date
    unit: str                 # Anzeige-Einheit der Beobachtung
    expected: float | None    # Backtest-Erwartung je Beobachtung (gleiche Einheit), None = siehe Hinweis
    source: str               # Ledger-Datei bzw. Art der Daten


TRACKERS = (
    Tracker("nikkei_night", date(2026, 9, 28), 200, date(2027, 10, 1), "bp", 4.21, "forward_trades.csv"),
    Tracker("gotobi", date(2026, 9, 28), 60, date(2027, 10, 1), "bp", 1.00, "forward_trades.csv"),
    Tracker("gotobi_eurjpy", date(2026, 9, 28), 60, date(2027, 10, 1), "bp", 1.84, "forward_trades.csv"),
    Tracker("bond_month_end", date(2026, 9, 28), 24, date(2028, 10, 1), "bp", 22.3, "forward_trades.csv"),
    Tracker("mid_month_spy", date(2026, 9, 28), 24, date(2028, 10, 1), "bp", 5.4, "forward_trades.csv"),
    Tracker("mid_month_qqq", date(2026, 9, 28), 24, date(2028, 10, 1), "bp", 33.7, "forward_trades.csv"),
    Tracker("orb_or5", date(2026, 10, 1), 200, date(2027, 10, 1), "R/Tag", None, "forward_orb.csv"),
    Tracker("quality_top50", date(2026, 10, 1), 24, date(2028, 10, 1), "%", 0.38, "forward_quality.csv"),
    Tracker("smallvq_top20", date(2026, 10, 1), 24, date(2028, 10, 1), "%", 1.00, "forward_smallvq.csv"),
    # Neustart 2026-10-02: ab dann Dry-Run mit offiziellen Schluss-/Eröffnungskursen (Paper-Auktionsorders unbrauchbar)
    # Erwartung (nachgetragen 2026-10-02 vor der ersten Dry-Run-Nacht): 2016-01..2025-09 Ø +0,040 % je Nacht und
    # Position nach 2 bp Kosten (dividendenbereinigt; der Dry-Run nutzt unbereinigte Kurse -> leicht strenger)
    Tracker("overnight_etf", date(2026, 10, 2), 200, date(2027, 10, 1), "%", 0.040, "overnight_trades.csv"),
    Tracker("liq_r125", date(2026, 10, 2), 40, date(2027, 10, 1), "Cluster", None, "data_cache/liquidations"),
)
# Eigene Familie 2 (Vorab-Regel 2026-10-03): eine Hypothese, Hürde t >= 2 und besser als SPY
FAMILY2 = (Tracker("gold_breakout", date(2026, 10, 5), 150, date(2028, 10, 1), "R", 0.165, "forward_gold.csv"),)
FAMILY2_T = 2.0
# Eigene Familie 3 (Vorab 2026-10-04, Runde 141): Pelosi-Käufe ab Meldedatum, 12 Monate. Anzeige: abgeschlossene
# Trades (% Überrendite ggü. SPY); bindend ist die Depot-Monatsüberrendite (forward_pelosi.portfolio_excess), t >= 2
FAMILY3 = (Tracker("pelosi_copy", date(2026, 10, 5), 20, date(2029, 10, 1), "% ggü. SPY", 11.1, "forward_pelosi.csv"),)
ORB_EXPECTED_R_PER_TRADE = 0.026      # Erwartung je Tag = 0,026 R x Ø Trades je Tag
OVERNIGHT_COST_PCT = 0.02             # Dry-Run-Ledger ist brutto: 1 bp je Seite abziehen (wie Backtest Familie E)


def t_crit(n: int, alpha: float = ALPHA) -> float:
    """Einseitiger kritischer Student-t-Wert (df = n - 1), Cornish-Fisher-Näherung (n 24 -> 2,85, n 200 -> 2,63)."""
    z = _norm_ppf(1 - alpha)
    df = max(n - 1, 1)
    return (z + (z ** 3 + z) / (4 * df) + (5 * z ** 5 + 16 * z ** 3 + 3 * z) / (96 * df ** 2)
            + (3 * z ** 7 + 19 * z ** 5 + 17 * z ** 3 - 15 * z) / (384 * df ** 3))


def _norm_ppf(p: float) -> float:
    lo, hi = -10.0, 10.0
    for _ in range(100):
        mid = (lo + hi) / 2
        if 0.5 * math.erfc(-mid / math.sqrt(2)) < p:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def _t(x: list[float]) -> float:
    n = len(x)
    if n < 3:
        return float("nan")
    m = sum(x) / n
    sd = math.sqrt(sum((v - m) ** 2 for v in x) / (n - 1))
    return m / sd * math.sqrt(n) if sd > 0 else float("nan")


def _rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def observations(tr: Tracker, base: Path) -> tuple[list[float], float | None] | None:
    """(Beobachtungen in Anzeige-Einheit, Erwartung) oder None, wenn nicht aus einem Ledger ablesbar."""
    start = tr.start.isoformat()
    if tr.source == "forward_trades.csv":
        xs = [float(r["net_bp"]) for r in _rows(base / tr.source) if r["strategy"] == tr.name and r["date"] >= start]
        return xs, tr.expected
    if tr.name == "orb_or5":
        by_day: dict[str, float] = defaultdict(float)
        rows = [r for r in _rows(base / tr.source) if r["date"] >= start]
        for r in rows:
            by_day[r["date"]] += float(r["r_net"])
        exp = ORB_EXPECTED_R_PER_TRADE * len(rows) / len(by_day) if by_day else None
        return [by_day[d] for d in sorted(by_day)], exp
    if tr.source in ("forward_quality.csv", "forward_smallvq.csv"):
        xs = [float(r["net_excess"]) * 100 for r in _rows(base / tr.source)
              if r["net_excess"] != "" and r["entry_date"] >= start]
        return xs, tr.expected
    if tr.source == "forward_gold.csv":
        xs = [float(r["r_net"]) for r in _rows(base / tr.source) if r["entry_time"][:10] >= start]
        return xs, tr.expected
    if tr.source == "forward_pelosi.csv":
        xs = [float(r["excess"]) * 100 for r in _rows(base / tr.source) if r["status"] == "abgeschlossen"]
        return xs, tr.expected
    if tr.name == "overnight_etf":
        nights: dict[str, list[float]] = defaultdict(list)
        for r in _rows(base / tr.source):
            if r["bought_on"] >= start and r.get("mode") == "dry-run" and r.get("return", "") != "":
                nights[r["bought_on"]].append(float(r["return"]) * 100 - OVERNIGHT_COST_PCT)
        return [sum(v) / len(v) for _, v in sorted(nights.items())], tr.expected
    return None


COST_PER_SIDE = {"quality_top50": 10e-4, "smallvq_top20": 75e-4}


def vs_etf(tr: Tracker, base: Path) -> tuple[int, float | None]:
    """Monatsdepots: Ø (Depotrendite nach Kosten - SPY) in %/Monat über abgerechnete Monate mit SPY-Wert
    (Nutzer-Maßstab: nur interessant, wenn besser als ETF halten)."""
    if tr.name not in COST_PER_SIDE:
        return 0, None
    xs = [(float(r["port_ret"]) - COST_PER_SIDE[tr.name] * float(r["turnover"]) - float(r["spy_ret"])) * 100
          for r in _rows(base / tr.source)
          if r["net_excess"] != "" and r.get("spy_ret", "") != "" and r["entry_date"] >= tr.start.isoformat()]
    return len(xs), (sum(xs) / len(xs) if xs else None)


def status(base: Path, today: date) -> list[dict]:
    out = []
    for tr in TRACKERS + FAMILY2 + FAMILY3:
        obs = observations(tr, base)
        row = {"name": tr.name, "unit": tr.unit, "min_n": tr.min_n, "eval_date": tr.eval_date,
               "days_left": (tr.eval_date - today).days, "n": None, "mean": None, "t": None, "t_crit": None,
               "expected": None, "note": "", "vs_etf": None}
        half = tr.start + (tr.eval_date - tr.start) / 2
        if obs is None:
            row["note"] = "Auswertung per Skript (Runde 125)"
        else:
            xs, exp = obs
            n = len(xs)
            row.update(n=n, expected=exp, t_crit=FAMILY2_T if tr in FAMILY2 + FAMILY3 else t_crit(max(n, tr.min_n)))
            if n:
                row["mean"] = sum(xs) / n
                row["t"] = _t(xs)
            row["vs_etf"] = vs_etf(tr, base)[1]
            if today >= half and row["mean"] is not None and row["mean"] < 0 and (row["t"] or 0) <= -1.5:
                row["note"] = "Abbruch erlaubt (Hälfte erreicht, Ø < 0, t <= -1,5)"
        out.append(row)
    return out


def _fmt(v, spec: str) -> str:
    return "–" if v is None or (isinstance(v, float) and math.isnan(v)) else format(v, spec)


def format_text(rows: list[dict]) -> str:
    lines = [f"Vorwärtstests (nur Information, Hürde p < 0,05/{K}):"]
    for r in rows:
        if r["n"] is None:
            lines.append(f"- {r['name']}: {r['note']}; Termin {r['eval_date']:%d.%m.%Y}")
            continue
        lines.append(f"- {r['name']}: {r['n']}/{r['min_n']} Beob., Ø {_fmt(r['mean'], '+.2f')} {r['unit']} "
                     f"(Erw. {_fmt(r['expected'], '+.2f')}), t {_fmt(r['t'], '.2f')} / Hürde {r['t_crit']:.2f}, "
                     f"Termin {r['eval_date']:%d.%m.%Y}"
                     + (f", gegen ETF (SPY) {r['vs_etf']:+.2f} %/Monat" if r.get("vs_etf") is not None else "")
                     + (f" -- {r['note']}" if r["note"] else ""))
    return "\n".join(lines)

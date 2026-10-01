"""Wochenbericht der Copilot-Trades: Ergebnis, Setups, Einstiege über/unter VWAP, Stop-Abstand, Hinweise.

Versand freitags nach Börsenschluss über ntfy (copilot watch, siehe notify.CopilotAlerts.weekly_step);
abrufbar mit `main.py copilot weekly`.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
TIGHT_STOP = 0.005   # unter 0,5 % Abstand gilt als eng
NO_JOURNAL = "(ohne Journal)"


def _avg(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def _fmt_r(x):
    return "–" if x is None else f"{x:+.2f} R"


def summarize_week(rows: list[dict], total_trades: int, start: datetime, end: datetime) -> tuple[str, str]:
    """rows: attach_setups-Zeilen der Woche, je mit 'above_vwap' (True/False/None). Gibt (Titel, Text) zurück."""
    title = f"Wochenbericht {start.astimezone(NY):%d.%m.}-{end.astimezone(NY):%d.%m.}"
    skipped = sum(1 for r in rows if r["setup"] == NO_JOURNAL)
    rows = [r for r in rows if r["setup"] != NO_JOURNAL]   # z.B. Testkäufe außerhalb des Copilot
    if not rows:
        return title, f"Keine abgeschlossenen Trades diese Woche. Insgesamt bisher {total_trades} von 100 Trades."
    rr = [r["r"] for r in rows if r["r"] is not None]
    wins = sum(1 for r in rows if r["pnl"] > 0)
    lines = [f"{len(rows)} Trades, {wins} Gewinner ({wins / len(rows):.0%}), Summe {sum(rr):+.1f} R "
             f"({sum(r['pnl'] for r in rows):+.0f} $)."]
    by_setup: dict[str, list] = {}
    for r in rows:
        by_setup.setdefault(r["setup"], []).append(r["r"])
    lines.append("Je Setup: " + "; ".join(f"{s} {len(v)}x Ø {_fmt_r(_avg(v))}" for s, v in sorted(by_setup.items())))
    above = [r["r"] for r in rows if r.get("above_vwap") is True]
    below = [r["r"] for r in rows if r.get("above_vwap") is False]
    if above or below:
        lines.append(f"Einstieg über VWAP: {len(above)}x Ø {_fmt_r(_avg(above))} · unter VWAP: {len(below)}x "
                     f"Ø {_fmt_r(_avg(below))}")
    dist = [(r, (r["planned_price"] - r["stop"]) / r["planned_price"]) for r in rows
            if r.get("planned_price") and r.get("stop") and r["planned_price"] > r["stop"]]
    tight = [r["r"] for r, d in dist if d < TIGHT_STOP]
    wide = [r["r"] for r, d in dist if d >= TIGHT_STOP]
    if dist:
        lines.append(f"Stop-Abstand Ø {sum(d for _, d in dist) / len(dist):.2%}; eng (< 0,5 %): {len(tight)}x "
                     f"Ø {_fmt_r(_avg(tight))} · weiter: {len(wide)}x Ø {_fmt_r(_avg(wide))}")
    tips = []
    if below and (_avg(below) or 0) < 0 and (_avg(below) or 0) < (_avg(above) if above else 0):
        tips.append("Unter der VWAP gekaufte Trades schneiden schlechter ab -- nur über der VWAP kaufen.")
    if len(tight) >= 2 and (_avg(tight) or 0) < 0 and (_avg(tight) or 0) < (_avg(wide) if wide else 0):
        tips.append("Enge Stops werden oft ausgelöst -- Stop unter ein sichtbares Tief bzw. die Gegenseite der "
                    "ersten Kerze legen, dafür weniger Stück kaufen.")
    rated = {s: _avg(v) for s, v in by_setup.items() if _avg(v) is not None}
    if len(rated) > 1 and max(rated.values()) > 0:
        tips.append(f"Bestes Setup diese Woche: {max(rated, key=rated.get)} -- darauf konzentrieren.")
    if len(rr) >= 3 and sum(rr) < -3:
        tips.append("Woche deutlich im Minus: nächste Woche bewusst weniger und nur klare Setups handeln.")
    if tips:
        lines.append("Hinweise: " + " ".join(f"({i}) {t}" for i, t in enumerate(tips, 1)))
    if skipped:
        lines.append(f"({skipped} Trade(s) ohne Journal-Eintrag, z.B. Tests, nicht mitgezählt.)")
    lines.append(f"Insgesamt bisher {total_trades} von 100 Trades bis zur Auswertung.")
    return title, "\n".join(lines)


def vwap_at(cp, symbol: str, when: datetime) -> float | None:
    """VWAP von 9:30 ET bis zum Zeitpunkt (5-Min-SIP-Kerzen)."""
    from alpaca.data.enums import DataFeed

    from tradingbot.copilot import vwap

    start = datetime.combine(when.astimezone(NY).date(), time(9, 30), tzinfo=NY)
    bars = cp._bars(symbol, DataFeed.SIP, start, when)
    return float(vwap(bars)[-1]) if len(bars) else None


def build_weekly(cp, now: datetime, days: int = 7) -> tuple[str, str]:
    from tradingbot.copilot import attach_setups, load_journal

    trades, _ = cp._closed_trades(now, days)
    rows = attach_setups(trades, load_journal(cp.journal_path))
    for r in rows:
        r["above_vwap"] = None
        if r.get("planned_price"):
            try:
                v = vwap_at(cp, r["symbol"], r["entry_time"])
                r["above_vwap"] = None if v is None else r["planned_price"] >= v
            except Exception:  # Datenlücke: VWAP-Vergleich für diesen Trade weglassen
                pass
    all_trades, _ = cp._closed_trades(now, 365)
    counted = sum(1 for r in attach_setups(all_trades, load_journal(cp.journal_path)) if r["setup"] != NO_JOURNAL)
    return summarize_week(rows, counted, now - timedelta(days=days), now)

"""Prüfpunkte des Momentum-Vorwärtstests (research/PROTOCOL.md, "Vorwärtstest Momentum-Bot", 2026-09-29):
gezählt ab 2026-09-23, Kosten-Aufschlag 1 Cent je Aktie und Round-Trip.
- 100 Trades: vorzeitiger Abbruch, wenn Netto < 0 UND Profit-Faktor < 0,8.
- 150 Trades: BESTANDEN nur bei Netto > 0 UND Profit-Faktor >= 1,3 UND t (Ø je Trade) >= 2.
Gewertet werden genau die ersten 100 bzw. 150 Trades (nach Ausstiegszeit). Jede Meldung geht einmal raus; der Bot
wird NICHT automatisch gestoppt -- die Entscheidung trifft der Nutzer.
"""

from __future__ import annotations

import math
from datetime import date
from pathlib import Path
from zoneinfo import ZoneInfo

from tradingbot.state_io import load_state, save_state

START = date(2026, 9, 23)
COST_PER_SHARE = 0.01
STATE = Path("data_cache") / "momentum_checkpoint.json"
NY = ZoneInfo("America/New_York")


def counted(trades: list) -> list:
    """Trades ab START (Einstiegstag New York), nach Ausstiegszeit sortiert."""
    return sorted((t for t in trades if t.entry_time.astimezone(NY).date() >= START), key=lambda t: t.exit_time)


def stats(trades: list) -> dict:
    pnl = [t.pnl - COST_PER_SHARE * t.shares for t in trades]
    n = len(pnl)
    wins, losses = sum(x for x in pnl if x > 0), -sum(x for x in pnl if x < 0)
    mean = sum(pnl) / n if n else 0.0
    sd = math.sqrt(sum((x - mean) ** 2 for x in pnl) / (n - 1)) if n > 1 else 0.0
    return {"n": n, "net": sum(pnl), "pf": wins / losses if losses > 0 else float("inf"),
            "t": mean / sd * math.sqrt(n) if sd > 0 else float("nan"),
            "win_rate": sum(x > 0 for x in pnl) / n if n else 0.0}


def verdict(s: dict, checkpoint: int) -> str:
    if checkpoint == 100:
        stop = s["net"] < 0 and s["pf"] < 0.8
        return ("ABBRUCH-REGEL ERFÜLLT (Netto < 0 und PF < 0,8): Vorwärtstest gilt als nicht bestanden"
                if stop else "Abbruch-Regel nicht erfüllt: weiter bis 150 Trades")
    ok = s["net"] > 0 and s["pf"] >= 1.3 and s["t"] >= 2
    return "BESTANDEN" if ok else "NICHT BESTANDEN (kein Echtgeld)"


def message(s: dict, checkpoint: int) -> str:
    return (f"Momentum-Bot, Prüfpunkt {checkpoint} Trades (ab {START:%d.%m.%Y}, 1 Cent/Aktie Kosten): "
            f"Netto {s['net']:+,.0f} $, Profit-Faktor {s['pf']:.2f}, Treffer {s['win_rate']:.0%}, t {s['t']:.2f}. "
            f"-> {verdict(s, checkpoint)}. Der Bot läuft weiter, bis du entscheidest.")


def step(trades: list, notifier, state_path: Path = STATE) -> list[str]:
    """Sendet fällige Prüfpunkt-Meldungen genau einmal; gibt die gesendeten Texte zurück."""
    done = load_state(state_path, [])
    ts = counted(trades)
    sent = []
    for cp in (100, 150):
        if len(ts) >= cp and cp not in done:
            text = message(stats(ts[:cp]), cp)
            if notifier.send(f"Momentum-Bot: {cp} Trades", text, priority="high"):
                done.append(cp)
                sent.append(text)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    save_state(state_path, done)
    return sent


def progress(trades: list) -> str:
    s = stats(counted(trades))
    return (f"Momentum-Bot: {s['n']} gezählte Trades (Prüfpunkte 100 / 150), Netto {s['net']:+,.0f} $, "
            f"PF {s['pf']:.2f}, t {s['t']:.2f}")

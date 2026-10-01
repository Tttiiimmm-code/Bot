"""Benachrichtigungen aufs Handy über ntfy (https://ntfy.sh, kostenlose App, kein Konto nötig).

Einrichtung: in copilot.env `NTFY_TOPIC=<langer zufälliger Name>` eintragen (wer den Namen kennt, kann mitlesen --
also nicht erratbar wählen), in der ntfy-App dasselbe Thema abonnieren. Optional `NTFY_SERVER` (Standard ntfy.sh).
Ohne NTFY_TOPIC ist alles aus. Gesendet werden nur Symbol, Kurse und Status -- keine Konto- oder Schlüsseldaten.

CopilotAlerts meldet Zustandswechsel und merkt sich Gesendetes je Handelstag in einer kleinen JSON-Datei, damit nach
einem Neustart nichts doppelt kommt:
- Setup-Melder: einmal die Top 5 des Tages, dann jedes Long-Setup, das ausbricht (Einstieg, Stop, Ziel 2 R), und
  dessen Ausgang (Ziel/Stop) -- nur zwischen 9:52 und 15:00 ET.
- Positionen: geschlossen (Stop, Ziel oder von Hand) und alle Eingriffe der Überwachung (Einstand, Tagesgrenze,
  Glattstellen).
"""

from __future__ import annotations

import json
import logging
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

NY = ZoneInfo("America/New_York")
BERLIN = ZoneInfo("Europe/Berlin")
STATE_PATH = Path("data_cache") / "copilot_notify_state.json"


def _ascii(text: str) -> str:
    """HTTP-Header vertragen keine Umlaute zuverlässig -- Titel umschreiben."""
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("Ä", "Ae"), ("Ö", "Oe"), ("Ü", "Ue"), ("ß", "ss")):
        text = text.replace(a, b)
    return text.encode("ascii", "ignore").decode()


class Notifier:
    def __init__(self, topic: str | None, server: str = "https://ntfy.sh", timeout: float = 10.0, opener=None):
        self.topic = (topic or "").strip()
        self.server = server.rstrip("/")
        self.timeout = timeout
        self._open = opener or urllib.request.urlopen

    @property
    def enabled(self) -> bool:
        return bool(self.topic)

    def send(self, title: str, message: str, priority: str = "default", tags: str = "") -> bool:
        """Sendet eine Nachricht; Fehler werden nur protokolliert (die Überwachung darf daran nie scheitern)."""
        if not self.enabled:
            return False
        headers = {"Title": _ascii(title), "Priority": priority}
        if tags:
            headers["Tags"] = tags
        req = urllib.request.Request(f"{self.server}/{self.topic}", data=message.encode("utf-8"), headers=headers,
                                     method="POST")
        try:
            with self._open(req, timeout=self.timeout):
                return True
        except Exception as e:  # noqa: BLE001 -- Netz/Server: nur melden
            logger.warning("ntfy-Benachrichtigung fehlgeschlagen: %s", e)
            return False


def notifier_from_env(env_file: str) -> Notifier:
    from dotenv import dotenv_values

    values = dotenv_values(env_file)
    return Notifier(values.get("NTFY_TOPIC"), values.get("NTFY_SERVER") or "https://ntfy.sh")


class CopilotAlerts:
    def __init__(self, notifier: Notifier, state_path: Path = STATE_PATH):
        self.notifier = notifier
        self.state_path = state_path

    # ------------------------------------------------------------ Zustand
    def _load(self, day: str) -> dict:
        try:
            st = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            st = {}
        if st.get("date") != day:
            st = {"date": day, "sent": [], "positions": st.get("positions", [])}
        return st

    def _save(self, st: dict) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(st), encoding="utf-8")
        tmp.replace(self.state_path)

    def _send_once(self, st: dict, key: str, title: str, msg: str, priority: str = "default", tags: str = "") -> bool:
        if key in st["sent"]:
            return False
        if self.notifier.send(title, msg, priority, tags):
            st["sent"].append(key)
            return True
        return False

    # ------------------------------------------------------------ Positionen / Überwachung
    def positions_step(self, now: datetime, open_symbols: set[str], watch_msg: str | None,
                       realized_fn=None) -> list[str]:
        """Meldet Eingriffe der Überwachung und geschlossene Positionen (Symbol war offen, ist es nicht mehr).
        realized_fn: liefert den heute realisierten Gewinn -- wird nur aufgerufen, wenn etwas geschlossen wurde."""
        st = self._load(now.astimezone(NY).date().isoformat())
        sent = []
        if watch_msg and self.notifier.send("Copilot-Sicherheit", watch_msg, "high", "shield"):
            sent.append(watch_msg)
        closed = sorted(set(st["positions"]) - open_symbols)
        realized = None
        if closed and realized_fn is not None:
            try:
                realized = realized_fn()
            except Exception as e:  # noqa: BLE001
                logger.warning("Tagesgewinn nicht abrufbar: %s", e)
        for sym in closed:
            pnl = f" Heute realisiert: {realized:+.2f} $." if realized is not None else ""
            msg = f"{sym}: Position geschlossen (Stop, Ziel oder von Hand).{pnl}"
            if self.notifier.send(f"{sym} geschlossen", msg, "default", "checkered_flag"):
                sent.append(msg)
        st["positions"] = sorted(open_symbols)
        self._save(st)
        return sent

    # ------------------------------------------------------------ Setup-Melder
    def melder_step(self, now: datetime, setups) -> list[str]:
        """setups: Liste von orb_scanner.OrbSetup (aktueller Stand)."""
        st = self._load(now.astimezone(NY).date().isoformat())
        sent = []
        if setups:
            parts = []
            for s in setups:
                if s.side == "long":
                    parts.append(f"{s.symbol} long (Ausbruch über {s.entry:.2f}, Stop {s.stop:.2f})")
                elif s.side == "short":
                    parts.append(f"{s.symbol} short (nicht handelbar)")
            msg = "Top 5 nach Eröffnungsvolumen: " + "; ".join(parts)
            if self._send_once(st, "summary", "Setup-Melder: Setups des Tages", msg, "low", "mag"):
                sent.append(msg)
        for s in setups:
            if s.side != "long":
                continue
            if s.state == "läuft":
                when = s.triggered_at.astimezone(BERLIN).strftime("%H:%M") if s.triggered_at else ""
                msg = (f"{s.symbol} bricht aus ({when} Uhr): Einstieg ~{s.entry:.2f}, Stop {s.stop:.2f}, "
                       f"Ziel {s.target:.2f} (2 R). Erst Chart prüfen -- Kauf nur im Copilot.")
                if self._send_once(st, f"{s.symbol}:läuft", f"{s.symbol}: Ausbruch", msg, "high", "rocket"):
                    sent.append(msg)
            elif s.state in ("ziel", "stop") and f"{s.symbol}:läuft" in st["sent"]:
                word = "Ziel erreicht (+2 R)" if s.state == "ziel" else "ausgestoppt (-1 R)"
                if self._send_once(st, f"{s.symbol}:{s.state}", f"{s.symbol}: {word}", f"{s.symbol}: Setup {word}.",
                                   "low"):
                    sent.append(f"{s.symbol}: {word}")
        self._save(st)
        return sent

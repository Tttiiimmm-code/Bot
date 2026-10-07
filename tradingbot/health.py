"""Wächter für den VPS: meldet per ntfy, wenn ein Dienst ausfällt (und wenn er wieder läuft), plus täglicher Status.

Läuft als `main.py health` alle 10 Minuten (deploy/health.timer). Nur lesend: systemctl-Abfragen, Plattenplatz,
Arbeitsspeicher, Aktualität der Liquidationsdaten. Meldet nur Zustandswechsel (Zustand in data_cache/health_state.json),
damit ein Ausfall nicht alle 10 Minuten neu gemeldet wird.
"""

from __future__ import annotations

import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from tradingbot.state_io import load_state, save_state

BERLIN = ZoneInfo("Europe/Berlin")
SERVICES = ["momentum", "overnight", "liq-recorder", "copilot-watch", "copilot-gui", "tailscaled", "pelosi-bot"]
ONESHOTS = ["forward-test", "forward-stocks", "forward-status", "momentum-checkpoint", "forward-gold", "forward-pelosi", "backup-data"]           # Timer-Läufe: letzter Lauf muss erfolgreich sein
STATE = Path("data_cache") / "health_state.json"
LIQ_DIR = Path("data_cache") / "liquidations"
SUMMARY_AT = (8, 30)                                    # tägliche Meldung (deutsche Zeit)


def _systemctl(*args: str) -> str:
    return subprocess.run(["systemctl", *args], capture_output=True, text=True, timeout=20).stdout.strip()


def problems(run=_systemctl, disk_path: str = "/", liq_dir: Path = LIQ_DIR, now: float | None = None) -> list[str]:
    now = now or time.time()
    out = []
    for s in SERVICES:
        state = run("is-active", f"{s}.service")
        if state != "active":
            out.append(f"Dienst {s} läuft nicht ({state or 'unbekannt'})")
    for s in ONESHOTS:
        state = run("is-active", f"{s}.timer")
        if state != "active":
            out.append(f"Timer {s} läuft nicht ({state or 'unbekannt'})")
        result = run("show", "-p", "Result", "--value", f"{s}.service")
        if result and result != "success":
            out.append(f"Letzter Lauf {s} fehlgeschlagen ({result})")
    du = shutil.disk_usage(disk_path)
    if du.used / du.total > 0.85:
        out.append(f"Festplatte zu {du.used / du.total:.0%} voll")
    try:
        mem = {k: int(v.split()[0]) for k, v in (line.split(":", 1) for line in Path("/proc/meminfo").read_text().splitlines())}
        if mem["MemAvailable"] / mem["MemTotal"] < 0.10:
            out.append(f"Arbeitsspeicher knapp ({mem['MemAvailable'] // 1024} MB frei)")
    except (OSError, KeyError, ValueError):
        pass
    files = sorted(liq_dir.glob("*.csv")) if liq_dir.exists() else []
    if files and now - max(f.stat().st_mtime for f in files) > 30 * 60:
        out.append("Liquidations-Recorder schreibt seit über 30 Min. keine Daten")
    return out


def step(notifier, state_path: Path = STATE, now: datetime | None = None, check=problems) -> list[str]:
    """Vergleicht mit dem letzten Zustand, sendet neue Probleme / Entwarnungen und einmal täglich den Status."""
    now = now or datetime.now(BERLIN)
    st = load_state(state_path, {"problems": [], "summary_date": ""}, strict=False)
    current = check()
    before = set(st.get("problems", []))
    sent = []
    new, fixed = [p for p in current if p not in before], [p for p in before if p not in current]
    if new and notifier.send("VPS: Problem", "\n".join(new), "high", "warning"):
        sent += new
    if fixed and notifier.send("VPS: wieder in Ordnung", "\n".join(fixed), "default", "white_check_mark"):
        sent += fixed
    today = now.astimezone(BERLIN).date().isoformat()
    if now.astimezone(BERLIN).timetuple()[3:5] >= SUMMARY_AT and st.get("summary_date") != today:
        text = (f"Alles läuft ({len(SERVICES)} Dienste)." if not current else
                f"{len(current)} Problem(e): " + "; ".join(current))
        if notifier.send("VPS: Tagesstatus", text, "low", "sunny" if not current else "warning"):
            st["summary_date"] = today
            sent.append(text)
    # nur gemeldete Änderungen übernehmen: scheitert ntfy, gilt das Problem beim nächsten Lauf weiter als neu
    known = set(before)
    if new and set(new) <= set(sent):
        known |= set(new)
    if fixed and set(fixed) <= set(sent):
        known -= set(fixed)
    st["problems"] = [p for p in current if p in known] + [p for p in before if p not in current and p in known]
    state_path.parent.mkdir(parents=True, exist_ok=True)
    save_state(state_path, st)
    return sent

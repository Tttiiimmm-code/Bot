"""JSON-Zustandsdateien: atomar schreiben (erst .tmp, dann austauschen) und beschädigte Dateien klar melden.

Order-Bots laden streng: eine kaputte Datei bricht den Start mit Dateipfad ab, statt mit leerem Zustand
weiterzulaufen (leerer Zustand könnte einen Kauf wiederholen). Reine Komfort-Zustände (Wächter, Copilot-
Einstellungen) laden tolerant und fallen auf den Standardwert zurück.
"""

from __future__ import annotations

import json
from pathlib import Path


def load_state(path: Path, default, *, strict: bool = True):
    """Inhalt der Datei oder `default`, wenn sie fehlt. Kaputt: strict -> RuntimeError, sonst `default`."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default
    except (OSError, ValueError) as exc:
        if not strict:
            return default
        raise RuntimeError(f"Zustandsdatei {path} beschädigt oder unlesbar ({exc}) -- Datei prüfen/entfernen.") from exc


def save_state(path: Path, value, *, indent: int | None = 2) -> None:
    """Schreibt erst nach `<datei>.tmp` und tauscht dann aus: ein Abbruch mitten im Schreiben lässt die
    alte Datei intakt."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=indent), encoding="utf-8")
    tmp.replace(path)

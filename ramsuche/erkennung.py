"""Erkennt aus Titel (und Beschreibung), ob eine Anzeige passender Desktop-DDR5-RAM ist und wie viel GB sie hat.

Bewusst streng: lieber eine echte Anzeige verwerfen als Laptop-, Server- oder defekten RAM melden. Der Titel entscheidet;
die Beschreibung füllt nur fehlende Angaben auf und liefert Warnhinweise.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

RIEGEL_GB = {8, 12, 16, 24, 32, 48, 64}
GESAMT_GB = {8, 12, 16, 24, 32, 48, 64, 96, 128, 192, 256}

# Verneinungen zuerst entfernen ("Non-ECC", "kein SO-DIMM", "On-Die ECC" hat jeder DDR5-Riegel)
_VERNEINT = re.compile(r"\b(?:non|kein|keine|ohne|no|on[\s-]*die)[\s-]*(?:ecc|so[\s-]*dimm|sodimm|laptop|notebook|server)\b")
_DDR5 = re.compile(r"(?<!lp)ddr\s*-?\s*5|\bpc5[\s-]*\d")
_DDR4 = re.compile(r"(?<!lp)ddr\s*-?\s*4|\bpc4[\s-]*\d")
_GESUCH = re.compile(r"\b(?:suche|suchen|gesucht|ankauf|kaufe|wtb)\b")
_LAPTOP = re.compile(r"so[\s-]*dimm|sodimm|laptop|notebook|\bcamm2?\b|lpddr|macbook|\bnuc\b|handheld|steam\s*deck")
_SERVER = re.compile(r"\becc\b|\brdimm\b|lrdimm|registered|\bserver\b|\breg\b")
_DEFEKT = re.compile(r"defekt|kaputt|bastler|ungetestet|nicht\s+getestet|f(?:ü|ue)r\s+teile|for\s+parts|ersatzteil"
                     r"|fehlerhaft|bluescreen")
_BUNDLE = re.compile(
    r"gaming[\s-]*pc|komplett[\s-]*pc|\bpc[\s-]*(?:system|komplett)|\bcomputer\b|\brechner\b|workstation|aufr(?:ü|ue)st"
    r"|bundle|mainboard|motherboard|\b(?:a620|b650e?|x670e?|b850|x870e?|z690|z790|z890|b760|b860|h610|h770)\b"
    r"|ryzen\s*[3579]\s*\d{4}|\d{4}x3d|\bi[3579][\s-]*\d{4,5}|core\s*ultra|threadripper|\bcpu\b|prozessor"
    r"|rtx\s*\d{4}|\brx\s*\d{4}|\bgtx\b|geforce|grafikkarte|netzteil|\bssd\b|nvme|geh(?:ä|ae)use")

# 2x16GB, 2 x 16 GB, 2x16
_X_VORNE = re.compile(r"(?<![\d.,])([1-4])\s*x\s*(\d{1,2})(?![\d.,])")
# 16GBx2, 16 GB x 2, 16x2
_X_HINTEN = re.compile(r"(?<![\d.,])(\d{1,2})\s*(?:gb?)?\s*x\s*([1-4])(?![\d.,])")
# 2x SK Hynix 16 GB, 2 Stück 16GB, zwei Riegel 16 GB
_X_LUECKE = re.compile(r"(?<![\d.,])(?:([1-4])\s*x|([1-4]|zwei|vier)\s*(?:st(?:ü|ue)ck|stk\.?|riegel|module?))\s*"
                       r"([^\d]{0,40}?)(\d{1,2})\s*gb")
_GB = re.compile(r"(?<![\d.,])(\d{1,3})\s*gb(?![a-z])")
_TAKT = re.compile(r"ddr5[\s-]*(\d{4})|(\d{4})\s*(?:mhz|mt/?s)|\bpc5[\s-]*(\d{5})|\bpc(\d{4})\b")
_CL = re.compile(r"\bcl\s*-?(\d{2})\b|\bc(\d{2})\b")

_ZAHLWORT = {"zwei": 2, "vier": 4}


@dataclass
class Erkennung:
    passt: bool
    grund: str = ""                      # Ablehnungsgrund, leer wenn passt
    anzahl: int | None = None            # Riegel, None = nicht angegeben
    riegel_gb: int | None = None
    gesamt_gb: int | None = None
    takt: int | None = None
    cl: int | None = None
    hinweise: list[str] = field(default_factory=list)


def _norm(text: str | None) -> str:
    t = (text or "").lower().replace("×", "x").replace(" ", " ")
    t = re.sub(r"(\d)\s*gib\b", r"\1gb", t)
    return _VERNEINT.sub(" ", t)


def kapazitaet(text: str) -> tuple[int | None, int | None, int | None]:
    """(Anzahl Riegel, GB je Riegel, GB gesamt) aus normalisiertem Text; fehlende Angaben None."""
    for rx, a_idx, g_idx in ((_X_VORNE, 1, 2), (_X_HINTEN, 2, 1)):
        for m in rx.finditer(text):
            n, gb = int(m.group(a_idx)), int(m.group(g_idx))
            if gb in RIEGEL_GB:
                return n, gb, n * gb
    for m in _X_LUECKE.finditer(text):
        wort = m.group(1) or m.group(2)
        n = _ZAHLWORT.get(wort) or int(wort)
        gb = int(m.group(4))
        if gb in RIEGEL_GB:
            return n, gb, n * gb
    werte = [int(v) for v in _GB.findall(text) if int(v) in GESAMT_GB]
    return (None, None, max(werte)) if werte else (None, None, None)


def _takt_cl(text: str) -> tuple[int | None, int | None]:
    takt = None
    for m in _TAKT.finditer(text):
        if m.group(3):
            v = int(m.group(3)) // 8                     # PC5-48000 -> 6000
        else:
            v = int(m.group(1) or m.group(2) or m.group(4))
        if 4000 <= v <= 9600:
            takt = v
            break
    cl = None
    m = _CL.search(text)
    if m:
        v = int(m.group(1) or m.group(2))
        if 26 <= v <= 52:
            cl = v
    return takt, cl


def pruefe(titel: str, beschreibung: str = "", min_gb: int = 32, min_riegel_gb: int = 16) -> Erkennung:
    t, d = _norm(titel), _norm(beschreibung)
    if _GESUCH.search(t):
        return Erkennung(False, "Gesuch/Ankauf")
    if _DDR4.search(t):
        return Erkennung(False, "DDR4")
    if not (_DDR5.search(t) or _DDR5.search(d)):
        return Erkennung(False, "kein DDR5 erkennbar")
    if _LAPTOP.search(t):
        return Erkennung(False, "Laptop-RAM (SO-DIMM)")
    if _SERVER.search(t):
        return Erkennung(False, "Server-RAM (ECC/RDIMM)")
    if _DEFEKT.search(t):
        return Erkennung(False, "defekt/ungetestet")
    if _BUNDLE.search(t):
        return Erkennung(False, "Bundle/Komplett-PC")

    anzahl, riegel, gesamt = kapazitaet(t)
    if gesamt is None and d:
        anzahl, riegel, gesamt = kapazitaet(d)
    elif riegel is None and d:                          # Titel "32GB DDR5", Beschreibung "2x16GB"
        a2, r2, g2 = kapazitaet(d)
        if r2 is not None and g2 == gesamt:
            anzahl, riegel = a2, r2
    if gesamt is None:
        return Erkennung(False, "Größe nicht erkennbar")
    takt, cl = _takt_cl(t)
    if takt is None or cl is None:
        t2, c2 = _takt_cl(d)
        takt, cl = takt or t2, cl or c2
    e = Erkennung(True, anzahl=anzahl, riegel_gb=riegel, gesamt_gb=gesamt, takt=takt, cl=cl)
    if gesamt < min_gb:
        e.passt, e.grund = False, f"nur {gesamt} GB"
    elif riegel is not None and riegel < min_riegel_gb:
        e.passt, e.grund = False, f"Riegel zu klein ({anzahl}x{riegel} GB)"
    if not e.passt:
        return e

    if riegel is None:
        e.hinweise.append("Aufteilung nicht angegeben (1 oder 2 Riegel?) -- nachfragen")
    elif anzahl and anzahl > 2:
        e.hinweise.append(f"{anzahl} Riegel: auf AM5 laufen 4 Riegel oft nur mit deutlich weniger Takt")
    if takt and takt < 5600:
        e.hinweise.append(f"langsam (DDR5-{takt}); für AM5 ideal sind 6000 MT/s CL30")
    if "cudimm" in t:
        e.hinweise.append("CUDIMM: auf AM5 nur im Bypass-Modus, Board-Unterstützung prüfen")
    for rx, was in ((_LAPTOP, "Laptop/SO-DIMM"), (_SERVER, "ECC/Server"), (_DEFEKT, "Defekt/ungetestet")):
        if rx.search(d):
            e.hinweise.append(f"Beschreibung erwähnt {was} -- genau lesen")
    return e

"""Ein Suchlauf: Anzeigen holen, erkennen, speichern, gegen den Marktpreis bewerten, Schnäppchen melden.

Marktpreis = Median Euro/GB (inkl. bekanntem Versand) aller passenden Festpreis-Anzeigen der letzten 14 Tage mit
derselben Gesamtgröße (32/48/64 GB ...), bei zu wenigen Werten über alle Größen. Er misst Angebotspreise, nicht
Verkaufspreise -- verkauft wird oft darunter. Gemeldet wird, was mindestens RABATT darunter liegt (oder unter
MAX_EUR_PRO_GB). Jede Anzeige wird einmal gemeldet, erneut nur nach einer Preissenkung um mindestens 10 %.
"""

from __future__ import annotations

import logging
import sqlite3
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from ramsuche.erkennung import Erkennung, pruefe
from ramsuche.quellen import Anzeige, Ebay, Kleinanzeigen, QuelleFehler

logger = logging.getLogger(__name__)

BERLIN = ZoneInfo("Europe/Berlin")
DB_PATH = Path("data_cache") / "ramsuche" / "ramsuche.db"
MARKT_TAGE = 14
MARKT_MINDEST = 8                 # so viele Vergleichswerte braucht ein Marktpreis
PREIS_MIN, PREIS_MAX = 40.0, 5000.0   # Platzhalterpreise (1 €, 9.999 €) ignorieren
FEHLER_MELDEN_AB = 3              # Quelle so viele Läufe in Folge ohne Ergebnis -> Meldung
QUELLNAME = {"kleinanzeigen": "Kleinanzeigen", "ebay": "eBay"}


@dataclass
class Einstellungen:
    min_gb: int = 32
    min_riegel_gb: int = 16
    rabatt: float = 0.30              # so weit unter Marktpreis gilt als Schnäppchen (Probelauf: 0.20 traf jede 5.)
    max_eur_pro_gb: float | None = None
    ka_seiten: int = 3
    auktion_stunden: float = 2.0      # Auktionen erst melden, wenn sie so bald enden
    abschlag_verkauf: float = 0.10    # Weiterverkauf: Abschlag auf Marktpreis (Verhandlung, Gebühren)
    versand_verkauf: float = 7.0
    max_meldungen: int = 5            # Einzelmeldungen je Lauf, der Rest als Sammelmeldung

    @classmethod
    def aus_env(cls, werte: dict) -> "Einstellungen":
        e = cls()
        for name, typ in (("min_gb", int), ("min_riegel_gb", int), ("rabatt", float), ("ka_seiten", int),
                          ("auktion_stunden", float), ("abschlag_verkauf", float), ("versand_verkauf", float),
                          ("max_meldungen", int)):
            v = werte.get(name.upper())
            if v not in (None, ""):
                setattr(e, name, typ(v))
        v = werte.get("MAX_EUR_PRO_GB")
        e.max_eur_pro_gb = float(v) if v not in (None, "") else None
        return e


@dataclass
class Treffer:
    anzeige: Anzeige
    erkennung: Erkennung
    kaufpreis: float                  # inkl. bekanntem Versand
    eur_pro_gb: float
    markt: float | None               # Euro/GB
    rabatt: float | None              # Anteil unter Markt
    weiterverkauf: float | None       # grober Gewinn in Euro
    preissenkung: bool = False
    warnungen: list[str] = field(default_factory=list)


# ------------------------------------------------------------------------------------------------------- Datenbank
SCHEMA = """
CREATE TABLE IF NOT EXISTS anzeigen (
    quelle TEXT NOT NULL, id TEXT NOT NULL, titel TEXT, url TEXT, preis REAL, versand REAL, gesamt_gb INTEGER,
    eur_pro_gb REAL, auktion INTEGER, passt INTEGER, grund TEXT, zuerst TEXT, zuletzt TEXT,
    gemeldet_eur_pro_gb REAL, PRIMARY KEY (quelle, id));
CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);
"""


def verbinden(pfad: Path | str = DB_PATH) -> sqlite3.Connection:
    if str(pfad) != ":memory:":
        Path(pfad).parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(pfad))
    db.executescript(SCHEMA)
    return db


def _meta(db, k: str, standard: str = "") -> str:
    row = db.execute("SELECT v FROM meta WHERE k=?", (k,)).fetchone()
    return row[0] if row else standard


def _meta_setzen(db, k: str, v: str) -> None:
    db.execute("INSERT INTO meta (k, v) VALUES (?, ?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, v))


def kaufpreis(a: Anzeige) -> float | None:
    if a.preis is None:
        return None
    return a.preis + (a.versand or 0.0)


def speichern(db, a: Anzeige, e: Erkennung, jetzt: datetime) -> None:
    preis = kaufpreis(a)
    passt = e.passt and not a.gesuch and not a.defekt and preis is not None and PREIS_MIN <= preis <= PREIS_MAX
    grund = e.grund or ("Gesuch" if a.gesuch else "defekt" if a.defekt else "" if passt else "kein/unplausibler Preis")
    epg = preis / e.gesamt_gb if preis is not None and e.gesamt_gb else None
    db.execute(
        """INSERT INTO anzeigen (quelle, id, titel, url, preis, versand, gesamt_gb, eur_pro_gb, auktion, passt, grund,
                                 zuerst, zuletzt)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(quelle, id) DO UPDATE SET titel=excluded.titel, url=excluded.url, preis=excluded.preis,
               versand=excluded.versand, gesamt_gb=excluded.gesamt_gb, eur_pro_gb=excluded.eur_pro_gb,
               auktion=excluded.auktion, passt=excluded.passt, grund=excluded.grund, zuletzt=excluded.zuletzt""",
        (a.quelle, a.id, a.titel, a.url, a.preis, a.versand, e.gesamt_gb, epg, int(a.auktion), int(passt), grund,
         jetzt.isoformat(), jetzt.isoformat()))


def marktpreis(db, gesamt_gb: int | None, jetzt: datetime) -> tuple[float | None, int]:
    """(Median Euro/GB, Anzahl Werte) der passenden Festpreis-Anzeigen; erst je Größe, sonst über alle."""
    seit = (jetzt - timedelta(days=MARKT_TAGE)).isoformat()
    sql = "SELECT eur_pro_gb FROM anzeigen WHERE passt=1 AND auktion=0 AND zuletzt>=?"
    werte = [r[0] for r in db.execute(sql + " AND gesamt_gb=?", (seit, gesamt_gb))] if gesamt_gb else []
    if len(werte) < MARKT_MINDEST:
        werte = [r[0] for r in db.execute(sql, (seit,))]
    if len(werte) < MARKT_MINDEST:
        return None, len(werte)
    return statistics.median(werte), len(werte)


# ------------------------------------------------------------------------------------------------------- Bewertung
def bewerte(a: Anzeige, e: Erkennung, markt: float | None, cfg: Einstellungen, jetzt: datetime) -> Treffer | None:
    """Treffer, wenn die Anzeige passt und billig genug ist; sonst None."""
    preis = kaufpreis(a)
    if not e.passt or a.gesuch or a.defekt or preis is None or not PREIS_MIN <= preis <= PREIS_MAX:
        return None
    if a.auktion and (a.endet is None or a.endet - jetzt > timedelta(hours=cfg.auktion_stunden)):
        return None                                        # Auktionspreis ist erst kurz vor Ende aussagekräftig
    epg = preis / e.gesamt_gb
    rabatt = 1 - epg / markt if markt else None
    billig = (rabatt is not None and rabatt >= cfg.rabatt) or (cfg.max_eur_pro_gb is not None and epg <= cfg.max_eur_pro_gb)
    if not billig:
        return None
    weiter = None
    if markt:
        weiter = markt * e.gesamt_gb * (1 - cfg.abschlag_verkauf) - cfg.versand_verkauf - preis
    w = list(e.hinweise)
    if rabatt is not None and rabatt >= 0.5:
        w.insert(0, "Sehr billig -- häufige Betrugsmasche. Nur mit Käuferschutz zahlen (Direkt kaufen, eBay-Kasse, "
                    "PayPal Waren und Dienstleistungen), nie Überweisung oder PayPal Freunde; Abholung mit Test am besten.")
    if a.auktion:
        w.append(f"Auktion ({a.gebote or 0} Gebote): Preis steigt bis zum Ende noch")
    if a.quelle == "ebay" and a.bewertungen is not None and a.bewertungen < 10:
        w.append(f"Verkäufer hat nur {a.bewertungen} Bewertungen")
    if a.bewertung_prozent is not None and a.bewertung_prozent < 97:
        w.append(f"Verkäufer nur {a.bewertung_prozent:.1f} % positiv")
    if a.quelle == "kleinanzeigen" and not a.versand_moeglich:
        w.append("nur Abholung")
    if a.quelle == "ebay" and a.versand is None:
        w.append("Versandkosten unbekannt (nicht eingerechnet)")
    return Treffer(a, e, preis, epg, markt, rabatt, weiter, warnungen=w)


def _eur(x: float, stellen: int = 0) -> str:
    return f"{x:,.{stellen}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def meldung(t: Treffer) -> tuple[str, str]:
    a, e = t.anzeige, t.erkennung
    titel = (("Preis gesenkt: " if t.preissenkung else "RAM: ") + f"{e.gesamt_gb} GB DDR5 fuer {_eur(t.kaufpreis)} EUR"
             f" ({_eur(t.eur_pro_gb, 2)} EUR/GB)")
    aufteilung = f"{e.anzahl}x{e.riegel_gb} GB" if e.riegel_gb else f"{e.gesamt_gb} GB, Aufteilung offen"
    technik = ", ".join(x for x in (aufteilung, f"DDR5-{e.takt}" if e.takt else "", f"CL{e.cl}" if e.cl else "") if x)
    merkmale = [QUELLNAME.get(a.quelle, a.quelle)]
    if a.ort:
        merkmale.append(a.ort)
    if a.vb:
        merkmale.append("VB" if a.quelle == "kleinanzeigen" else "Preisvorschlag möglich")
    if a.direkt_kaufen:
        merkmale.append("Direkt kaufen (Käuferschutz)")
    elif a.versand_moeglich and a.quelle == "kleinanzeigen":
        merkmale.append("Versand möglich")
    if a.gewerblich:
        merkmale.append("gewerblich")
    zeilen = [a.titel, technik, ", ".join(merkmale)]
    if a.versand:
        zeilen.append(f"Preis {_eur(a.preis or 0)} € + Versand {_eur(a.versand, 2)} €")
    if t.markt:
        zeilen.append(f"Marktpreis {_eur(t.markt, 2)} €/GB, {t.rabatt:.0%} darunter")
    if t.weiterverkauf is not None:
        zeilen.append(f"Weiterverkauf grob: {'+' if t.weiterverkauf >= 0 else ''}{_eur(t.weiterverkauf)} € "
                      f"(Marktpreis minus Abschlag und Versand, ohne Gewähr)")
    zeilen += [f"Achtung: {x}" for x in t.warnungen]
    zeilen.append(a.url)
    return titel, "\n".join(zeilen)


# ------------------------------------------------------------------------------------------------------------ Lauf
def quellen_aus_env(werte: dict, cfg: Einstellungen) -> list:
    qs: list = [Kleinanzeigen(seiten=cfg.ka_seiten)]
    if werte.get("EBAY_CLIENT_ID") and werte.get("EBAY_CLIENT_SECRET"):
        qs.append(Ebay(werte["EBAY_CLIENT_ID"], werte["EBAY_CLIENT_SECRET"],
                       kategorie=werte.get("EBAY_KATEGORIE", "170083") or "",
                       laender=werte.get("EBAY_LAENDER", "DE") or ""))
    else:
        logger.info("eBay aus (EBAY_CLIENT_ID/EBAY_CLIENT_SECRET in ramsuche.env fehlen)")
    return qs


def lauf(db, quellen: list, cfg: Einstellungen, notifier, jetzt: datetime | None = None) -> list[Treffer]:
    jetzt = jetzt or datetime.now(BERLIN)
    gesammelt: list[tuple[Anzeige, Erkennung]] = []
    for q in quellen:
        zaehler = f"fehler_{q.name}"
        bisher = int(_meta(db, zaehler, "0"))
        erster = db.execute("SELECT COUNT(*) FROM anzeigen WHERE quelle=?", (q.name,)).fetchone()[0] == 0
        try:
            anzeigen = q.holen(erster_lauf=erster)
        except QuelleFehler as ex:
            bisher += 1
            logger.warning("%s (%d. Lauf in Folge)", ex, bisher)
            _meta_setzen(db, zaehler, str(bisher))
            if bisher == FEHLER_MELDEN_AB:
                notifier.send(f"RAM-Suche: {QUELLNAME.get(q.name, q.name)} liefert nichts",
                              f"Seit {bisher} Läufen ohne Ergebnis: {ex}\nDie Suche ist dort blind, bis es wieder geht.",
                              "default", "warning")
            continue
        if bisher >= FEHLER_MELDEN_AB:
            notifier.send(f"RAM-Suche: {QUELLNAME.get(q.name, q.name)} geht wieder", "Abruf klappt wieder.", "low")
        _meta_setzen(db, zaehler, "0")
        for a in anzeigen:
            e = pruefe(a.titel, a.beschreibung, cfg.min_gb, cfg.min_riegel_gb)
            speichern(db, a, e, jetzt)
            gesammelt.append((a, e))
        logger.info("%s: %d Anzeigen, %d passend", q.name, len(anzeigen),
                    sum(1 for a, e in gesammelt if a.quelle == q.name and e.passt))
    db.commit()

    treffer: list[Treffer] = []
    for a, e in gesammelt:
        markt, _ = marktpreis(db, e.gesamt_gb, jetzt) if e.passt else (None, 0)
        t = bewerte(a, e, markt, cfg, jetzt)
        if t is None:
            continue
        row = db.execute("SELECT gemeldet_eur_pro_gb FROM anzeigen WHERE quelle=? AND id=?", (a.quelle, a.id)).fetchone()
        frueher = row[0] if row else None
        if frueher is not None:
            if t.eur_pro_gb > frueher * 0.9:
                continue                                   # schon gemeldet, nicht deutlich billiger geworden
            t.preissenkung = True
        treffer.append(t)
    treffer.sort(key=lambda t: -(t.rabatt or 0))
    _melden(db, treffer, cfg, notifier)
    db.commit()
    return treffer


def _melden(db, treffer: list[Treffer], cfg: Einstellungen, notifier) -> None:
    def gemeldet(t: Treffer) -> None:
        db.execute("UPDATE anzeigen SET gemeldet_eur_pro_gb=? WHERE quelle=? AND id=?",
                   (t.eur_pro_gb, t.anzeige.quelle, t.anzeige.id))

    for t in treffer[:cfg.max_meldungen]:
        titel, text = meldung(t)
        print(f"{titel}\n{text}\n")
        prio = "high" if (t.rabatt or 0) >= 0.30 else "default"
        if notifier.send(titel, text, prio) or not notifier.enabled:
            gemeldet(t)
    rest = treffer[cfg.max_meldungen:]
    if rest:
        zeilen = [f"{t.erkennung.gesamt_gb} GB, {_eur(t.kaufpreis)} € ({_eur(t.eur_pro_gb, 2)} €/GB): {t.anzeige.url}"
                  for t in rest[:20]]
        if notifier.send(f"RAM: {len(rest)} weitere Angebote", "\n".join(zeilen), "low") or not notifier.enabled:
            for t in rest:
                gemeldet(t)


# ----------------------------------------------------------------------------------------------------------- Liste
def liste(db, jetzt: datetime | None = None, stunden: int = 48, anzahl: int = 15) -> str:
    """Marktpreise je Größe und die günstigsten passenden Anzeigen der letzten Stunden (Text für die Konsole)."""
    jetzt = jetzt or datetime.now(BERLIN)
    seit_markt = (jetzt - timedelta(days=MARKT_TAGE)).isoformat()
    zeilen = [f"Marktpreis (Median Euro/GB, Festpreis-Anzeigen der letzten {MARKT_TAGE} Tage):"]
    for gb, n in db.execute("SELECT gesamt_gb, COUNT(*) FROM anzeigen WHERE passt=1 AND auktion=0 AND zuletzt>=? "
                            "GROUP BY gesamt_gb ORDER BY gesamt_gb", (seit_markt,)).fetchall():
        m, _ = marktpreis(db, gb, jetzt)
        zusatz = "" if n >= MARKT_MINDEST or not m else " (über alle Größen)"
        zeilen.append(f"  {gb:>3} GB: {n:>4} Anzeigen, " + (f"{_eur(m, 2)} €/GB" if m else "zu wenige Werte") + zusatz)
    gesamt = db.execute("SELECT COUNT(*), SUM(passt) FROM anzeigen").fetchone()
    zeilen.append(f"Gesehen insgesamt: {gesamt[0]} Anzeigen, davon {gesamt[1] or 0} passend.")
    seit = (jetzt - timedelta(hours=stunden)).isoformat()
    rows = db.execute("SELECT quelle, titel, url, preis, versand, gesamt_gb, eur_pro_gb, auktion FROM anzeigen "
                      "WHERE passt=1 AND zuletzt>=? ORDER BY eur_pro_gb LIMIT ?", (seit, anzahl)).fetchall()
    zeilen.append(f"\nGünstigste passende Anzeigen (zuletzt gesehen in den letzten {stunden} Stunden):")
    for quelle, titel, url, preis, versand, gb, epg, auktion in rows:
        m, _ = marktpreis(db, gb, jetzt)
        unter = f", {1 - epg / m:.0%} unter Markt" if m else ""
        zeilen.append(f"  {_eur(epg, 2):>6} €/GB  {gb} GB  {_eur(preis + (versand or 0))} €{unter}"
                      f"{'  [Auktion]' if auktion else ''}  {QUELLNAME.get(quelle, quelle)}: {titel[:70]}\n"
                      f"           {url}")
    return "\n".join(zeilen)

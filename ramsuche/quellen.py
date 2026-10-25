"""Anzeigen holen: Kleinanzeigen (Suchseiten, schonend) und eBay (offizielle Browse-API).

Kleinanzeigen hat keine offizielle Schnittstelle; automatischer Abruf widerspricht deren Nutzungsbedingungen. Deshalb
nur wenige Seiten je Lauf mit Pausen dazwischen, und bei Sperre (403/429/Captcha) wird nichts umgangen -- der Lauf meldet
den Ausfall. eBay nur mit eigenen Schlüsseln (developer.ebay.com, `EBAY_CLIENT_ID`/`EBAY_CLIENT_SECRET`).
"""

from __future__ import annotations

import html
import json
import logging
import random
import re
import time
from dataclasses import dataclass
from datetime import datetime

import requests

logger = logging.getLogger(__name__)

BROWSER_KOPF = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36",
    "Accept-Language": "de-DE,de;q=0.9",
}


class QuelleFehler(Exception):
    """Quelle hat nichts Verwertbares geliefert (Netz, Sperre, geänderter Seitenaufbau)."""


@dataclass
class Anzeige:
    quelle: str                        # "kleinanzeigen" | "ebay"
    id: str
    titel: str
    url: str
    preis: float | None                # None = kein Preis (nur "VB" o. ä.)
    beschreibung: str = ""
    versand: float | None = None       # None = unbekannt / nur Abholung
    vb: bool = False
    ort: str = ""
    gesuch: bool = False
    gewerblich: bool = False
    direkt_kaufen: bool = False        # Kleinanzeigen "Direkt kaufen" (bezahlt über Kleinanzeigen, Käuferschutz)
    versand_moeglich: bool = False
    auktion: bool = False
    endet: datetime | None = None
    gebote: int | None = None
    bewertungen: int | None = None     # eBay: Bewertungspunkte des Verkäufers
    bewertung_prozent: float | None = None
    defekt: bool = False               # eBay-Zustand "Als Ersatzteil / defekt"


# ------------------------------------------------------------------------------------------------------ Kleinanzeigen
KA_BASIS = "https://www.kleinanzeigen.de"
KA_SUCHE = KA_BASIS + "/s-pc-zubehoer-software/{seite}ddr5/k0c225"      # Kategorie PC-Zubehör & Software
_ARTIKEL = re.compile(r'<article[^>]*\bdata-adid="(\d+)"[^>]*\bdata-href="([^"]+)"[^>]*>(.*?)</article>', re.S)
_LDJSON = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.S)
_H3 = re.compile(r"<h3[^>]*>(.*?)</h3>", re.S)
_PREIS = re.compile(r"^(?:([\d.]+(?:,\d{1,2})?)\s*€)?\s*(VB)?$")
_PLZ = re.compile(r"^\d{5}\s")


def _texte(fragment: str) -> list[str]:
    ohne = re.sub(r"<script.*?</script>|<svg.*?</svg>|<style.*?</style>", "", fragment, flags=re.S)
    return [html.unescape(x).strip() for x in re.split(r"<[^>]+>", ohne) if x.strip()]


def _zahl(s: str) -> float:
    return float(s.replace(".", "").replace(",", "."))


def parse_kleinanzeigen(seite: str) -> list[Anzeige]:
    out = []
    for adid, href, body in _ARTIKEL.findall(seite):
        h3 = _H3.search(body)
        titel = " ".join(_texte(h3.group(1))) if h3 else ""
        beschreibung = ""
        m = _LDJSON.search(body)
        if m:
            try:
                ld = json.loads(m.group(1))
                titel = titel or ld.get("title", "")
                beschreibung = ld.get("description", "") or ""
            except json.JSONDecodeError:
                pass
        texte = _texte(body)
        preis, vb = None, False
        for t in texte:
            pm = _PREIS.match(t)
            if pm and (pm.group(1) or pm.group(2)):      # erster Preis = aktueller (danach ggf. durchgestrichener alter)
                preis = _zahl(pm.group(1)) if pm.group(1) else None
                vb = bool(pm.group(2))
                break
        if not beschreibung:                              # ohne Bild kein ld+json: sichtbaren Anrisstext nehmen
            nach_titel = texte[texte.index(titel) + 1:] if titel in texte else []
            beschreibung = nach_titel[0] if nach_titel and not _PREIS.match(nach_titel[0]) else ""
        a = Anzeige("kleinanzeigen", adid, titel, KA_BASIS + href, preis, beschreibung=beschreibung, vb=vb,
                    ort=next((t for t in texte if _PLZ.match(t)), ""), gesuch="Gesuch" in texte,
                    gewerblich="PRO" in texte, direkt_kaufen="Direkt kaufen" in texte,
                    versand_moeglich="Versand möglich" in texte)
        out.append(a)
    return out


class Kleinanzeigen:
    name = "kleinanzeigen"

    def __init__(self, seiten: int = 3, session: requests.Session | None = None, pause=(4.0, 8.0), schlafen=time.sleep):
        self.seiten = seiten
        self.s = session or requests.Session()
        self.pause = pause
        self.schlafen = schlafen

    def holen(self, erster_lauf: bool = False) -> list[Anzeige]:
        seiten = max(self.seiten, 10) if erster_lauf else self.seiten     # erster Lauf: Marktpreis aufbauen
        alle: dict[str, Anzeige] = {}
        for n in range(1, seiten + 1):
            if n > 1:
                self.schlafen(random.uniform(*self.pause))
            url = KA_SUCHE.format(seite="" if n == 1 else f"seite:{n}/")
            try:
                r = self.s.get(url, headers=BROWSER_KOPF, timeout=25)
            except requests.RequestException as e:
                if n == 1:
                    raise QuelleFehler(f"Kleinanzeigen nicht erreichbar: {e}") from e
                logger.warning("Kleinanzeigen Seite %d: %s", n, e)
                break
            if r.status_code in (403, 429) or "captcha" in r.text[:20000].lower():
                if n == 1:
                    raise QuelleFehler(f"Kleinanzeigen sperrt den Abruf (HTTP {r.status_code})")
                logger.warning("Kleinanzeigen Seite %d gesperrt (HTTP %d), Rest übersprungen", n, r.status_code)
                break
            if r.status_code != 200:
                if n == 1:
                    raise QuelleFehler(f"Kleinanzeigen HTTP {r.status_code}")
                break
            neu = parse_kleinanzeigen(r.text)
            if not neu:
                if n == 1:
                    raise QuelleFehler("Kleinanzeigen: keine Anzeigen gefunden (Seitenaufbau geändert?)")
                break
            for a in neu:
                alle.setdefault(a.id, a)
        return list(alle.values())


# --------------------------------------------------------------------------------------------------------------- eBay
EBAY_TOKEN = "https://api.ebay.com/identity/v1/oauth2/token"
EBAY_SUCHE = "https://api.ebay.com/buy/browse/v1/item_summary/search"


def _iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def ebay_anzeige(it: dict) -> Anzeige:
    optionen = it.get("buyingOptions") or []
    auktion = "AUCTION" in optionen and "FIXED_PRICE" not in optionen
    preis_feld = it.get("currentBidPrice") if auktion and it.get("currentBidPrice") else it.get("price")
    preis = float(preis_feld["value"]) if preis_feld and preis_feld.get("currency", "EUR") == "EUR" else None
    versand = None
    for opt in it.get("shippingOptions") or []:
        kosten = opt.get("shippingCost")
        if kosten and kosten.get("currency", "EUR") == "EUR":
            versand = float(kosten["value"])
            break
    ort = it.get("itemLocation") or {}
    verk = it.get("seller") or {}
    prozent = verk.get("feedbackPercentage")
    return Anzeige(
        "ebay", it["itemId"], it.get("title", ""), it.get("itemWebUrl", ""), preis,
        beschreibung=it.get("shortDescription", "") or "", versand=versand, vb="BEST_OFFER" in optionen,
        ort=" ".join(x for x in (ort.get("postalCode", ""), ort.get("city", "")) if x), versand_moeglich=True,
        auktion=auktion, endet=_iso(it.get("itemEndDate")), gebote=it.get("bidCount"),
        bewertungen=verk.get("feedbackScore"), bewertung_prozent=float(prozent) if prozent else None,
        defekt=str(it.get("conditionId", "")) == "7000")


class Ebay:
    name = "ebay"

    def __init__(self, client_id: str, client_secret: str, kategorie: str = "170083", laender: str = "DE",
                 session: requests.Session | None = None):
        self.client_id, self.client_secret = client_id, client_secret
        self.kategorie, self.laender = kategorie, laender
        self.s = session or requests.Session()
        self._token: str | None = None

    def _anmelden(self) -> str:
        if self._token:
            return self._token
        try:
            r = self.s.post(EBAY_TOKEN, auth=(self.client_id, self.client_secret), timeout=25,
                            data={"grant_type": "client_credentials", "scope": "https://api.ebay.com/oauth/api_scope"})
        except requests.RequestException as e:
            raise QuelleFehler(f"eBay-Anmeldung nicht erreichbar: {e}") from e
        if r.status_code != 200:
            raise QuelleFehler(f"eBay-Anmeldung abgelehnt (HTTP {r.status_code}) -- Schlüssel prüfen")
        self._token = r.json()["access_token"]
        return self._token

    def _suche(self, sort: str, optionen: str, limit: int, offset: int = 0) -> list[dict]:
        filt = [f"buyingOptions:{{{optionen}}}", "priceCurrency:EUR", "price:[40..3000]"]
        if self.laender:
            filt.append(f"itemLocationCountry:{self.laender}")
        params = {"q": "ddr5", "sort": sort, "limit": limit, "offset": offset, "filter": ",".join(filt)}
        if self.kategorie:
            params["category_ids"] = self.kategorie
        kopf = {"Authorization": f"Bearer {self._anmelden()}", "X-EBAY-C-MARKETPLACE-ID": "EBAY_DE",
                "Accept-Language": "de-DE"}
        try:
            r = self.s.get(EBAY_SUCHE, params=params, headers=kopf, timeout=25)
        except requests.RequestException as e:
            raise QuelleFehler(f"eBay-Suche nicht erreichbar: {e}") from e
        if r.status_code != 200:
            raise QuelleFehler(f"eBay-Suche HTTP {r.status_code}: {r.text[:200]}")
        return r.json().get("itemSummaries") or []

    def holen(self, erster_lauf: bool = False) -> list[Anzeige]:
        items = []
        for offset in range(0, 400 if erster_lauf else 200, 200):
            items += self._suche("newlyListed", "FIXED_PRICE|BEST_OFFER", 200, offset)
        items += self._suche("endingSoonest", "AUCTION", 100)
        alle: dict[str, Anzeige] = {}
        for it in items:
            try:
                a = ebay_anzeige(it)
            except (KeyError, TypeError, ValueError) as e:
                logger.warning("eBay-Angebot nicht lesbar (%s): %s", e, it.get("itemId"))
                continue
            alle.setdefault(a.id, a)
        return list(alle.values())

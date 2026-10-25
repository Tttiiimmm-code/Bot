"""RAM-Suche: Titelerkennung, Kleinanzeigen-/eBay-Auslesen, Marktpreis, Meldelogik (ohne Netz)."""

from datetime import datetime, timedelta, timezone

import pytest

from ramsuche import bot
from ramsuche.erkennung import pruefe
from ramsuche.quellen import Anzeige, Kleinanzeigen, QuelleFehler, ebay_anzeige, parse_kleinanzeigen

JETZT = datetime(2026, 10, 25, 20, 0, tzinfo=timezone.utc)


# ----------------------------------------------------------------------------------------------------- Erkennung
@pytest.mark.parametrize("titel, anzahl, riegel, gesamt", [
    ("G.Skill Trident Z5 Neo RGB 64GB (2x32GB) DDR5-6000 CL30", 2, 32, 64),
    ("Corsair vengeance 32GB DDR5-6000 RGB 2x16 Weiß White", 2, 16, 32),
    ("SK hynix 64 GB DDR5 RAM (2×32 GB) 5600 MT/s CL46 UDIMM", 2, 32, 64),
    ("2x SK Hynix 16 GB DDR5 RAM Riegel", 2, 16, 32),
    ("Kingston Fury Beast DDR5 16GBx2 6000", 2, 16, 32),
    ("Corsair Vengeance RGB DDR5 48GB (2x24GB) 5600 MHz CL40 Kit", 2, 24, 48),
    ("Crucial 32GB DDR5 5600 Einzelriegel", None, None, 32),
    ("1x 32GB DDR5 Kingston", 1, 32, 32),
])
def test_kapazitaet_passt(titel, anzahl, riegel, gesamt):
    e = pruefe(titel)
    assert e.passt, e.grund
    assert (e.anzahl, e.riegel_gb, e.gesamt_gb) == (anzahl, riegel, gesamt)


@pytest.mark.parametrize("titel, grund", [
    ("2x 8GB Crucial DDR5 RAM Arbeitsspeicher", "nur 16 GB"),
    ("2x8 Vulcan DDR5 5600mhz cl40", "nur 16 GB"),
    ("4x8GB DDR5 Kit 6000", "Riegel zu klein (4x8 GB)"),
    ("2x G.Skill Ripjaws DDR5 32GB SO-DIMM Kits (insg. 64GB)", "Laptop-RAM (SO-DIMM)"),
    ("Crucial 32GB DDR5-5600 SODIMM", "Laptop-RAM (SO-DIMM)"),
    ("Samsung 32GB DDR5 4800 ECC RDIMM", "Server-RAM (ECC/RDIMM)"),
    ("Suche DDR5 RAM – 32 GB (2×16 GB) UDIMM", "Gesuch/Ankauf"),
    ("RAM/SSD Ankauf DDR4/DDR5 SODIMM/UDIMM", "Gesuch/Ankauf"),
    ("Corsair 32GB DDR4 3200 (2x16)", "DDR4"),
    ("Gaming PC, RTX 5060ti 16GB, 32GB DDR5, Ryzen 5 7600x", "Bundle/Komplett-PC"),
    ("MSI X870e Godlike Mainboard AM5 AMD DDR5 guter Zustand", "Bundle/Komplett-PC"),
    ("G.Skill 32GB DDR5 2x16 defekt", "defekt/ungetestet"),
    ("Corsair Vengeance 32GB (2x16GB) 6000", "kein DDR5 erkennbar"),
])
def test_abgelehnt(titel, grund):
    e = pruefe(titel)
    assert not e.passt and e.grund == grund


def test_verneinungen_lehnen_nicht_ab():
    assert pruefe("Kingston 32GB (2x16GB) DDR5 6000 Non-ECC UDIMM").passt
    assert pruefe("G.Skill 2x16GB DDR5 On-Die ECC Desktop").passt


def test_amd_ryzen_im_titel_ohne_modell_ist_kein_bundle():
    assert pruefe("G.Skill Flare X5 32GB (2x16GB) DDR5-6000 CL30 für AMD Ryzen EXPO").passt


def test_beschreibung_fuellt_aufteilung_und_ddr5():
    e = pruefe("Corsair Vengeance 32GB 6000", "Verkaufe mein DDR5 Kit 2x16GB, läuft mit EXPO.")
    assert e.passt and (e.anzahl, e.riegel_gb) == (2, 16)
    e = pruefe("32GB DDR5 RAM", "")
    assert e.passt and any("Aufteilung" in h for h in e.hinweise)


def test_takt_cl_und_hinweise():
    e = pruefe("Kingston 32GB (2x16GB) DDR5-4800 CL40")
    assert (e.takt, e.cl) == (4800, 40) and any("langsam" in h for h in e.hinweise)
    assert pruefe("64 GB DDR5 T-Create PC5-51200 CL32 2x32").takt == 6400
    e = pruefe("Corsair 32GB (2x16) DDR5 6000", "Lief im Laptop? Nein, Desktop. Leider ungetestet.")
    assert any("Defekt" in h for h in e.hinweise)


# ------------------------------------------------------------------------------------------------- Kleinanzeigen
def _artikel(adid, titel, preis_text, extra=(), beschreibung="Beschreibung", bild=True):
    ld = (f'<script type="application/ld+json">{{"title":"{titel}","description":"{beschreibung}",'
          f'"@type":"ImageObject"}}</script>') if bild else ""
    extras = "".join(f"<span>{x}</span>" for x in extra)
    return (f'<article class="flex" data-adid="{adid}" data-href="/s-anzeige/x/{adid}-225-1"><div>{ld}'
            f'<svg><path d="M1"></path></svg><span>10551 Mitte</span></div><span>Heute, 16:54</span>'
            f'<h3 class="x"><a href="/s-anzeige/x/{adid}-225-1">{titel}</a></h3><p>{beschreibung}</p>'
            f'<p class="price">{preis_text}</p>{extras}</article>')


def test_parse_kleinanzeigen():
    seite = "<html>" + "".join([
        _artikel("1", "Corsair 32GB DDR5-6000 2x16", "530 €", ["Versand möglich", "Direkt kaufen"]),
        _artikel("2", "G.Skill 64GB (2x32GB) DDR5", "899 € VB", ["999 €", "Versand möglich"]),
        _artikel("3", "Suche DDR5", "VB", ["Gesuch"]),
        _artikel("4", "Händler 32GB DDR5", "1.250 €", ["PRO"], bild=False, beschreibung="Neuware 2x16GB"),
    ]) + "</html>"
    a = {x.id: x for x in parse_kleinanzeigen(seite)}
    assert a["1"].titel == "Corsair 32GB DDR5-6000 2x16" and a["1"].preis == 530 and not a["1"].vb
    assert a["1"].direkt_kaufen and a["1"].versand_moeglich and a["1"].ort == "10551 Mitte"
    assert a["1"].url == "https://www.kleinanzeigen.de/s-anzeige/x/1-225-1"
    assert a["2"].preis == 899 and a["2"].vb                       # alter durchgestrichener Preis zählt nicht
    assert a["3"].preis is None and a["3"].gesuch
    assert a["4"].preis == 1250 and a["4"].gewerblich and a["4"].beschreibung == "Neuware 2x16GB"


class _Antwort:
    def __init__(self, status, text):
        self.status_code, self.text = status, text


class _Sitzung:
    def __init__(self, antworten):
        self.antworten, self.urls = list(antworten), []

    def get(self, url, **kw):
        self.urls.append(url)
        return self.antworten.pop(0)


def test_kleinanzeigen_sperre_wird_gemeldet_nicht_umgangen():
    q = Kleinanzeigen(seiten=3, session=_Sitzung([_Antwort(403, "Zugriff verweigert")]), schlafen=lambda s: None)
    with pytest.raises(QuelleFehler, match="sperrt"):
        q.holen()
    assert len(q.s.urls) == 1                                      # kein weiterer Versuch


def test_kleinanzeigen_seiten_und_erster_lauf():
    seite = "<html>" + _artikel("1", "Corsair 32GB DDR5 2x16", "300 €") + "</html>"
    s = _Sitzung([_Antwort(200, seite)] * 10)
    pausen = []
    q = Kleinanzeigen(seiten=3, session=s, schlafen=pausen.append)
    assert [a.id for a in q.holen()] == ["1"]
    assert s.urls[0].endswith("/s-pc-zubehoer-software/ddr5/k0c225") and "seite:3/" in s.urls[2]
    assert len(pausen) == 2 and all(4 <= p <= 8 for p in pausen)
    s2 = _Sitzung([_Antwort(200, seite)] * 10)
    Kleinanzeigen(seiten=3, session=s2, schlafen=lambda p: None).holen(erster_lauf=True)
    assert len(s2.urls) == 10


# ----------------------------------------------------------------------------------------------------------- eBay
def test_ebay_anzeige_festpreis_und_auktion():
    a = ebay_anzeige({"itemId": "v1|1|0", "title": "Kingston Fury 32GB (2x16GB) DDR5-6000", "itemWebUrl": "https://e/1",
                      "price": {"value": "250.00", "currency": "EUR"}, "buyingOptions": ["FIXED_PRICE", "BEST_OFFER"],
                      "shippingOptions": [{"shippingCost": {"value": "4.99", "currency": "EUR"}}],
                      "seller": {"feedbackScore": 3, "feedbackPercentage": "100.0"}, "conditionId": "3000"})
    assert (a.preis, a.versand, a.vb, a.auktion, a.bewertungen, a.defekt) == (250.0, 4.99, True, False, 3, False)
    b = ebay_anzeige({"itemId": "v1|2|0", "title": "x", "buyingOptions": ["AUCTION"], "bidCount": 4,
                      "price": {"value": "1.00", "currency": "EUR"}, "currentBidPrice": {"value": "120", "currency": "EUR"},
                      "itemEndDate": "2026-10-25T21:00:00.000Z", "conditionId": "7000"})
    assert b.auktion and b.preis == 120 and b.endet == datetime(2026, 10, 25, 21, tzinfo=timezone.utc) and b.defekt


# --------------------------------------------------------------------------------------------- Marktpreis, Lauf
class _Quelle:
    name = "kleinanzeigen"

    def __init__(self, anzeigen=None, fehler=None):
        self.anzeigen, self.fehler, self.erster = anzeigen or [], fehler, None

    def holen(self, erster_lauf=False):
        self.erster = erster_lauf
        if self.fehler:
            raise QuelleFehler(self.fehler)
        return self.anzeigen


class _Notifier:
    def __init__(self, ok=True):
        self.ok, self.gesendet = ok, []

    @property
    def enabled(self):
        return True

    def send(self, title, message, priority="default", tags=""):
        self.gesendet.append((title, message, priority))
        return self.ok


def _markt(n=10, preis=400.0):
    return [Anzeige("kleinanzeigen", f"m{i}", "Corsair 32GB (2x16GB) DDR5-6000", f"https://k/m{i}", preis + i,
                    versand_moeglich=True) for i in range(n)]


def test_marktpreis_braucht_genug_werte():
    db = bot.verbinden(":memory:")
    bot.lauf(db, [_Quelle(_markt(5))], bot.Einstellungen(), _Notifier(), JETZT)
    assert bot.marktpreis(db, 32, JETZT) == (None, 5)
    bot.lauf(db, [_Quelle(_markt(10))], bot.Einstellungen(), _Notifier(), JETZT)
    m, n = bot.marktpreis(db, 32, JETZT)
    assert n == 10 and m == pytest.approx(404.5 / 32)
    assert bot.marktpreis(db, 32, JETZT + timedelta(days=15)) == (None, 0)     # alte Anzeigen zählen nicht


def test_lauf_meldet_schnaeppchen_einmal_und_nach_preissenkung():
    db = bot.verbinden(":memory:")
    billig = Anzeige("kleinanzeigen", "b1", "G.Skill Flare X5 32GB (2x16GB) DDR5-6000 CL30", "https://k/b1", 280.0,
                     versand_moeglich=True, direkt_kaufen=True)
    teuer = Anzeige("kleinanzeigen", "t1", "Corsair 32GB (2x16GB) DDR5", "https://k/t1", 390.0, versand_moeglich=True)
    n = _Notifier()
    treffer = bot.lauf(db, [_Quelle(_markt() + [billig, teuer])], bot.Einstellungen(), n, JETZT)
    assert [t.anzeige.id for t in treffer] == ["b1"]
    titel, text, prio = n.gesendet[0]
    assert titel.startswith("RAM: 32 GB DDR5 fuer 280 EUR") and "Direkt kaufen" in text and "https://k/b1" in text
    assert "Weiterverkauf grob" in text and prio == "high"          # über 30 % unter Markt
    assert bot.lauf(db, [_Quelle(_markt() + [billig])], bot.Einstellungen(), n, JETZT) == []   # nicht doppelt
    billig.preis = 240.0
    t2 = bot.lauf(db, [_Quelle(_markt() + [billig])], bot.Einstellungen(), n, JETZT)
    assert len(t2) == 1 and t2[0].preissenkung and n.gesendet[-1][0].startswith("Preis gesenkt")


def test_fehlgeschlagene_meldung_wird_wiederholt():
    db = bot.verbinden(":memory:")
    billig = Anzeige("kleinanzeigen", "b1", "Corsair 32GB (2x16GB) DDR5", "https://k/b1", 250.0)
    assert len(bot.lauf(db, [_Quelle(_markt() + [billig])], bot.Einstellungen(), _Notifier(ok=False), JETZT)) == 1
    assert len(bot.lauf(db, [_Quelle(_markt() + [billig])], bot.Einstellungen(), _Notifier(), JETZT)) == 1


def test_sehr_billig_warnt_vor_betrug_und_auktion_erst_kurz_vor_ende():
    cfg = bot.Einstellungen()
    e = pruefe("Corsair 32GB (2x16GB) DDR5")
    a = Anzeige("kleinanzeigen", "x", "Corsair 32GB (2x16GB) DDR5", "u", 150.0)
    t = bot.bewerte(a, e, 12.5, cfg, JETZT)
    assert t and "Betrug" in t.warnungen[0] and "nur Abholung" in t.warnungen
    auk = Anzeige("ebay", "y", "Corsair 32GB (2x16GB) DDR5", "u", 150.0, versand=5.0, auktion=True, gebote=3,
                  endet=JETZT + timedelta(hours=5))
    assert bot.bewerte(auk, e, 12.5, cfg, JETZT) is None
    auk.endet = JETZT + timedelta(minutes=30)
    t = bot.bewerte(auk, e, 12.5, cfg, JETZT)
    assert t and t.kaufpreis == 155.0 and any("Auktion" in w for w in t.warnungen)


def test_gesuch_defekt_und_platzhalterpreis_zaehlen_nicht():
    db = bot.verbinden(":memory:")
    e = pruefe("Corsair 32GB (2x16GB) DDR5")
    for i, a in enumerate([Anzeige("kleinanzeigen", "g", "x", "u", 100.0, gesuch=True),
                           Anzeige("ebay", "d", "x", "u", 100.0, defekt=True),
                           Anzeige("kleinanzeigen", "p", "x", "u", 1.0)]):
        bot.speichern(db, a, e, JETZT)
        assert bot.bewerte(a, e, 12.5, bot.Einstellungen(), JETZT) is None
    assert db.execute("SELECT SUM(passt) FROM anzeigen").fetchone()[0] == 0


def test_quellenausfall_ab_drittem_mal_gemeldet():
    db = bot.verbinden(":memory:")
    n = _Notifier()
    for _ in range(4):
        bot.lauf(db, [_Quelle(fehler="Kleinanzeigen sperrt den Abruf (HTTP 403)")], bot.Einstellungen(), n, JETZT)
    assert len(n.gesendet) == 1 and "liefert nichts" in n.gesendet[0][0]
    bot.lauf(db, [_Quelle(_markt(1))], bot.Einstellungen(), n, JETZT)
    assert "geht wieder" in n.gesendet[-1][0]


def test_erster_lauf_je_quelle():
    db = bot.verbinden(":memory:")
    q = _Quelle(_markt(2))
    bot.lauf(db, [q], bot.Einstellungen(), _Notifier(), JETZT)
    assert q.erster is True
    bot.lauf(db, [q], bot.Einstellungen(), _Notifier(), JETZT)
    assert q.erster is False


def test_einstellungen_aus_env_und_liste():
    cfg = bot.Einstellungen.aus_env({"RABATT": "0.3", "MAX_EUR_PRO_GB": "8", "KA_SEITEN": "2", "MIN_GB": ""})
    assert (cfg.rabatt, cfg.max_eur_pro_gb, cfg.ka_seiten, cfg.min_gb) == (0.3, 8.0, 2, 32)
    db = bot.verbinden(":memory:")
    bot.lauf(db, [_Quelle(_markt())], bot.Einstellungen(), _Notifier(), JETZT)
    text = bot.liste(db, JETZT)
    assert "32 GB:   10 Anzeigen" in text and "https://k/m0" in text

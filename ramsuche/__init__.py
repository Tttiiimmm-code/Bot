"""RAM-Suche: findet günstigen Desktop-DDR5-RAM (ab 32 GB, Riegel ab 16 GB) auf Kleinanzeigen und eBay.

Kein Trading-Bot und kein Kauf: der Bot sucht nur, bewertet gegen den selbst gemessenen Marktpreis (Median Euro/GB der
letzten 14 Tage) und meldet Ausreißer per ntfy. Gekauft wird von Hand.

Aufruf (aus dem Projektordner): `python -m ramsuche lauf | liste | meldung-test`, Einstellungen in `ramsuche.env`
(Vorlage `ramsuche.env.example`).
"""

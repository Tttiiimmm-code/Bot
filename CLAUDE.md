# Trading-Bot-Projekt

Ziel des Nutzers: ein selbst entwickelter oder nachgebauter Bot / eine Strategie, die nach Kosten **mehr als ein
S&P-500-ETF** bringt. Kein Kauf fremder Bots. Antworten auf Deutsch, ehrlich, mit Zahlen; Misserfolge klar benennen.

## Feste Regeln (nie ohne ausdrückliche Zustimmung ändern)

- **Nur Papiergeld.** Alle Bots auf Paper-/Demokonten; Live-Konten werden im Code abgelehnt (Alpaca `ALPACA_PAPER`,
  MT5-EA `AllowLive=false`). Keine Funktion bauen, die echtes Geld bewegt.
- **Schlüssel/Passwörter nie ausgeben** (nur Variablennamen). Zugangsdaten trägt der Nutzer selbst ein.
- **Keine Emojis** in GUI, Code-Texten oder Chat (Streamlit: Material-Icons `:material/...:`).
- **Maßstab ETF:** Eine Strategie zählt nur, wenn sie nach Kosten den S&P 500 schlägt. Die gemeinsame
  Vorwärtstest-Regel bleibt streng (Nutzer: "lass es streng").
- **Momentum-Bot:** während des Vorwärtstests keine Parameteränderungen; nur bei RAM-Not anhalten.
- `/opt/ict-bot` auf dem VPS nicht anfassen.
- Keine Memecoins/neuen Listings, keine Prognosemärkte (Polymarket in DE illegal).
- API-lastige Arbeit auf dem VPS erst nach 17:30 deutscher Zeit (Bots handeln bis dahin).

## Forschungsprotokoll (Branch `research/ideas`, Datei `research/PROTOCOL.md`)

1. Regeln, Zeiträume, Kosten und Bestehenskriterium **vorab** ins Protokoll schreiben, committen und pushen, bevor
   Ergebnisse angesehen werden.
2. Skript `research/scripts/rNNN.py`, Ausgabe `rNNN_output.txt`; Ergebnis ins Protokoll, committen, pushen.
3. Kriterien: Hauptzeitraum Rendite > SPY und t (monatliche Überrendite) >= Hürde (Bonferroni bei mehreren
   Thesen), Einordnungszeitraum ebenfalls positiv. Nachträgliche Varianten nur "zur Info", nie als Ergebnis.
4. Arbeiten in einem temporären Worktree im Scratchpad (`git worktree add <scratchpad>/wt_ideas research/ideas`),
   danach `git worktree remove`.
5. Was bereits getestet wurde, steht im Protokoll -- vor einer neuen Runde dort suchen (über 140 Runden).

## Laufende Vorwärtstests und Bots

- `tradingbot/forward_status.py`: gemeinsame Regel K=11 (Auswertung 2027-10-01 / 2028-10-01), eigene Familien
  `gold_breakout` (2028-10-01) und `pelosi_copy` (2029-10-01). Ein bindender Blick, nicht vorher entscheiden.
- VPS-Dienste: momentum, overnight (Dry-Run seit 2026-10-02), liq-recorder, copilot-gui, copilot-watch, pelosi-bot.
  Timer: forward-test, forward-stocks, forward-status, forward-gold, forward-pelosi, momentum-checkpoint, health,
  backup-data. Konten: `.env` (Momentum), `overnight.env` (Overnight-Dry-Run + Pelosi-Bot), `copilot.env`.
- MT5-EA `mql5/GoldBreakout.mq5` läuft auf dem PC des Nutzers (OANDA-Demo). Kompilieren:
  `MetaEditor64.exe /compile:"..." /log:"..."`.

## VPS

- `ssh root@116.203.115.99`, Repo `/home/tradingbot/Bot` (User `tradingbot`), Branch `feature/forward-test`.
- Deploy: lokal committen und pushen, dann `sudo -u tradingbot git pull`, Unit-Dateien aus `deploy/` nach
  `/etc/systemd/system`, `systemctl daemon-reload`, Dienst neu starten. Nicht schnell hintereinander neu starten
  (StartLimit; falls ausgelöst: `systemctl reset-failed <dienst>`).
- Neue Abhängigkeiten in `requirements.txt` eintragen und auf dem VPS installieren.
- Neue Dienste/Timer in `tradingbot/health.py` (SERVICES/ONESHOTS) und neue Datendateien in
  `deploy/backup-data.sh` und `.gitignore` aufnehmen.

## Code-Konventionen

- Python 3.14, Windows + Git Bash lokal; Tests: `.venv/Scripts/python -m pytest tests/ -q -p no:warnings`.
- Kommentare, Docstrings, Log- und GUI-Texte auf Deutsch, im Stil des umgebenden Codes.
- Jede Fehlerbehebung bekommt einen Regressionstest. Nach neuen Bots, die Orders senden: Code-Review laufen lassen.
- Order-Bots: Zustand sofort nach jeder abgeschickten Order speichern (kein Doppelkauf nach Teil-Fehlern);
  vorübergehende API-Fehler dürfen Signale nicht endgültig verwerfen.
- Commit-Nachrichten auf Deutsch, beschreibend.

## Daten-Fallstricke (teuer gelernt)

- Dukascopy-Minuten (`data_cache/dukascopy`): jahresweise als float32 laden, nur ein Download gleichzeitig
  (Speicher), abgeschnittene Dateien erkennen und neu laden.
- `pd.to_datetime(unit="ms")` behält ms-Auflösung -> `.as_unit("ns").asi8` vor Vergleichen mit ns-Werten.
- Stop-Einstiege nie mit H1-Kerzen simulieren (zählt Tiefs vor dem Ausbruch) -- immer M1.
- Yahoo vergibt alte Ticker neu ("FB" ist nicht Meta): bekannte Umbenennungen abbilden (FB->META, SQ->XYZ).
- SEC EDGAR: max. 10 Anfragen/s (sonst 10 Minuten Sperre), Range-Header wird ignoriert -> nur `*.hdr.sgml` laden,
  gedrosselt. `company_tickers.json` kennt nur heutige Ticker (Survivorship benennen).
- House-Meldungen: `disclosures-clerk.house.gov/public_disc/financial-pdfs/YYYYFD.zip` (+ PTR-PDFs), Senat:
  efdsearch.senate.gov (Nutzungsbedingungen per POST akzeptieren).
- Alpaca-Tagespanel `data_cache/universe/daily`: split-bereinigt ohne Dividenden, enthält delistete Titel, aber
  inaktive Titel ohne Namen (ETF-Filter greift dort nicht).
- Alpaca-Paper führt Auktionsorders (CLS/OPG) kaum aus -> Marktorders kurz vor Schluss oder Dry-Run.

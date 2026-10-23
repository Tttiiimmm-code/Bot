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
- Memecoins dürfen untersucht werden; Sorge des Nutzers ist ein Rug Pull (Team/Insider ziehen Liquidität ab oder
  verkaufen alles). Jeder Vorschlag muss dieses Risiko ausdrücklich behandeln (Alter, Liquidität, gesperrte
  Liquidität, Konzentration der Halter, Delisting-/Absturzquote im Backtest). Keine Prognosemärkte (Polymarket in
  DE illegal).
- API-lastige Arbeit auf dem VPS erst nach 17:30 deutscher Zeit (Bots handeln bis dahin).

## Forschungsprotokoll (Branch `research/ideas`, Datei `research/PROTOCOL.md`)

1. Regeln, Zeiträume, Kosten und Bestehenskriterium **vorab** ins Protokoll schreiben, committen und pushen, bevor
   Ergebnisse angesehen werden.
2. Skript `research/scripts/rNNN.py`, Ausgabe `rNNN_output.txt`; Ergebnis ins Protokoll, committen, pushen.
3. Kriterien: Hauptzeitraum Rendite > SPY und t (monatliche Überrendite) >= Hürde (Bonferroni bei mehreren
   Thesen), Einordnungszeitraum ebenfalls positiv. Nachträgliche Varianten nur "zur Info", nie als Ergebnis.
4. Arbeiten in einem temporären Worktree im Scratchpad (`git worktree add <scratchpad>/wt_ideas research/ideas`),
   danach `git worktree remove`.
5. Was bereits getestet wurde, steht im Protokoll -- vor einer neuen Runde dort suchen (über 170 Runden).
6. Werkzeug (seit 2026-10-24): `python tools/runde.py status | neu NNN "Titel" --vorab f.md --wt <scratchpad>/wt_ideas
   | rechnen NNN | abschluss NNN --ergebnis f.md --aufraeumen` (Vorab pushen, Rechnen erst danach, Ergebnis, Vault-
   Notizen + Linkcheck, Worktree weg). Skripte ab Runde 171 werten mit `research/scripts/rlib.py` aus (`judge`,
   `hurdle(k)`, letzte Zeile `URTEIL: ...`), Vorlage `_vorlage.py`. Commit-Zusatzzeile über `RUNDE_COMMIT_TRAILER`.

## Obsidian-Vault (2. Gehirn, `C:\Users\Nutzer\Trading-Bot-Vault`)

Nutzer (2026-10-18): "ab jetzt soll im Vault immer mitgeschrieben werden, wenn es neue Infos gibt, er ist unser
2. Gehirn und dient als Datensammlung". **Sitzungsbeginn: `00 Kontext.md` im Vault lesen** (Momentaufnahme: was
läuft, offene Entscheidungen, nächste Rundennummer, wo nachschlagen). **Verbindliche Anleitung: Vault-Notiz `01 Projekt/Dokumentationsregeln.md`
(vor dem ersten Schreiben einer Sitzung lesen), Vorlagen in `_vorlagen/`.** Umfang: **nur was die Tradingbots, ihre
Strategien, Vorwärtstests, Forschung, Konten und Datenquellen betrifft** -- keine Claude-Code-/Werkzeug-Einstellungen
oder PC-Kleinkram (außer es betrifft einen Bot/Test direkt). Kurzfassung -- in **jeder** Sitzung, sobald es solche
neuen Infos gibt (nicht erst am Ende):
- `08 Logbuch/JJJJ-MM-TT.md` anlegen bzw. ergänzen: was getan, Ergebnisse mit Zahlen, Entscheidungen des Nutzers,
  neue Probleme, Commits. Kurz, sachlich, mit `[[Links]]` auf die betroffenen Notizen.
- Betroffene Fachnotizen aktualisieren (Bots, Vorwärtstests, Betrieb, Daten, Termine/offene Aufgaben, Zeitleiste,
  Erkenntnisse); neue Themen als neue Notiz im passenden Ordner, verlinkt von `00 Start.md` oder einer Übersicht.
- Nach jeder Forschungsrunde: `python -I <vault>/_werkzeug/vault_gen.py <worktree>/research/PROTOCOL.md <vault>`
  (Urteile unklarer Runden im `OVERRIDE` des Skripts eintragen), danach `python -I <vault>/_werkzeug/linkcheck.py <vault>`.
- Am Ende: `00 Kontext.md` (`stand` + geänderte Zeilen) aktualisieren. Kurz halten, ein Ort pro Fakt, Kopfzeilen
  `typ`/`status`/`stand` pflegen (Regel 9 der Dokumentationsregeln).
- Keine Schlüssel/Passwörter, keine Emojis; Deutsch.

## Laufende Vorwärtstests und Bots

- `tradingbot/forward_status.py`: gemeinsame Regel K=11 (Auswertung 2027-10-01 / 2028-10-01), eigene Familien
  `gold_breakout` (2028-10-01) und `pelosi_copy` (2029-10-01). Ein bindender Blick, nicht vorher entscheiden.
- Minuten-Vorwärtstests (nikkei_night, gotobi, gotobi_eurjpy ab 2026-10-08, gold_breakout) rechnen aus Yahoo
  (`intraday_backup`: 1m, Lücken 5m, Gold-/Nikkei-Einzelkontrakte verkettet). Dukascopy für Vorwärtstests aufgegeben
  (Nutzer 2026-10-20); Kontraktwechsel Gold 20. des Vormonats der Lieferung, Nikkei 1. des Verfallsmonats.
- VPS-Dienste: momentum, overnight (Dry-Run seit 2026-10-02), liq-recorder, copilot-gui, copilot-watch, pelosi-bot.
  Timer: forward-test, forward-stocks, forward-status, forward-gold, forward-pelosi, momentum-checkpoint, health,
  backup-data. Konten: `.env` (Momentum), `overnight.env` (Overnight-Dry-Run + Pelosi-Bot), `copilot.env`.
- MT5-EA `mql5/GoldBreakout.mq5` läuft seit 2026-10-20 auf dem VPS (MT5 unter Wine, Dienste `mt5-display`/`mt5`,
  Benutzer `mt5`, `C:\MT5`, Logs UTF-16 in `logs/` und `MQL5/logs/`; Ansicht per `MT5 VPS anzeigen.bat`), OANDA-Demo.
  PC-MT5 stillgelegt (Algo-Handel aus) -- nie beide gleichzeitig. Kompilieren am PC:
  `MetaEditor64.exe /compile:"..." /log:"..."`, `.ex5` nach `/home/mt5/.wine/drive_c/MT5/MQL5/Experts/` kopieren.

## VPS

- `ssh root@116.203.115.99`, Repo `/home/tradingbot/Bot` (User `tradingbot`), Branch `feature/forward-test`.
- Deploy: lokal committen und pushen, dann `ssh root@116.203.115.99 'bash /home/tradingbot/Bot/deploy/deploy.sh'`
  (Pull, geänderte Units kopieren + daemon-reload, pip bei geänderter requirements.txt, Neustart nur der Dauerdienste
  mit neuerem Code/Unit; handelnde nicht Mo-Fr 15:20-22:10 deutsche Zeit, außer `--jetzt`; am Ende `health --check`).
  Neue Units installiert es nicht (nur Hinweis). StartLimit ausgelöst: `systemctl reset-failed <dienst>`.
- Sitzungsstart: SessionStart-Hook (`.claude/hooks/vps_status.sh`, eingetragen in `.claude/settings.local.json`)
  liefert `main.py health --check` vom VPS. Probleme daraus zuerst dem Nutzer melden.
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
- Alpaca ebenso: AMTD-5-Minuten-Balken 2016-20 ~60x Tagespanel (heute AMTD IDEAL, andere Bereinigung). Bei
  gemischten Quellen Tagesschluss gegen letzten Intraday-Balken prüfen (Runde 152).
- SEC EDGAR: max. 10 Anfragen/s (sonst 10 Minuten Sperre), Range-Header wird ignoriert -> nur `*.hdr.sgml` laden,
  gedrosselt. `company_tickers.json` kennt nur heutige Ticker (Survivorship benennen).
- House-Meldungen: `disclosures-clerk.house.gov/public_disc/financial-pdfs/YYYYFD.zip` (+ PTR-PDFs), Senat:
  efdsearch.senate.gov (Nutzungsbedingungen per POST akzeptieren).
- Alpaca-Tagespanel `data_cache/universe/daily`: split-bereinigt ohne Dividenden, enthält delistete Titel, aber
  inaktive Titel ohne Namen (ETF-Filter greift dort nicht).
- Alpaca-Paper führt Auktionsorders (CLS/OPG) kaum aus -> Marktorders kurz vor Schluss oder Dry-Run.

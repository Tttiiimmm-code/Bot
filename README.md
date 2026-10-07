# Tradingbot-Projekt (Alpaca, OANDA, MT5) -- nur Papiergeld

Selbst entwickelte Bots und Strategie-Forschung mit einem einzigen Maßstab: **Eine Strategie zählt nur, wenn sie
nach Kosten mehr bringt als ein S&P-500-ETF (SPY).** Alles läuft auf Paper-/Demokonten; Live-Konten werden im Code
abgelehnt (Alpaca `ALPACA_PAPER=true`, OANDA `OANDA_PRACTICE=true`, MT5-EA `AllowLive=false`).

**Risikohinweis:** Automatisierter Handel kann zu Verlusten führen. Nichts hier ist Anlageberatung, und bisher ist
keine Strategie als besser als der ETF nachgewiesen (siehe unten).

## Stand (Oktober 2026)

**Forschung:** 148 vorregistrierte Runden (Branch `research/ideas`, `research/PROTOCOL.md`). Trendfolge,
Mean Reversion, Tageszeit-Effekte, Eröffnungsausbrüche (ORB), Krypto, Memecoins, Insider-/13D-/Kongress-Kopien,
Faktoren, Saisonalität, ML-Ranking, News, TikTok/YouTube- und MQL5-Nachbauten, gehebelte Mischungen: **keine
hat das Bestehenskriterium erreicht.** Robust, aber klein und kostenabhängig sind der Nikkei-Nachteffekt und
Gotobi (USD/JPY); beide laufen als Vorwärtstest.

**Vorwärtstests (Papier, eine bindende Auswertung zum festen Termin, vorher keine Entscheidung):**

| Test | Was | Auswertung |
|---|---|---|
| Gemeinsame Regel, K = 11 Hypothesen | Nikkei-Nacht, Gotobi, Gotobi EUR/JPY, Anleihen-Monatsende, ORB Top 5, Qualität Top 50, Small-Cap Value+Qualität u. a. | 2027-10-01 / 2028-10-01 |
| `gold_breakout` (eigene Familie) | Nachbau "The Gold Reaper", Runde 134 | 2028-10-01 |
| `pelosi_copy` (eigene Familie) | Pelosi-Käufe ab Meldung 12 Monate halten, Runde 141 | 2029-10-01 |
| Momentum-Bot | Prüfpunkte nach 100 und 150 Trades (`momentum-checkpoint`) | nach Trades |

Zwischenstand aller Tests: `python main.py forward-status` (nur Information).

**Was wo läuft:**

| Wo | Dienst | Zweck |
|---|---|---|
| VPS | `momentum` | Momentum-Day-Trading-Bot, Alpaca-Paper (`.env`), Vorwärtstest ohne Parameteränderung |
| VPS | `overnight` | Overnight-ETF-Portfolio, seit 2026-10-02 nur Dry-Run (`overnight.env`) |
| VPS | `pelosi-bot` | Pelosi-Kopier-Bot, Alpaca-Paper (Overnight-Konto) |
| VPS | `copilot-gui`, `copilot-watch` | Diskretionärer Trading-Copilot (Streamlit über Tailscale) und seine Sicherheitsüberwachung (`copilot.env`) |
| VPS | `liq-recorder` | Krypto-Liquidationen aufzeichnen (nur Daten) |
| VPS, Timer | `forward-test`, `forward-stocks`, `forward-gold`, `forward-pelosi`, `forward-status`, `momentum-checkpoint` | Vorwärtstests ohne Orders, Monatsstand per ntfy |
| VPS, Timer | `health`, `backup-data` | Wächter alle 10 Minuten, nächtliche Datensicherung |
| PC | `mql5/GoldBreakout.mq5` | Gold-Ausbruch als MT5-EA auf einem OANDA-Demokonto |
| PC | `Copilot starten.bat`, `VPS-Sicherung holen.bat` | Copilot öffnen (lokal oder VPS), Sicherungen nach `backups/` holen |

## Setup

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt        # Linux/VPS: .venv/bin/pip
.venv/Scripts/pip install -r requirements-gui.txt    # nur für den Copilot (Streamlit, Plotly)

cp .env.example .env
# .env mit Alpaca-PAPER-Keys befüllen (kostenlos unter https://alpaca.markets), ALPACA_PAPER=true lassen
```

Jeder Bot mit Orders braucht ein **eigenes** Paper-Konto in einer eigenen Datei (`.env` Momentum,
`overnight.env` Overnight + Pelosi, `copilot.env` Copilot + `NTFY_TOPIC`, `gold.env` OANDA-Demo). Die Dateien
sind per `*.env` von git ausgeschlossen. Der Momentum-Bot stellt fremde Positionen in seinem Konto glatt.

Zusätzlich nötig: Node.js, denn `forward-run` und `forward-gold` laden Dukascopy-Kurse über
`npx dukascopy-node`.

## Referenz-Bot: SMA-Crossover (`run`, `backtest`, `validate`, `walkforward`)

Der ursprüngliche Bot des Projekts: ein einfacher Moving-Average-Crossover für ein Symbol. Er ist eine
Referenzimplementierung und wird nicht mehr betrieben (`deploy/tradingbot.service` ist auf dem VPS nicht installiert).

### Strategie

Moving-Average-Crossover mit optionalen Bestätigungsfiltern:
- **BUY**, wenn der kurze gleitende Durchschnitt (SMA) den langen von unten nach oben kreuzt
  (Golden Cross) -- UND, falls aktiviert, Trendfilter und RSI-Filter zustimmen.
- **SELL**, wenn der kurze SMA den langen von oben nach unten kreuzt (Death Cross). SELL wird
  NIE gefiltert -- die Filter sollen einen ungünstigen Einstieg verhindern, aber niemals einen
  Ausstieg blockieren.

Fenstergrößen sind über `SHORT_WINDOW` / `LONG_WINDOW` konfigurierbar.

#### Trendfilter (`TREND_FILTER_WINDOW`)

BUY nur, wenn der Kurs über dem gleitenden Durchschnitt dieses (längeren) Fensters liegt, z.B.
der 200-Tage-SMA. Soll verhindern, in einem übergeordneten Abwärtstrend zu kaufen, nur weil
kurzfristig ein Rebound einen Golden Cross auslöst. `0` deaktiviert den Filter.

#### RSI-Filter (`RSI_WINDOW`)

BUY nur, wenn der RSI (Relative Strength Index) über 50 liegt, also aufwärts gerichtetes
Momentum den Crossover bestätigt. `0` deaktiviert den Filter.

### Risikomanagement

#### Trailing-Stop-Loss (`STOP_LOSS_PCT`)

Sobald eine Position offen ist, wird bei jedem Zyklus geprüft, ob der aktuelle Kurs um mehr als
`STOP_LOSS_PCT` unter den **höchsten seit dem Einstieg beobachteten Kurs** gefallen ist (nicht
nur unter den Einstiegspreis). Falls ja, wird sofort verkauft – unabhängig vom Crossover-Signal.
Direkt nach dem Einstieg verhält sich das wie ein fixer Stop; steigt der Kurs danach, zieht die
Schwelle mit nach oben und sichert so einen Teil des bereits erzielten Gewinns.

- Live-/Paper-Trading: der Bot fragt den tatsächlichen Einstiegspreis der offenen Position direkt
  bei Alpaca ab (`avg_entry_price`) und verfolgt den seither höchsten Kurs im Prozessspeicher
  (`TradingBot._peak_price_by_symbol`). Das überlebt einen Neustart des Bots nicht -- nach einem
  Neustart mit noch offener Position startet die Nachverfolgung konservativ wieder beim
  Einstiegspreis, der Stop fällt dabei höchstens auf das ursprüngliche, weitere Niveau zurück,
  nie auf ein gefährlich engeres.
- Backtest/Validierung: der Stop wird auf Basis des Tagesschlusskurses geprüft (keine Intraday-
  Daten verfügbar), ausgelöste Stop-Exits erscheinen im Ergebnis als eigener Trade-Typ `STOP`.
- `STOP_LOSS_PCT=0` deaktiviert den Stop vollständig.

#### Take-Profit (`TAKE_PROFIT_PCT`)

Überschreitet der Kurs den Einstiegspreis um mehr als `TAKE_PROFIT_PCT`, wird der Gewinn sofort
mitgenommen -- unabhängig vom Crossover-Signal. Anders als der Trailing-Stop bezieht sich das
Ziel immer auf den Einstiegspreis, nicht auf einen laufenden Höchststand. Erscheint im
Backtest-Ergebnis als Trade-Typ `TP`. `TAKE_PROFIT_PCT=0` deaktiviert Take-Profit.

#### Risikobasierte Positionsgröße (`RISK_PER_TRADE_PCT`)

Standardmäßig setzt jeder Trade das volle verfügbare Kapital ein (Backtest) bzw. die feste
Stückzahl `QTY` (Live-Bot). Mit `RISK_PER_TRADE_PCT > 0` wird die Positionsgröße stattdessen so
gewählt, dass beim Erreichen des initialen Stops (Einstiegspreis · `STOP_LOSS_PCT`) höchstens
dieser Anteil des aktuellen Kapitals verloren geht -- klassisches Money-Management ("nie mehr als
X% pro Trade riskieren"). Nur wirksam, wenn `STOP_LOSS_PCT > 0` ist (sonst gibt es keinen
Bezugspunkt für "Risiko"). `RISK_PER_TRADE_PCT=0` deaktiviert die Berechnung.

**Achtung: Diese Funktionen sind kein Allheilmittel und keine garantierte Profitsteigerung** -- sie
verschieben das Verhältnis von Risiko zu Ertrag, verbessern es nicht automatisch:

- Ein fixer/trailender Stop kann bei volatilen Trendmärkten dazu führen, dass Positionen durch
  normale Schwankungen vorzeitig ausgestoppt werden, bevor sich der eigentliche Trend fortsetzt
  ("Whipsaw").
- Ein Take-Profit-Ziel **deckelt Gewinne in starken Trends**: in einem Backtest über 600
  Handelstage (Stand dieser Implementierung) verbesserten Trendfilter+RSI+Take-Profit das
  Ergebnis bei AAPL (+1,8% → +14,1%) und MSFT (+4,5% → +10,5%), verschlechterten es aber bei
  GOOGL (+93,5% → +15,7%), NVDA (+47,3% → +10,0%) und TSLA (+24,1% → +3,0%) deutlich -- weil die
  Filter zu vorsichtig in die Rallye eingestiegen sind und Take-Profit den Rest abgeschnitten hat.
  Es gibt hier keinen Parametersatz, der auf allen Symbolen/Marktphasen überlegen ist.
- Mit `validate` lässt sich prüfen, ob eine bestimmte Kombination für ein konkretes Symbol
  tatsächlich hilft oder eher schadet -- und ob sie out-of-sample überhaupt stabil ist.

### Robustheit & bekannte Grenzen

- **Keine doppelten Orders, aber Stop-Loss wird nie blockiert**: Vor jeder Kauf-/Verkaufs-
  entscheidung prüft der Bot *richtungsspezifisch*, ob für das Symbol bereits eine offene
  (unausgeführte) Order in dieselbe Richtung existiert, und überspringt den Zyklus in dem Fall.
  Das verhindert, dass bei langsamer Order-Füllung (z.B. sehr kurzes `POLL_INTERVAL_SECONDS` oder
  illiquide Symbole) eine zweite Order ausgelöst wird, bevor die erste gefüllt ist. Die Prüfung ist
  bewusst nach Kauf-/Verkaufs-Richtung getrennt: eine noch offene Kauf-Order darf einen dringenden
  Stop-Loss-Verkauf niemals blockieren (und umgekehrt).
- **Tagesschlusskurs-Latenz**: Der Bot arbeitet mit Tages-Bars, nicht mit Echtzeit-Quotes. Der
  "aktuelle Kurs" (auch für den Stop-Loss-Check) ist der letzte verfügbare Tages-Bar, der bei
  freien Alpaca-Datenplänen bis zu ~15-20 Minuten hinter dem realen Marktgeschehen liegen kann.
  Für einen auf Tagesbasis handelnden Swing-Bot ist das ausreichend, für sehr schnelle
  Kursbewegungen (Flash Crash o.ä.) reagiert der Stop-Loss entsprechend verzögert.
- **API-Fehler werden nicht als "keine Position" verschluckt**: Nur ein tatsächliches 404 ("keine
  Position offen") wird von `Broker.get_position()` als `None` interpretiert. Alle anderen Fehler
  (Netzwerk, Auth, Rate-Limit) werden weitergereicht und lösen im Live-Loop einen geloggten,
  übersprungenen Zyklus aus, statt fälschlich anzunehmen, es sei keine Position offen.
- **Backtest/Validierung sind NICHT 1:1 mit dem Live-Bot vergleichbar**: `backtest`/`validate`
  investieren bei jedem BUY das gesamte verfügbare Kapital (Zinseszins-Effekt über mehrere
  Trades). Der Live-/Paper-Bot kauft dagegen bei jedem Signal immer die feste Stückzahl `QTY`,
  unabhängig vom restlichen Kontostand. Eine im Backtest gezeigte Rendite ist daher mit denselben
  Parametern im Live-Bot so nicht erreichbar -- der Backtest dient der Strategie-/Parameter-
  Bewertung, nicht als exakte Vorhersage der Live-Performance.

### Nutzung

**Backtest gegen historische Kurse:**

```bash
python main.py backtest --days 250
```

Anderes Symbol testen, ohne `SYMBOL` in `.env` zu ändern (gilt nur für diesen Aufruf,
`run` kennt `--symbol` bewusst nicht -- siehe unten):

```bash
python main.py backtest --symbol MSFT --days 600
python main.py validate --symbol MSFT --days 600
```

Die CLI (`backtest`/`validate`) aktiviert standardmäßig alle Verbesserungen: Trendfilter
(200-Tage-SMA), RSI-Filter, Trailing-Stop (8%), Take-Profit (15%), Slippage (0,05%). Volle
Kontrolle über alle Flags:

```bash
python main.py backtest --days 600 \
  --commission-pct 0.001 --slippage-pct 0.001 \
  --stop-loss-pct 0.08 --take-profit-pct 0.15 --risk-per-trade-pct 0.02 \
  --trend-window 200 --rsi-window 14
```

Einzelne Filter/Exits deaktivieren (z.B. um die reine Crossover-Strategie ohne die neuen
Filter zu sehen, jeweils mit `0`):

```bash
python main.py backtest --days 600 --trend-window 0 --rsi-window 0 --take-profit-pct 0
```

Hinweis: `run_backtest()`/`validate()` selbst (die Python-Funktionen, z.B. für eigene Skripte)
haben davon abweichende, konservative Defaults (alle neuen Filter aus) -- nur die CLI aktiviert
sie standardmäßig. Das hält bestehenden Code, der diese Funktionen direkt aufruft, unverändert.

**Out-of-Sample-Validierung** (Parameter werden nur auf dem ersten Teil der Daten gesucht,
danach unverändert auf dem noch "ungesehenen" restlichen Zeitraum geprüft – so lässt sich
erkennen, ob eine Parameterkombination nur zufällig auf die Trainingsdaten überangepasst ist):

```bash
python main.py validate --days 600 --train-ratio 0.7 --grid "5:20,10:30,20:50,50:200"
```

Wichtig: Eine große negative Differenz zwischen Test- und Trainingsrendite ("Overfitting-
Warnsignal") bedeutet, dass die auf den Trainingsdaten beste Kombination auf neuen Daten
deutlich schlechter abschneidet – ein Hinweis, der Strategie/den Parametern nicht blind zu
vertrauen.

**Walk-Forward-Validierung** (wiederholt dieselbe Out-of-Sample-Idee über mehrere
aufeinanderfolgende Zeitfenster statt eines einzelnen Splits – ein einzelner Testzeitraum kann
zufällig günstig oder ungünstig ausfallen, mehrere Fenster zeigen, ob eine Strategie über
verschiedene Marktphasen hinweg konsistent funktioniert):

```bash
python main.py walkforward --symbol SPY --days 1500 --train-window 252 --test-window 63
```

`--train-window`/`--test-window` sind Handelstage (Standard: 252 ≈ 1 Jahr Training, 63 ≈ 1
Quartal Test). Standardmäßig rutscht das Trainingsfenster mit fester Größe mit ("rolling");
`--expanding` lässt es stattdessen ab Tag 0 wachsen. `--step` steuert, wie weit die Fenster pro
Schritt vorrücken (Standard: `--test-window`, also nicht überlappende Testfenster). Für jedes
Fenster wird intern `validate()` aufgerufen (nur die SMA-Fenster werden pro Zeitfenster neu
gewählt, Kosten/Stop-Loss/Take-Profit/Trend-/RSI-Filter bleiben über alle Fenster fest – sie
zusätzlich pro Fenster zu optimieren würde die Kombinatorik und damit das Overfitting-Risiko
explodieren lassen).

Am wichtigsten ist die **verkettete Testrendite** (compounded): sie verkettet die Testrenditen
aller Fenster sequentiell, so als hätte man die Parameter am Ende jedes Trainingsfensters neu
gewählt und dann nur im jeweils folgenden, ungesehenen Testfenster gehandelt – eine deutlich
realistischere Gesamtschätzung als ein einzelner Train-/Test-Split. Viele einzelne
Overfitting-Warnsignale (`*`) sind normal; eine stark negative verkettete Testrendite oder eine
sehr niedrige Gewinnfensterquote deuten dagegen darauf hin, dass die Parametersuche insgesamt
nicht robust ist.

**Live-/Paper-Trading-Loop starten** (fragt im konfigurierten Intervall neue Kurse ab und
platziert Market-Orders bei Crossover-Signalen):

```bash
python main.py run
```

Mit `Strg+C` sauber beenden.

### Konfiguration des Referenz-Bots (`.env`)

| Variable                | Beschreibung                                             | Default |
|--------------------------|-----------------------------------------------------------|---------|
| `ALPACA_API_KEY`         | Alpaca API Key                                            | –       |
| `ALPACA_SECRET_KEY`      | Alpaca Secret Key                                         | –       |
| `ALPACA_PAPER`           | `true` = Paper-Trading, `false` = Live-Trading             | `true`  |
| `SYMBOL`                 | Handelssymbol, z.B. `AAPL`                                 | `AAPL`  |
| `QTY`                    | Stückzahl pro Order                                        | `1`     |
| `SHORT_WINDOW`           | Fenstergröße kurzer SMA                                    | `20`    |
| `LONG_WINDOW`            | Fenstergröße langer SMA                                    | `50`    |
| `POLL_INTERVAL_SECONDS`  | Abfrageintervall im Live-Loop (Sekunden)                   | `60`    |
| `STOP_LOSS_PCT`          | Trailing-Stop als Anteil unter dem Höchststand, `0` = aus  | `0.08`  |
| `TAKE_PROFIT_PCT`        | Take-Profit als Anteil über dem Einstieg, `0` = aus        | `0.15`  |
| `RISK_PER_TRADE_PCT`     | Kapitalrisiko pro Trade (nur mit Stop-Loss), `0` = volles Kapital/feste QTY | `0.0` |
| `TREND_FILTER_WINDOW`    | Trendfilter-SMA, BUY nur über diesem Wert, `0` = aus       | `200`   |
| `RSI_WINDOW`             | RSI-Filter, BUY nur wenn RSI > 50, `0` = aus                | `14`    |

## Momentum-Day-Trading-Backtest (experimentell)

Historischer Backtest einer regelbasierten Näherung der öffentlich bekannten
["Warrior Trading" Momentum-Day-Trading-Strategie](https://www.warriortrading.com/momentum-day-trading-strategy/)
(Ross Cameron) auf Minutendaten: Bull-Flag- bzw. Flat-Top-Breakout-Muster, 2:1-Chance-Risiko-
Ziel mit hälftigem Teilverkauf, Breakeven-Stop, Ausstieg bei erster roter Kerze oder
"Extension Bar".

**Muster-Definition:** Flaggenstange = Anstieg vom Swing-Tief um mindestens
`--flagpole-min-gain-pct` bei erhöhtem Relativvolumen; Kerzen mit neuem Hoch verlängern die Stange.
Danach braucht es mindestens `--min-pullback-bars` echte Rücksetzer-Kerzen (Hoch nicht über der
Stange). Einstieg erst, wenn eine Kerze über dem Hoch der Vorkerze schließt ("first candle to make a
new high"); Stop = Tief des Rücksetzers. Ausstieg bei Schwäche vor dem Ziel über
`--weakness-exit`: `red_candle` (Standard, erste rot schließende Kerze), `new_low` (erste Kerze
mit Tief unter dem der Vorkerze) oder `none` (kein Schwäche-Ausstieg -- nur Stop, Ziel und
Extension Bar). Bei dünn gehandelten Small Caps liefert der IEX-Feed oft nur einzelne Abschlüsse
pro Minute; eine "rote Kerze" ist dann häufig Rauschen. Im Backtest über 22 Symbole/250 Tage
(Stand 24.09.) erreichten mit `none` 18 statt 12 Trades das Ziel (Ø R −0,14 statt −0,40) --
weiterhin nicht profitabel, aber deutlich weniger negativ.

```bash
python main.py momentum-backtest --symbol TSLA --days 200 \
  --daily-trend-window 20 --lookback-days 10 --flagpole-min-gain-pct 0.015 --min-relative-volume 1.5
```

**Mehrere Symbole auf einmal testen** (`--symbols`, kommagetrennt, statt `--symbol`): führt den
Backtest für jedes angegebene Symbol unabhängig mit demselben Startkapital aus und fasst die
Ergebnisse zusammen -- praktisch, um die Strategie über eine eigene Watchlist statt nur ein
einzelnes Symbol einzuschätzen:

```bash
python main.py momentum-backtest --symbols AAPL,TSLA,MSFT --days 200 --starting-cash 10000
```

**Wichtig:** dies simuliert NICHT ein einzelnes Konto mit begrenztem Gesamtkapital oder einer
Obergrenze gleichzeitiger Positionen (das macht live `momentum-run` über
`--max-concurrent-positions`) -- jedes Symbol bekommt unabhängig dasselbe `--starting-cash`, als
würde man für jedes Symbol separat Kapital reservieren. Und: dies simuliert NICHT, welche Aktien
der Scanner an einem vergangenen Tag tatsächlich gefunden hätte (dafür gibt es keine historische
Alpaca-API, siehe Abschnitt "Marktweiter Scanner" unten) -- die Symbole müssen selbst vorgegeben
werden.

**Wichtige Einschränkungen -- unbedingt lesen, bevor die Ergebnisse interpretiert werden:**

- **Reine historische Analyse.** Dieser Backtest selbst löst nie Orders aus -- für den
  tatsächlichen Live-Handel dieser Strategie siehe `python main.py momentum-run` weiter unten.
- **Standardmäßig anderer Datenfeed als der Live-Bot.** Ohne `--feed` lädt dieser Backtest Daten
  über Alpacas Standard-/SIP-Feed (vollen Marktüberblick, mit dem üblichen
  Sicherheitsabstand `_DATA_DELAY`) -- `momentum-run` nutzt live aber IMMER den IEX-Feed (nur
  ~2-3% des Marktvolumens, siehe unten). Ein Backtest gegen SIP kann deshalb Setups/Ergebnisse
  zeigen, die der Live-Bot mit seinem eingeschränkteren Datenblick so nie sehen würde. Mit
  `--feed iex` lädt dieser Backtest stattdessen exakt denselben (eingeschränkten) Feed wie
  `momentum-run` -- realistischer, um vorab abzuschätzen, wie sich die Strategie live tatsächlich
  verhalten würde:
  ```bash
  python main.py momentum-backtest --symbol TSLA --days 90 --feed iex
  ```
- **Kein Float-Filter.** Die Original-Strategie filtert u.a. nach Float (<100 Mio., ideal
  <20 Mio. Aktien). Alpacas Marktdaten-API liefert keinen Aktien-Float -- der separate
  `python main.py scan`-Befehl (siehe unten) deckt Tagesgewinn/Preisspanne/Relativvolumen/News
  ab, aber keinen Float. Dieser Backtest bekommt weiterhin ein bereits feststehendes Symbol
  übergeben (z.B. einen Kandidaten aus `scan`), er durchsucht nicht selbst den Gesamtmarkt.
- **Regelbasierte Näherung, kein Pixel-genauer Nachbau.** Bull Flag/Flat Top sind im Original
  diskretionäre Chartmuster ("das sieht sauber aus"); Schwellenwerte wie Flagpole-Mindestanstieg
  oder "Extension Bar" sind im Artikel nicht numerisch definiert und wurden hier sinnvoll, aber
  notwendigerweise etwas willkürlich gewählt (siehe `tradingbot/momentum.py`-Modul-Docstring und
  `--help` für alle Parameter-Defaults).
- Standardmäßig werden die ersten `--daily-trend-window` bzw. `--lookback-days` Handelstage des
  geladenen Zeitraums übersprungen (zu wenig Vortage für Trendfilter/Relativvolumen) -- die
  CLI-Ausgabe zeigt genau, wie viele.

## Marktweiter Scanner (experimentell)

Sucht den AKTUELLEN Marktzustand nach Kandidaten, die den in zwei Warrior-Trading-PDFs
("Stock Selection", "Sample Trading Plan") beschriebenen Aktienauswahl-Kriterien entsprechen:
Tagesgewinn (Standard: ≥10%), Kursspanne (Standard: $1-$20), relatives Volumen (Standard: ≥5x
30-Tage-Durchschnitt) und optional ein aktueller News-Katalysator.

```bash
python main.py scan
python main.py scan --min-price 5 --max-price 10 --min-relative-volume 2 --require-news
```

Nutzt Alpacas Screener-API (`get_market_movers`/`get_most_actives`, Top-Gewinner bzw.
höchstes Handelsvolumen) als Kandidatenpool statt selbst tausende Symbole einzeln abzufragen,
und die News-API für die Katalysator-Prüfung.

**Wichtige Einschränkungen:**

- **Rein lesend, nur aktueller Marktzustand.** Alpacas Screener-API kennt keinen historischen
  Datumsparameter -- der Scanner lässt sich NICHT in den historischen `momentum-backtest`
  einbauen. Er eignet sich, um manuell einen Kandidaten zu finden, den man dann per
  `momentum-backtest --symbol X` historisch prüft. Es werden nie Orders ausgelöst.
- **Kein Float-Filter** (siehe oben, Alpacas API liefert keinen Aktien-Float).
- **Relatives Volumen wird auf einen vollen Handelstag projiziert**, wenn die Sitzung noch
  läuft (sonst würde das bisherige Tagesvolumen systematisch zu niedrig wirken, gerade
  vormittags). Der letzte verfügbare Handelstag (inkl. Wochenenden/Feiertagen/Frühschluss-Tagen)
  wird über Alpacas echten Handelskalender bestimmt, nicht geraten.
- **News-Prüfung ist eine Näherung** (reine Präsenzprüfung eines Artikels im Zeitfenster, keine
  inhaltliche Bewertung, ob die News tatsächlich ein plausibler Kursgrund ist) und über alle
  Kandidaten hinweg auf eine Gesamtzahl Artikel gedeckelt (`_NEWS_FETCH_LIMIT`), nicht
  erschöpfend.

## Live-Momentum-Bot (experimentell, nur Paper-Trading)

Kombiniert den Scanner (periodische Kandidatensuche) mit der Bull-Flag/Flat-Top-Engine aus dem
Momentum-Backtest zu einem eigenständigen Live-Trading-Loop: sucht selbst Kandidaten, erkennt
Muster balkenweise in Echtzeit und platziert echte (Paper-)Orders.

```bash
python main.py momentum-run
python main.py momentum-run --max-risk-dollars 200 --max-concurrent-positions 2 --daily-max-loss-pct 0.05
```

Mit `Strg+C` sauber beenden.

**Warum live überhaupt möglich, obwohl `momentum-backtest` das explizit ausschließt:** Alpacas
"~15 Minuten Verzögerung" gilt nur für den Standard-/SIP-Feed ohne kostenpflichtiges
Zusatzabo ("Algo Trader Plus"). Der ebenfalls kostenlose **IEX-Feed ist echtzeitfähig** (sowohl
per REST-Abfrage als auch per WebSocket) -- empirisch verifiziert, siehe `tradingbot/momentum_live.py`.
Dieser Bot fragt deshalb konsequent mit `feed=DataFeed.IEX` ab statt mit dem Standard-Feed.

**Funktionsweise:** alle `--scan-interval-seconds` (Standard 300s) wird der Scanner erneut
ausgeführt und neue Kandidaten-Symbole (bis `--max-tracked-symbols`) aufgenommen; für jedes
beobachtete Symbol werden alle `--poll-interval-seconds` (Standard 60s) neue Minuten-Bars
abgefragt und balkenweise durch dieselbe `MomentumEngine` wie im Backtest verarbeitet -- ein
Fund (Bull Flag/Flat Top) löst eine echte Market-Buy-Order aus (Stückzahl risiko- und
kapitalbasiert wie im Backtest), Ausstiegssignale (Ziel/Stop/rote Kerze/Extension Bar) echte
Market-Sell-Orders.

**Nachvollziehbarkeit:** jeder erkannte Breakout wird mit voller Begründung geloggt (Swing-Tief,
Flaggenstange-Gewinn%, Rel.Volumen, Pullback-Balken, Stop, Risiko/Aktie) -- auch wenn der Einstieg
danach an einem Kapital-/Positionslimit scheitert. Jede Verkaufs-Order loggt zusätzlich zum Grund
(Ziel/Stop/rote Kerze/Extension) den Einstiegs-, Stop- und Zielkurs der Position, damit der
Ausstieg ohne Rückgriff auf frühere Log-Zeilen nachvollziehbar ist.

**Sicherheitsmechanismen:**

- `--max-concurrent-positions` (Standard 3): Obergrenze gleichzeitig offener Positionen.
- `--daily-max-loss-pct` (Standard 10%): fällt das Eigenkapital seit Tagesbeginn um diesen Anteil,
  schließt der Bot sofort alle offenen Positionen und pausiert für den Rest des Handelstags
  (Sample-Trading-Plan-PDF: "Daily Max loss: 10% of my account").
- `--flatten-minutes-before-close` (Standard 5): erzwungenes Glattstellen aller offenen
  Positionen vor Sitzungsende (kein Overnight-Halten, wie im Artikel beschrieben).
- Order-Ausführung wird aktiv überwacht: eine Kauf-Order, die nicht innerhalb von
  `--order-fill-timeout-seconds` (Standard 30s) füllt, wird storniert und der Einstieg verworfen;
  eine Verkaufs-Order wird dagegen NIE aufgegeben (reale Position bliebe sonst unbewacht) --
  sie wird bei Bedarf über mehrere Zyklen hinweg weiterverfolgt und erneut versucht.
- Stop-Order bei Alpaca als Sicherheitsnetz: nach jedem Kauf legt der Bot zusätzlich zum
  Software-Stop eine echte Stop-Order (DAY) beim Broker an. Sie greift auch, wenn der Bot
  abstürzt oder die Verbindung verliert. Vor jedem eigenen Verkauf wird sie storniert, nach
  einem Teilverkauf mit neuer Stückzahl und Breakeven-Stop neu angelegt; löst sie selbst aus,
  verbucht der Bot das im nächsten Zyklus. Abschaltbar mit `--no-broker-stop`.
- **Positionsgröße begrenzt:** Die Stückzahl rechnet mit mindestens 2 % Stop-Abstand
  (`--min-stop-pct`), auch wenn das Pullback-Tief nur wenige Cent unter dem Kurs liegt,
  und der Positionswert ist auf 25.000 $ begrenzt (`--max-position-dollars`). Der Stop
  selbst bleibt am Pullback-Tief.
- **Kauf als Limit-Order:** höchstens 1 % über dem Signalkurs (`--max-entry-slippage-pct`).
  Stückzahl und Risiko werden mit diesem Limit gerechnet, der tatsächliche Verlust beim
  Stop bleibt so nahe an `--max-risk-dollars`. Füllt die Order nicht rechtzeitig, wird sie
  storniert und der Trade ausgelassen.
- **Neustart mit offener Position:** Der Bot speichert seinen Zustand in `momentum_state.json`
  (anderer Pfad: `--state-file`; deaktivieren: `--no-state-file`). Offene Positionen werden nach
  einem Neustart weitergeführt und mit dem Depot abgeglichen. Ohne/mit kaputter Datei werden
  Positionen wie bisher samt offener Orders glattgestellt; kaputte Dateien werden als
  `.corrupt` aufbewahrt. Ein beim Absturz noch laufender Kauf wird storniert bzw. vom
  Depot-Abgleich verkauft. Positionen vom Vortag werden sofort glattgestellt.
- Rückstände werden nachgeholt, aber Einstiege daraus niemals real gehandelt: wird ein Symbol erst Stunden nach
  Sitzungsbeginn neu aufgenommen, oder war der Bot eine Weile offline (Neustart!), holt er die
  fehlenden Minuten-Bars auf einmal nach, damit Muster (Flagge/Pullback/Swing-Tief) korrekt aus
  der echten Historie erkannt werden. Ausstiegssignale für übernommene offene Positionen werden
  auch aus dem Rückstand real ausgeführt. Nur ein Einstiegssignal auf einem aktuellen Balken
  (innerhalb der letzten `2 * --poll-interval-seconds`, mind. 120s) kann real ausgeführt werden.
  Außerdem muss der Breakout auf der neuesten abgerufenen Kerze liegen -- gibt es schon eine
  neuere, ist das Signal überholt.
- **Fill auf/unter dem Stop:** Ist der Kurs zwischen Signal und Kauf schon auf den Stop gefallen,
  verkauft der Bot sofort wieder, statt bis zur nächsten Kerze zu warten.
- **Depot-Abgleich in jedem Zyklus:** Liegen während der Sitzung mehr Aktien im Depot, als der
  Bot verwaltet (z.B. eine stornierte Kauf-Order, die doch noch gefüllt wurde), verkauft er den
  Überschuss per Market-Order. **Das Konto muss deshalb dem Bot allein gehören** -- manuell
  gekaufte Aktien würden ebenfalls verkauft.

**Wichtige Einschränkungen -- vor Einsatz unbedingt lesen:**

- **NUR für Paper-Trading gedacht und getestet.** Vor echtem Kapitaleinsatz eigenverantwortlich
  über mehrere Handelstage im Paper-Modus beobachten.
- **IEX deckt nur einen Bruchteil (~2-3%) des gesamten Marktvolumens ab**, nicht die volle
  konsolidierte Tape (SIP) -- Muster-/Relativvolumen-Erkennung basiert auf einem unvollständigen
  Abbild des Marktes.
- **Kein WebSocket-Streaming, sondern Polling** -- die Reaktionszeit auf ein Setup ist durch
  `--poll-interval-seconds` nach unten begrenzt.
- **Neustarts benötigen eine gültige Zustandsdatei.** Mit `momentum_state.json` werden offene
  Positionen weitergeführt; ohne/mit kaputter Datei wie bisher glattgestellt. Ein beim Absturz
  noch laufender Kauf wird storniert bzw. vom Depot-Abgleich verkauft. Während der Bot ausfällt,
  schützt nur die Broker-Stop-Order bis Handelsschluss. Ohne Neustart greift der Zwangsverkauf
  vor Handelsschluss weiterhin nicht (die Stop-Order verfällt am Tagesende).
- **Kein Float-Filter** (siehe Scanner/Backtest oben).
- **Ein einzelner Prozess, keine Parallelisierung** -- alle beobachteten Symbole werden
  sequentiell im selben Zyklus abgefragt; bei sehr vielen gleichzeitig beobachteten Symbolen
  (hohes `--max-tracked-symbols`) kann ein Zyklus entsprechend länger dauern als
  `--poll-interval-seconds`.

### Trading-Report (P&L-Auswertung)

`momentum-report` wertet Alpacas Order-Historie (nicht die eigenen Logs) zu abgeschlossenen
Trades mit P&L aus -- ruft nur Daten ab, platziert keine Orders:

```bash
python main.py momentum-report --days 7
```

Fasst Kauf-/Verkaufs-Orders pro Symbol von "flach" bis wieder "flach" zu einem Trade zusammen
(auch bei mehreren Teil-Fills, z.B. Ziel-Teilverkauf + Rest-Ausstieg), gruppiert nach Handelstag
in America/New_York, und zeigt pro Tag sowie insgesamt Trades/Trefferquote/Netto-P&L, eine
Einzeltrade-Tabelle sowie noch offene Positionen. P&L ist brutto (im Paper-Modus ohnehin ohne
Kommissionen/Slippage).

### Mehrere Bots vergleichen (`momentum-compare`)

Mehrere Bots mit unterschiedlichen Einstellungen (z.B. `--weakness-exit red_candle` gegen
`none`) laufen parallel -- **jeder auf einem eigenen Alpaca-Paper-Konto**: der Bot hält das
Konto für seins und verkauft beim Start sowie in jedem Zyklus Aktien, die er nicht selbst
verwaltet; auch der Tages-Maximalverlust bezieht sich auf das ganze Konto. Die Keys des
zweiten Kontos in eine eigene Datei (z.B. `~/bot2.env`) und vor dem Start in der Shell laden
(Umgebungsvariablen haben Vorrang vor `.env`):

```bash
set -a; source ~/bot2.env; set +a
python main.py momentum-run --weakness-exit none
```

Der Vergleich liest jede Order-Historie mit den Keys aus der jeweiligen Datei (ändert die
Umgebung nicht, platziert keine Orders):

```bash
python main.py momentum-compare --days 5 --account red=.env --account none=~/bot2.env
```

Zeigt je Konto Equity, Trades, Trefferquote, Netto-P&L, Ø Gewinn/Verlust, Profit-Faktor und
Ø Haltedauer, den P&L pro Handelstag und eine Setup-Tabelle: Trades desselben Symbols mit
Einstieg innerhalb von `--tolerance-minutes` (Standard 3) stehen nebeneinander -- so wird
direkt sichtbar, wie unterschiedliche Regeln dasselbe Setup behandelt haben. Zweimal dasselbe
Konto (gleiche API-Keys) wird abgelehnt.

### News-Einschätzung per LLM (`--news-intel`, zunächst Schattenmodus)

```bash
python main.py momentum-run ... --news-intel                              # nur protokollieren
python main.py momentum-run ... --news-intel --news-filter block-dilution # Einstieg bei Emission ablehnen
```

- Für jeden neuen Kandidaten (einmal je Tag) holt `tradingbot/news_intel.py` die Alpaca-News der
  letzten `--news-lookback-hours` (Überschrift + Zusammenfassung) und die SEC-Meldungen der letzten
  14 Tage (8-K, S-1/S-3, 424B*, 13D/G, ...) und lässt ein LLM (Anthropic `claude-haiku-4-5-20251001`
  oder OpenAI `gpt-5-mini`; `--news-provider`, `--news-model`) einordnen: Katalysator (earnings, fda_clinical, offering_dilution, m_and_a, ...),
  Richtung, Verwässerungsrisiko, Konfidenz, Kurzbegründung.
- Ergebnis in `news_intel.csv` und im Log (auch beim Breakout). Läuft in einem Hintergrund-Thread;
  Fehler (fehlender Key, Netz) werden nur geloggt und blockieren nie den Handel.
- Schattenmodus zuerst: Die Einschätzung ändert nichts am Handel. Erst wenn die Auswertung
  (news_intel.csv gegen `momentum-report`) zeigt, dass z.B. "offering_dilution" schlechtere Trades
  anzeigt, `--news-filter block-dilution` einschalten.
- Voraussetzung: `ANTHROPIC_API_KEY` oder `OPENAI_API_KEY` in `.env` (bei beiden wird Anthropic
  genutzt). Kosten mit Haiku bzw. gpt-5-mini grob unter 1 Cent je Kandidat;
  Obergrenze 200 Einschätzungen je Tag.

## Overnight-Portfolio-Bot (Paper-Vorwärtstest)

Bester Kandidat aus der Strategie-Forschung (`research/PROTOCOL.md`): kurz vor Handelsschluss
jedes der 8 ETFs SPY, QQQ, IWM, DIA, XLK, XLF, XLE, SMH mit je 1/8 des Kapitals kaufen, wenn
der Kurs über dem 200-Tage-Durchschnitt liegt (Market-on-Close), am nächsten Morgen alles zum
Eröffnungskurs verkaufen (Market-on-Open).

**Nicht als profitabel nachgewiesen.** Im Backtest 2016-2025 +7,75 % p.a., Sharpe 1,0,
Alpha ggü. SPY 5,3 % p.a. -- nach 191 getesteten Varianten ist das aber statistisch nicht
von Glück zu unterscheiden. Der Paper-Betrieb ist ein Vorwärtstest auf neuen Daten, keine
Empfehlung für echtes Geld.

```bash
python main.py overnight-run --dry-run      # nur Entscheidungen loggen
python main.py overnight-run                # Paper-Orders (Keys aus overnight.env)
python main.py overnight-report             # Auswertung von overnight_trades.csv
```

- **Eigenes Alpaca-Paper-Konto nötig** (Keys in `overnight.env`, gleiche Variablennamen wie
  `.env.example`): `momentum-run` stellt beim Start alle unbekannten Positionen im Konto glatt
  und würde die Overnight-Positionen verkaufen.
- Margin-Konto, aber ohne Hebel: kein Day Trade (keine PDT-Regel), im Cash-Konto wäre der
  tägliche Wiederkauf mit unabgewickeltem Geld aber eine Good-Faith-Violation.
- Zeitplan (America/New_York, Frühschluss-Tage über Alpacas Handelskalender): Entscheidung
  und CLS-Orders 15 Minuten vor Schluss (Alpaca nimmt CLS nur bis 10 Minuten vorher an),
  OPG-Verkäufe ab 10 Minuten vor Open, nicht gefüllte Reste 5 Minuten nach Open per Market.
- Zustand in `overnight_state.json` (übersteht Neustarts über Nacht), jede Nacht mit
  Kauf-/Verkaufskurs und P&L in `overnight_trades.csv`.
- Dauerbetrieb: `deploy/overnight.service`, seit 2026-10-02 nur mit `--dry-run` (Entscheidungen loggen, keine
  Orders), weil Alpaca-Paper Auktionsorders (CLS/OPG) kaum ausführt.

### Vorwärtstest: Nikkei-Nachteffekt und Gotobi (ohne Broker)

Die zwei Befunde, die in der Strategie-Forschung (Branch `research/ideas`, `research/PROTOCOL.md`
Runden 46-49 und 53) alle vorregistrierten Prüfungen bestanden haben, beide klein und stark
kostenabhängig:

- **nikkei_night**: Nikkei 225 long vom Schluss der OSE-Tagessitzung (15:45 JST) bis zur
  Eröffnung am nächsten Handelstag (08:45 JST). Backtest 2013-2025 Ø +4,2 bp je Nacht netto.
- **gotobi**: USD/JPY long 05:00 -> 09:55 JST am 5./10./15./20./25. und Monatsletzten
  (Wochenende -> Freitag). Mit echten Bid/Ask-Kursen Ø +1,0 bp je Trade.
- **gotobi_eurjpy**: dieselbe Regel für EUR/JPY (Runde 85, 2017-2025 Ø +1,84 bp, t 2,70;
  Korrelation mit USD/JPY 0,81).
- **bond_month_end**: IEF (US-Staatsanleihen 7-10 J., Yahoo-Tagesschlüsse) long in den letzten
  3 Handelstagen jedes Monats (Runden 73/88; 2019-2025 Ø +22 bp je Monat über T-Bill, im letzten
  Jahr negativ). Erfasst ab dem ersten Monat, dessen Einstieg nach `--start` liegt (Oktober 2026).

```bash
python main.py forward-run      # lädt die letzten 10 Tage (Dukascopy), trägt Trades ein
python main.py forward-report   # Auswertung von forward_trades.csv
```

- Sendet **keine Orders** und braucht keine Keys; nur Node.js (`npx dukascopy-node`).
- Erfasst Trades ab `--start` (Standard 2026-09-28). Jeder Lauf ist idempotent (gleicher
  Tag wird ersetzt) -- einmal täglich reicht, verpasste Tage holt der nächste Lauf nach
  (bis `--lookback-days` zurück).
- Kosten wie im Backtest: Nikkei 0,5 bp je Seite (Handel in den Auktionen) + JPY-Zins je
  Nacht, Gotobi Kauf zum Ask/Verkauf zum Bid + 0,35 bp Kommission je Seite.
- Japanische Börsenfeiertage stehen fest in `tradingbot/forward_test.py`
  (`JP_MARKET_HOLIDAYS`, 2026-2027) und müssen jährlich ergänzt werden.
- Erwartung: Selbst ein Jahr reicht statistisch kaum (Nikkei ~245 Trades -> t ~1,6 bei
  4 bp); der Test zeigt vor allem, ob die Richtung stimmt und die Kostenannahmen halten.
- Täglich auf dem VPS: `deploy/forward-test.service` + `deploy/forward-test.timer`
  (06:00 UTC), aktivieren mit `sudo systemctl enable --now forward-test.timer`.

### Liquidations-Recorder (Krypto-Perpetuals, nur Datensammlung)

Historische Liquidationsdaten gibt es nicht kostenlos. Um Liquidationskaskaden später
testen zu können, zeichnet `tradingbot/liquidations.py` sie ab jetzt selbst auf:

```bash
python -m tradingbot.liquidations data_cache/liquidations
```

- **Binance** USDⓈ-M `!forceOrder@arr`: alle Symbole, aber je Symbol höchstens die größte
  Liquidation pro Sekunde (unvollständig). **Bybit** `allLiquidation.<SYMBOL>`: jede
  Liquidation, aber nur für die 20 Symbole in `BYBIT_SYMBOLS`.
- Ausgabe je Börse und UTC-Tag: `<exchange>_<YYYY-MM-DD>.csv` mit
  `recv_ms,trade_ms,symbol,liquidated,price,qty` (`liquidated` = Seite der zwangsgeschlossenen
  Position). Verbindungsabbrüche stehen in `gaps.csv`.
- Keine Keys, keine Orders, ~30-40 MB RAM (wird bewusst nicht über `main.py` gestartet, das
  pandas/alpaca lädt). Kurse für die spätere Auswertung gibt es kostenlos auf
  data.binance.vision.
- Dauerbetrieb: `deploy/liq-recorder.service` (`Restart=always`, `MemoryMax=120M`).

## Pelosi-Kopier-Bot (`pelosi-bot`, Alpaca-Paper)

Dieselben Regeln wie der Vorwärtstest `pelosi_copy` (Runde 141), aber mit echten Papier-Orders, um Ausführung und
Depot real zu sehen. Im Backtest t 1,78 -- **nicht bestanden**, deshalb nur als eigener Vorwärtstest.

- Neue Meldungen (House Clerk, elektronische Periodic Transaction Reports) stündlich prüfen.
- Je Kaufzeile (Aktie, oder Option -> Basiswert) ein Los: Kauf am 2. Handelstag nach dem Meldedatum,
  10 Minuten vor Schluss per Market-Order, 10 % des Kontowerts (höchstens das freie Bargeld, kein Hebel).
- Verkauf desselben Loses 252 Handelstage später, ebenfalls kurz vor Schluss; verpasste Fenster werden am nächsten
  Handelstag nachgeholt.
- Zustand (`pelosi_bot_state.json`) wird sofort nach jeder Order gespeichert (kein Doppelkauf nach Teil-Fehlern);
  vorübergehende API-Fehler lassen ein Los geplant statt es zu verwerfen. Trades in `pelosi_bot_trades.csv`.

```bash
python main.py pelosi-bot --env-file overnight.env --check   # nur Konto und Stand anzeigen
python main.py pelosi-bot --env-file overnight.env --notify-env copilot.env
```

## Gold-Ausbruch (Runde 134, Nachbau "The Gold Reaper")

Regel: zu Beginn jeder Stunde (UTC), wenn flach und keine eigene Order offen, Buy-Stop 0,1 ATR über dem höchsten
Hoch der letzten 48 abgeschlossenen H1-Kerzen, gültig 12 Stunden; Stop 2 ATR, Ziel 4 ATR ab Füllkurs; nur long.
ATR14 nach Wilder. Keine neuen Orders freitags ab 20:00 UTC, eigene Orders freitags ab 20:55 UTC löschen.
Risiko 1 % des Kontowerts je Trade.

Drei Umsetzungen derselben Regel:

- **`forward-gold`** (VPS-Timer, keine Orders): rechnet mit Dukascopy-XAUUSD-M1-Geld/Brief inkl. 6,3 % p.a. Swap
  und schreibt `forward_gold.csv`. Das ist der bindende Vorwärtstest (Auswertung 2028-10-01).
- **`mql5/GoldBreakout.mq5`** (MT5 auf dem PC, OANDA-Demo): protokolliert jeden Trade in
  `MQL5/Files/gold_breakout_trades.csv`. Kompilieren mit
  `MetaEditor64.exe /compile:"...\GoldBreakout.mq5" /log:"..."`.
- **`gold-live`** (Python, OANDA fxTrade Practice über `gold.env`): startet nur mit `OANDA_PRACTICE=true`;
  `--check` prüft nur die Verbindung. Unit `deploy/gold-live.service`, auf dem VPS derzeit nicht installiert.

Zweck von EA/Bot: Ausführung, Slippage, Spread und Swap im echten Betrieb mit der Simulation vergleichen.

## Trading-Copilot (diskretionär, `copilot`, Streamlit-Oberfläche)

Der Nutzer entscheidet (Symbol, Stop, Setup), der Copilot erzwingt die Regeln: Positionsgröße aus dem Risiko
(1 R, Standard 50 $), Stop direkt bei Alpaca, Tagesverlustgrenze (Standard 150 $), höchstens 6 Einstiege pro Tag,
nur long. Ein Journal (`copilot_journal.jsonl`) speichert Setup, Notiz und geplantes Risiko. Ziel ist ein
ehrlicher Test, ob diskretionäre Entscheidungen einen Vorteil haben: nach mindestens 100 Trades wertet
`copilot report` je Setup in R-Vielfachen aus.

```bash
python main.py copilot scan                                     # Aktien im Spiel
python main.py copilot buy ABCD --stop 4.80 --setup vwap-pullback --breakeven
python main.py copilot status                                   # ebenso: close ABCD, report, weekly, notify-test
python main.py copilot watch                                    # Sicherheit im Hintergrund
.venv/Scripts/python -m streamlit run gui/copilot_app.py         # Oberfläche
```

- **`copilot watch`** stellt bei Erreichen der Tagesverlustgrenze und um 15:55 ET glatt und zieht den Stop bei
  +1 R auf Einstand (`--breakeven`).
- **Oberfläche** (`gui/`): TradingView-ähnlicher Kerzenchart, ORB-Setup-Melder (`tradingbot/orb_scanner.py`,
  Top 5 nach relativem Eröffnungsvolumen), Übungsmodus "Replay" (vergangener Tag Kerze für Kerze, eigenes Journal
  `replay_journal.jsonl`), Anmeldung per Passwort (`COPILOT_PASSWORD`, Cookie 30 Tage).
- **Benachrichtigungen** über ntfy (`NTFY_TOPIC` in `copilot.env`): Setups, Ausgänge, Eingriffe der
  Überwachung, freitags der Wochenbericht.
- Auf dem VPS als `copilot-gui` (nur 127.0.0.1, Zugriff über Tailscale) und `copilot-watch`.
  `Copilot starten.bat` öffnet die VPS-Seite, wenn `COPILOT_VPS_URL` in `copilot.env` steht, sonst startet sie
  Oberfläche und Überwachung lokal.

## Weitere Vorwärtstests (ohne Orders)

| Befehl | Inhalt | Ausgabe |
|---|---|---|
| `forward-stocks` | ORB Top 5 täglich (Runden 107/107b), Qualität Top 50 monatlich (Runden 118/118b), Small-Cap Value+Qualität Top 20 (Runde 98); Alpaca-Marktdaten nur lesend + SEC-XBRL | `forward_orb.csv`, `forward_quality.csv`, `forward_smallvq.csv` |
| `forward-gold` | Gold-Ausbruch (siehe oben) | `forward_gold.csv` |
| `forward-pelosi` | Pelosi-Käufe, Schlusskurs 2. Handelstag nach Meldung, 252 Tage, 0,1 % Kosten je Seite | `forward_pelosi.csv` |
| `forward-status` | Alle Tests nach der gemeinsamen Regel (K = 11, einseitiger t-Test p < 0,05/11, Ø >= 50 % der Backtest-Erwartung) | Text, `--notify` per ntfy |
| `momentum-checkpoint` | Momentum-Bot: Abbruch bei 100 Trades, wenn Netto < 0 und PF < 0,8; bestanden bei 150 Trades nur mit Netto > 0, PF >= 1,3 und t >= 2 | ntfy, je einmal |

Auswertungen: `forward-report`, `forward-stocks-report`. Alle Läufe sind idempotent; verpasste Tage holt der
nächste Lauf nach. Einziger vorzeitiger Abbruch nach der gemeinsamen Regel: nach der Hälfte der Laufzeit bei
Ø < 0 und t <= -1,5.

## Überwachung und Datensicherung

- **`health`** (alle 10 Minuten): prüft die Dienste und Timer-Läufe (`SERVICES`/`ONESHOTS` in
  `tradingbot/health.py`), Plattenplatz, Speicher und die Aktualität der Liquidationsdaten. Meldet nur
  Zustandswechsel per ntfy, dazu täglich um 8:30 einen Status.
- **`backup-data`** (03:00): `deploy/backup-data.sh` packt Journale, Vorwärtstest-CSVs, Bot-Zustände und
  Liquidationsdaten nach `/home/tradingbot/backups` (14 Tage). Keine Schlüssel, keine neu ladbaren Caches.
  `VPS-Sicherung holen.bat` holt die Archive per scp nach `backups/` auf dem PC.

## Dauerbetrieb auf einem eigenen Server/VPS (systemd)

Für 24/7-Betrieb (statt eines Terminal-Fensters, das offen bleiben muss) liegt unter
`deploy/tradingbot.service` eine fertige systemd-Unit, die den Bot automatisch startet, bei
einem Absturz neu startet und beim Server-Reboot mit hochfährt.

```bash
# 1) Eigenen, nicht-root User für den Bot anlegen (einmalig, als root/mit sudo)
sudo useradd --system --create-home --shell /usr/sbin/nologin tradingbot

# 2) Repo als dieser User klonen und einrichten
sudo -u tradingbot -H bash -c '
  cd ~ && git clone https://github.com/Tttiiimmm-code/Bot.git Bot && cd Bot
  python3 -m venv .venv
  .venv/bin/pip install -r requirements.txt
  cp .env.example .env
'
# .env mit den echten Alpaca-Paper-API-Keys befüllen (ALPACA_PAPER=true lassen!):
sudo -u tradingbot nano /home/tradingbot/Bot/.env

# 3) Service installieren, aktivieren, starten
sudo cp /home/tradingbot/Bot/deploy/tradingbot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now tradingbot

# 4) Status prüfen / Logs live verfolgen
sudo systemctl status tradingbot
sudo journalctl -u tradingbot -f
```

Passe in `deploy/tradingbot.service` `User=`/`WorkingDirectory=`/`ExecStart=` an, falls du einen
anderen User oder Pfad verwendest. Neu starten nach einer `.env`-Änderung:
`sudo systemctl restart tradingbot`. Dauerhaft stoppen: `sudo systemctl disable --now tradingbot`.

Die Units aller Dienste liegen in `deploy/` (Übersicht oben unter "Was wo läuft"). Wichtig: zwei Bots nie mit
derselben `.env` betreiben -- beide würden im selben Alpaca-Konto handeln und sich gegenseitig Positionen
verändern.

**Änderungen ausrollen** (VPS `root@116.203.115.99`, Repo `/home/tradingbot/Bot`, Branch `feature/forward-test`):

```bash
# lokal committen und pushen, dann auf dem VPS:
cd /home/tradingbot/Bot && sudo -u tradingbot git pull
sudo cp deploy/<dienst>.service deploy/<dienst>.timer /etc/systemd/system/   # nur bei geänderten Units
sudo systemctl daemon-reload && sudo systemctl restart <dienst>
```

- Nicht schnell hintereinander neu starten (StartLimit; falls ausgelöst: `systemctl reset-failed <dienst>`).
- API-lastige Arbeiten erst nach 17:30 deutscher Zeit, solange die Bots handeln.
- Neue Abhängigkeiten in `requirements.txt` eintragen und auf dem VPS installieren; neue Dienste/Timer in
  `tradingbot/health.py` (`SERVICES`/`ONESHOTS`), neue Datendateien in `deploy/backup-data.sh` und `.gitignore`.
- `/opt/ict-bot` auf dem VPS gehört nicht zu diesem Projekt und bleibt unangetastet.

## Tests

Alle Tests laufen ohne Netzwerkzugriff:

```bash
.venv/Scripts/python -m pytest tests/ -q -p no:warnings
```

Jede Fehlerbehebung bekommt einen Regressionstest.

## Projektstruktur

```
main.py                  CLI-Einstiegspunkt für alle Befehle (python main.py --help)
tradingbot/cli/          Parser (parser.py) und Befehle je Gruppe: sma, momentum, overnight, copilot, forward
tradingbot/
  config.py, broker.py   Konfiguration, Alpaca-Wrapper (lehnt Live-Konten ab)
  strategy.py, bot.py    Referenz-Bot SMA-Crossover
  backtest.py, validation.py, walkforward.py   Backtest und Out-of-Sample-Prüfung des Referenz-Bots
  momentum.py            Bull-Flag/Flat-Top-Engine + Momentum-Backtest auf Minutendaten
  scanner.py             Marktweiter Aktien-Scanner
  momentum_live.py       Live-Momentum-Bot (Paper)
  momentum_checkpoint.py Prüfpunkte 100/150 Trades des Momentum-Vorwärtstests
  news_intel.py          LLM-Einschätzung von News/SEC-Meldungen (Schattenmodus)
  report.py              P&L-Report aus Alpacas Order-Historie (momentum-report/-compare)
  overnight_live.py      Overnight-ETF-Portfolio-Bot
  pelosi_bot.py          Pelosi-Kopier-Bot (Paper)
  gold_live.py           Gold-Ausbruch mit OANDA-Demo-Orders
  copilot.py             Trading-Copilot: Regeln, Positionsgröße, Stop, Journal
  orb_scanner.py         ORB-Setup-Melder für den Copilot
  replay.py              Übungsmodus (vergangener Tag Kerze für Kerze)
  weekly_report.py       Wochenbericht der Copilot-Trades
  notify.py              ntfy-Benachrichtigungen
  forward_test.py        Vorwärtstest Nikkei-Nacht, Gotobi, Anleihen-Monatsende
  forward_stocks.py      Vorwärtstest ORB Top 5, Qualität Top 50, Small-Cap Value+Qualität
  forward_gold.py        Vorwärtstest gold_breakout
  forward_pelosi.py      Vorwärtstest pelosi_copy
  forward_status.py      Gemeinsame Auswertungsregel K = 11, Monatsstand
  health.py              Wächter für den VPS
  liquidations.py        Liquidations-Recorder (eigenständig, ohne main.py)
  research/              Backtest-Werkzeuge der Forschung (engine, metrics, orb, swing, universe, strategies)
gui/                     Streamlit-Oberfläche des Copilots (copilot_app, chart, replay_view, auth)
mql5/GoldBreakout.mq5    Gold-Ausbruch als MT5-EA (nur Demo)
deploy/                  systemd-Units und -Timer, backup-data.sh, setup_copilot_vps.sh
research/                PROTOCOL.md und Ergebnisse; die Rundenskripte liegen auf Branch research/ideas
tests/                   Unit-Tests (kein API-Zugriff nötig)
data_cache/              Daten-Cache der Forschung (nicht in git)
```

## Erweitern

- Neue Strategie: eigene Funktion nach dem Muster von `generate_signal` in `strategy.py` schreiben
  und in `bot.py` einhängen.
- Anderer Broker/Markt (z.B. Krypto via ccxt): `broker.py` durch eine passende Implementierung
  mit gleicher Schnittstelle (`get_recent_closes`, `get_position`, `get_account_info`,
  `has_open_buy_order`, `has_open_sell_order`, `buy`, `sell`) ersetzen. `get_account_info()`
  gibt ein `AccountInfo`-Objekt mit `equity` (Gesamtkapital) und `available_cash` (tatsächlich
  freies Kapital) zurück -- Basis für die risikobasierte Positionsgröße (`RISK_PER_TRADE_PCT`).

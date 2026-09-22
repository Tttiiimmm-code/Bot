# Tradingbot (Alpaca, Moving-Average-Crossover)

Ein Python-Tradingbot für US-Aktien/Forex-Symbole über die [Alpaca](https://alpaca.markets)-API.
Standardmäßig läuft er im **Paper-Trading**-Modus (simuliertes Geld, kein echtes Risiko).

⚠️ **Risikohinweis**: Automatisierter Handel kann zu finanziellen Verlusten führen. Dieser Bot
ist eine einfache Referenzimplementierung, keine Anlageberatung. Vor Live-Trading gründlich
testen und nur Kapital einsetzen, dessen Verlust du dir leisten kannst.

## Strategie

Moving-Average-Crossover mit optionalen Bestätigungsfiltern:
- **BUY**, wenn der kurze gleitende Durchschnitt (SMA) den langen von unten nach oben kreuzt
  (Golden Cross) -- UND, falls aktiviert, Trendfilter und RSI-Filter zustimmen.
- **SELL**, wenn der kurze SMA den langen von oben nach unten kreuzt (Death Cross). SELL wird
  NIE gefiltert -- die Filter sollen einen ungünstigen Einstieg verhindern, aber niemals einen
  Ausstieg blockieren.

Fenstergrößen sind über `SHORT_WINDOW` / `LONG_WINDOW` konfigurierbar.

### Trendfilter (`TREND_FILTER_WINDOW`)

BUY nur, wenn der Kurs über dem gleitenden Durchschnitt dieses (längeren) Fensters liegt, z.B.
der 200-Tage-SMA. Soll verhindern, in einem übergeordneten Abwärtstrend zu kaufen, nur weil
kurzfristig ein Rebound einen Golden Cross auslöst. `0` deaktiviert den Filter.

### RSI-Filter (`RSI_WINDOW`)

BUY nur, wenn der RSI (Relative Strength Index) über 50 liegt, also aufwärts gerichtetes
Momentum den Crossover bestätigt. `0` deaktiviert den Filter.

## Risikomanagement

### Trailing-Stop-Loss (`STOP_LOSS_PCT`)

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

### Take-Profit (`TAKE_PROFIT_PCT`)

Überschreitet der Kurs den Einstiegspreis um mehr als `TAKE_PROFIT_PCT`, wird der Gewinn sofort
mitgenommen -- unabhängig vom Crossover-Signal. Anders als der Trailing-Stop bezieht sich das
Ziel immer auf den Einstiegspreis, nicht auf einen laufenden Höchststand. Erscheint im
Backtest-Ergebnis als Trade-Typ `TP`. `TAKE_PROFIT_PCT=0` deaktiviert Take-Profit.

### Risikobasierte Positionsgröße (`RISK_PER_TRADE_PCT`)

Standardmäßig setzt jeder Trade das volle verfügbare Kapital ein (Backtest) bzw. die feste
Stückzahl `QTY` (Live-Bot). Mit `RISK_PER_TRADE_PCT > 0` wird die Positionsgröße stattdessen so
gewählt, dass beim Erreichen des initialen Stops (Einstiegspreis · `STOP_LOSS_PCT`) höchstens
dieser Anteil des aktuellen Kapitals verloren geht -- klassisches Money-Management ("nie mehr als
X% pro Trade riskieren"). Nur wirksam, wenn `STOP_LOSS_PCT > 0` ist (sonst gibt es keinen
Bezugspunkt für "Risiko"). `RISK_PER_TRADE_PCT=0` deaktiviert die Berechnung.

⚠️ **Diese Funktionen sind kein Allheilmittel und keine garantierte Profitsteigerung** -- sie
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

## Robustheit & bekannte Grenzen

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

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# .env mit deinen Alpaca-Paper-API-Keys befüllen (kostenlos unter https://alpaca.markets)
```

## Nutzung

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

## Momentum-Day-Trading-Backtest (experimentell)

Historischer Backtest einer regelbasierten Näherung der öffentlich bekannten
["Warrior Trading" Momentum-Day-Trading-Strategie](https://www.warriortrading.com/momentum-day-trading-strategy/)
(Ross Cameron) auf Minutendaten: Bull-Flag- bzw. Flat-Top-Breakout-Muster, 2:1-Chance-Risiko-
Ziel mit hälftigem Teilverkauf, Breakeven-Stop, Ausstieg bei erster roter Kerze oder
"Extension Bar".

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
- **Neustart mit offener Position:** Findet der Bot beim Start Positionen im Depot, die er
  nicht kennt, stellt er sie samt offener Orders sofort glatt (sonst hätten sie keinen Stop
  und würden nicht vor Handelsschluss geschlossen). Neustarts daher möglichst ohne offene
  Position, also vor 15:30 oder nach 17:30 deutscher Zeit.
- Rückstände werden nachgeholt, aber niemals real gehandelt: wird ein Symbol erst Stunden nach
  Sitzungsbeginn neu aufgenommen, oder war der Bot eine Weile offline (Neustart!), holt er die
  fehlenden Minuten-Bars auf einmal nach, damit Muster (Flagge/Pullback/Swing-Tief) korrekt aus
  der echten Historie erkannt werden -- Signale aus diesem Rückstand lösen aber KEINE echte Order
  mehr aus, sondern werden nur simuliert nachgezogen. Nur ein Signal auf einem aktuellen Balken
  (innerhalb der letzten `2 * --poll-interval-seconds`, mind. 120s) kann real ausgeführt werden.

**Wichtige Einschränkungen -- vor Einsatz unbedingt lesen:**

- **NUR für Paper-Trading gedacht und getestet.** Vor echtem Kapitaleinsatz eigenverantwortlich
  über mehrere Handelstage im Paper-Modus beobachten.
- **IEX deckt nur einen Bruchteil (~2-3%) des gesamten Marktvolumens ab**, nicht die volle
  konsolidierte Tape (SIP) -- Muster-/Relativvolumen-Erkennung basiert auf einem unvollständigen
  Abbild des Marktes.
- **Kein WebSocket-Streaming, sondern Polling** -- die Reaktionszeit auf ein Setup ist durch
  `--poll-interval-seconds` nach unten begrenzt.
- **Kein Zustand übersteht einen Neustart.** Bei einem Absturz mit offener(n) Position(en)
  verliert der Bot jede Kenntnis davon (kein Persistenz-Layer) -- nach einem Absturz IMMER
  manuell im Alpaca-Dashboard prüfen, ob noch offene Positionen/Orders existieren. Die
  Broker-Stop-Order (s.o.) schützt die Position bis Handelsschluss, der Zwangsverkauf vor
  Handelsschluss greift nach einem Absturz aber NICHT (die Stop-Order verfällt am Tagesende).
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

## Konfiguration (`.env`)

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

## Tests

Die Strategie- und Backtest-Logik ist ohne Netzwerkzugriff testbar:

```bash
pytest
```

## Projektstruktur

```
main.py               CLI-Einstiegspunkt (run / backtest / validate / walkforward / momentum-backtest / scan / momentum-run / momentum-report)
tradingbot/
  config.py            Konfiguration aus Umgebungsvariablen
  broker.py            Alpaca-API-Wrapper (Marktdaten, Orders, Positionen)
  strategy.py           Signal-Logik: Crossover + Trendfilter + RSI-Filter
  bot.py               Live-/Paper-Trading-Loop (Moving-Average-Crossover)
  backtest.py          Vektor-Backtest inkl. Transaktionskosten
  validation.py         Out-of-Sample-Validierung (ein Train-/Test-Split)
  walkforward.py        Out-of-Sample-Validierung über mehrere Zeitfenster
  momentum.py            Bull-Flag/Flat-Top-Engine + Momentum-Backtest auf Minutendaten (experimentell)
  scanner.py             Marktweiter Aktien-Scanner, aktueller Marktzustand (experimentell)
  momentum_live.py       Live-Momentum-Bot: Scanner + Momentum-Engine + echte Orders (experimentell)
  report.py               P&L-Report aus Alpacas Order-Historie (momentum-report)
tests/                 Unit-Tests (kein API-Zugriff nötig)
```

## Erweitern

- Neue Strategie: eigene Funktion nach dem Muster von `generate_signal` in `strategy.py` schreiben
  und in `bot.py` einhängen.
- Anderer Broker/Markt (z.B. Krypto via ccxt): `broker.py` durch eine passende Implementierung
  mit gleicher Schnittstelle (`get_recent_closes`, `get_position`, `get_account_info`,
  `has_open_buy_order`, `has_open_sell_order`, `buy`, `sell`) ersetzen. `get_account_info()`
  gibt ein `AccountInfo`-Objekt mit `equity` (Gesamtkapital) und `available_cash` (tatsächlich
  freies Kapital) zurück -- Basis für die risikobasierte Positionsgröße (`RISK_PER_TRADE_PCT`).

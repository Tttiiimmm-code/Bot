# Tradingbot (Alpaca, Moving-Average-Crossover)

Ein Python-Tradingbot für US-Aktien/Forex-Symbole über die [Alpaca](https://alpaca.markets)-API.
Standardmäßig läuft er im **Paper-Trading**-Modus (simuliertes Geld, kein echtes Risiko).

⚠️ **Risikohinweis**: Automatisierter Handel kann zu finanziellen Verlusten führen. Dieser Bot
ist eine einfache Referenzimplementierung, keine Anlageberatung. Vor Live-Trading gründlich
testen und nur Kapital einsetzen, dessen Verlust du dir leisten kannst.

## Strategie

Moving-Average-Crossover:
- **BUY**, wenn der kurze gleitende Durchschnitt (SMA) den langen von unten nach oben kreuzt (Golden Cross).
- **SELL**, wenn der kurze SMA den langen von oben nach unten kreuzt (Death Cross).

Fenstergrößen sind über `SHORT_WINDOW` / `LONG_WINDOW` konfigurierbar.

## Risikomanagement: Stop-Loss

Sobald eine Position offen ist, wird bei jedem Zyklus geprüft, ob der aktuelle Kurs um mehr als
`STOP_LOSS_PCT` unter den Einstiegspreis gefallen ist. Falls ja, wird sofort verkauft –
unabhängig vom Crossover-Signal. Das begrenzt den Verlust pro Trade, unabhängig davon, wie lange
das nächste Death-Cross-Signal noch auf sich warten lässt.

- Live-/Paper-Trading: der Bot fragt den tatsächlichen Einstiegspreis der offenen Position direkt
  bei Alpaca ab (`avg_entry_price`), kein eigener Zustand nötig.
- Backtest/Validierung: der Stop wird auf Basis des Tagesschlusskurses geprüft (keine Intraday-
  Daten verfügbar), ausgelöste Stop-Exits erscheinen im Ergebnis als eigener Trade-Typ `STOP`.
- `STOP_LOSS_PCT=0` deaktiviert den Stop vollständig.

⚠️ Ein fixer prozentualer Stop ist kein Allheilmittel: Bei volatilen Trendmärkten kann ein zu
enger Stop dazu führen, dass Positionen durch normale Schwankungen vorzeitig ausgestoppt werden,
bevor sich der eigentliche Trend fortsetzt ("Whipsaw"). Mit `validate` lässt sich prüfen, ob ein
bestimmter Stop-Loss-Wert für ein Symbol/Parameter-Set tatsächlich hilft oder eher schadet.

## Robustheit & bekannte Grenzen

- **Keine doppelten Orders**: Vor jeder Kauf-/Verkaufsentscheidung prüft der Bot, ob für das
  Symbol bereits eine offene (unausgeführte) Order existiert, und überspringt den Zyklus in dem
  Fall. Das verhindert, dass bei langsamer Order-Füllung (z.B. sehr kurzes
  `POLL_INTERVAL_SECONDS` oder illiquide Symbole) eine zweite Order ausgelöst wird, bevor die
  erste gefüllt ist.
- **Tagesschlusskurs-Latenz**: Der Bot arbeitet mit Tages-Bars, nicht mit Echtzeit-Quotes. Der
  "aktuelle Kurs" (auch für den Stop-Loss-Check) ist der letzte verfügbare Tages-Bar, der bei
  freien Alpaca-Datenplänen bis zu ~15-20 Minuten hinter dem realen Marktgeschehen liegen kann.
  Für einen auf Tagesbasis handelnden Swing-Bot ist das ausreichend, für sehr schnelle
  Kursbewegungen (Flash Crash o.ä.) reagiert der Stop-Loss entsprechend verzögert.
- **API-Fehler werden nicht als "keine Position" verschluckt**: Nur ein tatsächliches 404 ("keine
  Position offen") wird von `Broker.get_position()` als `None` interpretiert. Alle anderen Fehler
  (Netzwerk, Auth, Rate-Limit) werden weitergereicht und lösen im Live-Loop einen geloggten,
  übersprungenen Zyklus aus, statt fälschlich anzunehmen, es sei keine Position offen.

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

Der Backtest berücksichtigt standardmäßig Slippage von 0,05% pro Order (Näherung an den
Bid-Ask-Spread bei liquiden Aktien; Alpaca selbst ist für US-Aktien provisionsfrei). Anpassbar:

```bash
python main.py backtest --days 250 --commission-pct 0.001 --slippage-pct 0.001 --stop-loss-pct 0.08
```

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

**Live-/Paper-Trading-Loop starten** (fragt im konfigurierten Intervall neue Kurse ab und
platziert Market-Orders bei Crossover-Signalen):

```bash
python main.py run
```

Mit `Strg+C` sauber beenden.

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
| `STOP_LOSS_PCT`          | Stop-Loss als Anteil unter dem Einstiegspreis, `0` = aus   | `0.08`  |

## Tests

Die Strategie- und Backtest-Logik ist ohne Netzwerkzugriff testbar:

```bash
pytest
```

## Projektstruktur

```
main.py               CLI-Einstiegspunkt (run / backtest / validate)
tradingbot/
  config.py            Konfiguration aus Umgebungsvariablen
  broker.py            Alpaca-API-Wrapper (Marktdaten, Orders, Positionen)
  strategy.py           Moving-Average-Crossover-Signal-Logik
  bot.py               Live-/Paper-Trading-Loop
  backtest.py          Vektor-Backtest inkl. Transaktionskosten
  validation.py         Out-of-Sample-Validierung (Train-/Test-Split)
tests/                 Unit-Tests (kein API-Zugriff nötig)
```

## Erweitern

- Neue Strategie: eigene Funktion nach dem Muster von `generate_signal` in `strategy.py` schreiben
  und in `bot.py` einhängen.
- Anderer Broker/Markt (z.B. Krypto via ccxt): `broker.py` durch eine passende Implementierung
  mit gleicher Schnittstelle (`get_recent_closes`, `get_position`, `has_open_order`, `buy`,
  `sell`) ersetzen.

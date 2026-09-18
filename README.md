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

## Tests

Die Strategie- und Backtest-Logik ist ohne Netzwerkzugriff testbar:

```bash
pytest
```

## Projektstruktur

```
main.py               CLI-Einstiegspunkt (run / backtest)
tradingbot/
  config.py            Konfiguration aus Umgebungsvariablen
  broker.py            Alpaca-API-Wrapper (Marktdaten, Orders, Positionen)
  strategy.py           Moving-Average-Crossover-Signal-Logik
  bot.py               Live-/Paper-Trading-Loop
  backtest.py          Einfacher Vektor-Backtest
tests/                 Unit-Tests (kein API-Zugriff nötig)
```

## Erweitern

- Neue Strategie: eigene Funktion nach dem Muster von `generate_signal` in `strategy.py` schreiben
  und in `bot.py` einhängen.
- Anderer Broker/Markt (z.B. Krypto via ccxt): `broker.py` durch eine passende Implementierung
  mit gleicher Schnittstelle (`get_recent_closes`, `get_position_qty`, `buy`, `sell`) ersetzen.

"""Befehl overnight-run (Overnight-Portfolio-Bot, eigenes Konto)."""
from __future__ import annotations


def cmd_overnight_run(env_file: str, dry_run: bool, allow_live_trading: bool):
    """Overnight-Portfolio als Paper-Bot (tradingbot/overnight_live.py). Liest
    die Keys bewusst NUR aus `env_file` (eigenes Alpaca-Konto), nicht aus .env."""
    from pathlib import Path

    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.trading.client import TradingClient
    from dotenv import dotenv_values

    from tradingbot.overnight_live import OvernightBot, OvernightConfig

    if not Path(env_file).exists():
        raise RuntimeError(
            f"{env_file} nicht gefunden. Der Overnight-Bot braucht ein EIGENES Alpaca-Paper-Konto "
            "(der Momentum-Bot stellt fremde Positionen beim Start glatt): Keys dort eintragen."
        )
    values = dotenv_values(env_file)
    key, secret = values.get("ALPACA_API_KEY"), values.get("ALPACA_SECRET_KEY")
    if not key or not secret:
        raise RuntimeError(f"ALPACA_API_KEY/ALPACA_SECRET_KEY fehlen in {env_file}.")
    paper_raw = (values.get("ALPACA_PAPER") or "true").strip().lower()
    if paper_raw not in ("1", "true", "yes", "0", "false", "no"):
        raise ValueError(f"ALPACA_PAPER in {env_file} muss true/false sein, nicht {paper_raw!r}.")
    paper = paper_raw in ("1", "true", "yes")
    if not paper and not allow_live_trading:
        raise RuntimeError(
            "overnight-run ist nur für Paper-Trading gedacht, aber ALPACA_PAPER=false ist gesetzt. "
            "Für echtes Geld zusätzlich --allow-live-trading angeben (auf eigenes Risiko)."
        )
    bot = OvernightBot(
        OvernightConfig(dry_run=dry_run),
        TradingClient(key, secret, paper=paper),
        StockHistoricalDataClient(key, secret),
        paper=paper,
    )
    bot.run_forever()

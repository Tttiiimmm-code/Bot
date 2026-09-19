"""Konfiguration des Tradingbots, geladen aus Umgebungsvariablen / .env."""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Config:
    api_key: str
    secret_key: str
    paper: bool
    symbol: str
    qty: float
    short_window: int
    long_window: int
    poll_interval_seconds: int
    stop_loss_pct: float

    @classmethod
    def from_env(cls) -> "Config":
        api_key = os.getenv("ALPACA_API_KEY", "")
        secret_key = os.getenv("ALPACA_SECRET_KEY", "")
        if not api_key or not secret_key:
            raise RuntimeError(
                "ALPACA_API_KEY und ALPACA_SECRET_KEY müssen gesetzt sein "
                "(siehe .env.example)."
            )

        symbol = os.getenv("SYMBOL", "AAPL").strip().upper()
        if not symbol:
            raise ValueError("SYMBOL darf nicht leer sein.")

        short_window = int(os.getenv("SHORT_WINDOW", "20"))
        long_window = int(os.getenv("LONG_WINDOW", "50"))
        if short_window < 1:
            raise ValueError("SHORT_WINDOW muss mindestens 1 sein.")
        if short_window >= long_window:
            raise ValueError("SHORT_WINDOW muss kleiner als LONG_WINDOW sein.")

        qty = float(os.getenv("QTY", "1"))
        if qty <= 0:
            raise ValueError("QTY muss größer als 0 sein.")

        poll_interval_seconds = int(os.getenv("POLL_INTERVAL_SECONDS", "60"))
        if poll_interval_seconds <= 0:
            raise ValueError("POLL_INTERVAL_SECONDS muss größer als 0 sein.")

        stop_loss_pct = float(os.getenv("STOP_LOSS_PCT", "0.08"))
        if stop_loss_pct < 0:
            raise ValueError("STOP_LOSS_PCT darf nicht negativ sein (0 = deaktiviert).")
        if stop_loss_pct >= 1:
            raise ValueError("STOP_LOSS_PCT muss kleiner als 1 (100%) sein.")

        return cls(
            api_key=api_key,
            secret_key=secret_key,
            paper=os.getenv("ALPACA_PAPER", "true").lower() in ("1", "true", "yes"),
            symbol=symbol,
            qty=qty,
            short_window=short_window,
            long_window=long_window,
            poll_interval_seconds=poll_interval_seconds,
            stop_loss_pct=stop_loss_pct,
        )

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

    @classmethod
    def from_env(cls) -> "Config":
        api_key = os.getenv("ALPACA_API_KEY", "")
        secret_key = os.getenv("ALPACA_SECRET_KEY", "")
        if not api_key or not secret_key:
            raise RuntimeError(
                "ALPACA_API_KEY und ALPACA_SECRET_KEY müssen gesetzt sein "
                "(siehe .env.example)."
            )

        short_window = int(os.getenv("SHORT_WINDOW", "20"))
        long_window = int(os.getenv("LONG_WINDOW", "50"))
        if short_window >= long_window:
            raise ValueError("SHORT_WINDOW muss kleiner als LONG_WINDOW sein.")

        return cls(
            api_key=api_key,
            secret_key=secret_key,
            paper=os.getenv("ALPACA_PAPER", "true").lower() in ("1", "true", "yes"),
            symbol=os.getenv("SYMBOL", "AAPL").upper(),
            qty=float(os.getenv("QTY", "1")),
            short_window=short_window,
            long_window=long_window,
            poll_interval_seconds=int(os.getenv("POLL_INTERVAL_SECONDS", "60")),
        )

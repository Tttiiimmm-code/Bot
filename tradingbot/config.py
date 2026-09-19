"""Konfiguration des Tradingbots, geladen aus Umgebungsvariablen / .env."""

from __future__ import annotations

import math
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

        paper_raw = os.getenv("ALPACA_PAPER", "true").strip().lower()
        if paper_raw in ("1", "true", "yes"):
            paper = True
        elif paper_raw in ("0", "false", "no"):
            paper = False
        else:
            # Bewusst kein stillschweigender Fallback: ein Tippfehler wie
            # "flase" soll niemals unbemerkt zu Live-Trading mit echtem
            # Geld führen.
            raise ValueError(
                f"ALPACA_PAPER muss true/false (oder 1/0, yes/no) sein, nicht {paper_raw!r}."
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
        # math.isfinite() ist hier zwingend: `qty <= 0` allein lässt NaN
        # (Vergleich immer False) und +inf durch, was als Order-Menge an
        # die Broker-API durchgereicht würde.
        if not math.isfinite(qty) or qty <= 0:
            raise ValueError("QTY muss eine positive, endliche Zahl sein.")

        poll_interval_seconds = int(os.getenv("POLL_INTERVAL_SECONDS", "60"))
        # Obergrenze verhindert einen OverflowError in time.sleep() bei
        # einem (z.B. um ein paar Nullen zu langen) Tippfehler; 1 Woche ist
        # für ein tagesbasiertes Polling bereits weit über jedem sinnvollen
        # Wert und liegt sicher unterhalb der C-time_t-Grenze.
        if not 0 < poll_interval_seconds <= 604_800:
            raise ValueError("POLL_INTERVAL_SECONDS muss zwischen 1 und 604800 (1 Woche) liegen.")

        stop_loss_pct = float(os.getenv("STOP_LOSS_PCT", "0.08"))
        # Verkettete Prüfung statt zweier separater Vergleiche: NaN
        # erfüllt weder "< 0" noch ">= 1" und würde sonst durchrutschen --
        # der Stop-Loss-Check in bot.py (`stop_loss_pct > 0`) wäre dann für
        # NaN ebenfalls immer False und der Stop liefe unbemerkt ins Leere.
        if not 0 <= stop_loss_pct < 1:
            raise ValueError("STOP_LOSS_PCT muss im Bereich [0, 1) liegen (0 = deaktiviert).")

        return cls(
            api_key=api_key,
            secret_key=secret_key,
            paper=paper,
            symbol=symbol,
            qty=qty,
            short_window=short_window,
            long_window=long_window,
            poll_interval_seconds=poll_interval_seconds,
            stop_loss_pct=stop_loss_pct,
        )

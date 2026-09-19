"""Haupt-Loop des Tradingbots: Daten holen, Signal berechnen, Order platzieren."""

from __future__ import annotations

import logging
import time

from tradingbot.broker import Broker
from tradingbot.config import Config
from tradingbot.strategy import Signal, generate_signal

logger = logging.getLogger(__name__)


class TradingBot:
    def __init__(self, config: Config, broker: Broker | None = None):
        self.config = config
        self.broker = broker or Broker(config)

    def run_once(self) -> Signal:
        """Führt einen einzelnen Entscheidungszyklus aus und gibt das Signal zurück."""
        closes = self.broker.get_recent_closes(limit=self.config.long_window + 5)
        if len(closes) < self.config.long_window + 1:
            logger.info(
                "Zu wenig Kursdaten (%d von %d benötigt), überspringe Zyklus.",
                len(closes),
                self.config.long_window + 1,
            )
            return Signal.HOLD

        current_price = closes.iloc[-1]
        position = self.broker.get_position()

        if position and position.qty > 0 and self.config.stop_loss_pct > 0:
            stop_price = position.avg_entry_price * (1 - self.config.stop_loss_pct)
            if current_price <= stop_price:
                if self.broker.has_open_sell_order():
                    logger.info(
                        "STOP-LOSS ausgelöst, aber bereits eine offene Verkaufs-Order für %s -> überspringe Zyklus.",
                        self.config.symbol,
                    )
                    return Signal.HOLD
                logger.warning(
                    "STOP-LOSS ausgelöst: Kurs %.2f <= Stop %.2f (Einstieg %.2f) -> VERKAUFE %s %s",
                    current_price,
                    stop_price,
                    position.avg_entry_price,
                    position.qty,
                    self.config.symbol,
                )
                self.broker.sell(position.qty)
                return Signal.SELL

        signal = generate_signal(closes, self.config.short_window, self.config.long_window)
        position_qty = position.qty if position else 0.0

        if signal == Signal.BUY and position_qty <= 0:
            if self.broker.has_open_buy_order():
                logger.info("Bereits eine offene Kauf-Order für %s -> überspringe Zyklus.", self.config.symbol)
                return Signal.HOLD
            logger.info("Golden Cross erkannt -> KAUFE %s %s", self.config.qty, self.config.symbol)
            self.broker.buy(self.config.qty)
        elif signal == Signal.SELL and position_qty > 0:
            if self.broker.has_open_sell_order():
                logger.info("Bereits eine offene Verkaufs-Order für %s -> überspringe Zyklus.", self.config.symbol)
                return Signal.HOLD
            logger.info("Death Cross erkannt -> VERKAUFE %s %s", position_qty, self.config.symbol)
            self.broker.sell(position_qty)
        else:
            logger.info("Signal=%s, Position=%s -> keine Aktion", signal, position_qty)

        return signal

    def run_forever(self):
        logger.info(
            "Starte Tradingbot für %s (paper=%s, short=%d, long=%d, intervall=%ds)",
            self.config.symbol,
            self.config.paper,
            self.config.short_window,
            self.config.long_window,
            self.config.poll_interval_seconds,
        )
        try:
            while True:
                try:
                    self.run_once()
                except Exception:
                    logger.exception("Fehler im Handelszyklus, versuche es beim nächsten Intervall erneut.")
                time.sleep(self.config.poll_interval_seconds)
        except KeyboardInterrupt:
            logger.info("Tradingbot wird beendet (KeyboardInterrupt).")

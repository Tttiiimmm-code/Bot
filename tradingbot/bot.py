"""Haupt-Loop des Tradingbots: Daten holen, Signal berechnen, Order platzieren."""

from __future__ import annotations

import logging
import math
import time

from tradingbot.broker import Broker
from tradingbot.config import Config
from tradingbot.strategy import Signal, generate_signal

logger = logging.getLogger(__name__)


class TradingBot:
    def __init__(self, config: Config, broker: Broker | None = None):
        self.config = config
        self.broker = broker or Broker(config)
        # Höchster seit Einstieg beobachteter Kurs je Symbol, für den
        # Trailing-Stop. Rein im Prozessspeicher: überlebt einen Neustart
        # des Bots nicht. Nach einem Neustart mit noch offener Position
        # startet die Nachverfolgung konservativ wieder beim Einstiegspreis
        # (siehe run_once) -- der Stop fällt dabei höchstens auf das
        # ursprüngliche, weitere Niveau zurück, nie auf ein gefährlich
        # engeres.
        self._peak_price_by_symbol: dict[str, float] = {}

    def _compute_buy_qty(self, current_price: float) -> float:
        """Stückzahl für einen Kauf: risikobasiert, wenn RISK_PER_TRADE_PCT
        aktiviert ist (und ein Stop-Loss als Risikobezug existiert), sonst
        die feste Stückzahl aus QTY."""
        if self.config.risk_per_trade_pct > 0 and self.config.stop_loss_pct > 0:
            equity = self.broker.get_account_equity()
            risk_amount = equity * self.config.risk_per_trade_pct
            # RISK_PER_TRADE_PCT und STOP_LOSS_PCT werden unabhängig
            # voneinander validiert (je [0, 1)) -- ihr Verhältnis kann
            # trotzdem > 1 ergeben (z.B. 10% Risiko bei 8% Stop = 125% des
            # Kapitals). Wie im Backtest (dort: notional = min(cash, ...))
            # wird die Notional-Größe hier hart auf das verfügbare Kapital
            # gedeckelt -- sonst könnte auf einem Margin-Konto eine Order
            # weit über das beabsichtigte "Risiko pro Trade" hinaus
            # gehebelt werden, auf einem Cash-Konto würde sie schlicht
            # jeden Zyklus als "insufficient buying power" abgelehnt.
            notional = min(equity, risk_amount / self.config.stop_loss_pct)
            return notional / current_price
        return self.config.qty

    def run_once(self) -> Signal:
        """Führt einen einzelnen Entscheidungszyklus aus und gibt das Signal zurück."""
        required_window = max(self.config.long_window, self.config.trend_window, self.config.rsi_window)
        closes = self.broker.get_recent_closes(limit=required_window + 5)
        if len(closes) < required_window + 1:
            logger.info(
                "Zu wenig Kursdaten (%d von %d benötigt), überspringe Zyklus.",
                len(closes),
                required_window + 1,
            )
            return Signal.HOLD

        current_price = closes.iloc[-1]
        # Ein kaputter letzter Datenpunkt (NaN oder <= 0, z.B. ein
        # Delisting/Datenfehler beim Broker) darf keinerlei Handelsaktion
        # auslösen: <=0 wäre <= jeder positiven Stop-Schwelle (spontaner
        # Verkauf auf Basis von Datenmüll), und dieselbe Kerze fließt auch
        # in generate_signal() ein und könnte dort ein Crossover-Signal aus
        # dem Datenmüll erzeugen. Deshalb wird der GESAMTE Zyklus
        # übersprungen, nicht nur der Stop-Loss-Zweig -- ein einzelner
        # gezielter Check pro Aktionspfad ist leicht zu vergessen, wenn ein
        # neuer Aktionspfad hinzukommt.
        if not (math.isfinite(current_price) and current_price > 0):
            logger.warning(
                "Ungültiger aktueller Kurs (%s) für %s erhalten -> überspringe Zyklus.",
                current_price,
                self.config.symbol,
            )
            return Signal.HOLD

        position = self.broker.get_position()
        symbol = self.config.symbol

        if position and position.qty > 0:
            peak = max(self._peak_price_by_symbol.get(symbol, position.avg_entry_price), current_price)
            self._peak_price_by_symbol[symbol] = peak

            if self.config.stop_loss_pct > 0:
                stop_price = peak * (1 - self.config.stop_loss_pct)
                if current_price <= stop_price:
                    if self.broker.has_open_sell_order():
                        logger.info(
                            "STOP-LOSS ausgelöst, aber bereits eine offene Verkaufs-Order für %s -> überspringe Zyklus.",
                            symbol,
                        )
                        return Signal.HOLD
                    logger.warning(
                        "STOP-LOSS (Trailing) ausgelöst: Kurs %.2f <= Stop %.2f (Höchststand %.2f, Einstieg %.2f) -> VERKAUFE %s %s",
                        current_price,
                        stop_price,
                        peak,
                        position.avg_entry_price,
                        position.qty,
                        symbol,
                    )
                    self.broker.sell(position.qty)
                    self._peak_price_by_symbol.pop(symbol, None)
                    return Signal.SELL

            if self.config.take_profit_pct > 0:
                target_price = position.avg_entry_price * (1 + self.config.take_profit_pct)
                if current_price >= target_price:
                    if self.broker.has_open_sell_order():
                        logger.info(
                            "TAKE-PROFIT erreicht, aber bereits eine offene Verkaufs-Order für %s -> überspringe Zyklus.",
                            symbol,
                        )
                        return Signal.HOLD
                    logger.warning(
                        "TAKE-PROFIT erreicht: Kurs %.2f >= Ziel %.2f (Einstieg %.2f) -> VERKAUFE %s %s",
                        current_price,
                        target_price,
                        position.avg_entry_price,
                        position.qty,
                        symbol,
                    )
                    self.broker.sell(position.qty)
                    self._peak_price_by_symbol.pop(symbol, None)
                    return Signal.SELL
        else:
            self._peak_price_by_symbol.pop(symbol, None)

        signal = generate_signal(
            closes,
            self.config.short_window,
            self.config.long_window,
            self.config.trend_window,
            self.config.rsi_window,
        )
        position_qty = position.qty if position else 0.0

        if signal == Signal.BUY and position_qty <= 0:
            if self.broker.has_open_buy_order():
                logger.info("Bereits eine offene Kauf-Order für %s -> überspringe Zyklus.", symbol)
                return Signal.HOLD
            qty = self._compute_buy_qty(current_price)
            logger.info("Golden Cross erkannt -> KAUFE %s %s", qty, symbol)
            self.broker.buy(qty)
        elif signal == Signal.SELL and position_qty > 0:
            if self.broker.has_open_sell_order():
                logger.info("Bereits eine offene Verkaufs-Order für %s -> überspringe Zyklus.", symbol)
                return Signal.HOLD
            logger.info("Death Cross erkannt -> VERKAUFE %s %s", position_qty, symbol)
            self.broker.sell(position_qty)
            self._peak_price_by_symbol.pop(symbol, None)
        else:
            logger.info("Signal=%s, Position=%s -> keine Aktion", signal, position_qty)

        return signal

    def run_forever(self):
        logger.info(
            "Starte Tradingbot für %s (paper=%s, short=%d, long=%d, trend=%d, rsi=%d, "
            "stop=%.2f%%, take_profit=%.2f%%, risk_per_trade=%.2f%%, intervall=%ds)",
            self.config.symbol,
            self.config.paper,
            self.config.short_window,
            self.config.long_window,
            self.config.trend_window,
            self.config.rsi_window,
            self.config.stop_loss_pct * 100,
            self.config.take_profit_pct * 100,
            self.config.risk_per_trade_pct * 100,
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

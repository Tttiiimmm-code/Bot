"""Overnight-Portfolio als Paper-Bot (Vorwärtstest des besten Forschungs-
kandidaten, siehe research/PROTOCOL.md, "E-Portfolio").

Regel: Kurz vor Handelsschluss wird jedes ETF aus `symbols`, dessen
aktueller Kurs über dem 200-Tage-Durchschnitt der Vortages-Schlüsse liegt,
per Market-on-Close-Order (TimeInForce.CLS) mit je 1/n des Kapitals gekauft.
Am nächsten Morgen wird alles per Market-on-Open-Order (TimeInForce.OPG)
verkauft. Kein Day Trade -> keine PDT-Regel; im Cash-Konto wäre der tägliche
Wiederkauf mit unabgewickeltem Geld aber eine Good-Faith-Violation, daher
Margin-Konto (ohne Hebel genutzt).

Abweichung vom Backtest: Alpaca nimmt CLS-Orders nur bis 10 Minuten vor
Handelsschluss an, deshalb fällt die Entscheidung 15 Minuten vorher (Backtest:
10 Minuten vorher).

WICHTIG: Eigenes Alpaca-Paper-Konto verwenden (eigene Keys, z.B. in
overnight.env). Der Momentum-Bot (momentum-run) stellt beim Start ALLE
unbekannten Positionen im Konto glatt und würde die Overnight-Positionen
verkaufen.

Zustand (heute gekaufte Orders) liegt in `state_file`, damit ein Neustart
über Nacht die Zuordnung der Käufe nicht verliert. Jede abgeschlossene Nacht
wird in `trade_log` (CSV) protokolliert.
"""

from __future__ import annotations

import csv
import json
import logging
import math
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

NY = ZoneInfo("America/New_York")
DEFAULT_SYMBOLS = ("SPY", "QQQ", "IWM", "DIA", "XLK", "XLF", "XLE", "SMH")


@dataclass(frozen=True)
class OvernightConfig:
    symbols: tuple[str, ...] = DEFAULT_SYMBOLS
    sma_window: int = 200
    # Entscheidung + CLS-Orders so viele Minuten vor Handelsschluss
    # (Alpaca-Annahmeschluss für CLS: 10 Minuten vorher).
    decision_minutes_before_close: int = 15
    # OPG-Verkaufsorders so viele Minuten vor Handelsbeginn (Annahmeschluss 9:28).
    sell_minutes_before_open: int = 10
    # Nicht per OPG gefüllte Restpositionen so viele Minuten nach Open per Market verkaufen.
    fallback_sell_minutes_after_open: int = 5
    poll_interval_seconds: int = 20
    state_file: Path = Path("overnight_state.json")
    trade_log: Path = Path("overnight_trades.csv")
    dry_run: bool = False


@dataclass
class _Session:
    day: date
    open: datetime
    close: datetime


@dataclass
class _State:
    """Überlebt Neustarts (JSON). `buys`: Kauf-Orders des letzten Abends,
    symbol -> order_id. `sold_for`/`logged_for`: Kauftag, dessen Positionen
    bereits zum Verkauf gegeben bzw. protokolliert wurden."""

    bought_on: str | None = None
    buys: dict[str, str] = field(default_factory=dict)
    sells: dict[str, str] = field(default_factory=dict)
    sold_for: str | None = None
    logged_for: str | None = None

    @classmethod
    def load(cls, path: Path) -> "_State":
        if not path.exists():
            return cls()
        return cls(**json.loads(path.read_text(encoding="utf-8")))

    def save(self, path: Path) -> None:
        path.write_text(json.dumps(self.__dict__, indent=2), encoding="utf-8")


def trend_signal(price: float, prior_closes: list[float], window: int) -> tuple[bool, float | None]:
    """(kaufen?, SMA). Ohne volle Historie kein Kauf."""
    if len(prior_closes) < window:
        return False, None
    sma = sum(prior_closes[-window:]) / window
    return price > sma, sma


def target_qty(equity: float, n_symbols: int, price: float) -> int:
    """Ganze Stück für 1/n des Kapitals, ohne Hebel."""
    if price <= 0 or equity <= 0:
        return 0
    return int(math.floor(equity / n_symbols / price))


class OvernightBot:
    def __init__(self, config: OvernightConfig, trading_client, data_client, paper: bool = True):
        self.config = config
        self.trading_client = trading_client
        self.data_client = data_client
        self.paper = paper
        self.state = _State.load(config.state_file)
        self._session_cache: tuple[date, _Session | None] | None = None

    # ------------------------------------------------------------ Zeitplan

    def _session(self, today: date) -> _Session | None:
        if self._session_cache and self._session_cache[0] == today:
            return self._session_cache[1]
        from alpaca.trading.requests import GetCalendarRequest

        cal = self.trading_client.get_calendar(GetCalendarRequest(start=today, end=today))
        session = None
        if cal:
            c = cal[0]
            session = _Session(day=c.date, open=_as_ny(c.open), close=_as_ny(c.close))
        self._session_cache = (today, session)
        return session

    def run_once(self, now: datetime | None = None) -> None:
        now = (now or datetime.now(timezone.utc)).astimezone(NY)
        session = self._session(now.date())
        if session is None:
            return
        cfg = self.config
        today = session.day.isoformat()

        # Morgen: Positionen vom letzten Abend verkaufen
        if self.state.bought_on and self.state.bought_on != today:
            sell_from = session.open - timedelta(minutes=cfg.sell_minutes_before_open)
            sell_until = session.open - timedelta(minutes=2)
            if self.state.sold_for != self.state.bought_on and sell_from <= now < sell_until:
                self._submit_morning_sells()
            fallback_at = session.open + timedelta(minutes=cfg.fallback_sell_minutes_after_open)
            if now >= fallback_at and self.state.logged_for != self.state.bought_on:
                self._finish_night()

        # Abend: neue Käufe zum Schlusskurs
        decide_from = session.close - timedelta(minutes=cfg.decision_minutes_before_close)
        decide_until = session.close - timedelta(minutes=10)
        if self.state.bought_on != today and decide_from <= now < decide_until:
            if self.state.bought_on and self.state.logged_for != self.state.bought_on:
                self._finish_night()  # Morgen-Abschluss nachholen, bevor neu gekauft wird
            self._submit_evening_buys(session)

    # ------------------------------------------------------------ Abend

    def _prior_closes(self, today: date) -> dict[str, list[float]]:
        from alpaca.data.enums import Adjustment, DataFeed
        from alpaca.data.requests import StockBarsRequest
        from alpaca.data.timeframe import TimeFrame

        start = datetime.combine(today - timedelta(days=int(self.config.sma_window * 1.6) + 30),
                                 datetime.min.time(), tzinfo=NY)
        end = datetime.combine(today, datetime.min.time(), tzinfo=NY)
        df = self.data_client.get_stock_bars(StockBarsRequest(
            symbol_or_symbols=list(self.config.symbols), timeframe=TimeFrame.Day, start=start, end=end,
            adjustment=Adjustment.SPLIT, feed=DataFeed.SIP,
        )).df
        out: dict[str, list[float]] = {}
        for sym in self.config.symbols:
            if df.empty or sym not in df.index.get_level_values("symbol"):
                out[sym] = []
                continue
            bars = df.xs(sym, level="symbol")
            days = bars.index.tz_convert(NY).date
            out[sym] = bars["close"][days < today].astype(float).tolist()
        return out

    def _latest_prices(self) -> dict[str, float]:
        from alpaca.data.enums import DataFeed
        from alpaca.data.requests import StockLatestTradeRequest

        trades = self.data_client.get_stock_latest_trade(
            StockLatestTradeRequest(symbol_or_symbols=list(self.config.symbols), feed=DataFeed.IEX)
        )
        return {sym: float(t.price) for sym, t in trades.items()}

    def _submit_evening_buys(self, session: _Session) -> None:
        from alpaca.trading.enums import OrderSide, TimeInForce
        from alpaca.trading.requests import MarketOrderRequest

        cfg = self.config
        prices = self._latest_prices()
        closes = self._prior_closes(session.day)
        equity = float(self.trading_client.get_account().equity)
        held = {p.symbol: int(float(p.qty)) for p in self.trading_client.get_all_positions()}
        buys: dict[str, str] = {}
        for sym in cfg.symbols:
            price = prices.get(sym)
            if price is None:
                logger.warning("%s: kein aktueller Kurs, übersprungen", sym)
                continue
            go, sma = trend_signal(price, closes.get(sym, []), cfg.sma_window)
            qty = target_qty(equity, len(cfg.symbols), price) - held.get(sym, 0)
            logger.info("%s: Kurs %.2f, SMA%d %s -> %s (Stück %d, bereits gehalten %d)", sym, price,
                        cfg.sma_window, f"{sma:.2f}" if sma else "n/a",
                        "KAUF zum Schlusskurs" if go and qty > 0 else "kein Kauf", max(qty, 0),
                        held.get(sym, 0))
            if not go or qty <= 0:
                continue
            if cfg.dry_run:
                buys[sym] = "dry-run"
                continue
            order = self.trading_client.submit_order(MarketOrderRequest(
                symbol=sym, qty=qty, side=OrderSide.BUY, time_in_force=TimeInForce.CLS))
            buys[sym] = str(order.id)
        self.state.bought_on = session.day.isoformat()
        self.state.buys = buys
        self.state.sells = {}
        self.state.save(cfg.state_file)
        logger.info("Abend %s: %d Kauf-Order(s) zum Schlusskurs (Kapital %.2f)", session.day, len(buys), equity)

    # ------------------------------------------------------------ Morgen

    def _submit_morning_sells(self) -> None:
        from alpaca.trading.enums import OrderSide, TimeInForce
        from alpaca.trading.requests import MarketOrderRequest

        sells: dict[str, str] = {}
        for p in self.trading_client.get_all_positions():
            if p.symbol not in self.config.symbols:
                logger.warning("Fremde Position %s im Konto -- bleibt unberührt (eigenes Konto verwenden!)",
                               p.symbol)
                continue
            qty = int(float(p.qty))
            if qty <= 0:
                continue
            if self.config.dry_run:
                sells[p.symbol] = "dry-run"
                continue
            order = self.trading_client.submit_order(MarketOrderRequest(
                symbol=p.symbol, qty=qty, side=OrderSide.SELL, time_in_force=TimeInForce.OPG))
            sells[p.symbol] = str(order.id)
        self.state.sells = sells
        self.state.sold_for = self.state.bought_on
        self.state.save(self.config.state_file)
        logger.info("Morgen: %d Verkaufs-Order(s) zum Eröffnungskurs für Käufe vom %s",
                    len(sells), self.state.bought_on)

    def _finish_night(self) -> None:
        """Nach Handelsbeginn: nicht gefüllte Reste per Market verkaufen und
        die Nacht protokollieren."""
        from alpaca.trading.enums import OrderSide, TimeInForce
        from alpaca.trading.requests import MarketOrderRequest

        if not self.config.dry_run:
            for p in self.trading_client.get_all_positions():
                qty = int(float(p.qty))
                if p.symbol in self.config.symbols and qty > 0:
                    logger.error("%s: %d Stück nach Handelsbeginn noch im Depot -- Market-Verkauf", p.symbol, qty)
                    order = self.trading_client.submit_order(MarketOrderRequest(
                        symbol=p.symbol, qty=qty, side=OrderSide.SELL, time_in_force=TimeInForce.DAY))
                    self.state.sells[p.symbol] = str(order.id)
        self._log_night()
        self.state.logged_for = self.state.bought_on
        self.state.sold_for = self.state.bought_on
        self.state.save(self.config.state_file)

    def _fill(self, order_id: str) -> tuple[float, float] | None:
        if not order_id or order_id == "dry-run":
            return None
        o = self.trading_client.get_order_by_id(order_id)
        if o.filled_avg_price is None or not o.filled_qty:
            return None
        return float(o.filled_qty), float(o.filled_avg_price)

    def _log_night(self) -> None:
        path = self.config.trade_log
        new = not path.exists()
        rows, total = [], 0.0
        for sym, buy_id in self.state.buys.items():
            buy = self._fill(buy_id)
            sell = self._fill(self.state.sells.get(sym, ""))
            if buy is None:
                logger.info("%s: Kauf-Order nicht gefüllt", sym)
                continue
            if sell is None:
                logger.error("%s: Verkauf noch nicht gefüllt -- im Alpaca-Dashboard prüfen", sym)
                continue
            qty, buy_px = buy
            _, sell_px = sell
            pnl = qty * (sell_px - buy_px)
            total += pnl
            rows.append([self.state.bought_on, sym, int(qty), f"{buy_px:.4f}", f"{sell_px:.4f}",
                         f"{pnl:.2f}", f"{sell_px / buy_px - 1:.6f}"])
        if rows:
            with path.open("a", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                if new:
                    w.writerow(["bought_on", "symbol", "qty", "buy_price", "sell_price", "pnl", "return"])
                w.writerows(rows)
        logger.info("Nacht ab %s abgeschlossen: %d Positionen, P&L %.2f $", self.state.bought_on, len(rows), total)

    # ------------------------------------------------------------ Loop

    def run_forever(self) -> None:
        logger.info("Starte Overnight-Bot (paper=%s, dry_run=%s, Symbole=%s)", self.paper,
                    self.config.dry_run, ",".join(self.config.symbols))
        try:
            while True:
                try:
                    self.run_once()
                except Exception:
                    logger.exception("Fehler im Overnight-Zyklus, nächster Versuch im nächsten Intervall.")
                time.sleep(self.config.poll_interval_seconds)
        except KeyboardInterrupt:
            logger.info("Overnight-Bot wird beendet (KeyboardInterrupt).")


def _as_ny(value) -> datetime:
    ts = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    return ts.replace(tzinfo=NY) if ts.tzinfo is None else ts.astimezone(NY)


def summarize_trade_log(path: Path) -> str:
    """Kurze Auswertung des CSV-Protokolls für `overnight-report`."""
    if not path.exists():
        return f"Noch kein Protokoll ({path})."
    with path.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        return "Protokoll ist leer."
    nights: dict[str, float] = {}
    for r in rows:
        nights[r["bought_on"]] = nights.get(r["bought_on"], 0.0) + float(r["pnl"])
    pnl = list(nights.values())
    wins = sum(1 for p in pnl if p > 0)
    return "\n".join([
        f"Nächte: {len(pnl)} ({rows[0]['bought_on']} bis {rows[-1]['bought_on']}), "
        f"davon positiv: {wins} ({wins / len(pnl):.0%})",
        f"Summe P&L: {sum(pnl):.2f} $, Ø je Nacht: {sum(pnl) / len(pnl):.2f} $",
        f"Positionen gesamt: {len(rows)}, Ø Rendite je Position: "
        f"{sum(float(r['return']) for r in rows) / len(rows) * 10_000:.1f} bp",
    ])

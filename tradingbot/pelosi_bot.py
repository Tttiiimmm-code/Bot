"""Pelosi-Kopier-Bot (Alpaca-PAPER, Runde 141): kauft jede neu gemeldete Aktie/Option von Nancy Pelosi und hält
sie 12 Monate -- dieselben Regeln wie der Vorwärtstest pelosi_copy (tradingbot/forward_pelosi.py), aber mit echten
Papier-Orders, um Ausführung und Depot real zu sehen.

Regeln: Meldungen (House Clerk, elektronisch) ab first_day stündlich prüfen. Je Kaufzeile (Aktie oder Option ->
Aktie) ein Los: Kauf am 2. Handelstag nach dem Meldedatum, buy_minutes_before_close vor Schluss per Market-Order,
Betrag position_pct des Kontowerts (höchstens das freie Bargeld -> kein Hebel); Verkauf desselben Loses 252
Handelstage später, ebenfalls kurz vor Schluss. Verpasste Fenster werden am nächsten Handelstag nachgeholt.

Konto: overnight.env (Overnight-Bot läuft seit 2026-10-02 nur im Dry-Run und sendet keine Orders). Nur Paper.
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

from tradingbot import forward_pelosi as fp
from tradingbot.overnight_live import NY, _as_ny

logger = logging.getLogger(__name__)

HOLD_SESSIONS = 252
LOG_FIELDS = ["doc", "ticker", "filing_date", "buy_date", "buy_price", "qty", "sell_date", "sell_price", "ret"]


@dataclass(frozen=True)
class PelosiBotConfig:
    first_day: date = date(2026, 10, 5)
    position_pct: float = 0.10
    buy_minutes_before_close: int = 10
    check_every: timedelta = timedelta(hours=1)
    poll_seconds: int = 30
    state_file: Path = Path("pelosi_bot_state.json")
    trade_log: Path = Path("pelosi_bot_trades.csv")
    cache: Path = Path("data_cache/forward/pelosi")


@dataclass
class _State:
    lots: list = field(default_factory=list)
    checked_at: str = ""

    @classmethod
    def load(cls, path: Path) -> "_State":
        return cls(**json.loads(path.read_text(encoding="utf-8"))) if path.exists() else cls()

    def save(self, path: Path) -> None:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.__dict__, indent=1), encoding="utf-8")
        tmp.replace(path)


class PelosiBot:
    def __init__(self, cfg: PelosiBotConfig, trading_client, price_fn, notifier=None, fetch=fp._get):
        """price_fn(symbol) -> letzter Kurs (float) oder None."""
        self.cfg, self.tc, self.price, self.notifier, self.fetch = cfg, trading_client, price_fn, notifier, fetch
        self.state = _State.load(cfg.state_file)

    def _say(self, title: str, text: str) -> None:
        logger.info("%s: %s", title, text)
        if self.notifier:
            self.notifier.send(title, text, tags="classical_building")

    # ------------------------------------------------------------ Kalender
    def sessions(self, start: date, end: date) -> list[tuple[date, datetime]]:
        from alpaca.trading.requests import GetCalendarRequest

        cal = self.tc.get_calendar(GetCalendarRequest(start=start, end=end))
        return [(c.date, _as_ny(c.close)) for c in cal]

    def _nth_session_after(self, day: date, n: int) -> date | None:
        s = [d for d, _ in self.sessions(day, day + timedelta(days=int(n * 1.6) + 15)) if d > day]
        return s[n - 1] if len(s) >= n else None

    # ------------------------------------------------------------ Meldungen
    def check_filings(self, now: datetime) -> None:
        cfg = fp.PelosiConfig(first_day=self.cfg.first_day, cache=self.cfg.cache)
        known = {(lot["doc"], lot["ticker"]) for lot in self.state.lots}
        new = []
        for f in fp.filings(cfg, now.astimezone(NY).date(), fetch=self.fetch):
            for t in fp.parse_buys(fp.filing_text(cfg, f, fetch=self.fetch)):
                if (f["doc"], t) in known:
                    continue
                buy_on = self._nth_session_after(f["filing_date"], 2)
                lot = {"doc": f["doc"], "ticker": t, "filing_date": f["filing_date"].isoformat(),
                       "buy_on": buy_on.isoformat() if buy_on else "", "sell_on": "", "qty": 0, "buy_id": "",
                       "buy_price": None, "sell_id": "", "sell_price": None, "status": "geplant"}
                self.state.lots.append(lot)
                new.append(lot)
        self.state.checked_at = now.isoformat()
        self.state.save(self.cfg.state_file)
        if new:
            self._say("Pelosi-Kauf gemeldet", "\n".join(
                f"{x['ticker']} (Meldung {x['filing_date']}): Bot kauft am {x['buy_on']} kurz vor Schluss, "
                f"{self.cfg.position_pct:.0%} des Kontos, Verkauf nach 12 Monaten" for x in new))

    # ------------------------------------------------------------ Orders
    def _order(self, symbol: str, side: str, qty: float | None = None, notional: float | None = None) -> str:
        from alpaca.trading.enums import OrderSide, TimeInForce
        from alpaca.trading.requests import MarketOrderRequest

        req = MarketOrderRequest(symbol=symbol, side=OrderSide.BUY if side == "buy" else OrderSide.SELL,
                                 time_in_force=TimeInForce.DAY, qty=qty, notional=notional)
        return str(self.tc.submit_order(req).id)

    def _fill(self, order_id: str) -> tuple[float, float] | None:
        if not order_id:
            return None
        o = self.tc.get_order_by_id(order_id)
        if o.filled_avg_price is None or not float(o.filled_qty or 0):
            return None
        return float(o.filled_qty), float(o.filled_avg_price)

    def _buy(self, lot: dict, today: date) -> None:
        sym = lot["ticker"].replace("-", ".")          # Yahoo BRK-B -> Alpaca BRK.B
        try:
            asset = self.tc.get_asset(sym)
            tradable, fractionable = bool(asset.tradable), bool(getattr(asset, "fractionable", False))
        except Exception:  # noqa: BLE001 -- unbekanntes Symbol
            tradable, fractionable = False, False
        if not tradable:
            lot["status"] = "nicht handelbar"
            self._say("Pelosi-Bot", f"{sym}: bei Alpaca nicht handelbar, Los übersprungen")
            return
        acct = self.tc.get_account()
        amount = min(self.cfg.position_pct * float(acct.equity), float(acct.cash))
        price = self.price(sym)
        if amount < 1 or not price:
            lot["status"] = "kein Geld/Kurs"
            self._say("Pelosi-Bot", f"{sym}: Kauf nicht möglich (Betrag {amount:.0f} $, Kurs {price})")
            return
        qty = math.floor(amount / price)
        if qty >= 1:
            lot["buy_id"] = self._order(sym, "buy", qty=qty)
        elif fractionable:
            lot["buy_id"] = self._order(sym, "buy", notional=round(amount, 2))
        else:
            lot["status"] = "zu teuer"
            self._say("Pelosi-Bot", f"{sym}: 1 Aktie ({price:.2f} $) kostet mehr als {amount:.0f} $")
            return
        sell_on = self._nth_session_after(today, HOLD_SESSIONS)
        lot.update(status="gekauft", bought_on=today.isoformat(),
                   sell_on=sell_on.isoformat() if sell_on else (today + timedelta(days=365)).isoformat())
        self._say("Pelosi-Bot kauft",
                  f"{sym}: Market-Order ~{amount:.0f} $ (Kurs {price:.2f}), Verkauf am {lot['sell_on']}")

    def _sell(self, lot: dict, today: date) -> None:
        fill = self._fill(lot["buy_id"])
        if fill is None:
            lot["status"] = "Kauf nicht gefüllt"
            self._say("Pelosi-Bot", f"{lot['ticker']}: Kauf-Order wurde nie ausgeführt, nichts zu verkaufen")
            return
        lot.update(qty=fill[0], buy_price=fill[1], status="verkauft", sold_on=today.isoformat())
        lot["sell_id"] = self._order(lot["ticker"].replace("-", "."), "sell", qty=fill[0])

    def _log_closed(self) -> None:
        changed = False
        for lot in self.state.lots:
            if lot["status"] != "verkauft" or lot.get("logged"):
                continue
            fill = self._fill(lot["sell_id"])
            if fill is None:
                continue
            lot["sell_price"] = fill[1]
            ret = fill[1] / lot["buy_price"] - 1
            new = not self.cfg.trade_log.exists()
            with self.cfg.trade_log.open("a", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=LOG_FIELDS)
                if new:
                    w.writeheader()
                w.writerow({"doc": lot["doc"], "ticker": lot["ticker"], "filing_date": lot["filing_date"],
                            "buy_date": lot.get("bought_on", ""), "buy_price": lot["buy_price"], "qty": lot["qty"],
                            "sell_date": lot.get("sold_on", ""), "sell_price": fill[1], "ret": round(ret, 6)})
            lot["logged"] = changed = True
            self._say("Pelosi-Bot verkauft", f"{lot['ticker']}: {ret:+.1%} nach 12 Monaten")
        if changed:
            self.state.save(self.cfg.state_file)

    # ------------------------------------------------------------ Takt
    def step(self, now: datetime) -> None:
        now = now.astimezone(NY)
        last = datetime.fromisoformat(self.state.checked_at) if self.state.checked_at else None
        if last is None or now - last >= self.cfg.check_every:
            self.check_filings(now)
        today = now.date()
        sess = self.sessions(today, today)
        if not sess or sess[0][0] != today:
            return
        close = sess[0][1]
        if not (close - timedelta(minutes=self.cfg.buy_minutes_before_close) <= now < close - timedelta(minutes=2)):
            self._log_closed()
            return
        changed = False
        for lot in self.state.lots:
            if lot["status"] == "geplant" and lot["buy_on"] and lot["buy_on"] <= today.isoformat():
                self._buy(lot, today)
                changed = True
            elif lot["status"] == "gekauft" and lot["sell_on"] <= today.isoformat() \
                    and lot.get("bought_on") != today.isoformat():
                self._sell(lot, today)
                changed = True
        if changed:
            self.state.save(self.cfg.state_file)

    def run_forever(self) -> None:
        logger.info("Pelosi-Bot gestartet (Paper, %d Lose bekannt)", len(self.state.lots))
        while True:
            try:
                self.step(datetime.now(timezone.utc))
            except Exception:
                logger.exception("Fehler im Pelosi-Bot-Zyklus, nächster Versuch im nächsten Intervall")
            time.sleep(self.cfg.poll_seconds)


def summarize(state_file: Path, trade_log: Path) -> str:
    st = _State.load(state_file)
    by: dict[str, int] = {}
    for lot in st.lots:
        by[lot["status"]] = by.get(lot["status"], 0) + 1
    txt = f"Pelosi-Bot: {len(st.lots)} Lose ({', '.join(f'{k} {v}' for k, v in sorted(by.items())) or 'keine'})"
    if trade_log.exists():
        with trade_log.open(newline="", encoding="utf-8") as f:
            r = [float(x["ret"]) for x in csv.DictReader(f)]
        if r:
            txt += f"; abgeschlossen {len(r)}, Ø {sum(r) / len(r):+.1%}"
    return txt

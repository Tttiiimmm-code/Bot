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
import logging
import math
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from tradingbot import forward_pelosi as fp
from tradingbot.order_recovery import client_order_id, submit_once
from tradingbot.overnight_live import NY, _as_ny
from tradingbot.state_io import load_state, save_state

logger = logging.getLogger(__name__)

HOLD_SESSIONS = 252
MAX_PRICE_MISSES = 20       # ~2 Kauffenster à 10 Abfragen
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
        return cls(**load_state(path, {}))

    def save(self, path: Path) -> None:
        save_state(path, self.__dict__, indent=1)


class PelosiBot:
    def __init__(self, cfg: PelosiBotConfig, trading_client, price_fn, notifier=None, fetch=fp._get):
        """price_fn(symbol) -> letzter Kurs (float) oder None (kein Kurs). Eine Ausnahme (Netz/API) gilt als
        vorübergehend: das Los bleibt geplant und der Versuch zählt nicht als Fehlversuch."""
        self.cfg, self.tc, self.price, self.notifier, self.fetch = cfg, trading_client, price_fn, notifier, fetch
        self.state = _State.load(cfg.state_file)
        self._filings_retry_at = datetime.min.replace(tzinfo=NY)

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
    def _order(self, symbol: str, side: str, cid: str, qty: float | None = None,
               notional: float | None = None) -> str:
        """Market-Order mit fester client_order_id: geht die Antwort verloren, wird die Order wiedergefunden
        statt ein zweites Mal gesendet (siehe order_recovery)."""
        from alpaca.trading.enums import OrderSide, TimeInForce
        from alpaca.trading.requests import MarketOrderRequest

        req = MarketOrderRequest(symbol=symbol, side=OrderSide.BUY if side == "buy" else OrderSide.SELL,
                                 time_in_force=TimeInForce.DAY, qty=qty, notional=notional, client_order_id=cid)
        return str(submit_once(self.tc, req).id)

    def _save_cid(self, lot: dict, key: str, cid: str) -> None:
        """client_order_id VOR dem Senden sichern: nach einem Absturz ist nachvollziehbar, welche Order zum
        Los gehört."""
        lot[key] = cid
        self.state.save(self.cfg.state_file)

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
        except Exception as e:  # noqa: BLE001
            if getattr(e, "status_code", None) != 404 and "not found" not in str(e).lower():
                raise                                     # vorübergehend (Netz/Limit): Los bleibt "geplant"
            tradable, fractionable = False, False
        if not tradable:
            lot["status"] = "nicht handelbar"
            self._say("Pelosi-Bot", f"{sym}: bei Alpaca nicht handelbar, Los übersprungen")
            return
        acct = self.tc.get_account()
        amount = min(self.cfg.position_pct * float(acct.equity), float(acct.cash))
        price = self.price(sym)
        if not price:
            lot["price_misses"] = lot.get("price_misses", 0) + 1
            if lot["price_misses"] >= MAX_PRICE_MISSES:
                lot["status"] = "kein Kurs"
                self._say("Pelosi-Bot", f"{sym}: {MAX_PRICE_MISSES}x kein Kurs, Los übersprungen")
            return                                        # sonst nächster Versuch (nächste Abfrage/nächster Tag)
        if amount < 1:
            lot["status"] = "kein Geld"
            self._say("Pelosi-Bot", f"{sym}: Kauf nicht möglich, kein freies Bargeld ({amount:.0f} $)")
            return
        qty = math.floor(amount / price)
        cid = client_order_id("pelosi", lot["doc"], lot["ticker"], "buy")
        if qty >= 1:
            self._save_cid(lot, "buy_cid", cid)
            lot["buy_id"] = self._order(sym, "buy", cid, qty=qty)
        elif fractionable:
            self._save_cid(lot, "buy_cid", cid)
            lot["buy_id"] = self._order(sym, "buy", cid, notional=round(amount, 2))
        else:
            lot["status"] = "zu teuer"
            self._say("Pelosi-Bot", f"{sym}: 1 Aktie ({price:.2f} $) kostet mehr als {amount:.0f} $")
            return
        # sofort als gekauft speichern: scheitert ein späterer Aufruf, darf der nächste Takt nicht erneut kaufen
        lot.update(status="gekauft", bought_on=today.isoformat(), sell_on=(today + timedelta(days=365)).isoformat())
        self.state.save(self.cfg.state_file)
        try:
            sell_on = self._nth_session_after(today, HOLD_SESSIONS)
            if sell_on:
                lot["sell_on"] = sell_on.isoformat()
        except Exception:  # noqa: BLE001 -- Kalender nicht erreichbar: Näherung 365 Kalendertage bleibt
            logger.exception("%s: Verkaufstag nicht berechenbar, nutze %s", sym, lot["sell_on"])
        self._say("Pelosi-Bot kauft",
                  f"{sym}: Market-Order ~{amount:.0f} $ (Kurs {price:.2f}), Verkauf am {lot['sell_on']}")

    def _sell(self, lot: dict, today: date) -> None:
        fill = self._fill(lot["buy_id"])
        if fill is None:
            lot["status"] = "Kauf nicht gefüllt"
            self._say("Pelosi-Bot", f"{lot['ticker']}: Kauf-Order wurde nie ausgeführt, nichts zu verkaufen")
            return
        # Restmenge: nach einem Teil-Fill eines früheren Verkaufs nur noch den unverkauften Rest
        remaining = fill[0] - sum(q for q, _ in lot.get("sell_fills", []))
        attempt = lot.get("sell_attempt", 0)
        cid = client_order_id("pelosi", lot["doc"], lot["ticker"], "sell", attempt)
        self._save_cid(lot, "sell_cid", cid)
        sell_id = self._order(lot["ticker"].replace("-", "."), "sell", cid, qty=remaining)  # scheitert -> bleibt "gekauft"
        lot.update(qty=fill[0], buy_price=fill[1], status="verkauft", sold_on=today.isoformat(), sell_id=sell_id)
        self.state.save(self.cfg.state_file)

    def _log_closed(self) -> None:
        changed = False
        for lot in self.state.lots:
            if lot["status"] != "verkauft" or lot.get("logged"):
                continue
            o = self.tc.get_order_by_id(lot["sell_id"])
            status = str(getattr(o.status, "value", o.status)).lower()
            filled = float(o.filled_qty or 0)
            fills = lot.get("sell_fills", []) + ([[filled, float(o.filled_avg_price)]] if filled else [])
            if status in ("canceled", "expired", "rejected"):
                # Verkauf endete ohne vollständige Ausführung: Teil-Fill merken, Rest im nächsten Fenster
                # erneut verkaufen (neue client_order_id je Versuch)
                lot.update(sell_fills=fills, status="gekauft", sell_id="", sell_attempt=lot.get("sell_attempt", 0) + 1,
                           qty_open=lot["qty"] - sum(q for q, _ in fills))
                changed = True
                self._say("Pelosi-Bot", f"{lot['ticker']}: Verkauf {status}, {filled:g} von {lot['qty']:g} Stück "
                                        f"ausgeführt -- Rest {lot['qty_open']:g} wird erneut verkauft")
                continue
            if status != "filled":
                continue                                  # noch offen bzw. teilweise ausgeführt: warten
            sold = sum(q for q, _ in fills)
            avg = sum(q * px for q, px in fills) / sold
            lot.update(sell_fills=fills, sell_price=avg)
            ret = avg / lot["buy_price"] - 1
            new = not self.cfg.trade_log.exists()
            with self.cfg.trade_log.open("a", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=LOG_FIELDS)
                if new:
                    w.writeheader()
                w.writerow({"doc": lot["doc"], "ticker": lot["ticker"], "filing_date": lot["filing_date"],
                            "buy_date": lot.get("bought_on", ""), "buy_price": lot["buy_price"], "qty": lot["qty"],
                            "sell_date": lot.get("sold_on", ""), "sell_price": avg, "ret": round(ret, 6)})
            lot["logged"] = changed = True
            self._say("Pelosi-Bot verkauft", f"{lot['ticker']}: {ret:+.1%} nach 12 Monaten")
        if changed:
            self.state.save(self.cfg.state_file)

    # ------------------------------------------------------------ Takt
    def step(self, now: datetime) -> None:
        now = now.astimezone(NY)
        last = datetime.fromisoformat(self.state.checked_at) if self.state.checked_at else None
        if (last is None or now - last >= self.cfg.check_every) and now >= self._filings_retry_at:
            try:
                self.check_filings(now)
            except Exception:  # noqa: BLE001 -- Meldungsabruf darf Käufe/Verkäufe nicht blockieren
                logger.exception("Meldungen nicht abrufbar, neuer Versuch in 10 Minuten")
                self._filings_retry_at = now + timedelta(minutes=10)
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

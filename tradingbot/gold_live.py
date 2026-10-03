"""Gold-Ausbruch als Papier-Bot bei OANDA (fxTrade Practice) -- dieselben Regeln wie der Vorwärtstest
gold_breakout (Runde 134, tradingbot/forward_gold.py), aber mit echten Demo-Orders. Zweck: Ausführung, Slippage,
Spread und Swap im echten Betrieb messen und mit der Simulation vergleichen.

Regeln: Zu Beginn jeder Stunde (UTC, erste 10 Minuten), wenn keine Position und keine eigene Order offen:
Buy-Stop 0,1 ATR über dem höchsten Hoch (Geld) der letzten 48 abgeschlossenen H1-Kerzen, gültig bis 12 Stunden
nach Stundenbeginn; Stop 2 ATR und Ziel 4 ATR ab Füllkurs (OANDA stopLossOnFill/takeProfitOnFill als Abstand).
ATR14 nach Wilder auf H1-Geldkursen. Keine neuen Orders Fr ab 20:00 UTC, eigene Orders Fr ab 20:55 UTC löschen.
Positionsgröße: risk_pct des Kontowerts / Stop-Abstand (ganze Unzen).

NUR DEMO: Der Bot startet nur mit OANDA_PRACTICE=true (Papiergeld). Schlüssel kommen aus einer .env-Datei.
"""

from __future__ import annotations

import csv
import json
import logging
import math
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

PRACTICE_URL = "https://api-fxpractice.oanda.com/v3"
INSTRUMENT = "XAU_USD"
TAG = "gold_breakout"
LEDGER_FIELDS = ["trade_id", "open_time", "close_time", "units", "entry", "exit", "sl_dist", "realized_pl",
                 "financing", "r", "r_net"]


@dataclass(frozen=True)
class GoldLiveConfig:
    risk_pct: float = 0.01
    n_lvl: int = 48
    expiry_h: int = 12
    sl_atr: float = 2.0
    tp_atr: float = 4.0
    buffer_atr: float = 0.1
    candles: int = 500
    state_file: Path = Path("gold_live_state.json")
    ledger: Path = Path("gold_live_trades.csv")
    poll_seconds: int = 30


class OandaClient:
    """Dünne Hülle um die OANDA-v20-REST-API (nur Practice)."""

    def __init__(self, token: str, account_id: str, session=None, base: str = PRACTICE_URL):
        if session is None:
            import requests
            session = requests.Session()
        self.base, self.account, self.s = base, account_id, session
        self.s.headers.update({"Authorization": f"Bearer {token}", "Content-Type": "application/json",
                               "Accept-Datetime-Format": "RFC3339"})

    def _get(self, path, **params):
        r = self.s.get(f"{self.base}{path}", params=params, timeout=30)
        r.raise_for_status()
        return r.json()

    def candles(self, count: int) -> list[dict]:
        data = self._get(f"/instruments/{INSTRUMENT}/candles", granularity="H1", price="BA", count=count)
        return [c for c in data["candles"] if c.get("complete")]

    def nav(self) -> float:
        return float(self._get(f"/accounts/{self.account}/summary")["account"]["NAV"])

    def pending_orders(self) -> list[dict]:
        orders = self._get(f"/accounts/{self.account}/pendingOrders")["orders"]
        return [o for o in orders if o.get("instrument") == INSTRUMENT
                and o.get("clientExtensions", {}).get("tag") == TAG]

    def open_trades(self) -> list[dict]:
        return [t for t in self._get(f"/accounts/{self.account}/openTrades")["trades"]
                if t.get("instrument") == INSTRUMENT]

    def closed_trades(self, count: int = 100) -> list[dict]:
        return self._get(f"/accounts/{self.account}/trades", state="CLOSED", instrument=INSTRUMENT,
                         count=count)["trades"]

    def place_stop(self, units: int, price: float, gtd: datetime, sl_dist: float, tp_dist: float, ref: str) -> dict:
        body = {"order": {
            "type": "STOP", "instrument": INSTRUMENT, "units": str(int(units)), "price": f"{price:.3f}",
            "timeInForce": "GTD", "gtdTime": gtd.strftime("%Y-%m-%dT%H:%M:%S.000000000Z"),
            "positionFill": "DEFAULT", "triggerCondition": "DEFAULT",
            "stopLossOnFill": {"distance": f"{sl_dist:.3f}"}, "takeProfitOnFill": {"distance": f"{tp_dist:.3f}"},
            "clientExtensions": {"id": ref, "tag": TAG},
            "tradeClientExtensions": {"id": ref, "tag": TAG, "comment": f"sd={sl_dist:.3f}"}}}
        r = self.s.post(f"{self.base}/accounts/{self.account}/orders", data=json.dumps(body), timeout=30)
        r.raise_for_status()
        return r.json()

    def cancel(self, order_id: str) -> None:
        r = self.s.put(f"{self.base}/accounts/{self.account}/orders/{order_id}/cancel", timeout=30)
        r.raise_for_status()


def signal_levels(candles: list[dict], cfg: GoldLiveConfig) -> tuple[float, float] | None:
    """(Buy-Stop-Kurs, ATR) aus abgeschlossenen H1-Kerzen (Geld) -- wie forward_gold/Runde 134."""
    if len(candles) < cfg.n_lvl + 15:
        return None
    hi = [float(c["bid"]["h"]) for c in candles]
    lo = [float(c["bid"]["l"]) for c in candles]
    cl = [float(c["bid"]["c"]) for c in candles]
    atr, a = None, 1 / 14
    for i in range(1, len(candles)):
        tr = max(hi[i] - lo[i], abs(hi[i] - cl[i - 1]), abs(lo[i] - cl[i - 1]))
        atr = tr if atr is None else atr + a * (tr - atr)     # Wilder-Glättung (ewm alpha=1/14, adjust=False)
    if atr is None or atr <= 0:
        return None
    return max(hi[-cfg.n_lvl:]) + cfg.buffer_atr * atr, atr


@dataclass
class _State:
    last_hour: str = ""
    seen_trades: list = field(default_factory=list)

    @classmethod
    def load(cls, path: Path) -> "_State":
        return cls(**json.loads(path.read_text())) if path.exists() else cls()

    def save(self, path: Path) -> None:
        path.write_text(json.dumps(self.__dict__))


class GoldLiveBot:
    def __init__(self, client, cfg: GoldLiveConfig = GoldLiveConfig(), notifier=None):
        self.c, self.cfg, self.notifier = client, cfg, notifier
        self.state = _State.load(cfg.state_file)

    def _say(self, title: str, text: str) -> None:
        logger.info("%s: %s", title, text)
        if self.notifier:
            self.notifier.send(title, text)

    def step(self, now: datetime) -> None:
        now = now.astimezone(timezone.utc)
        fri = now.weekday() == 4
        if fri and (now.hour > 20 or (now.hour == 20 and now.minute >= 55)):
            for o in self.c.pending_orders():
                self.c.cancel(o["id"])
                self._say("Gold-Bot", f"Order {o['id']} vor dem Wochenende gelöscht")
        hour_key = now.strftime("%Y-%m-%dT%H")
        if self.state.last_hour != hour_key and now.minute < 10:
            self.state.last_hour = hour_key
            self.state.save(self.cfg.state_file)
            if not (fri and now.hour >= 20) and not self.c.open_trades() and not self.c.pending_orders():
                self._place(now)
        self._sync_ledger()

    def _place(self, now: datetime) -> None:
        lv = signal_levels(self.c.candles(self.cfg.candles), self.cfg)
        if lv is None:
            return
        price, atr = lv
        sl, tp = self.cfg.sl_atr * atr, self.cfg.tp_atr * atr
        units = math.floor(self.cfg.risk_pct * self.c.nav() / sl)
        if units < 1:
            logger.warning("Konto zu klein für 1 Unze bei Stop-Abstand %.2f", sl)
            return
        start = now.replace(minute=0, second=0, microsecond=0)
        ref = f"gb-{start:%Y%m%d%H}"
        self.c.place_stop(units, price, start + timedelta(hours=self.cfg.expiry_h), sl, tp, ref)
        logger.info("Buy-Stop %s: %d oz @ %.3f (SL %.2f, TP %.2f, gültig %d h)", ref, units, price, sl, tp,
                    self.cfg.expiry_h)

    def _sync_ledger(self) -> None:
        new_rows = []
        for t in self.c.closed_trades():
            if t.get("clientExtensions", {}).get("tag") != TAG or t["id"] in self.state.seen_trades:
                continue
            comment = t.get("clientExtensions", {}).get("comment", "")
            sd = float(comment.split("=")[1]) if comment.startswith("sd=") else float("nan")
            units = abs(float(t["initialUnits"]))
            pl, fin = float(t.get("realizedPL", 0)), float(t.get("financing", 0))
            risk = units * sd
            ok = risk > 0
            row = {"trade_id": t["id"], "open_time": t["openTime"], "close_time": t.get("closeTime", ""),
                   "units": int(units), "entry": float(t["price"]), "exit": float(t.get("averageClosePrice", 0)),
                   "sl_dist": sd, "realized_pl": round(pl, 2), "financing": round(fin, 2),
                   "r": round(pl / risk, 4) if ok else "", "r_net": round((pl + fin) / risk, 4) if ok else ""}
            new_rows.append(row)
            self.state.seen_trades.append(t["id"])
            self._say("Gold-Bot", f"Trade {t['id']} geschlossen: {row['r_net']} R netto ({pl + fin:+.2f} $)")
        if new_rows:
            new = not self.cfg.ledger.exists()
            with self.cfg.ledger.open("a", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=LEDGER_FIELDS)
                if new:
                    w.writeheader()
                w.writerows(new_rows)
            self.state.save(self.cfg.state_file)

    def run_forever(self) -> None:
        logger.info("Gold-Bot (OANDA Practice) gestartet")
        while True:
            try:
                self.step(datetime.now(timezone.utc))
            except Exception:
                logger.exception("Fehler im Gold-Bot-Zyklus, nächster Versuch im nächsten Intervall")
            time.sleep(self.cfg.poll_seconds)


def client_from_env(env_file: str) -> OandaClient:
    from dotenv import dotenv_values

    v = dotenv_values(env_file)
    if (v.get("OANDA_PRACTICE") or "").strip().lower() != "true":
        raise ValueError(f"{env_file}: OANDA_PRACTICE=true fehlt -- der Gold-Bot läuft nur mit Demo-Konten.")
    token, account = (v.get("OANDA_TOKEN") or "").strip(), (v.get("OANDA_ACCOUNT_ID") or "").strip()
    if not token or not account:
        raise ValueError(f"{env_file}: OANDA_TOKEN und OANDA_ACCOUNT_ID müssen gesetzt sein.")
    return OandaClient(token, account)

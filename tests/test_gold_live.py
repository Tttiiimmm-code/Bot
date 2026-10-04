from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from tradingbot import gold_live as gl


def candle(i, h, l, c):
    t = datetime(2026, 10, 1, tzinfo=timezone.utc) + timedelta(hours=i)
    return {"time": t.isoformat(), "complete": True, "bid": {"o": str(c), "h": str(h), "l": str(l), "c": str(c)},
            "ask": {"o": str(c + 0.3), "h": str(h + 0.3), "l": str(l + 0.3), "c": str(c + 0.3)}}


class FakeClient:
    def __init__(self):
        self.cs = [candle(i, 2001.0 + (i == 70) * 5, 1999.0, 2000.0) for i in range(100)]
        self.orders, self.trades_open, self.closed, self.cancelled, self.placed = [], [], [], [], []

    def candles(self, count):
        return self.cs[-count:]

    def nav(self):
        return 100_000.0

    def pending_orders(self):
        return list(self.orders)

    def open_trades(self):
        return list(self.trades_open)

    def closed_trades(self, count=100):
        return list(self.closed)

    def place_stop(self, units, price, gtd, sl, tp, ref):
        self.placed.append(dict(units=units, price=price, gtd=gtd, sl=sl, tp=tp, ref=ref))
        self.orders.append({"id": str(len(self.placed)), "clientExtensions": {"tag": gl.TAG}})

    def cancel(self, oid):
        self.cancelled.append(oid)
        self.orders = [o for o in self.orders if o["id"] != oid]


@pytest.fixture
def cfg(tmp_path):
    return replace(gl.GoldLiveConfig(), state_file=tmp_path / "s.json", ledger=tmp_path / "l.csv")


def test_signal_levels_match_rules(cfg):
    price, atr = gl.signal_levels(FakeClient().cs, cfg)
    assert atr == pytest.approx(2.0, rel=0.05)                     # Spanne 2 je Kerze
    assert price == pytest.approx(2006.0 + 0.1 * atr, abs=0.01)    # höchstes Hoch der letzten 48 + 0,1 ATR


def test_places_once_per_hour_with_risk_sizing(cfg):
    c = FakeClient()
    bot = gl.GoldLiveBot(c, cfg)
    t = datetime(2026, 10, 6, 13, 2, tzinfo=timezone.utc)          # Dienstag
    bot.step(t)
    bot.step(t + timedelta(minutes=1))
    assert len(c.placed) == 1
    p = c.placed[0]
    assert p["sl"] == pytest.approx(2 * 2.0, rel=0.05) and p["tp"] == pytest.approx(2 * p["sl"])
    assert p["units"] == int(0.01 * 100_000 / p["sl"])
    assert p["gtd"] == datetime(2026, 10, 7, 1, 0, tzinfo=timezone.utc)
    bot.step(t + timedelta(hours=1))                              # Order noch offen -> keine neue
    assert len(c.placed) == 1
    c.orders.clear()
    bot.step(t + timedelta(hours=2, minutes=20))                  # nach Minute 10 -> nicht mehr in dieser Stunde
    assert len(c.placed) == 1
    bot.step(t + timedelta(hours=3, minutes=1))
    assert len(c.placed) == 2


def test_friday_rules(cfg):
    c = FakeClient()
    bot = gl.GoldLiveBot(c, cfg)
    bot.step(datetime(2026, 10, 9, 20, 1, tzinfo=timezone.utc))   # Freitag 20:01 -> keine neue Order
    assert c.placed == []
    c.orders.append({"id": "9", "clientExtensions": {"tag": gl.TAG}})
    bot.step(datetime(2026, 10, 9, 20, 56, tzinfo=timezone.utc))
    assert c.cancelled == ["9"]


def test_ledger_r_from_comment(cfg):
    c = FakeClient()
    c.closed = [{"id": "77", "openTime": "2026-10-06T13:20:00Z", "closeTime": "2026-10-06T18:00:00Z",
                 "initialUnits": "250", "price": "2006.2", "averageClosePrice": "2022.2", "realizedPL": "4000.0",
                 "financing": "-12.5", "clientExtensions": {"tag": gl.TAG, "comment": "sd=8.000"}}]
    bot = gl.GoldLiveBot(c, cfg)
    bot.step(datetime(2026, 10, 6, 18, 30, tzinfo=timezone.utc))
    bot.step(datetime(2026, 10, 6, 18, 31, tzinfo=timezone.utc))   # kein Doppel-Eintrag
    rows = cfg.ledger.read_text().splitlines()
    assert len(rows) == 2 and "77" in rows[1]
    assert ",2.0," in rows[1] and rows[1].endswith(",1.9937")      # 4000 / (250 x 8); netto (4000-12,5)/2000


def test_demo_only(tmp_path):
    env = tmp_path / "gold.env"
    env.write_text("OANDA_TOKEN=x\nOANDA_ACCOUNT_ID=1\nOANDA_PRACTICE=false\n")
    with pytest.raises(ValueError, match="Demo"):
        gl.client_from_env(str(env))
    env.write_text("OANDA_TOKEN=x\nOANDA_ACCOUNT_ID=101-004-1-001\nOANDA_PRACTICE=true\n")
    assert gl.client_from_env(str(env)).base.startswith("https://api-fxpractice")


def test_no_orders_on_weekend(cfg):
    c = FakeClient()
    bot = gl.GoldLiveBot(c, cfg)
    bot.step(datetime(2026, 10, 10, 10, 1, tzinfo=timezone.utc))   # Samstag
    bot.step(datetime(2026, 10, 11, 21, 1, tzinfo=timezone.utc))   # Sonntag vor 22 UTC
    assert c.placed == []
    bot.step(datetime(2026, 10, 11, 22, 1, tzinfo=timezone.utc))   # Sonntag 22 UTC: Markt offen
    assert len(c.placed) == 1

import io
import zipfile
from dataclasses import replace
from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pandas as pd
import pytest

from tradingbot import pelosi_bot as pb
from tradingbot.overnight_live import NY


def _zip(rows):
    head = "Prefix\tLast\tFirst\tSuffix\tFilingType\tStateDst\tYear\tFilingDate\tDocID\n"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("2026FD.txt", head + "".join("\t".join(r) + "\n" for r in rows))
    return buf.getvalue()


class FakeTC:
    def __init__(self):
        self.orders, self.cash, self.equity = {}, 20_000.0, 20_000.0
        self.tradable = {"NVDA": (True, True), "BRK-A": (True, False)}

    def get_calendar(self, req):
        return [SimpleNamespace(date=d.date(), close=datetime(d.year, d.month, d.day, 16, 0))
                for d in pd.bdate_range(req.start, req.end)]

    def get_account(self):
        return SimpleNamespace(equity=str(self.equity), cash=str(self.cash))

    def get_asset(self, sym):
        if sym not in self.tradable:
            e = ValueError("asset not found")                # wie Alpaca APIError 404
            e.status_code = 404
            raise e
        t, f = self.tradable[sym]
        return SimpleNamespace(tradable=t, fractionable=f)

    def submit_order(self, req):
        oid = str(len(self.orders) + 1)
        qty = req.qty if req.qty is not None else req.notional / 100
        self.orders[oid] = SimpleNamespace(req=req, filled_qty=str(qty), filled_avg_price="100.0")
        return SimpleNamespace(id=oid)

    def get_order_by_id(self, oid):
        return self.orders[oid]


PTR = "SP NVIDIA Corporation (NVDA) [ST] P 10/02/2026 10/02/2026 $1,000,001 - $5,000,000 " \
      "SP Unknown Co (ZZZZ) [ST] P 10/02/2026 10/02/2026 $15,001 - $50,000"


@pytest.fixture
def bot(tmp_path):
    cfg = replace(pb.PelosiBotConfig(), state_file=tmp_path / "s.json", trade_log=tmp_path / "t.csv",
                  cache=tmp_path / "c")
    (tmp_path / "c").mkdir()
    (tmp_path / "c" / "20030001.txt").write_text(PTR, encoding="utf-8")
    idx = _zip([("Hon.", "Pelosi", "Nancy", "", "P", "CA11", "2026", "10/6/2026", "20030001")])
    sent = []
    b = pb.PelosiBot(cfg, FakeTC(), lambda s: 180.0, fetch=lambda url: idx)
    b.notifier = SimpleNamespace(send=lambda title, text, **kw: sent.append((title, text)))
    b.sent = sent
    return b


def ny(y, m, d, hh, mm):
    return datetime(y, m, d, hh, mm, tzinfo=NY)


def at(day, hh, mm):
    return datetime(day.year, day.month, day.day, hh, mm, tzinfo=NY)


def test_full_cycle_buy_second_day_then_sell_after_252(bot):
    bot.step(ny(2026, 10, 6, 12, 0))                                   # Meldung Di 6.10. -> Kauf Do 8.10.
    lots = {x["ticker"]: x for x in bot.state.lots}
    assert lots["NVDA"]["buy_on"] == "2026-10-08" and lots["NVDA"]["status"] == "geplant"
    assert bot.sent and "NVDA" in bot.sent[0][1]
    bot.step(ny(2026, 10, 7, 15, 55))                                  # Mi: noch nicht Kauftag
    assert not bot.tc.orders
    bot.step(ny(2026, 10, 8, 15, 30))                                  # Do, aber vor dem Fenster
    assert not bot.tc.orders
    bot.step(ny(2026, 10, 8, 15, 52))
    nv = next(x for x in bot.state.lots if x["ticker"] == "NVDA")
    assert nv["status"] == "gekauft" and bot.tc.orders["1"].req.qty == 11     # 10 % von 20.000 / 180
    assert next(x for x in bot.state.lots if x["ticker"] == "ZZZZ")["status"] == "nicht handelbar"
    sell_on = date.fromisoformat(nv["sell_on"])
    assert len(pd.bdate_range("2026-10-09", sell_on)) == 252
    bot.step(at(sell_on - timedelta(days=1), 15, 55))
    assert nv["status"] == "gekauft"
    bot.step(at(sell_on, 15, 55))
    assert nv["status"] == "verkauft" and bot.tc.orders["2"].req.qty == 11.0
    bot.step(at(sell_on, 16, 5))
    assert bot.cfg.trade_log.read_text().count("NVDA") == 1
    assert "abgeschlossen 1" in pb.summarize(bot.cfg.state_file, bot.cfg.trade_log)


def test_no_leverage_and_fractional_fallback(bot):
    bot.tc.cash = 500.0                                                 # weniger Bargeld als 10 %
    bot.price = lambda s: 1000.0
    bot.step(ny(2026, 10, 6, 12, 0))
    bot.step(ny(2026, 10, 8, 15, 52))
    req = bot.tc.orders["1"].req
    assert req.qty is None and req.notional == 500.0                    # Bruchstück statt Hebel


def test_restart_keeps_state_and_no_duplicate_orders(bot):
    bot.step(ny(2026, 10, 6, 12, 0))
    bot.step(ny(2026, 10, 8, 15, 52))
    again = pb.PelosiBot(bot.cfg, bot.tc, bot.price, fetch=bot.fetch)
    again.step(ny(2026, 10, 8, 15, 53))
    again.step(ny(2026, 10, 8, 17, 0))                                 # nächste Prüfung der Meldungen
    assert len(bot.tc.orders) == 1 and len(again.state.lots) == 2


def test_failed_calendar_after_order_does_not_buy_twice(bot):
    bot.step(ny(2026, 10, 6, 12, 0))
    real = bot._nth_session_after
    calls = {"n": 0}

    def flaky(day, n):
        if n == pb.HOLD_SESSIONS:
            calls["n"] += 1
            raise ConnectionError("Kalender weg")
        return real(day, n)
    bot._nth_session_after = flaky
    bot.step(ny(2026, 10, 8, 15, 52))
    bot.step(ny(2026, 10, 8, 15, 53))
    nv = next(x for x in bot.state.lots if x["ticker"] == "NVDA")
    assert len(bot.tc.orders) == 1 and nv["status"] == "gekauft" and nv["sell_on"]


def test_transient_errors_keep_lot_planned(bot):
    bot.step(ny(2026, 10, 6, 12, 0))
    bot.tc.get_asset = lambda s: (_ for _ in ()).throw(TimeoutError("Netz"))
    with pytest.raises(TimeoutError):
        bot.step(ny(2026, 10, 8, 15, 52))
    assert next(x for x in bot.state.lots if x["ticker"] == "NVDA")["status"] == "geplant"
    bot.tc.get_asset = FakeTC().get_asset
    bot.price = lambda s: None                                          # kein Kurs: später erneut
    bot.step(ny(2026, 10, 8, 15, 53))
    assert next(x for x in bot.state.lots if x["ticker"] == "NVDA")["status"] == "geplant"
    bot.price = lambda s: 180.0
    bot.step(ny(2026, 10, 8, 15, 54))
    assert next(x for x in bot.state.lots if x["ticker"] == "NVDA")["status"] == "gekauft"


def test_filing_errors_do_not_block_trading(bot):
    bot.step(ny(2026, 10, 6, 12, 0))
    bot.fetch = lambda url: (_ for _ in ()).throw(ConnectionError("Clerk down"))
    bot.state.checked_at = ""                                           # Abruf fällig
    bot.step(ny(2026, 10, 8, 15, 52))
    assert len(bot.tc.orders) == 1

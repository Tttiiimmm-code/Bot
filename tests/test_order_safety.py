"""Regressionen aus dem Order-/Zustands-Review vom 07.10.2026 (Overnight, Pelosi, Gold, Copilot, Wächter,
Live-Sperre). Ausschließlich lokale Attrappen, keine Netzwerkzugriffe."""

from __future__ import annotations

import csv
import dataclasses
import json
from dataclasses import replace
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from tradingbot import gold_live as gl, overnight_live as on, pelosi_bot as pb
from tradingbot.copilot import Copilot, load_journal
from tradingbot.order_recovery import client_order_id
from tests.test_copilot import RULES, FakeData as CopilotData, FakeTrading as CopilotTrading, ny as cp_ny
from tests.test_gold_live import FakeClient
from tests.test_overnight_live import DAY1, DAY2, ny, setup  # noqa: F401 (Fixture)
from tests.test_pelosi_bot import bot  # noqa: F401 (Fixture)

PELOSI_DAY = date(2026, 10, 7)


# ------------------------------------------------------------ Zustandsdateien


@pytest.mark.parametrize("module", [on, gl, pb])
def test_corrupt_state_stops_with_clear_message(module, tmp_path):
    path = tmp_path / "kaputt.json"
    path.write_text("{", encoding="utf-8")
    with pytest.raises(RuntimeError, match="Datei prüfen/entfernen") as err:
        module._State.load(path)
    assert str(path) in str(err.value)


@pytest.mark.parametrize("module", [on, gl, pb])
def test_state_write_failure_keeps_old_file(module, tmp_path, monkeypatch):
    path = tmp_path / "zustand.json"
    module._State().save(path)
    old = path.read_bytes()
    original = Path.write_text

    def half_written(self, text, **kw):
        original(self, text[:2], **kw)
        raise OSError("Platte voll")

    monkeypatch.setattr(Path, "write_text", half_written)
    with pytest.raises(OSError):
        module._State().save(path)
    assert path.read_bytes() == old


def test_comfort_states_stay_tolerant(tmp_path):
    """Wächter und Copilot-Einstellungen fallen bei kaputter Datei auf den Standard zurück (wie bisher)."""
    from tradingbot import health

    state = tmp_path / "health.json"
    state.write_text("{", encoding="utf-8")
    sent = []
    notifier = SimpleNamespace(send=lambda *a, **k: sent.append(a) or True)
    health.step(notifier, state, datetime(2026, 10, 7, 12, 0, tzinfo=health.BERLIN), check=lambda: [])
    assert json.loads(state.read_text(encoding="utf-8"))["problems"] == []

    cp = Copilot(CopilotTrading(), CopilotData(25.0), RULES, tmp_path / "j.jsonl")
    cp.settings_path.write_text("{", encoding="utf-8")
    assert cp.settings() == {}


# ------------------------------------------------------------ Overnight


def test_overnight_partial_evening_resumes_only_missing_symbols(setup, monkeypatch):
    cfg, tc, dc = setup
    dc.prices["QQQ"] = 500                                   # beide über dem SMA
    original = tc.submit_order

    def qqq_fails(req):
        if req.symbol == "QQQ":
            raise TimeoutError()
        return original(req)

    monkeypatch.setattr(tc, "submit_order", qqq_fails)
    with pytest.raises(TimeoutError):
        on.OvernightBot(cfg, tc, dc).run_once(ny(DAY1, 15, 46))
    assert on._State.load(cfg.state_file).buys == {"SPY": "o0"}   # SPY sofort gespeichert
    monkeypatch.setattr(tc, "submit_order", original)
    on.OvernightBot(cfg, tc, dc).run_once(ny(DAY1, 15, 47))     # Neustart im selben Fenster
    assert [r.symbol for _, r in tc.orders] == ["SPY", "QQQ"]
    assert on._State.load(cfg.state_file).buys_done_for == DAY1.isoformat()


def test_overnight_lost_buy_response_is_recovered(setup, monkeypatch):
    cfg, tc, dc = setup
    original = tc.submit_order

    def accepted_but_lost(req):
        original(req)
        raise TimeoutError()

    monkeypatch.setattr(tc, "submit_order", accepted_but_lost)
    bot = on.OvernightBot(cfg, tc, dc)
    bot.run_once(ny(DAY1, 15, 46))
    assert bot.state.buys == {"SPY": "o0"} and len(tc.orders) == 1
    _, req = tc.orders[0]
    assert req.client_order_id == client_order_id("on", DAY1.isoformat(), "SPY", "buy")


def test_overnight_old_state_file_does_not_buy_again(setup):
    """Zustand aus der Zeit vor buys_done_for: bought_on = heute heißt Abendrunde abgeschlossen."""
    cfg, tc, dc = setup
    cfg.state_file.write_text(json.dumps({"bought_on": DAY1.isoformat(), "buys": {"SPY": "o9"}, "sells": {},
                                          "sold_for": None, "logged_for": None, "fallback_for": None}),
                              encoding="utf-8")
    bot = on.OvernightBot(cfg, tc, dc)
    bot.run_once(ny(DAY1, 15, 47))
    assert tc.orders == [] and bot.state.buys_done_for == DAY1.isoformat()


def test_overnight_morning_sells_saved_per_order(setup, monkeypatch):
    cfg, tc, dc = setup
    bot = on.OvernightBot(cfg, tc, dc)
    bot.run_once(ny(DAY1, 15, 46))
    tc.positions = {"SPY": 80, "QQQ": 10}
    original = tc.submit_order

    def qqq_fails(req):
        if req.symbol == "QQQ":
            raise TimeoutError()
        return original(req)

    bot.config = replace(cfg, symbols=("SPY", "QQQ"))
    monkeypatch.setattr(tc, "submit_order", qqq_fails)
    with pytest.raises(TimeoutError):
        bot.run_once(ny(DAY2, 9, 21))
    assert set(on._State.load(cfg.state_file).sells) == {"SPY"}
    monkeypatch.setattr(tc, "submit_order", original)
    on.OvernightBot(cfg, tc, dc).run_once(ny(DAY2, 9, 22))
    sells = [r.symbol for _, r in tc.orders if r.side.value == "sell"]
    assert sells == ["SPY", "QQQ"]


def test_overnight_unlogged_night_is_kept_and_logged_later(setup):
    cfg, tc, dc = setup
    cfg = replace(cfg, dry_run=True)
    bot = on.OvernightBot(cfg, tc, dc)
    bot.run_once(ny(DAY1, 15, 46))
    bot.run_once(ny(DAY2, 15, 46))                            # Kurse der Vornacht fehlen noch
    bot = on.OvernightBot(cfg, tc, dc)
    assert [n["bought_on"] for n in bot.state.unlogged_nights] == [DAY1.isoformat()]
    assert bot.state.bought_on == DAY2.isoformat()            # neuer Abend trotzdem gekauft
    dc.daily = {"SPY": [(DAY1, 498, 500), (DAY2, 502.5, 503)]}
    bot.run_once(ny(DAY2, 15, 57))
    assert bot.state.unlogged_nights == []
    [row] = list(csv.DictReader(cfg.trade_log.open(encoding="utf-8")))
    assert row["bought_on"] == DAY1.isoformat() and row["pnl"] == "200.00" and row["mode"] == "dry-run"


# ------------------------------------------------------------ Pelosi


def _planned_lot():
    return {"doc": "123", "ticker": "NVDA", "filing_date": "2026-10-02", "buy_on": PELOSI_DAY.isoformat(),
            "sell_on": "", "qty": 0, "buy_id": "", "buy_price": None, "sell_id": "", "sell_price": None,
            "status": "geplant"}


def test_pelosi_lost_buy_response_is_recovered(bot, monkeypatch):
    lot = _planned_lot()
    bot.state.lots = [lot]
    original = bot.tc.submit_order

    def accepted_but_lost(req):
        assert pb._State.load(bot.cfg.state_file).lots[0]["buy_cid"] == req.client_order_id  # vorher gesichert
        original(req)
        raise TimeoutError()

    monkeypatch.setattr(bot.tc, "submit_order", accepted_but_lost)
    bot._buy(lot, PELOSI_DAY)
    assert lot["buy_id"] == "1" and lot["status"] == "gekauft" and len(bot.tc.orders) == 1


def test_pelosi_unconfirmed_send_retries_without_duplicate(bot, monkeypatch):
    """Antwort verloren UND Nachschlagen scheitert (Netz): Los bleibt geplant; der nächste Versuch sendet mit
    derselben ID, Alpaca lehnt das Duplikat ab, die erste Order wird übernommen."""
    lot = _planned_lot()
    bot.state.lots = [lot]
    submit, lookup = bot.tc.submit_order, bot.tc.get_order_by_client_id

    def accepted_but_lost(req):
        submit(req)
        raise TimeoutError()

    def network_down(cid):
        raise ConnectionError("Netz weg")

    monkeypatch.setattr(bot.tc, "submit_order", accepted_but_lost)
    monkeypatch.setattr(bot.tc, "get_order_by_client_id", network_down)
    with pytest.raises(ConnectionError):
        bot._buy(lot, PELOSI_DAY)
    assert lot["status"] == "geplant"
    monkeypatch.setattr(bot.tc, "submit_order", submit)
    monkeypatch.setattr(bot.tc, "get_order_by_client_id", lookup)
    bot._buy(lot, PELOSI_DAY)
    assert lot["status"] == "gekauft" and lot["buy_id"] == "1" and len(bot.tc.orders) == 1


def test_pelosi_transient_price_error_is_not_a_miss(bot):
    lot = _planned_lot()
    bot.state.lots = [lot]
    bot.price = lambda sym: (_ for _ in ()).throw(ConnectionError("Kurs-API weg"))
    with pytest.raises(ConnectionError):
        bot._buy(lot, PELOSI_DAY)
    assert lot["status"] == "geplant" and lot.get("price_misses", 0) == 0


def _sold_lot(bot, sell_status):
    bot.tc.orders["b"] = SimpleNamespace(status="filled", filled_qty="10", filled_avg_price="100")
    bot.tc.orders["s"] = SimpleNamespace(status=sell_status, filled_qty="4", filled_avg_price="110")
    lot = {"doc": "123", "ticker": "NVDA", "filing_date": "2025-10-01", "status": "verkauft", "buy_id": "b",
           "sell_id": "s", "qty": 10, "buy_price": 100.0, "bought_on": "2025-10-03", "sell_on": "2026-10-06",
           "sold_on": "2026-10-06"}
    bot.state.lots = [lot]
    return lot


@pytest.mark.parametrize("status", ["partially_filled", "canceled", "expired", "rejected"])
def test_pelosi_incomplete_sale_does_not_close_lot(bot, status):
    lot = _sold_lot(bot, status)
    bot._log_closed()
    assert not bot.cfg.trade_log.exists()
    if status == "partially_filled":
        assert lot["status"] == "verkauft"                    # noch offen: warten
    else:
        assert lot["status"] == "gekauft" and lot["qty_open"] == 6 and lot["sell_fills"] == [[4, 110]]


def test_pelosi_remainder_is_resold_and_logged_with_weighted_price(bot):
    lot = _sold_lot(bot, "canceled")
    bot._log_closed()
    bot._sell(lot, PELOSI_DAY)
    req = bot.tc.orders[lot["sell_id"]].req
    assert req.qty == 6 and req.client_order_id == client_order_id("pelosi", "123", "NVDA", "sell", 1)
    bot._log_closed()                                          # Rest gefüllt zu 100
    [row] = list(csv.DictReader(bot.cfg.trade_log.open(encoding="utf-8")))
    assert float(row["qty"]) == 10 and float(row["sell_price"]) == pytest.approx(104.0)
    assert float(row["ret"]) == pytest.approx(0.04)
    assert lot["logged"] is True


# ------------------------------------------------------------ Gold


@pytest.mark.parametrize("method", ["open_trades", "pending_orders", "candles", "nav", "place_stop"])
def test_gold_hour_retried_after_api_failure(method, tmp_path, monkeypatch):
    cfg = replace(gl.GoldLiveConfig(), state_file=tmp_path / "s.json", ledger=tmp_path / "l.csv")
    c = FakeClient()
    b = gl.GoldLiveBot(c, cfg)
    original = getattr(c, method)
    monkeypatch.setattr(c, method, lambda *a: (_ for _ in ()).throw(TimeoutError()))
    now = datetime(2026, 10, 6, 13, 2, tzinfo=timezone.utc)
    with pytest.raises(TimeoutError):
        b.step(now)
    assert b.state.last_hour == ""
    monkeypatch.setattr(c, method, original)
    b.step(now.replace(minute=3))
    assert len(c.placed) == 1 and b.state.last_hour == "2026-10-06T13"


def _closed_trade(tid):
    return {"id": tid, "clientExtensions": {"tag": gl.TAG, "comment": "sd=2.000"}, "initialUnits": "10",
            "realizedPL": "40.0", "financing": "-1.0", "openTime": "2026-10-06T13:05:00Z",
            "closeTime": "2026-10-06T15:00:00Z", "price": "2006.2", "averageClosePrice": "2010.2"}


def test_gold_trade_only_marked_seen_after_ledger_write(tmp_path):
    blocked = tmp_path / "ledger_ist_ordner"
    blocked.mkdir()                                            # Schreiben ins Protokoll scheitert
    cfg = replace(gl.GoldLiveConfig(), state_file=tmp_path / "s.json", ledger=blocked)
    c = FakeClient()
    c.closed = [_closed_trade("7")]
    b = gl.GoldLiveBot(c, cfg)
    with pytest.raises(OSError):
        b._sync_ledger()
    assert b.state.seen_trades == []
    b.cfg = replace(cfg, ledger=tmp_path / "l.csv")
    b._sync_ledger()
    assert [r["trade_id"] for r in csv.DictReader(b.cfg.ledger.open(encoding="utf-8"))] == ["7"]
    assert b.state.seen_trades == ["7"]


def test_gold_trade_already_in_ledger_is_not_duplicated(tmp_path):
    """Protokoll geschrieben, aber Zustand nicht mehr gespeichert (Absturz): keine Doppelzeile."""
    cfg = replace(gl.GoldLiveConfig(), state_file=tmp_path / "s.json", ledger=tmp_path / "l.csv")
    c = FakeClient()
    c.closed = [_closed_trade("7")]
    gl.GoldLiveBot(c, cfg)._sync_ledger()
    cfg.state_file.unlink()
    b = gl.GoldLiveBot(c, cfg)
    b._sync_ledger()
    assert [r["trade_id"] for r in csv.DictReader(cfg.ledger.open(encoding="utf-8"))] == ["7"]
    assert b.state.seen_trades == ["7"]


# ------------------------------------------------------------ Copilot


def test_copilot_refuses_second_buy_while_buy_order_open(tmp_path):
    trading = CopilotTrading()
    trading.get_orders = lambda filter=None: ([SimpleNamespace(id="offen")]
                                              if filter.status.value == "open" else [])
    cp = Copilot(trading, CopilotData(25.0), RULES, tmp_path / "j.jsonl")
    msg = cp.buy("XYZ", stop=24.0, setup="vwap", now=cp_ny(12, 0))
    assert msg.startswith("KEIN TRADE") and "Kauf-Order offen" in msg and trading.submitted == []


def test_copilot_lost_response_is_recovered(tmp_path):
    trading = CopilotTrading()

    def accepted_but_lost(req):
        trading.submitted.append(req)
        raise TimeoutError()

    trading.submit_order = accepted_but_lost
    trading.get_order_by_client_id = lambda cid: SimpleNamespace(id="o7") if trading.submitted else None
    cp = Copilot(trading, CopilotData(25.0), RULES, tmp_path / "j.jsonl")
    msg = cp.buy("XYZ", stop=24.0, setup="vwap", now=cp_ny(12, 0))
    assert msg.startswith("GEKAUFT")
    [e] = load_journal(tmp_path / "j.jsonl")
    assert e.order_id == "o7"


def test_copilot_unclear_send_is_reported_not_retried(tmp_path):
    trading = CopilotTrading()

    def lost(req):
        raise TimeoutError("keine Antwort")

    def lookup_fails(cid):
        raise ConnectionError("Netz weg")

    trading.submit_order, trading.get_order_by_client_id = lost, lookup_fails
    cp = Copilot(trading, CopilotData(25.0), RULES, tmp_path / "j.jsonl")
    msg = cp.buy("XYZ", stop=24.0, setup="vwap", now=cp_ny(12, 0))
    assert msg.startswith("ORDER-STATUS UNKLAR") and "Alpaca-Dashboard" in msg
    assert load_journal(tmp_path / "j.jsonl") == []


# ------------------------------------------------------------ Wächter


def test_health_checks_backup_and_all_timers(tmp_path):
    from tradingbot import health

    def run(*args):
        if args[-1].endswith(".timer"):
            return "inactive"
        return "active" if args[0] == "is-active" else "success"

    problems = health.problems(run=run, disk_path=str(tmp_path), liq_dir=tmp_path)
    assert "backup-data" in health.ONESHOTS
    for name in health.ONESHOTS:
        assert f"Timer {name} läuft nicht (inactive)" in problems


# ------------------------------------------------------------ Live-Sperre


def test_order_bots_refuse_live_accounts():
    from tradingbot.bot import TradingBot
    from tradingbot.momentum_live import LiveMomentumBot
    from tradingbot.scanner import ScanCriteria
    from tests.test_scanner import make_config

    live = dataclasses.replace(make_config(), paper=False)
    with pytest.raises(RuntimeError, match="ALPACA_PAPER=false"):
        TradingBot(live, broker=SimpleNamespace())
    with pytest.raises(RuntimeError, match="ALPACA_PAPER=false"):
        LiveMomentumBot(live, ScanCriteria(), scanner=SimpleNamespace(), trading_client=SimpleNamespace(),
                        data_client=SimpleNamespace())


def test_overnight_cli_refuses_live_account(tmp_path):
    from tradingbot.cli.overnight import cmd_overnight_run

    env = tmp_path / "live.env"
    env.write_text("ALPACA_API_KEY=x\nALPACA_SECRET_KEY=y\nALPACA_PAPER=false\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="Live-Konten werden abgelehnt"):
        cmd_overnight_run(str(env), dry_run=True)

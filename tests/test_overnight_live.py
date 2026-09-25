from __future__ import annotations

import csv
from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pandas as pd
import pytest
from alpaca.trading.enums import OrderSide, TimeInForce

from tradingbot.overnight_live import (
    NY,
    OvernightBot,
    OvernightConfig,
    summarize_trade_log,
    target_qty,
    trend_signal,
)

DAY1, DAY2 = date(2026, 9, 24), date(2026, 9, 25)


class FakeTrading:
    def __init__(self, equity=80_000.0, early_close=False):
        self.equity = equity
        self.early_close = early_close
        self.positions: dict[str, int] = {}
        self.orders: list = []
        self.fills: dict[str, tuple[float, float]] = {}

    def get_calendar(self, req):
        midnight = datetime.combine(req.start, datetime.min.time())
        close_hour = 13 if self.early_close else 16
        return [SimpleNamespace(date=req.start, open=midnight + timedelta(hours=9, minutes=30),
                                close=midnight + timedelta(hours=close_hour))]

    def get_account(self):
        return SimpleNamespace(equity=str(self.equity))

    def get_all_positions(self):
        return [SimpleNamespace(symbol=s, qty=str(q)) for s, q in self.positions.items() if q]

    def submit_order(self, req):
        oid = f"o{len(self.orders)}"
        self.orders.append((oid, req))
        return SimpleNamespace(id=oid)

    def get_order_by_id(self, oid):
        qty, px = self.fills.get(oid, (0, None))
        return SimpleNamespace(filled_qty=str(qty) if qty else None, filled_avg_price=px)


class FakeData:
    def __init__(self, prices, closes):
        self.prices, self.closes = prices, closes

    def get_stock_latest_trade(self, req):
        return {s: SimpleNamespace(price=p) for s, p in self.prices.items()}

    def get_stock_bars(self, req):
        frames = []
        for s, cl in self.closes.items():
            idx = pd.date_range(end=pd.Timestamp(DAY1) - pd.Timedelta(days=1), periods=len(cl), freq="B",
                                tz="America/New_York").tz_convert("UTC")
            frames.append(pd.DataFrame({"close": cl}, index=pd.MultiIndex.from_arrays(
                [[s] * len(cl), idx], names=["symbol", "timestamp"])))
        return SimpleNamespace(df=pd.concat(frames))


def ny(d, hh, mm):
    return datetime.combine(d, datetime.min.time()).replace(hour=hh, minute=mm, tzinfo=NY)


@pytest.fixture
def setup(tmp_path):
    cfg = OvernightConfig(symbols=("SPY", "QQQ"), state_file=tmp_path / "state.json",
                          trade_log=tmp_path / "trades.csv")
    trading = FakeTrading()
    data = FakeData({"SPY": 500.0, "QQQ": 390.0}, {"SPY": [450.0] * 210, "QQQ": [400.0] * 210})
    return cfg, trading, data


def test_trend_signal_and_qty():
    assert trend_signal(101, [100] * 200, 200) == (True, 100)
    assert trend_signal(99, [100] * 200, 200)[0] is False
    assert trend_signal(200, [100] * 50, 200) == (False, None)
    assert target_qty(80_000, 8, 333.0) == 30


def test_evening_buys_only_above_sma_as_moc(setup):
    cfg, trading, data = setup
    bot = OvernightBot(cfg, trading, data)
    bot.run_once(ny(DAY1, 15, 40))
    assert trading.orders == []  # zu früh
    bot.run_once(ny(DAY1, 15, 46))
    assert len(trading.orders) == 1
    _, req = trading.orders[0]
    assert req.symbol == "SPY" and req.qty == 80 and req.side == OrderSide.BUY
    assert req.time_in_force == TimeInForce.CLS
    bot.run_once(ny(DAY1, 15, 47))
    assert len(trading.orders) == 1  # nur einmal pro Abend


def test_no_buy_after_moc_cutoff(setup):
    cfg, trading, data = setup
    OvernightBot(cfg, trading, data).run_once(ny(DAY1, 15, 51))
    assert trading.orders == []


def test_early_close_day_decides_before_1300(setup):
    cfg, _, data = setup
    trading = FakeTrading(early_close=True)
    OvernightBot(cfg, trading, data).run_once(ny(DAY1, 12, 46))
    assert len(trading.orders) == 1


def test_full_night_survives_restart_and_logs_pnl(setup):
    cfg, trading, data = setup
    OvernightBot(cfg, trading, data).run_once(ny(DAY1, 15, 46))
    buy_id = trading.orders[0][0]
    trading.fills[buy_id] = (80, 500.0)
    trading.positions = {"SPY": 80, "AAPL": 5}

    bot = OvernightBot(cfg, trading, data)  # Neustart über Nacht
    bot.run_once(ny(DAY2, 9, 15))
    assert len(trading.orders) == 1  # noch vor dem Verkaufsfenster
    bot.run_once(ny(DAY2, 9, 21))
    sell_id, sell = trading.orders[1]
    assert sell.symbol == "SPY" and sell.qty == 80 and sell.time_in_force == TimeInForce.OPG
    assert len(trading.orders) == 2  # fremde Position AAPL unberührt

    trading.fills[sell_id] = (80, 502.5)
    trading.positions = {"AAPL": 5}
    bot.run_once(ny(DAY2, 9, 36))
    rows = list(csv.DictReader(cfg.trade_log.open(encoding="utf-8")))
    assert rows == [{"bought_on": "2026-09-24", "symbol": "SPY", "qty": "80", "buy_price": "500.0000",
                     "sell_price": "502.5000", "pnl": "200.00", "return": "0.005000"}]
    bot.run_once(ny(DAY2, 9, 40))
    assert len(list(csv.DictReader(cfg.trade_log.open(encoding="utf-8")))) == 1  # nur einmal
    assert "Summe P&L: 200.00 $" in summarize_trade_log(cfg.trade_log)


def test_unfilled_opg_sell_falls_back_to_market(setup):
    cfg, trading, data = setup
    bot = OvernightBot(cfg, trading, data)
    bot.run_once(ny(DAY1, 15, 46))
    trading.fills[trading.orders[0][0]] = (80, 500.0)
    trading.positions = {"SPY": 80}
    bot.run_once(ny(DAY2, 9, 21))
    bot.run_once(ny(DAY2, 9, 36))  # OPG nicht gefüllt, Position noch da
    _, fallback = trading.orders[-1]
    assert fallback.side == OrderSide.SELL and fallback.time_in_force == TimeInForce.DAY


def test_existing_position_reduces_buy_qty(setup):
    cfg, trading, data = setup
    trading.positions = {"SPY": 30}
    OvernightBot(cfg, trading, data).run_once(ny(DAY1, 15, 46))
    assert trading.orders[0][1].qty == 50


def test_dry_run_places_no_orders(setup):
    cfg, trading, data = setup
    cfg = OvernightConfig(symbols=cfg.symbols, state_file=cfg.state_file, trade_log=cfg.trade_log, dry_run=True)
    bot = OvernightBot(cfg, trading, data)
    bot.run_once(ny(DAY1, 15, 46))
    trading.positions = {"SPY": 80}
    bot.run_once(ny(DAY2, 9, 21))
    bot.run_once(ny(DAY2, 9, 36))
    assert trading.orders == []

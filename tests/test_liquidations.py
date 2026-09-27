import csv

from tradingbot.liquidations import DailyCsvWriter, log_gap, parse_binance, parse_bybit


def test_parse_binance_sell_is_long_liquidation():
    msg = {"e": "forceOrder", "E": 1, "o": {"s": "BTCUSDT", "S": "SELL", "q": "0.02", "p": "99",
                                             "ap": "100.5", "z": "0.02", "T": 1790500000100}}
    assert parse_binance(msg) == [(1790500000100, "BTCUSDT", "long", "100.5", "0.02")]


def test_parse_binance_buy_is_short_and_ignores_other_events():
    msg = {"e": "forceOrder", "o": {"s": "ETHUSDT", "S": "BUY", "q": "1", "p": "10", "T": 5}}
    assert parse_binance(msg) == [(5, "ETHUSDT", "short", "10", "1")]
    assert parse_binance({"e": "other"}) == []


def test_parse_bybit_rows_and_non_liquidation_messages():
    msg = {"topic": "allLiquidation.BTCUSDT", "data": [
        {"T": 7, "s": "BTCUSDT", "S": "Buy", "v": "0.003", "p": "43511.7"},
        {"T": 8, "s": "BTCUSDT", "S": "Sell", "v": "1", "p": "43500"},
    ]}
    assert parse_bybit(msg) == [(7, "BTCUSDT", "long", "43511.7", "0.003"),
                                (8, "BTCUSDT", "short", "43500", "1")]
    assert parse_bybit({"op": "pong", "success": True}) == []


def test_writer_splits_by_utc_day_and_writes_header_once(tmp_path):
    w = DailyCsvWriter(tmp_path, "bybit")
    day1, day2 = 1790467199000, 1790467200000  # 2026-09-26 23:59:59 / 2026-09-27 00:00:00 UTC
    w.add(day1, [(day1, "BTCUSDT", "long", "1", "2")])
    w.add(day2, [(day2, "BTCUSDT", "short", "3", "4")])
    w.flush()
    w.add(day2, [(day2, "ETHUSDT", "long", "5", "6")])
    w.flush()
    rows = list(csv.reader((tmp_path / "bybit_2026-09-27.csv").open()))
    assert rows[0] == ["recv_ms", "trade_ms", "symbol", "liquidated", "price", "qty"]
    assert [r[2] for r in rows[1:]] == ["BTCUSDT", "ETHUSDT"]
    assert len(list(csv.reader((tmp_path / "bybit_2026-09-26.csv").open()))) == 2


def test_log_gap_appends(tmp_path):
    log_gap(tmp_path, "binance", 1, 2, "start")
    log_gap(tmp_path, "binance", 3, 4, "ConnectionClosed")
    rows = list(csv.reader((tmp_path / "gaps.csv").open()))
    assert rows == [["exchange", "from_ms", "to_ms", "reason"],
                    ["binance", "1", "2", "start"], ["binance", "3", "4", "ConnectionClosed"]]

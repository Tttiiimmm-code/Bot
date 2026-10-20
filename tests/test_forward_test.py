from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from tradingbot.forward_test import (
    bond_month_end_trades,
    gotobi_days,
    gotobi_trades,
    mid_month_trades,
    nikkei_trades,
    read_ledger,
    summarize,
    update_ledger,
)

NOW = pd.Timestamp("2030-01-01", tz="UTC")


def series(points: dict[str, float]) -> pd.Series:
    """Minutenkurse aus {'YYYY-MM-DD HH:MM' (Tokio): Kurs}."""
    idx = pd.DatetimeIndex([pd.Timestamp(k, tz="Asia/Tokyo") for k in points]).tz_convert("UTC")
    return pd.Series(list(points.values()), index=idx).sort_index()


def test_gotobi_days_shift_weekend_to_friday_and_include_month_end():
    days = gotobi_days(2026, 2026)
    assert date(2026, 10, 9) in days       # 10.10.2026 ist Samstag -> Freitag
    assert date(2026, 10, 10) not in days
    assert date(2026, 9, 30) in days       # Monatsletzter
    assert date(2026, 10, 5) in days


def test_nikkei_night_uses_new_close_time_and_charges_carry():
    bid = series({"2026-09-28 08:45": 100.0, "2026-09-28 15:45": 100.0,
                  "2026-09-29 08:45": 101.0, "2026-09-29 15:45": 101.0})
    rows = nikkei_trades(bid, date(2026, 9, 1), date(2026, 9, 30), cost_per_side=0.5e-4, jpy_rate=0.036, now=NOW)
    assert len(rows) == 1
    r = rows[0]
    assert r["date"] == "2026-09-29"
    assert r["entry_time"].startswith("2026-09-28T15:45")
    # +1 % - 2 x 0,5 bp - 3,6 %/360 x 1 Nacht (1 bp)
    assert r["net_bp"] == pytest.approx(100 - 1 - 1, abs=1e-6)


def test_nikkei_night_before_2024_change_uses_1515_and_skips_unfinished():
    bid = series({"2024-10-01 08:45": 100.0, "2024-10-01 15:15": 100.0, "2024-10-01 15:45": 999.0,
                  "2024-10-02 08:45": 100.0, "2024-10-02 15:15": 100.0})
    rows = nikkei_trades(bid, date(2024, 10, 1), date(2024, 10, 31), 0.0, 0.0, now=NOW)
    assert [r["net_bp"] for r in rows] == [0.0]
    later = nikkei_trades(bid, date(2024, 10, 1), date(2024, 10, 31), 0.0, 0.0,
                          now=pd.Timestamp("2024-10-02 08:00", tz="Asia/Tokyo"))
    assert later == []


def test_nikkei_night_holds_across_japanese_holidays():
    # 18.09.2026 (Fr) -> 24.09.2026 (Do): 21.-23.09. sind Feiertage, 19./20. Wochenende
    pts = {}
    for d, px in (("2026-09-18", 100.0), ("2026-09-21", 500.0), ("2026-09-22", 500.0),
                  ("2026-09-23", 500.0), ("2026-09-24", 102.0)):
        pts[f"{d} 08:45"] = px
        pts[f"{d} 15:45"] = px
    rows = nikkei_trades(series(pts), date(2026, 9, 1), date(2026, 9, 30), 0.0, 0.036, now=NOW)
    assert [r["date"] for r in rows] == ["2026-09-24"]
    # +2 % abzüglich 6 Kalendernächte Carry (6 x 1 bp)
    assert rows[0]["net_bp"] == pytest.approx(200 - 6, abs=1e-6)


def test_gotobi_buys_ask_sells_bid():
    bid = series({"2026-10-05 05:00": 150.00, "2026-10-05 09:55": 150.30})
    ask = series({"2026-10-05 05:00": 150.01, "2026-10-05 09:55": 150.31})
    rows = gotobi_trades(bid, ask, date(2026, 10, 1), date(2026, 10, 31), commission=0.0, now=NOW)
    assert len(rows) == 1
    assert rows[0]["net_bp"] == pytest.approx((150.30 / 150.01 - 1) * 1e4, abs=1e-3)


def test_gotobi_skips_days_without_prices():
    empty = series({"2026-10-06 05:00": 150.0})
    assert gotobi_trades(empty, empty, date(2026, 10, 1), date(2026, 10, 31), 0.0, now=NOW) == []


def test_ledger_replaces_same_day_and_summarizes(tmp_path):
    path = tmp_path / "ledger.csv"
    row = {"strategy": "gotobi", "date": "2026-10-05", "entry_time": "a", "entry_price": 1.0,
           "exit_time": "b", "exit_price": 1.0, "net_bp": 1.0}
    assert update_ledger(path, [row]) == 1
    assert update_ledger(path, [dict(row, net_bp=3.0), dict(row, date="2026-10-09", net_bp=-1.0)]) == 1
    rows = read_ledger(path)
    assert [(r["date"], float(r["net_bp"])) for r in rows] == [("2026-10-05", 3.0), ("2026-10-09", -1.0)]
    text = summarize(path)
    assert "gotobi: 2 Trades" in text and "nikkei_night: noch keine Trades" in text


def test_gotobi_strategy_label_for_second_pair():
    idx = pd.date_range("2026-10-04 19:00", "2026-10-05 02:00", freq="min", tz="UTC")
    bid = pd.Series(170.0, index=idx)
    ask = pd.Series(170.01, index=idx)
    rows = gotobi_trades(bid, ask, date(2026, 10, 1), date(2026, 10, 31), 0.0, now=NOW, strategy="gotobi_eurjpy")
    assert rows and all(r["strategy"] == "gotobi_eurjpy" for r in rows)


def test_bond_month_end_uses_last_four_trading_days_and_skips_open_month():
    days = [d.date() for d in pd.bdate_range("2026-09-01", "2026-10-15")]
    px = pd.Series([100 + i for i in range(len(days))], index=days, dtype=float)
    rows = bond_month_end_trades(px, date(2026, 9, 1), date(2026, 12, 31), cost=0.0, tbill_rate=0.0,
                                 today=date(2026, 10, 15))
    assert len(rows) == 1  # Oktober noch nicht abgeschlossen
    r = rows[0]
    assert r["exit_time"] == "2026-09-30" and r["entry_time"] == "2026-09-25"
    assert r["net_bp"] == round((r["exit_price"] / r["entry_price"] - 1) * 1e4, 3)


def test_mid_month_uses_9th_to_15th_trading_day_and_skips_unfinished():
    days = [d.date() for d in pd.bdate_range("2026-10-01", "2026-11-18")]
    px = pd.Series([100 + i for i in range(len(days))], index=days, dtype=float)
    rows = mid_month_trades(px, date(2026, 10, 1), date(2026, 12, 31), cost=2e-4, today=date(2026, 11, 18),
                            strategy="mid_month_spy")
    assert len(rows) == 1  # November-Fenster endet am 20.11. -> noch offen
    r = rows[0]
    assert r["entry_time"] == "2026-10-13" and r["exit_time"] == "2026-10-21"
    assert r["net_bp"] == round((r["exit_price"] / r["entry_price"] - 1 - 2e-4) * 1e4, 3)


# ------------------------------------------------------------ Yahoo statt Dukascopy (2026-10-20)


def _write_bars(path, points: dict[str, float]):
    """1-Minuten-Kerzen aus {'YYYY-MM-DD HH:MM' (Tokio): Kurs} als Yahoo-Aufzeichnung."""
    ts = [int(pd.Timestamp(k, tz="Asia/Tokyo").timestamp()) for k in points]
    v = list(points.values())
    pd.DataFrame({"ts": ts, "open": v, "high": v, "low": v, "close": v, "volume": 0}).to_csv(path, index=False)


def test_gotobi_charges_spread_on_mid_prices():
    mid = series({"2026-10-09 05:00": 150.0, "2026-10-09 09:55": 150.3})
    row = gotobi_trades(mid, mid, date(2026, 10, 9), date(2026, 10, 9), 0.35e-4, NOW, spread=1.07e-4)[0]
    assert row["net_bp"] == pytest.approx((150.3 / 150.0 - 1) * 1e4 - 0.7 - 1.07, abs=1e-3)


def test_run_uses_yahoo_from_cutover_and_keeps_dukascopy_rows(tmp_path, monkeypatch):
    """Zeilen vor YAHOO_FROM (Dukascopy) bleiben unverändert; ab dann Yahoo-Mittelkurse + Spanne; Nikkei aus dem
    verketteten Future. Fehlt die Aufzeichnung teilweise, wird trotzdem mit den gespeicherten Kursen gerechnet."""
    from tradingbot import forward_test as ft

    old = {"strategy": "gotobi", "date": "2026-10-05", "entry_time": "x", "entry_price": 1.0, "exit_time": "x",
           "exit_price": 1.0, "net_bp": -0.003}
    ledger = tmp_path / "f.csv"
    update_ledger(ledger, [old])
    _write_bars(tmp_path / "usdjpy_1m.csv", {"2026-10-05 05:00": 1.0, "2026-10-05 09:55": 2.0,     # vor Umstellung
                                             "2026-10-09 05:00": 150.0, "2026-10-09 09:55": 150.3})
    _write_bars(tmp_path / "eurjpy_1m.csv", {"2026-10-09 05:00": 170.0, "2026-10-09 09:55": 170.0})
    _write_bars(tmp_path / "niy_NIYZ26_1m.csv", {"2026-10-07 08:45": 49900.0, "2026-10-07 15:45": 50000.0,
                                                 "2026-10-08 08:45": 50100.0, "2026-10-08 15:45": 50200.0,
                                                 "2026-10-09 08:45": 50150.0, "2026-10-09 15:45": 50150.0})
    monkeypatch.setattr(ft, "fetch_daily_yahoo", lambda *a, **k: pd.Series(dtype=float))

    def refresh(base):
        raise RuntimeError("Yahoo kurz weg")

    cfg = ft.ForwardConfig(first_day=date(2026, 9, 28), ledger=ledger, yahoo_dir=tmp_path)
    ft.run(cfg, today=date(2026, 10, 9), now=pd.Timestamp("2026-10-09 06:00", tz="UTC"), refresh=refresh)
    rows = {(r["strategy"], r["date"]): r for r in read_ledger(ledger)}
    assert float(rows[("gotobi", "2026-10-05")]["net_bp"]) == -0.003
    assert float(rows[("gotobi", "2026-10-09")]["net_bp"]) == pytest.approx(20 - 0.7 - 1.07, abs=1e-3)
    assert float(rows[("gotobi_eurjpy", "2026-10-09")]["net_bp"]) == pytest.approx(-0.7 - 1.66, abs=1e-3)
    assert {d for s, d in rows if s == "nikkei_night"} == {"2026-10-08", "2026-10-09"}

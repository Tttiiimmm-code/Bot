from datetime import date, datetime

import pandas as pd

from tradingbot import orb_scanner as orb

DAY = date(2026, 10, 1)


def et(hh, mm):
    return datetime(2026, 10, 1, hh, mm, tzinfo=orb.NY)


def bars5(rows):
    """rows: [(HH:MM, open, high, low, close)]"""
    idx = pd.DatetimeIndex([pd.Timestamp(f"2026-10-01 {t}", tz="America/New_York") for t, *_ in rows])
    return pd.DataFrame([r[1:] for r in rows], columns=["open", "high", "low", "close"], index=idx)


GREEN = {"open": 10.0, "high": 10.5, "low": 9.9, "close": 10.4}


def test_waiting_then_expired():
    b = bars5([("09:35", 10.4, 10.45, 10.2, 10.3)])
    s = orb.evaluate("XYZ", 3.0, GREEN, b, 10.3, et(11, 0))
    assert s.state == "wartet" and "über 10.50" in s.status and s.stop == 9.9 and s.target == 10.5 + 2 * 0.6
    assert orb.evaluate("XYZ", 3.0, GREEN, b, 10.3, et(15, 30)).state == "abgelaufen"


def test_triggered_running_target_and_stop():
    run = bars5([("09:35", 10.4, 10.7, 10.4, 10.6), ("09:40", 10.6, 10.8, 10.5, 10.7)])
    s = orb.evaluate("XYZ", 3.0, GREEN, run, 10.8, et(10, 0))
    assert s.state == "läuft" and s.entry == 10.5 and abs(s.r_now - 0.5) < 1e-9
    hit = bars5([("09:35", 10.4, 10.7, 10.4, 10.6), ("09:40", 10.6, 11.8, 10.5, 11.7)])
    assert orb.evaluate("XYZ", 3.0, GREEN, hit, 11.7, et(10, 0)).state == "ziel"
    # Stop in der Ausbruchskerze zählt (vorsichtig)
    stopped = bars5([("09:35", 10.4, 10.7, 9.8, 9.9)])
    assert orb.evaluate("XYZ", 3.0, GREEN, stopped, 9.9, et(10, 0)).state == "stop"


def test_short_and_no_direction():
    red = {"open": 10.5, "high": 10.6, "low": 10.0, "close": 10.1}
    s = orb.evaluate("XYZ", 2.0, red, bars5([("09:35", 10.1, 10.2, 10.05, 10.1)]), 10.1, et(10, 0))
    assert s.side == "short" and s.stop == 10.6 and "unter 10.00" in s.status
    flat = {"open": 10.0, "high": 10.2, "low": 9.9, "close": 10.0}
    assert orb.evaluate("XYZ", 2.0, flat, bars5([]), None, et(10, 0)).state == "keine"


def test_daily_filter_and_rank_candidates():
    days = pd.bdate_range("2026-09-01", "2026-09-30").date
    rows = []
    for sym, vol, rng in (("BIG", 5e6, 2.0), ("THIN", 5e5, 2.0), ("CALM", 5e6, 0.2)):
        for d in days:
            rows.append((sym, d, 20.0, 20 + rng / 2, 20 - rng / 2, 20.0, vol))
    panel = pd.DataFrame(rows, columns=["symbol", "date", "open", "high", "low", "close", "volume"]).set_index(
        ["symbol", "date"])
    f = orb.daily_filter(panel)
    assert f.loc["BIG", "eligible"] and not f.loc["THIN", "eligible"] and not f.loc["CALM", "eligible"]
    hist = pd.DataFrame([(d, "BIG", 20, 20.5, 19.5, 20, 1e5) for d in days[-14:]],
                        columns=["date", "symbol", "open", "high", "low", "close", "volume"]).set_index(["date", "symbol"])
    today = pd.DataFrame([("BIG", 20, 20.5, 19.8, 20.3, 4e5), ("THIN", 20, 21, 19, 20.5, 9e9)],
                         columns=["symbol", "open", "high", "low", "close", "volume"]).set_index("symbol")
    cand = orb.rank_candidates(hist, today, f)
    assert list(cand.index) == ["BIG"] and abs(cand.loc["BIG", "relvol"] - 4.0) < 1e-9


def test_dollar_volume_minimum():
    days = pd.bdate_range("2026-09-01", "2026-09-30").date
    rows = [(sym, d, px, px + 1, px - 1, px, vol) for sym, px, vol in (("OK", 30.0, 1.5e6), ("SMALL", 10.0, 1.5e6))
            for d in days]
    panel = pd.DataFrame(rows, columns=["symbol", "date", "open", "high", "low", "close", "volume"]).set_index(
        ["symbol", "date"])
    f = orb.daily_filter(panel)
    assert f.loc["OK", "eligible"] and not f.loc["SMALL", "eligible"]      # 45 Mio. $ vs. 15 Mio. $


def test_only_common_stock_drops_preferred_warrants_units():
    funds = pd.DataFrame({"symbol": ["NOBL", "TQQQ", "QQQ", "SOXL"],
                          "name": ["ProShares S&P 500 Dividend Aristocrats ETF", "ProShares UltraPro QQQ",
                                   "Invesco QQQ Trust, Series 1", "Direxion Daily Semiconductor Bull 3X Shares"]})
    assert orb.only_common_stock(list(funds.symbol), funds) == []
    stocks = pd.DataFrame({"symbol": ["RARE", "UCTT", "BBW", "IVZ", "IVR", "AVD"],
                           "name": ["Ultragenyx Pharmaceutical Inc. Common Stock", "Ultra Clean Holdings, Inc. Common Stock",
                                    "Build-A-Bear Workshop, Inc.", "Invesco LTD", "Invesco Mortgage Capital Inc.",
                                    "American Vanguard Corporation"]})
    assert orb.only_common_stock(list(stocks.symbol), stocks) == list(stocks.symbol)
    assets = pd.DataFrame({"symbol": ["GOOGN", "GOOGL", "BABA", "ABCDW", "ABCDU", "XYZ_DELISTED", "PFX"],
                           "name": ["Alphabet Inc. Depositary Shares representing a 1/20th Interest in a Share of "
                                    "Series B Mandatory Convertible Preferred Stock", "Alphabet Inc. Class A Common Stock",
                                    "Alibaba Group Holding Limited American Depositary Shares", "ABCD Corp Warrants",
                                    "ABCD Acquisition Corp Units", "XYZ Inc", "PFX 6.5% Notes due 2031"]})
    keep = orb.only_common_stock(["GOOGN", "GOOGL", "BABA", "ABCDW", "ABCDU", "XYZ", "PFX"], assets)
    assert keep == ["GOOGL", "BABA", "XYZ"]


def test_load_candidates_ignores_filtered_symbols_in_daily_cache(tmp_path, monkeypatch):
    from tradingbot.research import universe as uni

    today = date(2026, 10, 2)
    days = pd.bdate_range("2026-09-01", "2026-10-01").date
    day_dir = tmp_path / today.isoformat()
    day_dir.mkdir(parents=True)
    pd.DataFrame({"symbol": ["GOOD", "GOOGN"], "name": ["Good Corp Common Stock", "Alphabet Inc. Depositary Shares "
                  "representing a 1/20th Interest in a Share of Series B Mandatory Convertible Preferred Stock"]}
                 ).to_pickle(day_dir / "assets.pkl")
    # Cache enthält beide Papiere (vor dem Filter geladen)
    panel = pd.DataFrame([(s, d, 50.0, 51.0, 49.0, 50.0, 5e6) for s in ("GOOD", "GOOGN") for d in days],
                         columns=["symbol", "date", "open", "high", "low", "close", "volume"]).set_index(["symbol", "date"])
    hist = pd.DataFrame([(d, s, 50, 50.5, 49.5, 50, 1e5) for d in days[-14:] for s in ("GOOD", "GOOGN")],
                        columns=["date", "symbol", "open", "high", "low", "close", "volume"]).set_index(["date", "symbol"])
    tod = pd.DataFrame([(today, s, 50, 50.6, 49.9, 50.4, 9e5) for s in ("GOOD", "GOOGN")],
                       columns=["date", "symbol", "open", "high", "low", "close", "volume"]).set_index(["date", "symbol"])
    monkeypatch.setattr(uni, "fetch_assets", lambda tc, base: ["GOOD", "GOOGN"])
    monkeypatch.setattr(uni, "fetch_daily", lambda *a, **k: panel)
    monkeypatch.setattr(uni, "fetch_opening_bars", lambda *a, **k: None)
    monkeypatch.setattr(uni, "load_opening", lambda base: hist if base.name == "hist" else tod)
    cand = orb.load_candidates(None, None, today, base=tmp_path)
    assert list(cand.index) == ["GOOD"]

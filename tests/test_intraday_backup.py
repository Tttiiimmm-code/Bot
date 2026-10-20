import io
import json

import pandas as pd
import pytest

from tradingbot import intraday_backup as ib


def _opener(payload):
    def opener(req, timeout):
        return io.BytesIO(json.dumps(payload).encode())
    return opener


def _chart(ts, closes):
    return {"chart": {"result": [{"timestamp": ts, "indicators": {"quote": [
        {"open": closes, "high": closes, "low": closes, "close": closes, "volume": [0] * len(ts)}]}}], "error": None}}


def test_fetch_verwirft_kerzen_ohne_schlusskurs():
    df = ib.fetch("USDJPY=X", "1m", "7d", opener=_opener(_chart([60, 120, 180], [150.0, None, 150.2])))
    assert df["ts"].tolist() == [60, 180]


def test_fetch_ohne_ergebnis_ist_fehler():
    with pytest.raises(RuntimeError):
        ib.fetch("XX", "1m", "7d", opener=_opener({"chart": {"result": None, "error": {"code": "Not Found"}}}))


def test_merge_haengt_an_und_entfernt_doppelte(tmp_path):
    p = tmp_path / "usdjpy_1m.csv"
    first = pd.DataFrame({"ts": [60, 120], "open": 1.0, "high": 1.0, "low": 1.0, "close": [1.0, 2.0], "volume": 0})
    assert ib.merge(p, first) == (2, 2)
    second = pd.DataFrame({"ts": [120, 180], "open": 1.0, "high": 1.0, "low": 1.0, "close": [2.5, 3.0], "volume": 0})
    assert ib.merge(p, second) == (1, 3)
    df = pd.read_csv(p)
    assert df["ts"].tolist() == [60, 120, 180]
    assert df.loc[df.ts == 120, "close"].item() == 2.5          # neuer Wert gilt
    assert not p.with_suffix(".csv.tmp").exists()


def test_run_sichert_rest_und_meldet_fehler(tmp_path):
    def fetcher(symbol, interval, rng):
        if symbol == "NIY=F":
            raise OSError("Netz weg")
        return pd.DataFrame({"ts": [60], "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 0})

    with pytest.raises(RuntimeError, match="NIY=F"):
        ib.run(tmp_path, fetcher)
    assert (tmp_path / "usdjpy_5m.csv").exists() and (tmp_path / "gc_1m.csv").exists()
    assert not (tmp_path / "niy_1m.csv").exists()


def _bars(path, start, n, price, freq="min"):
    idx = pd.date_range(start, periods=n, freq=freq, tz="UTC")
    p = [price] * n
    pd.DataFrame({"ts": idx.as_unit("s").asi8, "open": p, "high": p, "low": p, "close": p, "volume": 0}).to_csv(
        path, index=False)


def test_contracts_roll_on_fixed_dates():
    now = pd.Timestamp("2026-10-20", tz="UTC")
    assert ib.contracts_to_record("gc", now) == ["GCZ26", "GCG27"]
    assert ib.contracts_to_record("niy", now) == ["NIYZ26", "NIYH27"]
    assert ib.contracts_to_record("gc", pd.Timestamp("2026-11-20", tz="UTC")) == ["GCG27", "GCJ27"]
    assert ib.contracts_to_record("niy", pd.Timestamp("2026-12-01", tz="UTC")) == ["NIYH27", "NIYM27"]


def test_load_bars_fills_only_uncovered_5m_windows(tmp_path):
    _bars(tmp_path / "x_1m.csv", "2026-10-10 10:00", 3, 1.0)                 # 10:00-10:02
    _bars(tmp_path / "x_5m.csv", "2026-10-10 09:50", 4, 2.0, freq="5min")    # 09:50, 09:55, 10:00, 10:05
    b = ib.load_bars("x", tmp_path)
    assert [t.strftime("%H:%M") for t in b.index] == ["09:50", "09:55", "10:00", "10:01", "10:02", "10:05"]
    assert b.loc["2026-10-10 10:00", "close"].item() == 1.0


def test_continuous_adjusts_older_contract_by_ratio_at_roll(tmp_path):
    """Gold-Wechsel 20.11.: Dezember 100 -> Februar 101; ältere Kurse x 1,01, kein Sprung in der Reihe."""
    _bars(tmp_path / "gc_GCZ26_1m.csv", "2026-11-19 23:58", 3, 100.0)       # bis 20.11. 00:00
    _bars(tmp_path / "gc_GCG27_1m.csv", "2026-11-19 23:58", 5, 101.0)
    c = ib.continuous("gc", pd.Timestamp("2026-11-19", tz="UTC"), pd.Timestamp("2026-11-21", tz="UTC"), tmp_path)
    assert c["close"].tolist() == pytest.approx([101.0] * 5)


def test_continuous_without_common_price_at_roll_is_error(tmp_path):
    _bars(tmp_path / "gc_GCZ26_1m.csv", "2026-11-19 23:58", 2, 100.0)
    _bars(tmp_path / "gc_GCG27_1m.csv", "2026-11-20 00:05", 2, 101.0)
    with pytest.raises(RuntimeError, match="kein gemeinsamer Kurs"):
        ib.continuous("gc", pd.Timestamp("2026-11-19", tz="UTC"), pd.Timestamp("2026-11-21", tz="UTC"), tmp_path)

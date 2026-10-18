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

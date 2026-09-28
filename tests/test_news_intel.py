import csv
import time
from datetime import datetime, timezone

import pytest

from tradingbot.news_intel import Assessment, NewsIntel, NewsIntelConfig, openai_text, parse_assessment

NOW = datetime(2026, 10, 1, 14, 0, tzinfo=timezone.utc)


def test_parse_valid_json_with_surrounding_text():
    a = parse_assessment("ABC", 'Sure: {"catalyst": "earnings", "direction": "positive", '
                                '"dilution_risk": "low", "confidence": 0.8, "summary": "Q2 beat"} done')
    assert (a.catalyst, a.direction, a.dilution_risk, a.confidence, a.summary) == \
        ("earnings", "positive", "low", 0.8, "Q2 beat")
    assert a.error == ""


def test_parse_unknown_values_fall_back_and_confidence_is_clamped():
    a = parse_assessment("ABC", '{"catalyst": "moon", "direction": "up", "dilution_risk": "huge", "confidence": 7}')
    assert (a.catalyst, a.direction, a.dilution_risk, a.confidence) == ("other", "unclear", "low", 1.0)


def test_parse_garbage_sets_error():
    assert parse_assessment("ABC", "no json here").error
    assert parse_assessment("ABC", "{broken").error


def _wait(intel, symbol):
    for _ in range(100):
        a = intel.get(symbol, NOW)
        if a is not None:
            return a
        time.sleep(0.02)
    raise AssertionError("keine Einschätzung")


@pytest.fixture
def key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")


def test_request_runs_once_per_symbol_and_day_and_logs(tmp_path, key):
    calls = []

    def fake_llm(prompt, model, api_key, timeout):
        calls.append(prompt)
        return '{"catalyst": "offering_dilution", "direction": "negative", "dilution_risk": "high", "confidence": 0.9}'

    cfg = NewsIntelConfig(enabled=True, log_path=tmp_path / "ni.csv")
    intel = NewsIntel(cfg, news_client=None, llm=fake_llm)
    intel._cik = {}  # keine SEC-Abfrage im Test
    intel.request("ABC", 3.0, 40.0, 8.0, NOW)
    intel.request("ABC", 3.1, 42.0, 8.5, NOW)
    a = _wait(intel, "ABC")
    assert len(calls) == 1 and a.catalyst == "offering_dilution"
    rows = list(csv.DictReader((tmp_path / "ni.csv").open(encoding="utf-8")))
    assert rows[0]["symbol"] == "ABC" and rows[0]["dilution_risk"] == "high"
    assert "test-key" not in (tmp_path / "ni.csv").read_text(encoding="utf-8")


def test_llm_failure_never_raises_and_never_blocks(tmp_path, key):
    def broken_llm(*a, **k):
        raise TimeoutError("netz weg")

    cfg = NewsIntelConfig(enabled=True, filter_mode="block_dilution", log_path=tmp_path / "ni.csv")
    intel = NewsIntel(cfg, llm=broken_llm)
    intel._cik = {}
    intel.request("XYZ", 2.0, 30.0, 5.0, NOW)
    a = _wait(intel, "XYZ")
    assert a.error and not intel.should_block_entry("XYZ", NOW)


def test_shadow_mode_never_blocks_filter_mode_blocks_dilution(tmp_path, key):
    for mode, expected in (("off", False), ("block_dilution", True)):
        intel = NewsIntel(NewsIntelConfig(enabled=True, filter_mode=mode, log_path=tmp_path / f"{mode}.csv"))
        intel._cache[(NOW.date(), "ABC")] = Assessment("ABC", catalyst="offering_dilution", dilution_risk="high")
        assert intel.should_block_entry("ABC", NOW) is expected
        assert intel.should_block_entry("OTHER", NOW) is False  # ohne Einschätzung nie blockieren


def test_disabled_or_missing_key_does_nothing(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    called = []
    intel = NewsIntel(NewsIntelConfig(enabled=True, log_path=tmp_path / "ni.csv"), llm=lambda *a: called.append(1))
    intel.request("ABC", 1.0, 1.0, 1.0, NOW)
    time.sleep(0.05)
    assert not called and intel.get("ABC", NOW) is None


def test_provider_auto_prefers_anthropic_then_openai(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "oa")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    intel = NewsIntel(NewsIntelConfig(enabled=True))
    assert intel.provider == "openai" and intel.model == "gpt-5-mini"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "an")
    intel = NewsIntel(NewsIntelConfig(enabled=True))
    assert intel.provider == "anthropic" and intel.model.startswith("claude")
    intel = NewsIntel(NewsIntelConfig(enabled=True, provider="openai", model="my-model"))
    assert intel.provider == "openai" and intel.model == "my-model"
    with pytest.raises(ValueError):
        NewsIntel(NewsIntelConfig(enabled=True, provider="xyz"))


def test_openai_text_extracts_message_content():
    assert openai_text({"choices": [{"message": {"content": '{"catalyst": "earnings"}'}}]}) == '{"catalyst": "earnings"}'
    assert openai_text({"choices": []}) == ""

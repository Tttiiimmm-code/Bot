"""Statische Prüfungen des MT5-EA mql5/GoldBreakout.mq5 (kein MQL5-Testrahmen vorhanden)."""
from pathlib import Path

EA = Path(__file__).resolve().parents[1] / "mql5" / "GoldBreakout.mq5"


def test_buy_stop_traegt_ablaufzeit_beim_broker():
    # Regression 2026-10-18: Order vom 06.10. blieb 12 Tage offen, weil MT5 aus war und der EA
    # die 12-Stunden-Gültigkeit nur selbst verwaltete (ORDER_TIME_GTC ohne Ablaufzeit).
    src = EA.read_text(encoding="utf-8")
    assert "ORDER_TIME_SPECIFIED" in src
    assert "SYMBOL_EXPIRATION_SPECIFIED" in src
    assert "timeType, expiration, comment" in src


def test_eigene_loeschung_nach_ablauf_bleibt():
    src = EA.read_text(encoding="utf-8")
    assert "trade.OrderDelete(own[i])" in src
    assert "ExpiryHours * 3600" in src


def test_live_konten_bleiben_gesperrt():
    src = EA.read_text(encoding="utf-8")
    assert "AllowLive" in src

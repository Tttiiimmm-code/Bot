from datetime import date

import numpy as np
import pandas as pd
import pytest

from tradingbot import forward_stocks as fs


def minute_bars(rows, day="2026-10-01"):
    idx = pd.date_range(f"{day} 09:30", periods=len(rows), freq="min", tz="America/New_York")
    return pd.DataFrame(rows, columns=["open", "high", "low", "close"], index=idx)


# Range 9:30-9:34: Hoch 10,5, Tief 9,9, grüne Kerze (Open 10, Schluss 10,5)
OR_ROWS = [(10, 10.1, 9.9, 10.1), (10.1, 10.2, 10.0, 10.2), (10.2, 10.3, 10.1, 10.3), (10.3, 10.4, 10.2, 10.4),
           (10.4, 10.5, 10.3, 10.5)]


def test_orb_trade_target_hit_matches_round_107():
    bars = minute_bars(OR_ROWS + [(10.45, 10.6, 10.4, 10.55), (10.6, 11.2, 10.5, 10.7), (10.7, 10.8, 10.6, 10.75)])
    t = fs.orb_trade(bars, target_r=1.0)
    # Einstieg 10,5 (Level), Stop 9,9 (Gegenseite), sd 0,6, Ziel 11,1 in Minute 6
    assert t["side"] == "long" and t["entry"] == 10.5 and t["stop"] == 9.9 and t["exit"] == pytest.approx(11.1)
    assert t["r_net"] == pytest.approx(1 - 2 * (0.0001 * 10.5 + 0.01) / 0.6, abs=1e-4)


def test_orb_trade_stop_in_entry_minute_is_worst_case():
    bars = minute_bars(OR_ROWS + [(10.45, 10.6, 9.8, 9.9), (9.9, 10.0, 9.7, 9.8)])
    t = fs.orb_trade(bars)
    assert t["exit"] == 9.9 and t["r_net"] < -1


def test_orb_trade_short_and_no_trade_cases():
    red = [(10.5, 10.6, 10.4, 10.4), (10.4, 10.4, 10.2, 10.2), (10.2, 10.3, 10.1, 10.1), (10.1, 10.1, 10.0, 10.0),
           (10.0, 10.1, 9.9, 10.0)]
    t = fs.orb_trade(minute_bars(red + [(9.95, 9.95, 9.5, 9.6), (9.6, 9.6, 8.0, 8.1)]))
    assert t["side"] == "short" and t["entry"] == 9.9 and t["stop"] == 10.6
    # kein Ausbruch -> kein Trade; erster Bar nicht 9:30 -> kein Trade
    assert fs.orb_trade(minute_bars(OR_ROWS + [(10.4, 10.45, 10.3, 10.4)])) is None
    late = minute_bars(OR_ROWS + [(10.45, 10.6, 10.4, 10.55)])
    assert fs.orb_trade(late.iloc[1:]) is None


def test_quality_pick_prefers_high_margin_and_low_issuance():
    opm = pd.Series({"A": 0.30, "B": 0.10, "C": 0.25, "D": -0.05})
    iss = pd.Series({"A": 0.00, "B": 0.00, "C": 0.40, "D": 0.10})
    assert fs.quality_pick(opm, iss, ["A", "B", "C", "D", "E"], 2) == ["A", "B"]


def test_point_in_time_availability():
    assert fs.annual_year(pd.Timestamp("2026-09-30")) == 2025
    assert fs.annual_year(pd.Timestamp("2026-04-30")) == 2024
    q = fs.available_quarter(pd.Timestamp("2026-09-30"))
    assert (q.year, q.quarter) == (2026, 2)       # Q2 endet 30.6., verfügbar ab 30.9.
    q = fs.available_quarter(pd.Timestamp("2026-10-30"))
    assert (q.year, q.quarter) == (2026, 2)


def test_month_schedule_and_quality_rows(tmp_path):
    days = pd.bdate_range("2025-06-02", "2026-12-15")
    syms = ["A", "B", "C"]
    rng = np.random.default_rng(0)
    c = pd.DataFrame(20 + rng.random((len(days), 3)), index=days, columns=syms)
    o = c.copy()
    v = pd.DataFrame(1e6, index=days, columns=syms)
    o.loc[:, "A"] *= np.linspace(1, 2, len(days))        # A steigt stark
    sched = fs.month_schedule(days)
    assert sched[-1][2] is None                           # letzter Monat noch offen
    cfg = fs.StockForwardConfig(first_day=date(2026, 10, 1), quality_top=1,
                                quality_ledger=tmp_path / "q.csv", orb_ledger=tmp_path / "o.csv")
    rows = fs.quality_rows(cfg, o, c, v, {}, lambda signal, members: ["A"])
    assert rows[0]["signal"] == "2026-09-30" and rows[0]["entry_date"] == "2026-10-01"
    assert rows[0]["net_excess"] > 0 and rows[0]["turnover"] == 1.0
    assert rows[-1]["net_excess"] == ""                   # laufender Monat ohne Abrechnung
    fs.update_quality_ledger(cfg.quality_ledger, rows)
    assert fs.update_quality_ledger(cfg.quality_ledger, rows) == 0     # idempotent
    assert sum(r["net_excess"] != "" for r in rows) == 2    # Okt. und Nov. abgerechnet
    assert "quality_top50: 2 Monate" in fs.summarize(cfg)


def test_quality_due_only_after_month_end():
    ledger = {"2026-09-30": {}}
    assert fs.quality_due(ledger, date(2026, 10, 2))          # erste Woche: immer
    assert not fs.quality_due(ledger, date(2026, 10, 20))     # Septemberzeile da -> überspringen
    assert fs.quality_due({}, date(2026, 10, 20))             # Lauf verpasst -> nachholen


def test_orb_ledger_idempotent(tmp_path):
    cfg = fs.StockForwardConfig(first_day=date(2026, 10, 1), orb_ledger=tmp_path / "o.csv")
    t = fs.orb_trade(minute_bars(OR_ROWS + [(10.45, 10.6, 10.4, 10.55), (10.6, 11.2, 10.5, 10.7)]))
    rows = [{"date": "2026-10-01", "symbol": "XYZ", **t}]
    assert fs.update_orb_ledger(cfg.orb_ledger, rows) == 1
    assert fs.update_orb_ledger(cfg.orb_ledger, rows) == 0
    assert "orb_or5: 1 Trades" in fs.summarize(cfg)


def test_smallvq_pick_top20_buy_top40_hold():
    syms = [f"S{i}" for i in range(10)]
    m = pd.DataFrame({k: np.arange(10, dtype=float) for k in fs.VQ_KEYS}, index=syms)
    m["equity"] = 1.0
    m.loc["S0", "equity"] = -1.0                      # negatives Eigenkapital -> nicht im Universum
    m.loc["S1", "bm"] = np.nan                        # B/M fehlt -> nicht im Universum
    hold, members = fs.smallvq_pick(m, syms + ["ZZ"], prev=set())
    assert members == syms[2:]
    assert hold == ["S8", "S9"]                       # Top 20 % von 8 = Ränge > 0,8
    hold, _ = fs.smallvq_pick(m, syms, prev={"S6", "S3"})
    assert hold == ["S6", "S8", "S9"]                 # S6 in Top 40 % gehalten, S3 nicht


def test_value_quality_metrics_point_in_time(tmp_path):
    import json
    signal = pd.Timestamp("2026-09-30")               # Quartal 2026Q2 (verfügbar 30.9.), Jahr 2025
    cik = "0000000001"
    vals = {"Assets_CY2026Q2I": 100, "Assets_CY2025Q2I": 80, "StockholdersEquity_CY2026Q2I": 50,
            "EntityCommonStockSharesOutstanding_CY2026Q2I": 10, "EntityCommonStockSharesOutstanding_CY2025Q2I": 8,
            "NetIncomeLoss_CY2025": 5, "NetCashProvidedByUsedInOperatingActivities_CY2025": 7,
            "GrossProfit_CY2025": 30}
    for name, val in vals.items():
        (tmp_path / f"{name}.json").write_text(json.dumps({cik: val}))
    m = fs.value_quality_metrics(signal, tmp_path, {cik: "AAA"}, pd.Series({"AAA": 4.0}))
    r = m.loc["AAA"]
    assert r["bm"] == pytest.approx(50 / 40) and r["ep"] == pytest.approx(5 / 40) and r["cfp"] == pytest.approx(7 / 40)
    assert r["gpa"] == pytest.approx(0.3) and r["roa"] == pytest.approx(0.05)
    assert r["ag"] == pytest.approx(-0.25) and r["iss"] == pytest.approx(-0.25) and r["acc"] == pytest.approx(0.02)


def test_smallvq_rows_costs_and_frozen_holdings(tmp_path):
    days = pd.bdate_range("2025-06-02", "2026-12-15")
    syms = ["A", "B", "C", "D", "E"]
    c = pd.DataFrame(10.0, index=days, columns=syms)
    o = c.copy()
    o.loc[:, "A"] *= np.linspace(1, 2, len(days))
    v = pd.DataFrame(50_000, index=days, columns=syms)     # $-Umsatz 0,5 Mio. -> Kandidat
    v.loc[:, "E"] = 1e6                                    # 10 Mio. $ -> zu liquide
    cfg = fs.StockForwardConfig(first_day=date(2026, 10, 1), smallvq_ledger=tmp_path / "vq.csv",
                                quality_ledger=tmp_path / "q.csv", orb_ledger=tmp_path / "o.csv")
    seen = []

    def metrics(signal, close_row):
        seen.append(signal)
        m = pd.DataFrame({k: [5.0, 1, 2, 3, 4] for k in fs.VQ_KEYS}, index=syms)
        m["equity"] = 1.0
        return m

    rows = fs.smallvq_rows(cfg, o, c, v, {}, metrics)
    assert rows[0]["holdings"] == "A"                      # Bester von 4 Kandidaten (E ausgeschlossen)
    assert rows[0]["turnover"] == 1.0
    port, bench = rows[0]["port_ret"], rows[0]["bench_ret"]
    assert rows[0]["net_excess"] == pytest.approx(port - bench - 0.0075, abs=1e-6)
    assert rows[1]["turnover"] == 0.0 and rows[-1]["net_excess"] == ""
    fs.update_quality_ledger(cfg.smallvq_ledger, rows)
    ledger = {r["signal"]: r for r in fs._read(cfg.smallvq_ledger)}
    ledger[rows[-1]["signal"]]["holdings"] = "B"           # festgelegtes Depot wird nicht neu berechnet
    o2 = pd.concat([o, o.iloc[[-1]].set_axis([pd.Timestamp("2027-01-04")])])
    c2, v2 = (pd.concat([w, w.iloc[[-1]].set_axis([pd.Timestamp("2027-01-04")])]) for w in (c, v))
    again = fs.smallvq_rows(cfg, o2, c2, v2, ledger, metrics)
    assert again[0]["holdings"] == "B" and again[0]["net_excess"] != ""
    assert "smallvq_top20: 2 Monate" in fs.summarize(cfg)

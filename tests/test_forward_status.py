from datetime import date

import pytest

from tradingbot import forward_status as fs


def test_t_crit_matches_protocol_table():
    assert fs.t_crit(24) == pytest.approx(2.85, abs=0.01)
    assert fs.t_crit(40) == pytest.approx(2.75, abs=0.01)
    assert fs.t_crit(60) == pytest.approx(2.70, abs=0.01)
    assert fs.t_crit(200) == pytest.approx(2.63, abs=0.01)


def write(path, header, rows):
    path.write_text("\n".join([header] + rows) + "\n", encoding="utf-8")


def test_status_reads_all_ledgers(tmp_path):
    write(tmp_path / "forward_trades.csv", "strategy,date,entry_time,entry_price,exit_time,exit_price,net_bp",
          ["nikkei_night,2026-09-25,a,1,b,1,99", "nikkei_night,2026-09-28,a,1,b,1,10",
           "nikkei_night,2026-09-29,a,1,b,1,-4", "gotobi,2026-09-30,a,1,b,1,2"])
    write(tmp_path / "forward_orb.csv", "date,symbol,side,entry_time,entry,stop,target,exit_time,exit,r_net",
          ["2026-10-01,A,long,t,1,1,1,t,1,1.0", "2026-10-01,B,long,t,1,1,1,t,1,-1.5",
           "2026-10-02,A,long,t,1,1,1,t,1,2.0"])
    write(tmp_path / "forward_quality.csv", "signal,entry_date,exit_date,holdings,port_ret,bench_ret,turnover,net_excess",
          ["2026-09-30,2026-10-01,2026-11-02,A,0.01,0.0,1,0.004", "2026-10-30,2026-11-02,,A,,,,"])
    write(tmp_path / "overnight_trades.csv", "bought_on,symbol,qty,buy_price,sell_price,pnl,return,mode",
          ["2026-09-30,XLE,1,1,1,0,-0.03,paper",                                  # vor Neustart: zählt nicht
           "2026-10-05,XLE,1,1,1,0,-0.004,dry-run", "2026-10-05,XLK,1,1,1,0,0.002,dry-run"])
    rows = {r["name"]: r for r in fs.status(tmp_path, date(2026, 11, 3))}
    assert rows["nikkei_night"]["n"] == 2 and rows["nikkei_night"]["mean"] == pytest.approx(3.0)  # vor Start ignoriert
    assert rows["gotobi"]["n"] == 1
    assert rows["orb_or5"]["n"] == 2 and rows["orb_or5"]["mean"] == pytest.approx(0.75)        # Summe je Tag
    assert rows["orb_or5"]["expected"] == pytest.approx(0.026 * 1.5)
    assert rows["quality_top50"]["n"] == 1 and rows["quality_top50"]["mean"] == pytest.approx(0.4)  # offen zählt nicht
    assert rows["smallvq_top20"]["n"] == 0
    assert rows["overnight_etf"]["mean"] == pytest.approx(-0.1)                                 # Nacht = Ø Positionen
    assert rows["liq_r125"]["n"] is None
    text = fs.format_text(list(rows.values()))
    assert "nikkei_night: 2/200" in text and "Termin 01.10.2027" in text


def test_futility_note_only_after_half(tmp_path):
    lines = [f"gotobi,2027-0{m}-1{d},a,1,b,1,{-5 - d}" for m in range(1, 4) for d in range(5)]
    write(tmp_path / "forward_trades.csv", "strategy,date,entry_time,entry_price,exit_time,exit_price,net_bp", lines)
    early = {r["name"]: r for r in fs.status(tmp_path, date(2027, 3, 20))}
    late = {r["name"]: r for r in fs.status(tmp_path, date(2027, 4, 1))}
    assert early["gotobi"]["note"] == ""
    assert "Abbruch erlaubt" in late["gotobi"]["note"]

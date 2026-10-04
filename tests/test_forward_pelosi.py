import io
import zipfile
from dataclasses import replace
from datetime import date

import numpy as np
import pandas as pd
import pytest

from tradingbot import forward_pelosi as fp

PTR = """SP Broadcom Inc. - Common Stock
(AVGO) [OP]
P 06/24/2024 06/24/2024 $1,000,001 -
$5,000,000
D : Purchased 20 call options.
SP NVIDIA Corporation - Common
Stock (NVDA) [ST]
P 06/26/2024 06/26/2024 $1,000,001 -
$5,000,000
SP Tesla, Inc. - Common Stock (TSLA)
[ST]
S 06/24/2024 06/24/2024 $250,001 -
$500,000
SP Apollo Debt Solutions BDC (ADS) [OT] P 06/24/2024 06/24/2024 $1,001 - $15,000
SP NVIDIA Corporation (NVDA) [ST] P 06/27/2024 06/27/2024 $15,001 - $50,000
SP Berkshire Hathaway (BRK.B) [ST] P 06/27/2024 06/27/2024 $15,001 - $50,000"""


def test_parse_buys_stock_and_options_only():
    assert fp.parse_buys(PTR) == ["AVGO", "NVDA", "BRK-B"]       # Verkauf TSLA und [OT] weg, NVDA einmal


def _zip(year, rows):
    head = "Prefix\tLast\tFirst\tSuffix\tFilingType\tStateDst\tYear\tFilingDate\tDocID\n"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(f"{year}FD.txt", head + "".join("\t".join(r) + "\n" for r in rows))
    return buf.getvalue()


def test_filings_filters_person_type_electronic_and_start(tmp_path):
    cfg = replace(fp.PelosiConfig(), cache=tmp_path)
    rows = [("Hon.", "Pelosi", "Nancy", "", "P", "CA11", "2026", "10/6/2026", "20030001"),
            ("Hon.", "Pelosi", "Nancy", "", "P", "CA11", "2026", "9/30/2026", "20030000"),   # vor Start
            ("Hon.", "Pelosi", "Nancy", "", "O", "CA11", "2026", "10/7/2026", "10070000"),  # Jahresbericht
            ("Hon.", "Pelosi", "Nancy", "", "P", "CA11", "2026", "10/8/2026", "80030002"),  # Papier/Scan
            ("Hon.", "Smith", "Adam", "", "P", "WA09", "2026", "10/8/2026", "20030003")]
    got = fp.filings(cfg, date(2026, 10, 9), fetch=lambda url: _zip(2026, rows))
    assert got == [{"doc": "20030001", "year": 2026, "filing_date": date(2026, 10, 6)}]


def _series(start, n, growth):
    idx = pd.bdate_range(start, periods=n)
    return pd.Series(100 * np.cumprod(np.full(n, 1 + growth)), index=idx)


def test_build_rows_entry_second_day_and_close_after_252():
    spy = _series("2026-10-01", 300, 0.0)
    stock = _series("2026-10-01", 300, 0.001)
    rows = fp.build_rows([{"doc": "1", "filing_date": date(2026, 10, 5), "ticker": "X"},
                          {"doc": "1", "filing_date": date(2026, 10, 5), "ticker": "GONE"}],
                         spy, lambda t: stock if t == "X" else None)
    r = rows[0]
    assert r["entry_date"] == "2026-10-07"                     # Mo 5.10. gemeldet -> Di 6. (1.) -> Mi 7. (2.)
    assert r["status"] == "abgeschlossen"
    assert r["ret"] == pytest.approx(1.001 ** 252 * 0.999 ** 2 - 1, rel=1e-4)
    assert r["excess"] == pytest.approx(r["ret"])               # SPY flach
    assert rows[1]["status"] == "kein Kurs"


def test_open_position_and_portfolio_excess(tmp_path):
    spy = _series("2026-10-01", 80, 0.0)
    stock = _series("2026-10-01", 80, 0.002)
    rows = fp.build_rows([{"doc": "1", "filing_date": date(2026, 10, 5), "ticker": "X"}], spy, lambda t: stock)
    assert rows[0]["status"] == "offen"
    ex, t = fp.portfolio_excess(rows, spy, lambda t: stock, date(2026, 10, 1))
    assert len(ex) >= 3 and (ex.iloc[1:] > 0).all()
    path = tmp_path / "l.csv"
    fp.write_ledger(path, rows)
    assert "1 offen" in fp.summarize(fp.read_ledger(path))


def test_filing_before_price_history_is_not_shifted():
    spy = _series("2026-10-01", 50, 0.0)
    rows = fp.build_rows([{"doc": "1", "filing_date": date(2026, 9, 1), "ticker": "X"}], spy, lambda t: spy)
    assert rows[0]["status"] == "kein Kurs" and rows[0]["entry_date"] == ""

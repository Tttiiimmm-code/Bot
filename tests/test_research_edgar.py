from __future__ import annotations

import io
import zipfile
from datetime import date

import pandas as pd

from tradingbot.research.edgar import (
    _parse_quarter,
    earnings_events,
    event_day,
    event_weights,
    insider_events,
    quarters,
)


def _zip(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, text in files.items():
            z.writestr(name, text)
    return buf.getvalue()


def test_parse_quarter_keeps_open_market_purchases_by_insiders():
    sub = ("ACCESSION_NUMBER\tFILING_DATE\tDOCUMENT_TYPE\tISSUERCIK\tISSUERTRADINGSYMBOL\n"
           "A1\t31-MAR-2020\t4\t0001\tabc\nA2\t31-MAR-2020\t4\t0002\tXYZ\nA3\t31-MAR-2020\t4\t0003\tQQQ\n"
           "A4\t31-MAR-2020\t4/A\t0001\tABC\n")
    own = ("ACCESSION_NUMBER\tRPTOWNERCIK\tRPTOWNER_RELATIONSHIP\n"
           "A1\t9\tDirector\nA2\t8\tTenPercentOwner\nA3\t7\tOfficer\nA4\t9\tDirector\n")
    tr = ("ACCESSION_NUMBER\tTRANS_CODE\tTRANS_SHARES\tTRANS_PRICEPERSHARE\tTRANS_ACQUIRED_DISP_CD\n"
          "A1\tP\t1000\t30\tA\nA2\tP\t5000\t10\tA\nA3\tS\t1000\t50\tD\nA4\tP\t1000\t30\tA\n")
    df = _parse_quarter(_zip({"SUBMISSION.tsv": sub, "REPORTINGOWNER.tsv": own, "NONDERIV_TRANS.tsv": tr}))
    # nur A1: Director-Kauf 30.000 $; A2 kein Officer/Director, A3 Verkauf, A4 Korrektur (4/A)
    assert df["symbol"].tolist() == ["ABC"] and df["value"].iloc[0] == 30_000
    assert df["filing_date"].iloc[0] == date(2020, 3, 31)


def test_quarters_range():
    assert quarters("2015q4", "2016q2") == ["2015q4", "2016q1", "2016q2"]


def test_event_day_uses_market_open_cutoff():
    days = pd.Index(pd.bdate_range("2021-04-26", periods=5).date)
    tz = "America/New_York"
    assert event_day(pd.Timestamp("2021-04-27 08:00", tz=tz), days) == date(2021, 4, 27)
    assert event_day(pd.Timestamp("2021-04-27 16:05", tz=tz), days) == date(2021, 4, 28)


def test_insider_events_entry_next_day_and_cluster():
    days = pd.Index(pd.bdate_range("2021-01-04", periods=40).date)
    p = pd.DataFrame({"filing_date": [date(2021, 1, 5), date(2021, 1, 12), date(2021, 1, 20)],
                      "symbol": ["ABC"] * 3, "owner_cik": ["1", "1", "2"], "value": [5e4] * 3})
    assert insider_events(p, days, cluster=False)[0] == ("ABC", date(2021, 1, 6))
    assert insider_events(p, days, cluster=True) == [("ABC", date(2021, 1, 21))]


def test_event_weights_equal_weight_and_no_overlap():
    idx = pd.bdate_range("2021-01-04", periods=10).date
    close = pd.DataFrame({"A": 1.0, "B": 1.0}, index=idx)
    w = event_weights(close, [("A", idx[1]), ("B", idx[2]), ("A", idx[3])], hold=3)
    assert w.loc[idx[1]].tolist() == [1.0, 0.0]
    assert w.loc[idx[2]].tolist() == [0.5, 0.5]
    assert w.loc[idx[4]].tolist() == [0.0, 1.0]  # zweites A-Ereignis ignoriert (Position aktiv)
    assert w.loc[idx[5]].sum() == 0


def test_earnings_events_threshold_on_abnormal_return():
    idx = pd.bdate_range("2021-01-04", periods=5).date
    close = pd.DataFrame({"A": [100, 100, 112, 113, 113.0], "B": [50, 50, 51, 51, 51.0]}, index=idx)
    spy = pd.Series([400, 400, 404, 404, 404.0], index=idx)  # +1 % am Ereignistag
    ev = earnings_events(close, spy, {"A": [idx[2]], "B": [idx[2]]}, threshold=0.05)
    assert ev == [("A", idx[3])]  # A: +12 % - 1 % > 5 %, B: +2 % - 1 % nicht

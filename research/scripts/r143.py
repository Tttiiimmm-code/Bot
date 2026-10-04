"""Runde 143: Senatoren-Käufe ab Meldedatum nachhandeln -- Vorab: PROTOCOL.md."""
import re
import sys
from datetime import date
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import r141 as R  # noqa: E402

S = R.D / "senate"
LEAD = ["McConnell", "Schumer", "Thune", "Durbin", "Cornyn", "Barrasso"]


def load():
    t = pd.read_csv(S / "senate_trades.csv", dtype=str)
    t = t[t["type"].str.strip().eq("Purchase") & t.asset_type.str.contains("Stock", na=False)]
    t["ticker"] = t.ticker.fillna("").str.strip().str.upper().str.replace(".", "-", regex=False)
    t = t[t.ticker.str.fullmatch(r"[A-Z][A-Z\-]{0,6}")]
    t["ticker"] = t.ticker.replace({"FB": "META", "SQ": "XYZ"})
    t["filing_date"] = pd.to_datetime(t.filing_date, format="%m/%d/%Y").dt.date
    t["amount_lo"] = t.amount.map(lambda a: int(re.sub(r"[^\d]", "", a.split("-")[0]) or 1001))
    t["member"] = t["first"] + " " + t["last"]
    return t.drop_duplicates(["doc", "ticker"])


def main():
    b = load()
    spy = R.fetch_daily_yahoo("SPY", date(2014, 6, 1), date(2026, 10, 3))
    spy.index = pd.to_datetime(spy.index)
    spy = spy[spy.index <= "2026-09-30"]
    print(f"{len(b)} Kaufsignale von {b.member.nunique()} Senatoren, {b.ticker.nunique()} Ticker; je Jahr "
          f"{b.groupby(pd.to_datetime(b.filing_date).dt.year).size().to_dict()}\n")
    print("HAUPTERGEBNIS A alle Senatoren (Kriterium 2022-26 > SPY, t >= 2,0; 2015-21 > 0)")
    (c0, s0, _), (c1, s1, t1) = R.report("A alle Senatoren", b, spy)
    print(f"  -> {'BESTANDEN' if c1 > s1 and t1 >= 2.0 and c0 > s0 else 'nicht bestanden'}\n\nNUR INFO")
    lead = b[b["last"].isin(LEAD)]
    print(f"  Führung: {lead.groupby('last').size().to_dict()}")
    if len(lead):
        R.report("B Parteiführung", lead, spy)
    R.report("C nach Betragsklasse gewichtet", b.assign(w=b.amount_lo), spy, weight=True)
    print("\n  D Senatoren mit >= 30 Käufen (beschreibend):")
    for m, g in b.groupby("member"):
        if len(g) >= 30:
            eq, used, miss, inv = R.backtest(g, spy)
            c, cs, dd, t = R.stats(eq, spy, "2015-01-01", "2026-09-30")
            print(f"    {m:32s} {len(g):4d} Käufe  2015-26 {c:+6.1%} vs SPY {cs:+6.1%}  t {t:+.2f}  investiert {inv:.0%}")


if __name__ == "__main__":
    main()

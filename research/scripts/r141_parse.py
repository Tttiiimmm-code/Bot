"""Runde 141: Transaktionen aus den PTR-Texten ziehen -> data_cache/congress/trades.csv."""
import re
from pathlib import Path

import pandas as pd

D = Path(r"C:\Users\Nutzer\Bot\data_cache\congress")
PAT = re.compile(
    r"\(\s*([A-Za-z][A-Za-z.\- ]{0,8}?)\s*\)\s*(?:\[\s*([A-Za-z]{2})\s*\])?\s*"
    r"(P|S|E|p|s|e)(?:\s*\(\s*partial\s*\))?\s*"
    r"(\d{1,2}/\d{1,2}\s*/\s*\d{4})\s*(\d{1,2}/\d{1,2}\s*/\s*\d{4})\s*\$\s*([\d,]+)", re.S)


def parse(text):
    t = re.sub(r"\s+", " ", text)
    out = []
    for m in PAT.finditer(t):
        tick, tag, typ, d1, _d2, amt = m.groups()
        tick = tick.replace(" ", "").upper()
        tag = (tag or "").upper()
        if tag and tag not in ("ST", "OP"):
            continue
        out.append({"ticker": tick.replace(".", "-"), "tag": tag or "?", "type": typ.upper(),
                    "tx_date": d1.replace(" ", ""), "amount_lo": int(amt.replace(",", ""))})
    return out


if __name__ == "__main__":
    idx = pd.read_csv(D / "ptr_index.csv", dtype=str)
    rows = []
    for r in idx.itertuples():
        f = D / "ptr" / f"{r.DocID}.txt"
        if not f.exists():
            continue
        for x in parse(f.read_text(encoding="utf-8")):
            rows.append({"doc": r.DocID, "last": r.Last, "first": r.First, "state": r.StateDst,
                         "filing_date": pd.to_datetime(r.FilingDate).date()} | x)
    df = pd.DataFrame(rows)
    df.to_csv(D / "trades.csv", index=False)
    print(len(df), "Transaktionen aus", df.doc.nunique(), "Meldungen;", (df.type == "P").sum(), "Käufe;",
          df.ticker.nunique(), "Ticker")
    print(df[df["last"] == "Pelosi"].groupby("type").size())

"""Runde 87: alle SC-TO-T-Erstmeldungen 2016-01..2025-06 aus der EDGAR-Volltextsuche."""
import json
import time
import urllib.request
from pathlib import Path

import pandas as pd

OUT = Path("data_cache/tender"); OUT.mkdir(parents=True, exist_ok=True)
rows = []
for q in pd.date_range("2016-01-01", "2025-06-30", freq="QS"):
    e = (q + pd.offsets.QuarterEnd(0)).strftime("%Y-%m-%d")
    frm = 0
    while True:
        url = (f"https://efts.sec.gov/LATEST/search-index?forms=SC%20TO-T&dateRange=custom"
               f"&startdt={q:%Y-%m-%d}&enddt={e}&from={frm}")
        for attempt in range(6):
            try:
                j = json.loads(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "tradingbot-research-script"}), timeout=60).read())
                break
            except Exception:
                time.sleep(5 * (attempt + 1))
        else:
            raise RuntimeError(url)
        hits = j["hits"]["hits"]
        for h in hits:
            s = h["_source"]
            if s.get("file_type") == "SC TO-T" or s.get("form") == "SC TO-T":
                rows.append({"date": s["file_date"], "ciks": s["ciks"], "names": s["display_names"], "adsh": s["adsh"]})
        frm += len(hits)
        time.sleep(0.2)
        if not hits or frm >= j["hits"]["total"]["value"]:
            break
    print(q.strftime("%Y-%m"), len(rows), flush=True)
df = pd.DataFrame(rows).drop_duplicates("adsh")
df.to_pickle(OUT / "sc_to_t.pkl")
print("fertig", len(df))

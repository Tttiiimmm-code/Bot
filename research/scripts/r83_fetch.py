"""Runde 83: GDELT-Tonzeitreihe ("stock market", Englisch) monatsweise laden, mit Pausen."""
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

import pandas as pd

D = Path("data_cache/gdelt")
Q = urllib.parse.quote('"stock market" sourcelang:english')
for m in pd.date_range("2017-01-01", "2026-09-01", freq="MS"):
    p = D / f"tone_{m:%Y-%m}.json"
    if p.exists():
        continue
    e = (m + pd.offsets.MonthEnd(0)).strftime("%Y%m%d") + "235959"
    url = (f"https://api.gdeltproject.org/api/v2/doc/doc?query={Q}&mode=timelinetone"
           f"&startdatetime={m:%Y%m%d}000000&enddatetime={e}&format=json")
    for attempt in range(8):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "tradingbot-research-script"})
            txt = urllib.request.urlopen(req, timeout=90).read().decode("utf-8", "replace")
        except Exception as ex:
            txt = f"ERR {ex}"
        if txt.lstrip().startswith("{"):
            p.write_text(txt)
            break
        time.sleep(30 * (attempt + 1))
    print(m.strftime("%Y-%m"), "ok" if p.exists() else "FEHLT", flush=True)
    time.sleep(8)
print("fertig", flush=True)

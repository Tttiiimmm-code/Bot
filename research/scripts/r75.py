"""Runde 75: Nikkei-225-Aufnahmen, Ankündigung -> Stichtag."""
import json
import time
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

EV = [  # (Ankündigung, Stichtag, [Codes])
    ("2005-09-05", "2005-09-27", ["8303", "8795", "4795"]), ("2006-09-05", "2006-10-02", ["8815", "9602"]),
    ("2007-09-07", "2007-10-01", ["3086", "3436"]), ("2008-09-08", "2008-10-01", ["5541", "6305"]),
    ("2010-09-06", "2010-09-28", ["5214"]), ("2010-09-06", "2010-10-01", ["8804"]),
    ("2012-09-07", "2012-09-26", ["4043"]), ("2013-09-06", "2013-09-26", ["6988"]),
    ("2015-09-04", "2015-10-01", ["1808", "2432"]), ("2016-09-06", "2016-10-03", ["4755"]),
    ("2017-09-05", "2017-10-02", ["6098", "6178"]), ("2018-09-05", "2018-10-01", ["4751"]),
    ("2019-09-04", "2019-10-01", ["2413"]), ("2020-09-01", "2020-10-01", ["9434"]),
    ("2021-09-06", "2021-10-01", ["6861", "6981", "7974"]), ("2022-09-05", "2022-09-29", ["6594"]),
    ("2022-09-05", "2022-10-03", ["6273", "7741"]), ("2023-03-03", "2023-04-03", ["4661", "6723", "9201"]),
    ("2023-09-04", "2023-10-02", ["4385", "6920", "9843"]), ("2024-03-04", "2024-04-01", ["6146", "6526", "3092"]),
    ("2024-09-04", "2024-10-01", ["4307", "7453"]), ("2025-03-05", "2025-04-01", ["6532"]),
    ("2025-09-08", "2025-10-01", ["3697"]), ("2026-03-05", "2026-04-01", ["285A", "7532"]),
]
D = Path("data_cache/nikkei225/prices"); D.mkdir(exist_ok=True)


def load(sym):
    p = D / f"{sym}.json"
    if not p.exists():
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?period1=1104537600&period2=1790640000&interval=1d"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            p.write_text(urllib.request.urlopen(req, timeout=60).read().decode())
        except Exception:
            p.write_text("{}")
        time.sleep(0.5)
    j = json.loads(p.read_text())
    try:
        r = j["chart"]["result"][0]; q = r["indicators"]["quote"][0]
    except Exception:
        return None
    idx = pd.to_datetime(r["timestamp"], unit="s", utc=True).tz_convert("Asia/Tokyo").normalize().tz_localize(None)
    return pd.DataFrame({"open": q["open"], "close": q["close"]}, index=idx).dropna()


nk = load("%5EN225")
rows = []
for ann, eff, codes in EV:
    a, e = pd.Timestamp(ann), pd.Timestamp(eff)
    for c in codes:
        s = load(f"{c}.T")
        if s is None or s.empty:
            print("keine Daten", c); continue
        d0 = s.index[s.index > a]; d1 = s.index[s.index < e]
        if len(d0) == 0 or len(d1) == 0 or d0[0] > d1[-1]:
            print("Fenster fehlt", c, ann); continue
        i0, i1 = d0[0], d1[-1]
        ret = s.loc[i1, "close"] / s.loc[i0, "open"] - 1
        bench = nk.loc[nk.index[nk.index >= i0][0]:i1]
        bret = bench["close"].iloc[-1] / bench["open"].iloc[0] - 1
        after = s.index[s.index >= e][:10]
        rev = (s.loc[after[-1], "close"] / s.loc[i1, "close"] - 1) - \
              (nk.loc[nk.index[nk.index <= after[-1]][-1], "close"] / nk.loc[nk.index[nk.index <= i1][-1], "close"] - 1) \
            if len(after) == 10 else np.nan
        rows.append((a, c, i0.date(), i1.date(), ret - bret - 0.002, rev))
r = pd.DataFrame(rows, columns=["ann", "code", "in", "out", "abn", "rev10"])
print(r.to_string())
for name, s, e in [("Entdeckung 2005-2016", "2005", "2016-12-31"), ("Bestätigung 2017-2026", "2017", "2026-12-31")]:
    x = r[(r["ann"] >= s) & (r["ann"] <= e)]
    t = x["abn"].mean() / x["abn"].std() * np.sqrt(len(x))
    print(f"{name}: n {len(x)} Ø Überrendite netto {x['abn'].mean()*100:5.2f} % t {t:5.2f} Treffer {(x['abn']>0).mean():.2f} "
          f"| Umkehr +10T Ø {x['rev10'].mean()*100:5.2f} %")

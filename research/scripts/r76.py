"""Runde 76: Short um den IPO-Lockup-Ablauf (E-5 .. E+5)."""
import json
import re
import time
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

from tradingbot.research.universe import load_daily_panel

D = Path("data_cache/ipo")
rows = []
for m in pd.date_range("2016-01-01", "2025-02-01", freq="MS"):
    p = D / f"{m:%Y-%m}.json"
    if not p.exists():
        req = urllib.request.Request(f"https://api.nasdaq.com/api/ipo/calendar?date={m:%Y-%m}",
                                     headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
        p.write_text(urllib.request.urlopen(req, timeout=60).read().decode())
        time.sleep(0.5)
    pr = (json.loads(p.read_text()).get("data") or {}).get("priced") or {}
    rows += pr.get("rows") or []
ipo = pd.DataFrame(rows)
ipo["amt"] = ipo["dollarValueOfSharesOffered"].str.replace(r"[$,]", "", regex=True).astype(float)
ipo["date"] = pd.to_datetime(ipo["pricedDate"])
bad = re.compile(r"Acquisition|Merger|SPAC|Capital Corp|Trust|Fund|Units", re.I)
ipo = ipo[(ipo["amt"] >= 5e7) & ~ipo["companyName"].str.contains(bad)].drop_duplicates("proposedTickerSymbol")
print("IPOs nach Filter:", len(ipo))

panel = load_daily_panel()
close = panel["close"].unstack(0) if isinstance(panel.index, pd.MultiIndex) else panel
close.index = pd.to_datetime(close.index).tz_localize(None).normalize() if getattr(close.index, "tz", None) else pd.to_datetime(close.index).normalize()
vol = (panel["close"] * panel["volume"]).unstack(0)
vol.index = close.index
spy = close["SPY"].dropna()
days = spy.index
BOR, RT = 0.005, 0.002
ev = []
for _, x in ipo.iterrows():
    s = x["proposedTickerSymbol"]
    if s not in close.columns:
        continue
    c = close[s].dropna()
    first = c.index[c.index >= x["date"]]
    if len(first) == 0 or (first[0] - x["date"]).days > 5:
        continue
    e_idx = days.searchsorted(first[0] + pd.Timedelta(days=180))
    if e_idx + 5 >= len(days) or e_idx < 5:
        continue
    t0, t1 = days[e_idx - 5], days[e_idx + 5]
    if t0 not in c.index or t1 not in c.index:
        continue
    dv = vol[s].loc[:t0].iloc[-20:].mean()
    if c[t0] < 5 or not dv >= 1e6:
        continue
    abn = -((c[t1] / c[t0] - 1) - (spy[t1] / spy[t0] - 1)) - RT - BOR
    ev.append((x["date"], s, t0, abn))
r = pd.DataFrame(ev, columns=["ipo", "sym", "t0", "abn"])
print("Ereignisse:", len(r))
for name, s, e in [("Entdeckung IPO 2016-2019", "2016", "2019-12-31"), ("Bestätigung IPO 2020-2025-02", "2020", "2025-02-28")]:
    x = r[(r["ipo"] >= s) & (r["ipo"] <= e)]
    t = x["abn"].mean() / x["abn"].std() * np.sqrt(len(x))
    mm = x.groupby(x["t0"].dt.to_period("M"))["abn"].mean()
    tm = mm.mean() / mm.std() * np.sqrt(len(mm))
    print(f"{name}: n {len(x)} Ø Short-Überrendite netto {x['abn'].mean()*100:5.2f} % (brutto {(x['abn'].mean()+RT+BOR)*100:5.2f} %) "
          f"t {t:5.2f} | Monats-t {tm:5.2f} ({len(mm)} Monate) Treffer {(x['abn']>0).mean():.2f} Median {x['abn'].median()*100:5.2f} %")

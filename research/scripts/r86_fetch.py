"""Runde 86: 10-K-Worthäufigkeiten für die 500 liquidesten Aktien je Jahresende (2015-2024)."""
import gzip
import json
import pickle
import re
from collections import Counter
from pathlib import Path

import pandas as pd

from tradingbot.research import edgar

OUT = Path("data_cache/lazy"); OUT.mkdir(parents=True, exist_ok=True)
uni_path = OUT / "universe.pkl"
if not uni_path.exists():
    assets = pd.read_pickle("data_cache/universe/assets.pkl")
    fundlike = set(assets.loc[assets["name"].str.contains(r"ETF|Fund|Trust|iShares|SPDR|ProShares|Invesco|Direxion", case=False, na=False), "symbol"])
    rows = []
    for p in sorted(Path("data_cache/universe/daily").glob("batch_*.pkl")):
        d = pd.read_pickle(p)
        if d.empty:
            continue
        d = d[["close", "volume"]].copy()
        d.index = pd.MultiIndex.from_arrays([d.index.get_level_values(0), d.index.get_level_values(1).tz_convert("America/New_York").normalize().tz_localize(None)])
        dv = (d["close"] * d["volume"]).unstack(0)
        px = d["close"].unstack(0)
        adv = dv.rolling(60, min_periods=40).mean()
        for y in range(2015, 2025):
            e = adv.loc[:f"{y}-12-31"]
            if e.empty:
                continue
            last = e.iloc[-1]; lp = px.loc[:f"{y}-12-31"].iloc[-1]
            for s in last.index:
                if pd.notna(last[s]) and lp.get(s, 0) >= 5 and s not in fundlike:
                    rows.append((y, s, last[s]))
        del d, dv, px, adv
    u = pd.DataFrame(rows, columns=["year", "symbol", "adv"])
    u = u.sort_values("adv", ascending=False).groupby("year").head(500)
    u.to_pickle(uni_path)
u = pd.read_pickle(uni_path)
cik_map = edgar.symbol_to_cik(pd.read_pickle("data_cache/edgar/insider_purchases.pkl"))
syms = sorted(set(u["symbol"]))
ciks = sorted({cik_map[s] for s in syms if s in cik_map})
print("Symbole", len(syms), "mit CIK", len(ciks), flush=True)
json.dump({s: cik_map[s] for s in syms if s in cik_map}, open(OUT / "sym_cik.json", "w"))

TAG = re.compile(r"<[^>]+>"); WORD = re.compile(r"[a-z]{3,}")
n = 0
for cik in ciks:
    lst = OUT / f"{cik}_list.json"
    if not lst.exists():
        try:
            sub = json.loads(edgar._get(f"https://data.sec.gov/submissions/CIK{cik}.json"))
        except Exception:
            lst.write_text("[]"); continue
        pages = [sub["filings"]["recent"]]
        for f in sub["filings"].get("files", []):
            if f.get("filingTo", "9999") >= "2014-01-01":
                pages.append(json.loads(edgar._get(f"https://data.sec.gov/submissions/{f['name']}")))
        fl = []
        for p in pages:
            for form, fd, acc, doc in zip(p["form"], p["filingDate"], p["accessionNumber"], p["primaryDocument"]):
                if form == "10-K" and fd >= "2014-01-01" and doc:
                    fl.append((fd, acc, doc))
        lst.write_text(json.dumps(sorted(set(fl))))
    for fd, acc, doc in json.loads(lst.read_text()):
        out = OUT / f"{cik}_{fd}.pkl.gz"
        if out.exists():
            continue
        url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc.replace('-', '')}/{doc}"
        try:
            raw = edgar._get(url, timeout=180).decode("utf-8", "ignore")
        except Exception:
            continue
        txt = TAG.sub(" ", raw).lower()
        txt = re.sub(r"&[a-z#0-9]+;", " ", txt)
        with gzip.open(out, "wb") as f:
            pickle.dump(Counter(WORD.findall(txt)), f)
        n += 1
        if n % 200 == 0:
            print("10-K", n, flush=True)
print("fertig", n, flush=True)

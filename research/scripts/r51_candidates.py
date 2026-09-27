"""Runde 51, Schritt 2: Kandidaten (Top-3 je Meldung nach Ausschluss der Top-100) und CUSIP-Mapping."""
import json, time, urllib.request
from pathlib import Path
import pandas as pd

base = Path("data_cache/sec13f")
files = sorted(base.glob("*_form13f.pkl"))


def prep(p):
    df = pd.read_pickle(p)
    df["FILING_DATE"] = pd.to_datetime(df["FILING_DATE"], format="%d-%b-%Y")
    df["PERIODOFREPORT"] = pd.to_datetime(df["PERIODOFREPORT"], format="%d-%b-%Y")
    df["CUSIP"] = df["CUSIP"].str.upper().str.strip()
    df["USD"] = df["VALUE"] * (df["FILING_DATE"] < "2023-01-03").map({True: 1000.0, False: 1.0})
    return df


# Durchlauf 1: Gesamtwert je (Periode, CUSIP) und Kennzahlen je Meldung
aggs, stats, seen = [], [], set()
for p in files:
    df = prep(p)
    df = df[~df["ACCESSION_NUMBER"].isin(seen)]
    seen |= set(df["ACCESSION_NUMBER"].unique())
    aggs.append(df.groupby(["PERIODOFREPORT", "CUSIP"])["USD"].sum())
    g = df.groupby("ACCESSION_NUMBER")
    stats.append(pd.DataFrame({"n": g.size(), "total": g["USD"].sum()}))
    del df
agg = pd.concat(aggs).groupby(level=[0, 1]).sum()
stats = pd.concat(stats)
mega = set(agg.groupby(level=0, group_keys=False).nlargest(100).index)
ok = set(stats[(stats["n"] >= 20) & (stats["n"] <= 200) & (stats["total"] >= 1e8)].index)
# Durchlauf 2: Top-3 Nicht-Mega-Positionen je qualifizierter Meldung
parts, seen = [], set()
for p in files:
    df = prep(p)
    df = df[df["ACCESSION_NUMBER"].isin(ok) & ~df["ACCESSION_NUMBER"].isin(seen)]
    seen |= set(df["ACCESSION_NUMBER"].unique())
    keys = list(zip(df["PERIODOFREPORT"], df["CUSIP"]))
    df = df[[k not in mega for k in keys]]
    parts.append(df.sort_values("USD", ascending=False).groupby("ACCESSION_NUMBER").head(3))
c = pd.concat(parts, ignore_index=True)
c = c.merge(stats, left_on="ACCESSION_NUMBER", right_index=True)
c["rank"] = c.groupby("ACCESSION_NUMBER")["USD"].rank(ascending=False, method="first")
c.to_pickle(base / "candidates.pkl")
cusips = sorted(set(c["CUSIP"]))
print("Meldungen gesamt", len(stats), "qualifiziert", len(ok), "Kandidaten-CUSIPs", len(cusips), flush=True)

mpath = base / "figi.json"
mapping = json.load(open(mpath)) if mpath.exists() else {}
todo = [x for x in cusips if x not in mapping]
for i in range(0, len(todo), 10):
    chunk = todo[i:i + 10]
    body = json.dumps([{"idType": "ID_CUSIP", "idValue": x, "exchCode": "US"} for x in chunk]).encode()
    for attempt in range(6):
        try:
            req = urllib.request.Request("https://api.openfigi.com/v3/mapping", data=body, headers={"Content-Type": "application/json"})
            res = json.loads(urllib.request.urlopen(req, timeout=60).read())
            break
        except Exception:
            time.sleep(30)
    else:
        continue
    for x, r in zip(chunk, res):
        d = r.get("data") or []
        eq = [e for e in d if e.get("marketSector") == "Equity"]
        mapping[x] = (eq or d or [{}])[0].get("ticker")
    if (i // 10) % 20 == 0:
        json.dump(mapping, open(mpath, "w"))
        print(i, len(todo), flush=True)
    time.sleep(2.5)
json.dump(mapping, open(mpath, "w"))
print("Mapping fertig", sum(v is not None for v in mapping.values()), "von", len(mapping))

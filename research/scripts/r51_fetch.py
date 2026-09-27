"""Runde 51: SEC-13F-Datensätze laden und verdichten."""
import io, time, urllib.request, zipfile
from pathlib import Path
import pandas as pd

base = Path("data_cache/sec13f")
for url in open(base / "urls.txt").read().split():
    name = url.rsplit("/", 1)[1].replace(".zip", "")
    out = base / f"{name}.pkl"
    if out.exists():
        continue
    for i in range(5):
        try:
            data = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "tradingbot-research-script"}), timeout=300).read()
            break
        except Exception:
            time.sleep(20)
    z = zipfile.ZipFile(io.BytesIO(data))
    names = {n.split("/")[-1].upper(): n for n in z.namelist()}
    sub = pd.read_csv(z.open(names["SUBMISSION.TSV"]), sep="\t", dtype=str, usecols=lambda c: c in ("ACCESSION_NUMBER", "FILING_DATE", "SUBMISSIONTYPE", "CIK", "PERIODOFREPORT"))
    sub = sub[sub["SUBMISSIONTYPE"] == "13F-HR"]
    info = pd.read_csv(z.open(names["INFOTABLE.TSV"]), sep="\t", dtype=str,
                       usecols=lambda c: c in ("ACCESSION_NUMBER", "CUSIP", "VALUE", "SSHPRNAMTTYPE", "PUTCALL", "TITLEOFCLASS"))
    info = info[info["ACCESSION_NUMBER"].isin(sub["ACCESSION_NUMBER"])]
    info = info[info["PUTCALL"].isna() & (info["SSHPRNAMTTYPE"] != "PRN")]
    info["VALUE"] = pd.to_numeric(info["VALUE"], errors="coerce")
    info = info.groupby(["ACCESSION_NUMBER", "CUSIP"], as_index=False)["VALUE"].sum()
    info = info.merge(sub, on="ACCESSION_NUMBER")
    info.to_pickle(out)
    print(name, len(sub), len(info), flush=True)
    time.sleep(1)
print("fertig")

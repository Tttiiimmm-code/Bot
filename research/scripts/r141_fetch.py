"""Runde 141: elektronische PTR-Meldungen (House) 2015-2026 laden und als Text speichern."""
import csv
import io
import time
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pypdf

D = Path(r"C:\Users\Nutzer\Bot\data_cache\congress")
OUT = D / "ptr"
OUT.mkdir(exist_ok=True)


def index():
    rows = []
    for y in range(2015, 2027):
        with zipfile.ZipFile(D / f"{y}FD.zip") as z:
            txt = z.read(f"{y}FD.txt").decode("utf-8", "replace")
        for r in csv.DictReader(io.StringIO(txt), delimiter="\t"):
            if r["FilingType"] == "P" and r["DocID"].startswith("2"):
                rows.append(r | {"Year": str(y)})
    return rows


def fetch(r):
    out = OUT / f"{r['DocID']}.txt"
    if out.exists() and out.stat().st_size > 0:
        return "cached"
    url = f"https://disclosures-clerk.house.gov/public_disc/ptr-pdfs/{r['Year']}/{r['DocID']}.pdf"
    for attempt in range(4):
        try:
            data = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}),
                                          timeout=60).read()
            text = "\n".join(p.extract_text() or "" for p in pypdf.PdfReader(io.BytesIO(data)).pages)
            out.write_text(text, encoding="utf-8")
            return "ok"
        except Exception as e:  # noqa: BLE001
            err = e
            time.sleep(2 * (attempt + 1))
    return f"fail {err}"


if __name__ == "__main__":
    rows = index()
    with open(D / "ptr_index.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(len(rows), "Meldungen", flush=True)
    stats = {}
    with ThreadPoolExecutor(4) as ex:
        for i, s in enumerate(ex.map(fetch, rows)):
            k = s.split()[0]
            stats[k] = stats.get(k, 0) + 1
            if i % 500 == 0:
                print(i, stats, flush=True)
    print("fertig", stats)

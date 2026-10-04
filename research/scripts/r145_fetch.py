"""Runde 145: 13D-Meldungen aus EDGAR (Index + Kopfzeilen) -> data_cache/sec13d/filings.csv."""
import gzip
import re
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd

D = Path(r"C:\Users\Nutzer\Bot\data_cache\sec13d")
D.mkdir(exist_ok=True)
UA = {"User-Agent": "tradingbot-research-script"}


_LOCK = threading.Lock()
_NEXT = [0.0]
MIN_GAP = 0.16                                   # <= ~6 Anfragen/s (SEC-Grenze 10/s)


def get(url):
    for a in range(6):
        with _LOCK:
            wait = _NEXT[0] - time.time()
            if wait > 0:
                time.sleep(wait)
            _NEXT[0] = time.time() + MIN_GAP
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
                data = r.read()
            if b"Request Rate Threshold" in data[:3000]:
                raise RuntimeError("rate")
            return data
        except Exception as e:  # noqa: BLE001
            if "429" in str(e) or "rate" in str(e):
                with _LOCK:
                    _NEXT[0] = time.time() + 660         # SEC-Sperre 10 Minuten abwarten
            else:
                time.sleep(2 * (a + 1))
    return None


def index_rows():
    rows = []
    for y in range(2014, 2027):
        for q in range(1, 5):
            if (y, q) < (2014, 4) or (y, q) > (2026, 3):
                continue
            f = D / f"form_{y}Q{q}.csv"
            if not f.exists():
                raw = gzip.decompress(get(f"https://www.sec.gov/Archives/edgar/full-index/{y}/QTR{q}/form.gz"))
                out = []
                for line in raw.decode("latin-1").splitlines():
                    if line.startswith("SC 13D ") or line.startswith("SCHEDULE 13D "):
                        path = line.split()[-1]
                        out.append({"form": "13D", "date": line.split()[-2], "path": path})
                pd.DataFrame(out).to_csv(f, index=False)
                time.sleep(0.5)
            rows.append(pd.read_csv(f))
            print(y, q, len(rows[-1]), flush=True)
    return pd.concat(rows, ignore_index=True)


def header(path):
    cik, acc = path.split("/")[2], path.split("/")[3].replace(".txt", "")
    raw = get(f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc.replace('-', '')}/{acc}.hdr.sgml")
    if raw is None:
        return None
    t = raw.decode("latin-1")
    subj = re.search(r"<SUBJECT-COMPANY>.*?<CIK>(\d+)", t, re.S)
    by = re.search(r"<FILED-BY>.*?<CONFORMED-NAME>([^\n]*)\n.*?<CIK>(\d+)", t, re.S)
    acc_t = re.search(r"<ACCEPTANCE-DATETIME>(\d{14})", t)
    return {"path": path, "subject_cik": int(subj.group(1)) if subj else None,
            "filer": by.group(1).strip() if by else "", "filer_cik": int(by.group(2)) if by else None,
            "accepted": acc_t.group(1) if acc_t else ""}


if __name__ == "__main__":
    idx = index_rows()
    print("13D gesamt", len(idx), flush=True)
    hf = D / "headers.csv"
    done = pd.read_csv(hf) if hf.exists() else pd.DataFrame(columns=["path"])
    todo = [p for p in idx.path if p not in set(done.path)]
    out = []
    with ThreadPoolExecutor(4) as ex:
        for i, h in enumerate(ex.map(header, todo)):
            if h:
                out.append(h)
            if i % 2000 == 0:
                print(i, len(todo), flush=True)
                pd.concat([done, pd.DataFrame(out)]).to_csv(hf, index=False)
    allh = pd.concat([done, pd.DataFrame(out)])
    allh.to_csv(hf, index=False)
    res = idx.merge(allh, on="path")
    tick = pd.read_json(get("https://www.sec.gov/files/company_tickers.json").decode()).T
    res = res.merge(tick.rename(columns={"cik_str": "subject_cik"})[["subject_cik", "ticker"]], on="subject_cik", how="left")
    res.to_csv(D / "filings.csv", index=False)
    print("fertig", len(res), "mit Ticker", res.ticker.notna().sum())

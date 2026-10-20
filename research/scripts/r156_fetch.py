"""Runde 156: Formular-10-12B-Melder aus der SEC-Volltextsuche + Kürzel -> data_cache/spinoff/candidates.csv.

Kürzel: aus der SEC-Anzeige ("Name (KÜRZEL) (CIK ...)"), sonst aus den Dateinamen der 10-Q/10-K-Hauptdokumente
(kürzel-JJJJMMTT.htm) der Einreichungsliste (data.sec.gov/submissions). Fortsetzbar. Aufruf aus dem Haupt-Repo.
"""
import json
import re
import time
import urllib.request
from pathlib import Path

import pandas as pd

D = Path("data_cache/spinoff")
D.mkdir(parents=True, exist_ok=True)
UA = {"User-Agent": "tradingbot-research-script"}
_last = [0.0]


def get(url: str) -> bytes | None:
    for a in range(6):
        wait = _last[0] + 0.17 - time.time()               # <= ~6 Anfragen/s (SEC-Grenze 10/s)
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.time()
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001
            if "404" in str(e):
                return None
            if "429" in str(e):
                print("  SEC-Sperre, warte 11 Minuten", flush=True)
                time.sleep(660)
            else:
                time.sleep(3 * (a + 1))
    return None


def filings() -> pd.DataFrame:
    f = D / "filings_10-12B.csv"
    if f.exists():
        return pd.read_csv(f)
    rows = []
    for y in range(2015, 2026):
        a, b = f"{y}-01-01", (f"{y}-12-31" if y < 2025 else "2025-06-30")
        start = 0
        while True:
            u = (f"https://efts.sec.gov/LATEST/search-index?forms=10-12B&dateRange=custom&startdt={a}&enddt={b}"
                 f"&from={start}")
            hits = json.loads(get(u))["hits"]
            for h in hits["hits"]:
                s = h["_source"]
                if "10-12B" not in (s.get("root_forms") or []):
                    continue
                for cik, name in zip(s.get("ciks", []), s.get("display_names", [])):
                    rows.append({"cik": int(cik), "display": name, "form": s.get("form"), "date": s.get("file_date")})
            start += len(hits["hits"])
            if not hits["hits"] or start >= hits["total"]["value"]:
                break
        print(f"{y}: {len(rows)} Zeilen gesamt", flush=True)
    df = pd.DataFrame(rows)
    df.to_csv(f, index=False)
    return df


TICK_RE = re.compile(r"\(([A-Z0-9.\-]{1,6}(?:, [A-Z0-9.\-]{1,6})*)\)\s+\(CIK")
DOC_RE = re.compile(r"^([a-z]{1,5})-?(20\d{6})")


def doc_ticker(cik: int) -> tuple[str, str]:
    raw = get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json")
    if raw is None:
        return "", ""
    js = json.loads(raw)
    tick = ",".join(js.get("tickers") or [])
    rec = js.get("filings", {}).get("recent", {})
    docs = [d for form, d in zip(rec.get("form", []), rec.get("primaryDocument", [])) if form in ("10-Q", "10-K")]
    pref = ""
    for d in reversed(docs):                                # älteste zuerst
        m = DOC_RE.match(d.lower())
        if m:
            pref = m.group(1).upper()
            break
    return tick, pref


def main():
    f = filings()
    first = f.sort_values("date").groupby("cik").agg(display=("display", "last"), date=("date", "first")).reset_index()
    first = first[first["date"] <= "2025-06-30"]
    out_f = D / "candidates.csv"
    done = pd.read_csv(out_f) if out_f.exists() else pd.DataFrame(columns=["cik"])
    rows = done.to_dict("records")
    seen = set(done["cik"])
    for k, r in enumerate(first.itertuples()):
        if r.cik in seen:
            continue
        m = TICK_RE.search(r.display)
        sec_tick = m.group(1) if m else ""
        sub_tick, doc_pref = doc_ticker(r.cik)
        rows.append({"cik": r.cik, "name": re.sub(r"\s+\(.*", "", r.display), "first_10_12b": r.date,
                     "sec_ticker": sec_tick, "sub_tickers": sub_tick, "doc_prefix": doc_pref})
        if len(rows) % 50 == 0:
            pd.DataFrame(rows).to_csv(out_f, index=False)
            print(f"  {len(rows)}/{len(first)} Firmen", flush=True)
    pd.DataFrame(rows).to_csv(out_f, index=False)
    print(f"fertig: {len(rows)} Firmen", flush=True)


if __name__ == "__main__":
    main()

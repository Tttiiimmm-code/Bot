"""Mitgliederlisten aus alten Wikipedia-Revisionen (Runde 37, R1)."""
import re, html as H
from pathlib import Path

WIKI = Path("data_cache/europe/wiki")
SUFFIX = {"DAX": ".DE", "MDAX": ".DE", "CAC_40": ".PA", "FTSE_100_Index": ".L", "AEX_index": ".AS",
          "Swiss_Market_Index": ".SW", "IBEX_35": ".MC", "FTSE_MIB": ".MI", "OMX_Stockholm_30": ".ST"}


def tables(h):
    for t in re.findall(r'<table class="[^"]*wikitable.*?</table>', h, re.S):
        rows = [[H.unescape(re.sub(r"<[^>]+>", "", c)).strip()
                 for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", r, re.S)]
                for r in re.findall(r"<tr[^>]*>(.*?)</tr>", t, re.S)]
        if rows:
            yield rows


def tickers(page, year):
    f = WIKI / f"{page}_{year}.html"
    if not f.exists() or f.stat().st_size == 0:
        return []
    h = f.read_text(encoding="utf-8")
    best = []
    for rows in tables(h):
        hdr = [x.lower() for x in rows[0]]
        col = next((i for i, x in enumerate(hdr) if "ticker" in x or "symbol" in x or x == "epic"), None)
        if col is None:
            continue
        tk = [r[col].split()[0].rstrip(".") for r in rows[1:] if len(r) > col and r[col].strip()]
        if len(tk) > len(best):
            best = tk
    return best


def normalize(page, t):
    suf = SUFFIX[page]
    t = t.upper()
    if page == "FTSE_100_Index":
        return t.replace(".", "-") + suf
    return t if "." in t else t + suf

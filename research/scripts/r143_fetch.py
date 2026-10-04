"""Runde 143: Senats-PTRs (efdsearch.senate.gov, Nutzungsbedingungen akzeptiert mit Zustimmung des Nutzers)."""
import html
import re
import time
from pathlib import Path

import pandas as pd
import requests

D = Path(r"C:\Users\Nutzer\Bot\data_cache\congress\senate")
D.mkdir(parents=True, exist_ok=True)
B = "https://efdsearch.senate.gov"


def session():
    s = requests.Session()
    s.headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
    h = s.get(f"{B}/search/home/", timeout=60)
    tok = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', h.text).group(1)
    s.post(f"{B}/search/home/", data={"prohibition_agreement": "1", "csrfmiddlewaretoken": tok},
           headers={"Referer": f"{B}/search/home/"}, timeout=60)
    return s


def listing(s):
    rows, start = [], 0
    while True:
        csrf = s.cookies.get("csrftoken")
        j = s.post(f"{B}/search/report/data/", data={
            "start": str(start), "length": "100", "report_types": "[11]", "filer_types": "[]",
            "submitted_start_date": "01/01/2014 00:00:00", "submitted_end_date": "", "candidate_state": "",
            "senator_state": "", "office_id": "", "first_name": "", "last_name": "", "csrfmiddlewaretoken": csrf},
            headers={"Referer": f"{B}/search/", "X-CSRFToken": csrf}, timeout=60).json()
        for first, last, _full, link, filed in j["data"]:
            href = re.search(r'href="([^"]+)"', link).group(1)
            rows.append({"first": first, "last": last, "href": href, "filing_date": filed})
        start += 100
        if start >= j["recordsTotal"]:
            return pd.DataFrame(rows)
        time.sleep(1)


def cell(x):
    return html.unescape(re.sub(r"<[^>]+>", " ", x)).split("Company:")[0].strip()


def parse(page):
    body = page[page.find("<tbody"):page.find("</tbody>")]
    out = []
    for tr in re.findall(r"<tr>(.*?)</tr>", body, re.S):
        td = [cell(x) for x in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)]
        if len(td) >= 8:
            out.append({"tx_date": td[1], "owner": td[2], "ticker": re.sub(r"\s+", " ", td[3]), "asset": td[4][:80],
                        "asset_type": td[5], "type": td[6], "amount": td[7]})
    return out


if __name__ == "__main__":
    s = session()
    idx = listing(s)
    idx.to_csv(D / "senate_index.csv", index=False)
    print(len(idx), "Meldungen,", idx.href.str.contains("/ptr/").sum(), "elektronisch", flush=True)
    rows = []
    for k, r in enumerate(idx[idx.href.str.contains("/ptr/")].itertuples()):
        f = D / (r.href.strip("/").split("/")[-1] + ".html")
        if not f.exists():
            for attempt in range(4):
                try:
                    p = s.get(B + r.href, timeout=60)
                    if "agreement_form" in p.text:
                        s = session()
                        continue
                    f.write_text(p.text, encoding="utf-8")
                    break
                except Exception:  # noqa: BLE001
                    time.sleep(5 * (attempt + 1))
            time.sleep(0.7)
        if f.exists():
            for x in parse(f.read_text(encoding="utf-8")):
                rows.append({"doc": f.stem, "first": r.first, "last": r.last, "filing_date": r.filing_date} | x)
        if k % 200 == 0:
            print(k, len(rows), flush=True)
    pd.DataFrame(rows).to_csv(D / "senate_trades.csv", index=False)
    print("fertig", len(rows))

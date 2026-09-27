"""Runde 60: Polymarket-Märkte und Preisverläufe laden."""
import json, time, urllib.request
from pathlib import Path

base = Path("data_cache/polymarket")
base.mkdir(parents=True, exist_ok=True)
H = {"User-Agent": "tradingbot-research-script"}


def get(u):
    for i in range(5):
        try:
            return json.loads(urllib.request.urlopen(urllib.request.Request(u, headers=H), timeout=60).read())
        except Exception:
            time.sleep(5 * (i + 1))
    return None


mpath = base / "markets.json"
if not mpath.exists():
    # Gamma liefert je Abfrage höchstens ~2100 Treffer -> monatsweise nach Enddatum abfragen
    import pandas as pd
    markets, seen = [], set()
    for start in pd.date_range("2023-01-01", "2026-09-01", freq="MS"):
        end = start + pd.offsets.MonthBegin(1)
        offset = 0
        while True:
            batch = get(f"https://gamma-api.polymarket.com/markets?closed=true&limit=100&offset={offset}"
                        f"&volume_num_min=50000&end_date_min={start:%Y-%m-%d}T00:00:00Z&end_date_max={end:%Y-%m-%d}T00:00:00Z")
            if not batch:
                break
            for m in batch:
                if m["id"] not in seen:
                    seen.add(m["id"])
                    markets.append(m)
            offset += len(batch)
            time.sleep(0.3)
        print("Monat", f"{start:%Y-%m}", "Märkte gesamt", len(markets), flush=True)
    json.dump(markets, open(mpath, "w"))
markets = json.load(open(mpath))
hdir = base / "hist"
hdir.mkdir(exist_ok=True)
n = 0
for m in markets:
    try:
        tok = json.loads(m.get("clobTokenIds") or "[]")
        outs = json.loads(m.get("outcomes") or "[]")
    except Exception:
        continue
    if len(tok) != 2 or [o.lower() for o in outs] != ["yes", "no"]:
        continue
    f = hdir / f"{m['id']}.json"
    if f.exists():
        continue
    h = get(f"https://clob.polymarket.com/prices-history?market={tok[0]}&interval=max&fidelity=1440")
    json.dump(h or {}, open(f, "w"))
    n += 1
    if n % 200 == 0:
        print("Verläufe", n, flush=True)
    time.sleep(0.15)
print("fertig", len(markets), n)

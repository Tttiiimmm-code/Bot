"""Runde 70: Portfolio-Historien der Hyperliquid-Konten mit Gesamtvolumen >= 100 Mio. USD laden."""
import json
import time
import urllib.request
from pathlib import Path

D = Path("data_cache/hyperliquid")
rows = json.load(open(D / "leaderboard_2026-09-27.json", encoding="utf-8"))["leaderboardRows"]
addrs = [r["ethAddress"] for r in rows if float(dict(r["windowPerformances"])["allTime"]["vlm"]) >= 1e8]
print("Konten", len(addrs), flush=True)
done = 0
for a in addrs:
    p = D / "portfolio" / f"{a}.json"
    if p.exists():
        continue
    for attempt in range(5):
        try:
            req = urllib.request.Request("https://api.hyperliquid.xyz/info",
                                         data=json.dumps({"type": "portfolio", "user": a}).encode(),
                                         headers={"Content-Type": "application/json"})
            data = json.load(urllib.request.urlopen(req, timeout=60))
            p.write_text(json.dumps(data))
            break
        except Exception as e:
            time.sleep(10 * (attempt + 1))
    done += 1
    if done % 250 == 0:
        print("geladen", done, flush=True)
    time.sleep(1.0)
print("fertig", flush=True)

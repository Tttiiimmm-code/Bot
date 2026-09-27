"""Runde 60: Favoriten-Außenseiter-Verzerrung auf Polymarket."""
import json
from datetime import datetime, timezone
from pathlib import Path
import numpy as np, pandas as pd

base = Path("data_cache/polymarket")
markets = json.load(open(base / "markets.json"))
rows, skipped = [], {"kein_verlauf": 0, "nicht_eindeutig": 0, "keine_zeit": 0, "kein_preis": 0}
for m in markets:
    f = base / "hist" / f"{m['id']}.json"
    if not f.exists():
        continue
    try:
        prices = [float(x) for x in json.loads(m.get("outcomePrices") or "[]")]
    except Exception:
        prices = []
    if sorted(prices) != [0.0, 1.0]:
        skipped["nicht_eindeutig"] += 1
        continue
    yes_won = prices[0] == 1.0
    ct = m.get("closedTime") or m.get("umaEndDate") or m.get("endDate")
    if not ct:
        skipped["keine_zeit"] += 1
        continue
    close = pd.Timestamp(ct.replace(" ", "T").replace("+00", "+00:00") if "+00" in ct and "+00:00" not in ct else ct)
    if close.tzinfo is None:
        close = close.tz_localize("UTC")
    h = (json.load(open(f)) or {}).get("history") or []
    if not h:
        skipped["kein_verlauf"] += 1
        continue
    s = pd.Series([x["p"] for x in h], index=pd.to_datetime([x["t"] for x in h], unit="s", utc=True)).sort_index()
    entry = close - pd.Timedelta(days=7)
    s = s[s.index <= entry]
    if len(s) == 0 or entry - s.index[-1] > pd.Timedelta(days=2):
        skipped["kein_preis"] += 1
        continue
    p = float(s.iloc[-1])
    fav_yes = p >= 0.5
    q = p if fav_yes else 1 - p
    won = yes_won == fav_yes
    ev = (m.get("events") or [{}])[0].get("id") or m["id"]
    rows.append({"id": m["id"], "event": ev, "close": close, "q": q, "won": won})
df = pd.DataFrame(rows)
print("Märkte mit Preis 7 Tage vorher:", len(df), "übersprungen:", skipped)
bins = [0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 0.97, 1.0001]
df["bin"] = pd.cut(df["q"], bins, right=False)
cal = df.groupby("bin", observed=True).agg(n=("won", "size"), preis=("q", "mean"), trefferquote=("won", "mean"))
print("Kalibrierung (alle Zeiträume):")
print(cal.to_string())
t = df[(df["q"] >= 0.80) & (df["q"] <= 0.97)].copy()
t["r"] = np.where(t["won"], 1 / (t["q"] + 0.01) - 1, -1.0)
P = {"2023-2024": ("2023-01-01", "2024-12-31"), "2025-01..09-19": ("2025-01-01", "2025-09-19 23:59"),
     "unberührt": ("2025-09-22", "2026-09-25 23:59")}
res = {}
for name, (a, b) in P.items():
    x = t[(t["close"] >= pd.Timestamp(a, tz="UTC")) & (t["close"] <= pd.Timestamp(b, tz="UTC"))]
    e = x.groupby("event")["r"].mean()
    tt = e.mean() / e.std() * np.sqrt(len(e)) if len(e) > 1 else np.nan
    res[name] = (tt, e.mean())
    print(f"{name:15s} Märkte {len(x):5d} Ereignisse {len(e):5d} Ø Preis {x['q'].mean():.3f} Trefferquote {x['won'].mean():.3f} "
          f"Ø Rendite je Ereignis {e.mean():+.2%} t {tt:5.2f}")
ok = res["2023-2024"][0] >= 2 and res["2025-01..09-19"][0] >= 2 and res["unberührt"][1] > 0
print("->", "BESTANDEN" if ok else "NICHT BESTANDEN")

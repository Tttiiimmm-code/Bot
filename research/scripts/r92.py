"""Runde 92, Schritt 3+4: Ereignisse bilden, per gpt-5-mini bewerten (gecacht), auswerten.

Aufruf: PYTHONPATH=. python research/scripts/r92.py [env-datei] [--rate]
  ohne --rate: nur Ereignisse zählen und bereits vorhandene Bewertungen auswerten (keine Kosten)
  mit  --rate: fehlende Bewertungen bei OpenAI abrufen (Obergrenze 3.000, Kosten ~3-4 USD)
"""
import json
import os
import sys
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
from dotenv import load_dotenv

args = [a for a in sys.argv[1:] if not a.startswith("--")]
load_dotenv(args[0] if args else "bottest.env")
RATE = "--rate" in sys.argv
OUT = Path("data_cache/r92")
MODEL, CAP, COST = "gpt-5-mini", 3000, 0.003

# ---------------------------------------------------------------- Ereignisse
bars = pd.read_pickle(OUT / "bars.pkl").reset_index()
bars["day"] = pd.to_datetime(bars["timestamp"]).dt.tz_convert("America/New_York").dt.normalize().dt.tz_localize(None)
bars = bars.sort_values(["symbol", "day"]).reset_index(drop=True)
bars["prev_close"] = bars.groupby("symbol")["close"].shift(1)
dv = (bars["close"] * bars["volume"]).groupby(bars["symbol"]).shift(1)
bars["adv20"] = dv.groupby(bars["symbol"]).transform(lambda x: x.rolling(20, min_periods=15).mean())
B = bars.set_index(["symbol", "day"])

events = []
for p in sorted((OUT / "news").glob("*.json")):
    d = pd.Timestamp(p.stem)
    by_sym = {}
    for r in json.loads(p.read_text()):
        if 1 <= len(r["sym"]) <= 3:
            for s in r["sym"]:
                by_sym.setdefault(s, []).append(r)
    for s, items in by_sym.items():
        if (s, d) not in B.index:
            continue
        row = B.loc[(s, d)]
        if not (1 <= row["prev_close"] <= 20) or not (row["adv20"] >= 1e6) or not (row["open"] > 0):
            continue
        items = sorted(items, key=lambda r: r["t"], reverse=True)[:8]
        events.append({"id": f"{d:%Y-%m-%d}_{s}", "day": d, "sym": s, "ret": row["close"] / row["open"] - 1,
                       "gap": row["open"] / row["prev_close"] - 1, "items": items})
ev = pd.DataFrame(events)
print("Ereignisse:", len(ev), "Handelstage:", ev["day"].nunique())
sample = ev.sample(n=CAP, random_state=92) if len(ev) > CAP else ev
print("Stichprobe zur Bewertung:", len(sample))

# ---------------------------------------------------------------- Bewertung
cache_path = OUT / "ratings.jsonl"
cache = {}
if cache_path.exists():
    for line in cache_path.read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        cache[r["id"]] = r
PROMPT = """You rate overnight news for the US stock {sym} before today's market open.
Using ONLY the items below, predict the stock's likely reaction during today's regular session.

{items}

Answer with ONE JSON object and nothing else:
{{"direction": "positive"|"negative"|"mixed"|"unclear", "strength": 1-5 (expected price impact, 5 = very large),
 "dilution": true|false (share offering, ATM, warrants, S-1/S-3/424B, reverse split)}}"""
lock = threading.Lock()


def rate(row):
    text = "\n".join(f"- [{it['t'][:16]}] {it['h']}" + (f" -- {it['s'][:300]}" if it["s"] else "")
                     for it in row["items"])
    body = json.dumps({"model": MODEL, "max_completion_tokens": 2000,
                       "messages": [{"role": "user", "content": PROMPT.format(sym=row["sym"], items=text)}]}).encode()
    req = urllib.request.Request("https://api.openai.com/v1/chat/completions", data=body, method="POST",
                                 headers={"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}",
                                          "content-type": "application/json"})
    out = None
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                res = json.load(r)
            content = res["choices"][0]["message"]["content"]
            j = json.loads(content[content.find("{"):content.rfind("}") + 1])
            out = {"id": row["id"], "direction": str(j.get("direction", "unclear")).lower(),
                   "strength": int(j.get("strength", 0) or 0), "dilution": bool(j.get("dilution", False)),
                   "usage": res.get("usage", {})}
            break
        except Exception as e:
            out = {"id": row["id"], "error": f"{type(e).__name__}: {e}"[:200]}
            time.sleep(5 * (attempt + 1))
    with lock:
        cache[row["id"]] = out
        with cache_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(out) + "\n")


if RATE:
    if not os.environ.get("OPENAI_API_KEY"):
        sys.exit("OPENAI_API_KEY fehlt in der env-Datei.")
    todo = [r for _, r in sample.iterrows() if r["id"] not in cache or "error" in cache[r["id"]]]
    print("zu bewerten:", len(todo), flush=True)
    done = [0]

    def job(r):
        rate(r)
        done[0] += 1
        if done[0] % 100 == 0:
            print("bewertet", done[0], flush=True)

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(job, todo))

# ---------------------------------------------------------------- Auswertung
rated = sample[sample["id"].map(lambda i: i in cache and "error" not in cache[i])].copy()
if rated.empty:
    sys.exit("Noch keine Bewertungen -- mit --rate starten.")
for k in ("direction", "strength", "dilution"):
    rated[k] = rated["id"].map(lambda i, k=k: cache[i][k])
rated["net"] = rated["ret"] - COST
tok = [cache[i].get("usage", {}) for i in rated["id"]]
inp = sum(u.get("prompt_tokens", 0) for u in tok)
outp = sum(u.get("completion_tokens", 0) for u in tok)
print(f"Bewertet: {len(rated)} | Token ein {inp:,} aus {outp:,} | Kosten ~{inp/1e6*0.25 + outp/1e6*2:.2f} USD "
      "(Listenpreis-Schätzung)")
print(rated.groupby("direction")["net"].agg(["count", "mean"]).round(4))


def tstat(x):
    return x.mean() / x.std() * np.sqrt(len(x)) if len(x) > 1 else float("nan")


ln = rated[(rated["direction"] == "positive") & (rated["strength"] >= 4) & (~rated["dilution"])]
base = rated
print(f"\nLN Long-Signal: n {len(ln)}, Ø netto {ln['net'].mean()*100:.2f} % je Trade, t {tstat(ln['net']):.2f}, "
      f"Treffer {(ln['net'] > 0).mean():.2f}")
print(f"Basis alle Ereignisse: n {len(base)}, Ø netto {base['net'].mean()*100:.2f} %")
diff_t = (ln["net"].mean() - base["net"].mean()) / np.sqrt(ln["net"].var() / len(ln) + base["net"].var() / len(base))
print(f"Differenz LN - Basis: {(ln['net'].mean() - base['net'].mean())*100:.2f} %-Punkte, t {diff_t:.2f}")
h1, h2 = ln[ln["day"] < "2026-04-01"], ln[ln["day"] >= "2026-04-01"]
print(f"Hälften: 2025-10..2026-03 n {len(h1)} Ø {h1['net'].mean()*100:.2f} % | 2026-04..09 n {len(h2)} "
      f"Ø {h2['net'].mean()*100:.2f} %")
neg = rated[(rated["direction"] == "negative") & (rated["strength"] >= 4)]
dil = rated[rated["dilution"]]
print(f"Berichtet: negativ Stärke>=4 n {len(neg)} Ø brutto {neg['ret'].mean()*100:.2f} % | Verwässerung n {len(dil)} "
      f"Ø brutto {dil['ret'].mean()*100:.2f} %")
ok = ln["net"].mean() > 0 and tstat(ln["net"]) >= 2 and h1["net"].mean() > 0 and h2["net"].mean() > 0 and diff_t >= 2
print("->", "BESTANDEN" if ok else "NICHT BESTANDEN")

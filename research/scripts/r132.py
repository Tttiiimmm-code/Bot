"""Runde 132: Wikipedia-Aufmerksamkeit bei starken Tagesgewinnern -- Vorab: PROTOCOL.md."""
import itertools
import json
import math
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path.cwd()))
from tradingbot.research.universe import load_daily_panel  # noqa: E402

CACHE = Path("data_cache/wiki")
UA = {"User-Agent": "tradingbot-research/1.0 (private research)"}
PERIODS = {"Entdeckung": ("2016-01-01", "2020-12-31"), "Bestätigung": ("2021-01-01", "2026-09-30")}


def tstat(x):
    x = np.asarray(x, float)
    return float(x.mean() / x.std(ddof=1) * math.sqrt(len(x))) if len(x) > 2 and x.std() > 0 else float("nan")


def views(article: str) -> pd.Series:
    f = CACHE / "views" / (urllib.parse.quote(article, safe="") + ".json")
    if not f.exists():
        url = ("https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/en.wikipedia/all-access/user/"
               f"{urllib.parse.quote(article, safe='')}/daily/20151101/20261001")
        items = None
        for attempt in range(8):        # 429 (zu viele Anfragen): warten und erneut versuchen, nie leer cachen
            try:
                items = json.load(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60))["items"]
                break
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    items = []
                    break
                time.sleep(min(60, 2 ** attempt))
            except Exception:
                time.sleep(min(60, 2 ** attempt))
        if items is None:
            raise RuntimeError(f"Aufrufe für {article} nicht abrufbar")
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps({i["timestamp"][:8]: i["views"] for i in items}))
        time.sleep(0.6)
    d = json.loads(f.read_text())
    return pd.Series(d, dtype=float).rename(lambda k: pd.Timestamp(k))


def main():
    t0 = time.time()
    m = json.loads((CACHE / "ticker_article.json").read_text())
    panel = load_daily_panel()
    c, o, v = (panel[k].unstack("symbol") for k in ("close", "open", "volume"))
    for w in (c, o, v):
        w.index = pd.DatetimeIndex(w.index)
    spy_c, spy_o = c["SPY"], o["SPY"]
    ret = c / c.shift(1) - 1
    ok = (c > 5) & (c * v > 1e6) & ret.notna()
    syms = [s for s in c.columns if s in m]
    ev = []
    for s in syms:
        idx = np.flatnonzero((ok[s] & (ret[s] >= 0.10)).to_numpy())
        for i in idx:
            ev.append((s, i, float(ret[s].iloc[i])))
    print(f"{len(ev)} Gewinner-Ereignisse (>= 10 %) bei {len({e[0] for e in ev})} Aktien mit Artikel", flush=True)
    rows = []
    vc = {}
    for k, (s, i, r) in enumerate(ev):
        if s not in vc:
            vc[s] = views(m[s])
            if len(vc) % 200 == 0:
                print(f"  Aufrufe geladen: {len(vc)} Artikel ({time.time() - t0:.0f} s)", flush=True)
        pv = vc[s]
        d = c.index[i]
        if d not in pv.index:
            continue
        prev = pv[(pv.index >= d - pd.Timedelta(days=28)) & (pv.index < d)]
        if len(prev) < 20 or prev.mean() <= 0:
            continue
        ratio = pv[d] / prev.mean()
        out = {"sym": s, "day": d, "gain": r, "ratio": ratio}
        for h in (5, 20):
            if i + h < len(c) and not np.isnan(o[s].iloc[i + 1]) and not np.isnan(c[s].iloc[i + h]):
                stock = c[s].iloc[i + h] / o[s].iloc[i + 1] - 1
                mkt = spy_c.iloc[i + h] / spy_o.iloc[i + 1] - 1
                out[f"x{h}"] = stock - mkt
        rows.append(out)
    df = pd.DataFrame(rows)
    df.to_pickle(CACHE / "r132_events.pkl")
    print(f"{len(df)} Ereignisse mit Aufrufdaten; Aufmerksamkeit hoch (>= 3): {(df.ratio >= 3).sum()}, "
          f"niedrig (<= 1,5): {(df.ratio <= 1.5).sum()}", flush=True)

    res = []
    for thr, h in itertools.product((0.10, 0.20), (5, 20)):
        x = df[(df.gain >= thr) & df[f"x{h}"].notna()].copy()
        x["grp"] = np.where(x.ratio >= 3, "hoch", np.where(x.ratio <= 1.5, "niedrig", ""))
        for per, (a, b) in PERIODS.items():
            y = x[(x.day >= a) & (x.day <= b)]
            g = y[y.grp != ""].groupby(["day", "grp"])[f"x{h}"].mean().unstack()
            diff = (g["hoch"] - g["niedrig"]).dropna() if {"hoch", "niedrig"} <= set(g.columns) else pd.Series(dtype=float)
            hi, lo = y[y.grp == "hoch"][f"x{h}"], y[y.grp == "niedrig"][f"x{h}"]
            res.append(dict(thr=thr, h=h, per=per, tage=len(diff), diff=diff.mean(), t=tstat(diff),
                            n_hoch=len(hi), hoch=hi.mean(), n_niedrig=len(lo), niedrig=lo.mean(),
                            t_niedrig=tstat(lo)))
    r = pd.DataFrame(res)
    r.to_csv(Path(__file__).with_name("r132_results.csv"), index=False)
    pd.set_option("display.width", 220)
    print(r.to_string(index=False, float_format=lambda v: f"{v:+.4f}"))
    d0 = r[r.per == "Entdeckung"]
    sel = d0[(d0["diff"] < 0) & (d0["t"] <= -2.5)]
    print(f"\n--- Zählend (Entdeckung Differenz < 0, t <= -2,5): {len(sel)}")
    for _, s in sel.iterrows():
        b = r[(r.thr == s.thr) & (r.h == s.h) & (r.per == "Bestätigung")].iloc[0]
        ok = b["diff"] < 0 and b["t"] <= -2
        print(f"  >= {s.thr:.0%}, {s.h} T: Entdeckung {s['diff']:+.2%} (t {s.t:.2f}) -> Bestätigung {b['diff']:+.2%} "
              f"(t {b.t:.2f}) -> {'BESTANDEN' if ok else 'nicht bestanden'}")
    if sel.empty:
        print("  keine -> RUNDE NICHT BESTANDEN")
    print(f"Laufzeit {time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()

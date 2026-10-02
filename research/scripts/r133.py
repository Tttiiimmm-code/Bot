"""Runde 133: Copilot-Annahme "nur über VWAP kaufen" -- Vorab: PROTOCOL.md."""
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path.cwd()))
from tradingbot.orb_scanner import only_common_stock  # noqa: E402
from tradingbot.research.universe import load_intraday_month  # noqa: E402

CHECKS = {"12:00": 150, "13:30": 240, "15:00": 330}
END = 385                                   # 15:55 ET
PERIODS = {"Training": ("2016-01-01", "2019-12-31"), "Bestätigung": ("2020-01-01", "2022-12-31"),
           "Endtest": ("2023-01-01", "2026-12-31")}


def tstat(x):
    x = np.asarray(x, float)
    return float(x.mean() / x.std(ddof=1) * math.sqrt(len(x))) if len(x) > 2 and x.std() > 0 else float("nan")


def main():
    assets = pd.read_pickle("data_cache/universe/assets.pkl")
    allowed = set(only_common_stock(sorted(set(assets["symbol"].str.replace(r"_DELISTED$", "", regex=True))), assets))
    rows = []
    for f in sorted(Path("data_cache/universe/intraday").glob("*.pkl")):
        y, m = map(int, f.stem.split("-"))
        df = load_intraday_month(y, m)
        if df.empty:
            continue
        df = df[df.index.get_level_values("symbol").isin(allowed)]
        ts = df.index.get_level_values("timestamp").tz_convert("America/New_York")
        df = df.assign(day=ts.normalize().tz_localize(None), minute=ts.hour * 60 + ts.minute - 570)
        df = df[(df.minute >= 0) & (df.minute < 390)]
        for (sym, day), g in df.groupby([df.index.get_level_values("symbol"), "day"], sort=False):
            g = g.set_index("minute").sort_index()
            if 0 not in g.index:
                continue
            o, h, l, c, v = (g[k].to_numpy(float) for k in ("open", "high", "low", "close", "volume"))
            mins = g.index.to_numpy()
            cum_pv, cum_v = np.cumsum((h + l + c) / 3 * v), np.cumsum(v)
            open0 = o[0]
            for name, T in CHECKS.items():
                prev = np.flatnonzero(mins < T)
                at = np.flatnonzero(mins >= T)
                if not len(prev) or not len(at):
                    continue
                p, a = prev[-1], at[0]
                if mins[a] > T + 5 or cum_v[p] <= 0:
                    continue
                last = c[p]
                if last < 5 or last / open0 - 1 < 0.02:
                    continue
                vwap = cum_pv[p] / cum_v[p]
                entry = o[a]
                e60 = np.flatnonzero(mins <= T + 59)[-1]
                eend = np.flatnonzero(mins <= END)[-1]
                rows.append(dict(day=day, sym=sym, check=name, above=last >= vwap, dist=last / vwap - 1,
                                 r60=c[e60] / entry - 1, rend=c[eend] / entry - 1))
        print(f"{f.stem}: {len(rows)} Beobachtungen", flush=True)
    d = pd.DataFrame(rows)
    d.to_pickle(Path(__file__).with_name("r133_obs.pkl"))
    out = []
    for name in CHECKS:
        for hcol in ("r60", "rend"):
            for per, (a, b) in PERIODS.items():
                x = d[(d.check == name) & (d.day >= a) & (d.day <= b)]
                g = x.groupby(["day", "above"])[hcol].mean().unstack()
                diff = (g[True] - g[False]).dropna() if {True, False} <= set(g.columns) else pd.Series(dtype=float)
                up, dn = x[x.above][hcol], x[~x.above][hcol]
                out.append(dict(check=name, h="60 Min" if hcol == "r60" else "bis 15:55", per=per, tage=len(diff),
                                diff=diff.mean() * 100, t=tstat(diff), n_ueber=len(up), ueber=up.mean() * 100,
                                t_ueber=tstat(up), n_unter=len(dn), unter=dn.mean() * 100, t_unter=tstat(dn)))
    r = pd.DataFrame(out)
    r.to_csv(Path(__file__).with_name("r133_results.csv"), index=False)
    pd.set_option("display.width", 220)
    print(r.to_string(index=False, float_format=lambda v: f"{v:+.3f}"))
    tr = r[r.per == "Training"]
    sel = tr[tr["t"] >= 2.6].sort_values("t", ascending=False)
    print(f"\n--- Zählend (Training t >= 2,6): {len(sel)}")
    for _, s in sel.head(3).iterrows():
        b = r[(r.check == s.check) & (r.h == s.h) & (r.per == "Bestätigung")].iloc[0]
        e = r[(r.check == s.check) & (r.h == s.h) & (r.per == "Endtest")].iloc[0]
        ok = b["diff"] > 0 and b["t"] >= 2
        print(f"  {s.check} {s.h}: Training {s['diff']:+.3f} % (t {s['t']:.2f}) -> Bestätigung {b['diff']:+.3f} % "
              f"(t {b['t']:.2f})" + (f" -> Endtest {e['diff']:+.3f} % (t {e['t']:.2f})" if ok else " -> nicht bestanden"))
    if sel.empty:
        print("  keine -> Annahme NICHT BESTÄTIGT")


if __name__ == "__main__":
    main()

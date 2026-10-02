"""Runde 133b: Stop-Abstand 0,3 / 0,5 / 1 / 2 % bei Käufen zu den Copilot-Zeiten -- Vorab: PROTOCOL.md."""
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path.cwd()))
from tradingbot.orb_scanner import only_common_stock  # noqa: E402
from tradingbot.research.universe import load_intraday_month  # noqa: E402

CHECKS = (150, 240, 330)
END = 385
STOPS = (0.003, 0.005, 0.01, 0.02)
PERIODS = {"Training": ("2016-01-01", "2019-12-31"), "Bestätigung": ("2020-01-01", "2022-12-31"),
           "Endtest": ("2023-01-01", "2026-12-31")}


def tstat(x):
    x = np.asarray(x, float)
    return float(x.mean() / x.std(ddof=1) * math.sqrt(len(x))) if len(x) > 2 and x.std() > 0 else float("nan")


def trade(o, h, l, c, a, last, sd_pct):
    e = o[a]
    sd = e * sd_pct
    stop, tp = e - sd, e + 2 * sd
    for j in range(a, last + 1):
        if j > a and o[j] <= stop:
            x = o[j]; break
        if l[j] <= stop:
            x = stop; break
        if j > a and o[j] >= tp:
            x = o[j]; break
        if h[j] >= tp:
            x = tp; break
    else:
        x = c[last]
    cost = 2 * (0.0002 * e + 0.005)
    return (x - e - cost) / sd


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
            o, h, l, c = (g[k].to_numpy(float) for k in ("open", "high", "low", "close"))
            mins = g.index.to_numpy()
            for T in CHECKS:
                prev, at = np.flatnonzero(mins < T), np.flatnonzero(mins >= T)
                if not len(prev) or not len(at) or mins[at[0]] > T + 5:
                    continue
                p, a = prev[-1], at[0]
                if c[p] < 5 or c[p] / o[0] - 1 < 0.02:
                    continue
                last = np.flatnonzero(mins <= END)[-1]
                rows.append(dict(day=day, **{f"s{s}": trade(o, h, l, c, a, last, s) for s in STOPS}))
    d = pd.DataFrame(rows)
    print(f"{len(d)} Käufe")
    for per, (a, b) in PERIODS.items():
        x = d[(d.day >= a) & (d.day <= b)].groupby("day").mean()
        line = " | ".join(f"Stop {s:.1%}: Ø {x[f's{s}'].mean():+.3f} R (t {tstat(x[f's{s}']):+.2f})" for s in STOPS)
        diff = x["s0.003"] - x["s0.005"]
        print(f"{per}: {line} || 0,3 % minus 0,5 %: {diff.mean():+.3f} R (t {tstat(diff):+.2f})")


if __name__ == "__main__":
    main()

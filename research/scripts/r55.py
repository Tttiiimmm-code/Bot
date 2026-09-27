"""Runde 55: Aktien-Impuls -> FX-Nachzügler."""
from datetime import date, timedelta
from pathlib import Path
import numpy as np, pandas as pd
from tradingbot.research import gold

NY = "America/New_York"


def series_idx(name):
    parts = [gold.load_minutes(Path("data_cache/dukascopy/idx"), f"{name}_*.csv"),
             gold.load_minutes(Path("data_cache/dukascopy/unseen"), f"{name}_*.csv")]
    m = pd.concat(parts)
    s = m["open"]
    return s[~s.index.duplicated()].sort_index()


def series_fx(pair):
    s = pd.concat([gold.load_fx(pair), gold.load_fx(pair, Path("data_cache/dukascopy/unseen_fx"))])
    return s[~s.index.duplicated()].sort_index()


spx = series_idx("usa500idxusd")
fx = {p: series_fx(p) for p in ("eurusd", "gbpusd", "usdjpy")}


def at(s, d, hh, mm):
    return gold.price_at(s, pd.Timestamp(f"{d} {hh:02d}:{mm:02d}", tz=NY))


rows = []
d = date(2013, 10, 1)
while d <= date(2026, 9, 25):
    if d.weekday() < 5:
        prev = d - timedelta(days=3 if d.weekday() == 0 else 1)
        e0, e1 = at(spx, prev, 16, 0), at(spx, d, 3, 0)
        row = {"date": d, "eq": (e1 / e0 - 1) if e0 and e1 else np.nan}
        for p, s in fx.items():
            a, b, c = at(s, prev, 16, 0), at(s, d, 3, 0), at(s, d, 7, 0)
            row[f"{p}_w"] = (b / a - 1) if a and b else np.nan
            row[f"{p}_n"] = (c / b - 1) if b and c else np.nan
        rows.append(row)
    d += timedelta(days=1)
df = pd.DataFrame(rows).set_index("date")
df.to_pickle("data_cache/dukascopy/r55_windows.pkl")
sd = df["eq"].rolling(60, min_periods=40).std().shift(1)
out = {}
for p in fx:
    x, y = df["eq"], df[f"{p}_w"]
    cov = (x * y).rolling(250, min_periods=150).mean() - x.rolling(250, min_periods=150).mean() * y.rolling(250, min_periods=150).mean()
    var = x.rolling(250, min_periods=150).var(ddof=0)
    beta = (cov / var).shift(1)
    exp = beta * df["eq"]
    big = df["eq"].abs() > sd
    lag = (np.sign(exp) * df[f"{p}_w"]) < 0.5 * exp.abs()
    trade = big & lag & exp.notna() & df[f"{p}_n"].notna()
    out[p] = (np.sign(exp) * df[f"{p}_n"] - 2 * 0.00005).where(trade)
T = pd.DataFrame(out)
port = T.mean(axis=1).fillna(0.0)
ntr = T.notna().sum(axis=1)
P = {"Entdeckung": (date(2013, 10, 1), date(2018, 12, 31)), "Bestätigung": (date(2019, 1, 1), date(2025, 9, 19)),
     "unberührt": (date(2025, 9, 22), date(2026, 9, 25))}
res = {}
for name, (a, b) in P.items():
    x = port[(port.index >= a) & (port.index <= b)]
    tr = T[(T.index >= a) & (T.index <= b)].stack().dropna()
    t = x.mean() / x.std() * np.sqrt(len(x))
    res[name] = (t, x.mean())
    print(f"{name:11s} Tage {len(x):4d} Tage mit Trade {(ntr[(ntr.index >= a) & (ntr.index <= b)] > 0).sum():4d} Trades {len(tr):4d} "
          f"Ø je Trade {tr.mean() * 1e4:5.2f} bp Treffer {(tr > 0).mean():.0%} | Portfolio {x.mean() * 252:6.2%} p.a. t {t:5.2f}")
    for p in fx:
        q = T[p][(T.index >= a) & (T.index <= b)].dropna()
        print(f"     {p}: {len(q):4d} Trades Ø {q.mean() * 1e4:5.2f} bp")
ok = res["Entdeckung"][0] >= 2 and res["Bestätigung"][0] >= 2 and res["unberührt"][1] > 0
print("->", "BESTANDEN" if ok else "NICHT BESTANDEN")

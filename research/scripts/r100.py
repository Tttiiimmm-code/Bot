"""Runde 100: TikTok "The Quant Builder" -- erste 5-Minuten-Kerze vs. EMA12 (Vorab-Registrierung in PROTOCOL.md)."""
import numpy as np
import pandas as pd

from tradingbot.research import ml_rank as ml

COST = 2e-4
PERIODS = {"P1 2016-2018": ("2016-01-01", "2018-12-31"), "P2 2019-2025-09": ("2019-01-01", "2025-09-19"),
           "jüngst 2025-09..": ("2025-09-22", "2026-12-31")}


def daily_trades(sym: str) -> pd.DataFrame:
    m = pd.read_pickle(f"data_cache/{sym}_1min.pkl")
    m = m.between_time("09:30", "15:59")
    five = m.resample("5min", label="left", closed="left").agg(
        {"open": "first", "close": "last"}).dropna()
    five = five.between_time("09:30", "15:55")
    ema = five["close"].ewm(span=12, adjust=False).mean()
    rows = []
    for day, g in m.groupby(m.index.date):
        first = five[(five.index.date == day) & (five.index.time == pd.Timestamp("09:30").time())]
        if first.empty:
            continue
        t0 = first.index[0]
        sig = np.sign(first["close"].iloc[0] - ema.loc[t0])
        entry = g[g.index.time == pd.Timestamp("09:35").time()]
        exit_ = g[g.index.time == pd.Timestamp("15:59").time()]
        if sig == 0 or entry.empty or exit_.empty:
            continue
        r = exit_["close"].iloc[0] / entry["open"].iloc[0] - 1
        rows.append({"day": pd.Timestamp(day), "sig": sig, "ret": sig * r - COST})
    return pd.DataFrame(rows).set_index("day")


def report(label: str, x: pd.Series) -> None:
    parts = [f"{label:22s}"]
    for pname, (a, b) in PERIODS.items():
        y = x[(x.index >= a) & (x.index <= b)]
        pf = y[y > 0].sum() / -y[y < 0].sum() if (y < 0).any() else float("nan")
        parts.append(f"{pname}: n {len(y)}, Ø {y.mean() * 1e4:+.1f} bp (t {ml.t_stat(y):+.2f}, "
                     f"Treffer {(y > 0).mean():.0%}, PF {pf:.2f})")
    print(" | ".join(parts), flush=True)


res = {}
for sym in ("QQQ", "SPY", "IWM", "DIA"):
    t = daily_trades(sym)
    res[sym] = t
    tag = "PRIMÄR " if sym == "QQQ" else ""
    report(f"{tag}{sym} long+short", t["ret"])
q = res["QQQ"]
report("QQQ nur long", q.loc[q["sig"] > 0, "ret"])
report("QQQ nur short", q.loc[q["sig"] < 0, "ret"])
yr = q["ret"].groupby(q.index.year).sum() * 100
print("QQQ Summe % je Jahr (ohne Zinseszins):", " ".join(f"{k}: {v:+.1f}" for k, v in yr.items()))
p1 = q["ret"][(q.index >= "2016-01-01") & (q.index <= "2018-12-31")]
p2 = q["ret"][(q.index >= "2019-01-01") & (q.index <= "2025-09-19")]
ok = ml.t_stat(p1) >= 2 and p2.mean() > 0
print(f"Kriterien: t P1 {ml.t_stat(p1):+.2f} (>=2), Ø P2 {p2.mean() * 1e4:+.1f} bp (>0) -> "
      f"{'BESTANDEN' if ok else 'NICHT BESTANDEN'}")

"""Runde 138: Gold-Ausbruch (Runde 134, eingefroren) auf 13 anderen Märkten, H1 Geld/Brief -- Vorab: PROTOCOL.md."""
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from r102 import load  # noqa: E402  (H1 Geld/Brief, Dukascopy)
from r134 import sim  # noqa: E402

MARKETS = ("xagusd", "eurusd", "gbpusd", "usdjpy", "usdchf", "usdcnh", "audusd", "nzdusd", "usdsek", "gbpjpy",
           "eurjpy", "chfjpy", "usatechidxusd")
START, END = "2012-07-01", "2026-09-30"


def tstat(x):
    x = np.asarray(x, float)
    return float(x.mean() / x.std(ddof=1) * math.sqrt(len(x))) if len(x) > 2 and x.std() > 0 else float("nan")


def run_market(sym, rate):
    bid, ask = load(sym)
    bid, ask = bid[START:END], ask[START:END]
    t = bid.index
    pc = bid["close"].shift(1)
    tr = np.maximum(bid["high"] - bid["low"], np.maximum((bid["high"] - pc).abs(), (bid["low"] - pc).abs()))
    atr = tr.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean().to_numpy()
    n = len(t)
    wd, hr = t.weekday.to_numpy(), t.hour.to_numpy()
    fri_stop = (wd == 4) & (hr >= 20)
    fri_cancel = (wd == 4) & (hr >= 21)
    arrs = [bid[c].to_numpy(np.float64) for c in ("open", "high", "low", "close")] + \
           [ask[c].to_numpy(np.float64) for c in ("open", "high", "low", "close")]
    ei, r, xi, q = sim(np.arange(n, dtype=np.int64), bid["high"].to_numpy(np.float64), bid["low"].to_numpy(np.float64),
                       atr, *arrs, fri_stop, fri_cancel, 48, 12, 2.0, 4.0, False, True)
    tin, tout = t[ei], t[xi]
    hold = np.asarray((tout - tin).total_seconds()) / 86400
    rr = rate.reindex(tin.tz_localize(None), method="ffill").fillna(rate.iloc[-1]).to_numpy() + 0.025
    net = r - rr * hold / 365 / q
    s = pd.Series(net, index=tin.tz_localize(None).normalize())
    yrs = (t[-1] - t[0]).days / 365.25
    eq = (1 + 0.01 * s).prod()
    hold_ret = bid["close"].iloc[-1] / bid["close"].iloc[0] - 1
    return s, {"n": len(s), "avg": s.mean(), "t": tstat(s.groupby(level=0).sum()),
               "cagr": eq ** (1 / yrs) - 1, "halten": (1 + hold_ret) ** (1 / yrs) - 1, "raw_avg": r.mean()}


def main():
    rate = pd.read_pickle(r"C:\Users\Nutzer\Bot\data_cache\fred\IR3TIB01USM156N.pkl")
    rate = ((rate.iloc[:, 0] if hasattr(rate, "columns") else rate) / 100)
    rate.index = pd.to_datetime(rate.index)
    rate = rate.sort_index()
    xs, xst = run_market("xauusd", rate)
    print(f"Prüfung H1-Näherung XAUUSD 2012-07..2026-09: n {xst['n']}, Ø {xst['avg']:+.3f} R netto (brutto "
          f"{xst['raw_avg']:+.3f}), t {xst['t']:.2f}, {xst['cagr']:+.1%} p.a. bei 1 % Risiko (M1-Backtest Runde 134 "
          f"nach Swap 2008-2026: Ø +0,165 R)")
    allp, rows = [], []
    for m in MARKETS:
        s, st = run_market(m, rate)
        allp.append(s)
        rows.append((m, st))
        print(f"{m:14s} n {st['n']:5d}  Ø {st['avg']:+.3f} R  t {st['t']:+.2f}  Bot {st['cagr']:+6.1%} p.a.  "
              f"Markt halten {st['halten']:+6.1%} p.a.", flush=True)
    pooled = pd.concat(allp).groupby(level=0).sum()
    allr = pd.concat(allp)
    t_ = tstat(pooled)
    print(f"\nGEPOOLT 13 Märkte: Trades {len(allr)}, Ø {allr.mean():+.3f} R, t(Tage) {t_:+.2f} -> "
          f"{'BESTANDEN' if allr.mean() > 0 and t_ >= 2 else 'NICHT BESTANDEN'}")
    print(f"Märkte mit Ø > 0: {sum(st['avg'] > 0 for _, st in rows)} von {len(rows)}")


if __name__ == "__main__":
    main()

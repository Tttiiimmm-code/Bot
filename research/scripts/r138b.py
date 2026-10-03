"""Runde 138b: Gold-Ausbruch (Runde 134, eingefroren) mit M1 Geld/Brief auf 9 Märkten -- Vorab: PROTOCOL.md."""
import gc
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from r134 import h1_features, sim  # noqa: E402

D = Path(r"C:\Users\Nutzer\Bot\data_cache\dukascopy")
DT = {"timestamp": "int64", "open": "float32", "high": "float32", "low": "float32", "close": "float32"}
START = pd.Timestamp("2012-07-01", tz="UTC")
END = pd.Timestamp("2026-09-26", tz="UTC")


def files(sym, side):
    if sym in ("eurusd", "gbpusd", "usdjpy"):
        if side == "bid":
            return sorted((D / "fx").glob(f"{sym}_20*.csv")) + [D / "unseen_fx" / f"{sym}_2026.csv"]
        return sorted((D / "fx_ask").glob(f"{sym}_20*.csv"))
    return sorted((D / "luna").glob(f"{sym}_{side}_20*.csv"))


def load(sym):
    bid = pd.concat(pd.read_csv(f, dtype=DT) for f in files(sym, "bid")).drop_duplicates("timestamp").set_index("timestamp")
    ask = pd.concat(pd.read_csv(f, dtype=DT) for f in files(sym, "ask")).drop_duplicates("timestamp").set_index("timestamp")
    idx = bid.index.intersection(ask.index)
    bid, ask = bid.loc[idx].sort_index(), ask.loc[idx].sort_index()
    t = pd.to_datetime(bid.index.to_numpy(), unit="ms", utc=True)
    keep = (ask["close"].to_numpy() >= bid["close"].to_numpy()) & ~((t.weekday == 5) | ((t.weekday == 6) & (t.hour < 22)))
    keep &= ~((bid["high"] == bid["low"]).to_numpy() & (bid["open"] == bid["close"]).to_numpy())
    keep &= (t >= START) & (t < END)
    return t[keep], bid[keep], ask[keep]


def tstat(x):
    x = np.asarray(x, float)
    return float(x.mean() / x.std(ddof=1) * math.sqrt(len(x))) if len(x) > 2 and x.std() > 0 else float("nan")


def main():
    rate = pd.read_pickle(r"C:\Users\Nutzer\Bot\data_cache\fred\IR3TIB01USM156N.pkl")
    rate = ((rate.iloc[:, 0] if hasattr(rate, "columns") else rate) / 100)
    rate.index = pd.to_datetime(rate.index)
    rate = rate.sort_index()
    allp = []
    for sym in ("eurusd", "gbpusd", "usdjpy", "euraud", "gbpaud", "audcad", "audusd", "nzdcad", "audnzd"):
        t, bid, ask = load(sym)
        h, hh, hl, atr = h1_features(t, bid)
        arrs = [bid[c].to_numpy(np.float64) for c in ("open", "high", "low", "close")] + \
               [ask[c].to_numpy(np.float64) for c in ("open", "high", "low", "close")]
        wd, hr, mi = t.weekday.to_numpy(), t.hour.to_numpy(), t.minute.to_numpy()
        ei, r, xi, q = sim(h, hh, hl, atr, *arrs, (wd == 4) & (hr >= 20),
                           (wd == 4) & ((hr > 20) | ((hr == 20) & (mi >= 55))), 48, 12, 2.0, 4.0, False, True)
        tin, tout = t[ei], t[xi]
        hold = np.asarray((tout - tin).total_seconds()) / 86400
        rr = rate.reindex(tin.tz_localize(None), method="ffill").fillna(rate.iloc[-1]).to_numpy() + 0.025
        net = r - rr * hold / 365 / q
        s = pd.Series(net, index=tin.tz_localize(None).normalize())
        allp.append(s)
        yrs = (t[-1] - t[0]).days / 365.25
        c = bid["close"].to_numpy()
        print(f"{sym}: {t[0]:%Y-%m}..{t[-1]:%Y-%m}  n {len(s):5d}  Ø {s.mean():+.3f} R (brutto {r.mean():+.3f})  "
              f"t {tstat(s.groupby(level=0).sum()):+.2f}  Bot {(1 + 0.01 * s).prod() ** (1 / yrs) - 1:+6.1%} p.a.  "
              f"Kurs {(c[-1] / c[0]) ** (1 / yrs) - 1:+6.1%} p.a.", flush=True)
        del t, bid, ask, arrs
        gc.collect()
    allr = pd.concat(allp)
    pooled = allr.groupby(level=0).sum()
    t_ = tstat(pooled)
    print(f"\nGEPOOLT 9 Märkte: Trades {len(allr)}, Ø {allr.mean():+.3f} R, t(Tage) {t_:+.2f} -> "
          f"{'BESTANDEN' if allr.mean() > 0 and t_ >= 2 else 'NICHT BESTANDEN'}")


if __name__ == "__main__":
    main()

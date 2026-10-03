"""Runde 139: Gold-Ausbruch (Runde 134, eingefroren) auf Silber, M1 Geld/Brief -- Vorab: PROTOCOL.md."""
import math
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, r"C:\Users\Nutzer\Bot")
from r134 import h1_features, sim  # noqa: E402
from r138b import load  # noqa: E402  (Dateien aus data_cache/dukascopy/luna, gleiche Filter)

PERIODS = {"2012-07..2016": ("2012-07-01", "2016-12-31"), "2017-2022": ("2017-01-01", "2022-12-31"),
           "2023-2026-09": ("2023-01-01", "2026-09-25")}


def tstat(x):
    x = np.asarray(x, float)
    return float(x.mean() / x.std(ddof=1) * math.sqrt(len(x))) if len(x) > 2 and x.std() > 0 else float("nan")


def cagr(series):
    yrs = (series.index[-1] - series.index[0]).days / 365.25
    return (series.iloc[-1] / series.iloc[0]) ** (1 / yrs) - 1


def main():
    from tradingbot.forward_test import fetch_daily_yahoo
    rate = pd.read_pickle(r"C:\Users\Nutzer\Bot\data_cache\fred\IR3TIB01USM156N.pkl")
    rate = ((rate.iloc[:, 0] if hasattr(rate, "columns") else rate) / 100)
    rate.index = pd.to_datetime(rate.index)
    rate = rate.sort_index()
    t, bid, ask = load("xagusd")
    h, hh, hl, atr = h1_features(t, bid)
    arrs = [bid[c].to_numpy(np.float64) for c in ("open", "high", "low", "close")] + \
           [ask[c].to_numpy(np.float64) for c in ("open", "high", "low", "close")]
    wd, hr, mi = t.weekday.to_numpy(), t.hour.to_numpy(), t.minute.to_numpy()
    ei, r, xi, q = sim(h, hh, hl, atr, *arrs, (wd == 4) & (hr >= 20),
                       (wd == 4) & ((hr > 20) | ((hr == 20) & (mi >= 55))), 48, 12, 2.0, 4.0, False, True)
    tin, tout = t[ei], t[xi]
    hold = np.asarray((tout - tin).total_seconds()) / 86400
    rr = rate.reindex(tin.tz_localize(None), method="ffill").fillna(rate.iloc[-1]).to_numpy() + 0.025
    net = pd.Series(r - rr * hold / 365 / q, index=tin.tz_localize(None).normalize())
    days = net.groupby(level=0).sum()
    spy = fetch_daily_yahoo("SPY", date(2012, 6, 1), date(2026, 10, 1))
    spy.index = pd.to_datetime(spy.index)
    silver = pd.Series(bid["close"].to_numpy(), index=t.tz_localize(None)).resample("D").last().dropna()
    passed = net.mean() > 0 and tstat(days) >= 2
    print(f"XAGUSD {t[0]:%Y-%m}..{t[-1]:%Y-%m}: Trades {len(net)}, Ø {net.mean():+.3f} R netto (brutto {r.mean():+.3f}), "
          f"t(Tage) {tstat(days):+.2f} -> {'BESTANDEN' if passed else 'NICHT BESTANDEN'}")
    for name, (a, b) in PERIODS.items():
        x = net[a:b]
        eq = (1 + 0.01 * x).cumprod()
        yrs = (pd.Timestamp(b) - pd.Timestamp(a)).days / 365.25
        bot = eq.iloc[-1] ** (1 / yrs) - 1 if len(x) else float("nan")
        print(f"  {name}: n {len(x)}, Ø {x.mean():+.3f} R, t {tstat(x.groupby(level=0).sum()):+.2f}, "
              f"Bot {bot:+.1%} p.a. (1 % Risiko) | Silber halten {cagr(silver[a:b]):+.1%} | S&P 500 {cagr(spy[a:b]):+.1%}")


if __name__ == "__main__":
    main()

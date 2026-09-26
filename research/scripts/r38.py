"""Runde 38: gehebelte Indexfonds mit SMA200-Filter."""
from datetime import date
import numpy as np, pandas as pd
from tradingbot.research import anomalies, history, swing
from tradingbot.research.__main__ import _log_trial
from tradingbot.research.engine import CostModel, BacktestResult
from tradingbot.research.metrics import compute_metrics

def long_history(sym):
    import json, urllib.parse, urllib.request
    from pathlib import Path
    path = Path("data_cache/yahoo_long") / f"{sym}.pkl"
    if path.exists():
        return pd.read_pickle(path)
    u = (f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(sym)}"
         f"?period1=-1325376000&period2=1758326400&interval=1d")
    res = json.load(urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"}), timeout=60))["chart"]["result"][0]
    idx = pd.to_datetime(res["timestamp"], unit="s", utc=True).tz_convert("America/New_York").date
    s = pd.Series(res["indicators"]["quote"][0]["close"], index=idx, dtype=float).dropna()
    s = s[~s.index.duplicated(keep="last")]
    path.parent.mkdir(parents=True, exist_ok=True)
    s.to_pickle(path)
    return s


tb = anomalies.fetch_fred("TB3MS") / 100
fams = {"BN": ("^GSPC", (date(1934, 1, 1), date(1979, 12, 31)), (date(1980, 1, 1), date(2025, 9, 19))),
        "BO": ("^NDX", (date(1986, 1, 1), date(2005, 12, 31)), (date(2006, 1, 1), date(2025, 9, 19)))}
table = {}
for fam, (sym, disc, conf) in fams.items():
    px = long_history(sym)
    px = px[px.index <= date(2025, 9, 19)]
    r = px.pct_change().fillna(0.0)
    ym = pd.PeriodIndex([pd.Timestamp(d) for d in px.index], freq="M").to_timestamp()
    rf = pd.Series(tb.reindex(ym, method="ffill").to_numpy(), index=px.index).ffill().fillna(0.0) / 252
    sig = (px > px.rolling(200).mean()).astype(float).shift(1).fillna(0.0)
    switch = sig.diff().abs().fillna(0.0)
    for L in (2, 3):
        lev = L * r - (L - 1) * (rf + 0.005 / 252) - 0.006 / 252
        strat = sig * lev + (1 - sig) * rf - 0.001 * switch
        label = f"{fam} {sym} {L}x SMA200"
        row = {}
        for name, (a, b) in (("Entdeckung", disc), ("Bestätigung", conf)):
            m_ = (strat.index >= a) & (strat.index <= b)
            s, h, nf = strat[m_], r[m_], lev[m_]
            ms, mh, mn = (compute_metrics(BacktestResult("x", x)) for x in (s, h, nf))
            al, t, beta = swing.alpha_vs_benchmark(s, h)
            row[name] = t
            print(f"{label:22s} {name:11s} CAGR {ms.cagr:6.1%} Sharpe {ms.sharpe:4.2f} MaxDD {ms.max_drawdown:6.1%} | "
                  f"Halten {mh.cagr:6.1%} {mh.sharpe:4.2f} {mh.max_drawdown:6.1%} | {L}x ohne Filter {mn.cagr:6.1%} "
                  f"{mn.max_drawdown:6.1%} | Alpha {al:6.1%} t {t:5.2f} beta {beta:4.2f} investiert {sig[m_].mean():.0%}")
            if name == "Entdeckung":
                _log_trial("letf_trend", sym, {"L": L, "sma": 200}, CostModel(slippage_bps=10.0), float(L), BacktestResult(label, s))
        table[label] = row
for fam in fams:
    ls = [k for k in table if k.startswith(fam)]
    best = max(ls, key=lambda k: table[k]["Entdeckung"])
    ok = table[best]["Entdeckung"] >= 2.24 and table[best]["Bestätigung"] >= 2
    print(f"Familie {fam}: {best} {table[best]} -> {'BESTANDEN' if ok else 'NICHT BESTANDEN'}")

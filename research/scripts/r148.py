"""Runde 148: etablierte Memecoins mit Rug-Pull-Filter -- Vorab: PROTOCOL.md."""
import math
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, r"C:\Users\Nutzer\Bot")
from tradingbot.forward_test import fetch_daily_yahoo  # noqa: E402

C = Path(r"C:\Users\Nutzer\Bot\data_cache\crypto")
MEMES = ["1000CAT", "1000CHEEMS", "1MBABYDOGE", "ACT", "BANANAS31", "BOME", "BONK", "DOGE", "DOGS", "FLOKI", "GIGGLE",
         "MEME", "MUBARAK", "NEIRO", "NOT", "PENGU", "PEOPLE", "PEPE", "PNUT", "SHIB", "TRUMP", "TST", "TURBO", "TUT", "WIF"]
COST = 0.001
INFO, MAIN = ("2020-07-01", "2022-12-31"), ("2023-01-01", "2026-09-25")


def load(sym):
    d = pd.read_pickle(C / f"{sym}USDT.pkl")
    d.index = pd.to_datetime(d.index)
    return d


def simulate(weights_fn, rets, days):
    """weights_fn(i) -> Zielgewichte (Series) für Tag i oder None (= alte Gewichte driften lassen)."""
    w = pd.Series(0.0, index=rets.columns)
    out = []
    for i, d in enumerate(days):
        tgt = weights_fn(i)
        cost = 0.0
        if tgt is not None:
            cost = COST * float((tgt - w).abs().sum())
            w = tgt.copy()
        r = rets.loc[d].fillna(0.0)
        gross = float((w * r).sum())
        out.append(gross - cost)
        total = 1 + gross
        w = w * (1 + r) / total if total > 0 else w * 0
    return pd.Series(out, index=days)


def stats(port, spy, a, b):
    e = (1 + port[a:b]).cumprod()
    yrs = (e.index[-1] - e.index[0]).days / 365.25
    cagr = e.iloc[-1] ** (1 / yrs) - 1
    s = spy[a:b]
    cs = (s.iloc[-1] / s.iloc[0]) ** (1 / yrs) - 1
    m = e.resample("ME").last().pct_change().fillna(e.resample("ME").last().iloc[0] - 1)
    ms = s.resample("ME").last().pct_change().dropna()
    ex = (m - ms).dropna()
    t = ex.mean() / ex.std(ddof=1) * math.sqrt(len(ex))
    return cagr, cs, (e / e.cummax() - 1).min(), t


def main():
    data = {m: load(m) for m in MEMES}
    btc = load("BTC")["close"]
    days = pd.date_range("2020-01-01", "2026-09-25", freq="D")
    close = pd.DataFrame({m: d["close"] for m, d in data.items()}).reindex(days)
    qv = pd.DataFrame({m: d["quote_volume"] for m, d in data.items()}).reindex(days)
    first = {m: d.index[0] for m, d in data.items()}
    rets = close.pct_change(fill_method=None)
    age_ok = pd.DataFrame({m: days - first[m] >= pd.Timedelta(days=365) for m in MEMES}, index=days)
    elig = (age_ok & (qv.rolling(30, min_periods=30).mean() >= 20e6) & close.notna()).shift(1, fill_value=False)

    def eq_weights(i):
        e = elig.iloc[i]
        n = int(e.sum())
        return (e.astype(float) / n) if n else pd.Series(0.0, index=MEMES)

    def a_fn(i):
        return eq_weights(i) if i == 0 or days[i].month != days[i - 1].month else None
    a = simulate(a_fn, rets, days)
    idx = (1 + simulate(lambda i: eq_weights(i), rets, days) + 0).cumprod()   # Korb-Index (täglich gleichgewichtet)
    on = (idx > idx.rolling(50).mean()).shift(1, fill_value=False)
    state = {"on": None}

    def b_fn(i):
        flag = bool(on.iloc[i])
        new_month = i == 0 or days[i].month != days[i - 1].month
        if flag != state["on"] or (flag and new_month):
            state["on"] = flag
            return eq_weights(i) if flag else pd.Series(0.0, index=MEMES)
        return None
    b = simulate(b_fn, rets, days)
    mom = close.pct_change(28, fill_method=None).shift(1)

    def c_fn(i):
        if days[i].weekday() != 0 and i != 0:
            return None
        sc = mom.iloc[i].where(elig.iloc[i]).dropna()
        sc = sc[sc > 0].nlargest(3)
        w = pd.Series(0.0, index=MEMES)
        if len(sc):
            w[sc.index] = 1 / 3
        return w
    c = simulate(c_fn, rets, days)
    spy = fetch_daily_yahoo("SPY", date(2019, 12, 1), date(2026, 9, 26))
    spy.index = pd.to_datetime(spy.index)
    btc_r = btc.reindex(days).pct_change(fill_method=None).fillna(0)
    print("Zulässige Coins je Jahr (Ø Anzahl):", elig.resample("YE").mean().sum(axis=1).round(1).to_dict(), "\n")
    print("HAUPTERGEBNIS (K=3: 2023-26 > SPY, t >= 2,4; 2020-22 > 0)")
    for name, p in (("A Korb monatlich", a), ("B Korb + Trendfilter", b), ("C Rotation Top 3", c), ("BTC halten", btc_r)):
        res = []
        for lab, (x, y) in (("2020-22", INFO), ("2023-26", MAIN)):
            cg, cs, dd, t = stats(p, spy, x, y)
            res.append((cg, cs, t))
            print(f"  {name:22s} {lab}: {cg:+7.1%} vs SPY {cs:+6.1%}  MaxDD {dd:6.1%}  t {t:+.2f}")
        if name != "BTC halten":
            ok = res[1][0] > res[1][1] and res[1][2] >= 2.4 and res[0][0] > res[0][1]
            print(f"  -> {name}: {'BESTANDEN' if ok else 'nicht bestanden'}")
    print("\nInvestiert-Anteil B:", f"{on['2023':].mean():.0%}", " Kalenderjahre A / B / C / BTC / SPY:")
    for y in range(2021, 2027):
        f = lambda p: (1 + p[str(y)]).prod() - 1
        sy = spy[str(y)]
        print(f"  {y}: {f(a):+7.1%} / {f(b):+7.1%} / {f(c):+7.1%} / {f(btc_r):+7.1%} / {sy.iloc[-1] / spy[:str(y - 1)].iloc[-1] - 1:+6.1%}")
    print("\nAbsturz je Coin (ab erster Zulässigkeit, größter Verlust vom Hoch, heute vs Hoch):")
    for m in MEMES:
        e = elig[m]
        if not e.any():
            print(f"  {m:11s} nie zulässig (zu jung oder zu wenig Umsatz)")
            continue
        p = close[m][e.idxmax():].dropna()
        print(f"  {m:11s} ab {e.idxmax():%Y-%m}: MaxDD {(p / p.cummax() - 1).min():6.1%}, heute {p.iloc[-1] / p.max() - 1:6.1%} vom Hoch")


if __name__ == "__main__":
    main()

"""Runde 141: Kongress-Käufe ab Meldedatum nachhandeln -- Vorab: PROTOCOL.md."""
import math
import pickle
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, r"C:\Users\Nutzer\Bot")
from tradingbot.forward_test import fetch_daily_yahoo  # noqa: E402

D = Path(r"C:\Users\Nutzer\Bot\data_cache\congress")
PX = D / "px"
PX.mkdir(exist_ok=True)
COST = 0.001
MAIN, PRE = ("2022-01-01", "2026-09-30"), ("2015-01-01", "2021-12-31")
# House-Parteiführung (Speaker, Mehrheits-/Minderheitsführer, Whips, Assistant Leader/Speaker), ohne Pelosi
LEADERS = [("Boehner", "", "2015-01-01", "2015-10-29"), ("Ryan", "Paul", "2015-10-29", "2019-01-03"),
           ("McCarthy", "Kevin", "2015-01-01", "2023-10-03"), ("Johnson", "Mike", "2023-10-25", "2026-12-31"),
           ("Scalise", "", "2015-01-01", "2026-12-31"), ("Hoyer", "", "2015-01-01", "2023-01-03"),
           ("Clyburn", "", "2015-01-01", "2025-01-03"), ("Jeffries", "", "2023-01-03", "2026-12-31"),
           ("Emmer", "", "2023-01-03", "2026-12-31"), ("Clark", "Katherine", "2021-01-03", "2026-12-31")]


def price(tick):
    f = PX / f"{tick}.pkl"
    if f.exists():
        return pickle.loads(f.read_bytes())
    try:
        s = fetch_daily_yahoo(tick, date(2014, 6, 1), date(2026, 10, 3))
        s.index = pd.to_datetime(s.index)
    except Exception:  # noqa: BLE001
        s = None
    f.write_bytes(pickle.dumps(s))
    return s


def is_leader(r):
    for last, first, a, b in LEADERS:
        if r["last"] == last and first.lower() in str(r["first"]).lower() and a <= str(r["filing_date"]) < b:
            return True
    return False


def backtest(sig, spy, hold=252, weight=None):
    """sig: DataFrame mit ticker, filing_date (+ weight). Rückgabe Kurve, Anzahl genutzt/fehlend."""
    days = spy.index
    num = pd.Series(0.0, index=days)
    den = pd.Series(0.0, index=days)
    used = miss = 0
    for r in sig.itertuples():
        i = days.searchsorted(pd.Timestamp(r.filing_date), side="right") + 1   # 2. Handelstag nach Meldung
        if i >= len(days) - 1:
            continue
        p = price(r.ticker)
        if p is None or p.index[0] > days[i] or p.index[-1] < days[i]:
            miss += 1
            continue
        p = p.reindex(days[i:min(i + hold, len(days) - 1) + 1]).ffill()
        if p.isna().iloc[0]:
            miss += 1
            continue
        ret = p.pct_change().iloc[1:].fillna(0.0)
        ret = ret.clip(-0.9, 3.0)
        ret.iloc[0] -= COST
        ret.iloc[-1] -= COST
        w = getattr(r, "w", 1.0) if weight else 1.0
        num[ret.index] += w * ret.values
        den[ret.index] += w
        used += 1
    spy_r = spy.pct_change().fillna(0.0)
    port = (num / den.replace(0, np.nan)).fillna(spy_r)
    return (1 + port).cumprod(), used, miss, (den > 0).mean()


def stats(eq, spy, a, b):
    e, s = eq[a:b], spy[a:b]
    yrs = (e.index[-1] - e.index[0]).days / 365.25
    c = (e.iloc[-1] / e.iloc[0]) ** (1 / yrs) - 1
    cs = (s.iloc[-1] / s.iloc[0]) ** (1 / yrs) - 1
    dd = (e / e.cummax() - 1).min()
    ex = (e.resample("ME").last().pct_change() - s.resample("ME").last().pct_change()).dropna()
    t = ex.mean() / ex.std(ddof=1) * math.sqrt(len(ex))
    return c, cs, dd, t


def report(name, sig, spy, **kw):
    eq, used, miss, inv = backtest(sig, spy, **kw)
    out = []
    for lab, (a, b) in (("2015-21", PRE), ("2022-26", MAIN)):
        c, cs, dd, t = stats(eq, spy, a, b)
        out.append((c, cs, t))
        print(f"  {name:34s} {lab}: {c:+6.1%} vs SPY {cs:+6.1%}  MaxDD {dd:6.1%}  t {t:+.2f}")
    print(f"  {'':34s} Signale genutzt {used}, ohne Kurs {miss}, investiert {inv:.0%} der Tage")
    return out


def main():
    tr = pd.read_csv(D / "trades.csv", parse_dates=["filing_date"])
    buys = tr[tr.type == "P"].drop_duplicates(["doc", "ticker"]).copy()
    spy = fetch_daily_yahoo("SPY", date(2014, 6, 1), date(2026, 10, 3))
    spy.index = pd.to_datetime(spy.index)
    spy = spy[spy.index <= "2026-09-30"]
    buys["filing_date"] = buys.filing_date.dt.date
    pel = buys[buys["last"] == "Pelosi"]
    lead = buys[buys.apply(is_leader, axis=1)]
    print(f"Käufe gesamt {len(buys)} (aus {tr.doc.nunique()} Meldungen), Pelosi {len(pel)}, Führung {len(lead)} "
          f"({', '.join(sorted(lead['last'].unique()))})\n")
    print("HAUPTERGEBNIS (Kriterium: 2022-26 Rendite > SPY, t >= 2,4; 2015-21 Überrendite > 0)")
    res = {}
    for name, s in (("A Pelosi", pel), ("B Führung ohne Pelosi", lead), ("C alle House-Mitglieder", buys)):
        res[name] = report(name, s, spy)
    print()
    for name, ((c0, s0, t0), (c1, s1, t1)) in res.items():
        ok = c1 > s1 and t1 >= 2.4 and c0 > s0
        print(f"  {name:34s} -> {'BESTANDEN' if ok else 'nicht bestanden'}")
    print("\nNUR INFO")
    for h in (63, 126):
        report(f"A Pelosi, Haltedauer {h} Tage", pel, spy, hold=h)
    w = buys.assign(w=buys.amount_lo.clip(lower=1001))
    report("C alle, nach Betragsklasse gewichtet", w, spy, weight=True)
    report("C alle, Käufe >= 50.001 $", buys[buys.amount_lo >= 50001], spy)
    print("\nPelosi-Käufe je Jahr:", pel.groupby(pd.to_datetime(pel.filing_date).dt.year).size().to_dict())
    print("Pelosi häufigste Ticker:", pel.ticker.value_counts().head(15).to_dict())


if __name__ == "__main__":
    main()

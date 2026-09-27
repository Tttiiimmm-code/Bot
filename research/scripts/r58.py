"""Runde 58: Rohstoff-Saisonalität, X-11-Signal."""
from datetime import date
from pathlib import Path
import numpy as np, pandas as pd
from tradingbot.research import anomalies, history

base = Path("data_cache/yahoo_unseen")


def month_end(sym):
    df = history.fetch_yahoo(sym, base=base, until=date(2026, 9, 26))
    s = pd.Series(df["adjclose"].to_numpy(), index=pd.to_datetime(df.index))
    return s.resample("ME").last()


def strat(ret):
    """ret: Monatsrenditen (Index Monatsende) x 4 Sektoren -> Strategierendite je Monat."""
    sig = ret.shift(11)
    rank = sig.rank(axis=1)
    w = pd.DataFrame(np.where(rank >= 3, 0.25, np.where(rank <= 2, -0.25, 0.0)), index=ret.index, columns=ret.columns)
    w = w.where(sig.notna().all(axis=1), 0.0, axis=0)
    turnover = (w - w.shift(1)).abs().sum(axis=1)
    return (w * ret).sum(axis=1) - 0.001 * turnover, w


def report(name, s):
    t = s.mean() / s.std() * np.sqrt(len(s))
    print(f"{name:34s} Monate {len(s):3d} Ø {s.mean() * 1e4:6.1f} bp/Monat ({s.mean() * 12:6.1%} p.a.) "
          f"Sharpe {s.mean() / s.std() * np.sqrt(12):5.2f} Treffer {(s > 0).mean():.0%} t {t:5.2f}")
    return t, s.mean()


# vorher: IMF-Indizes + Gold
imf = pd.DataFrame({k: anomalies.fetch_fred(c) for k, c in (("energy", "PNRGINDEXM"), ("metals", "PMETAINDEXM"), ("agri", "PFOODINDEXM"))})
imf.index = imf.index + pd.offsets.MonthEnd(0)
gold = month_end("GC=F").rename("precious")
pre = pd.concat([imf, gold], axis=1).dropna().pct_change().dropna()
s_pre, _ = strat(pre)
s_pre = s_pre[(s_pre.index >= "2001-09-01") & (s_pre.index <= "2006-12-31")]
s_pre = s_pre[s_pre.index >= s_pre.ne(0).idxmax()]
res_pre = report("vorher 2001-2006 (IMF + Gold)", s_pre)
# ETFs
etf = pd.concat([month_end(s).rename(s) for s in ("DBA", "DBB", "DBE", "DBP")], axis=1).dropna().pct_change().dropna()
etf = etf[etf.index <= "2026-08-31"]
s_etf, _ = strat(etf)
report("Replikation 2008-2024-06 (ETFs)", s_etf[(s_etf.index >= "2008-01-01") & (s_etf.index <= "2024-06-30")])
res_post = report("nachher 2024-07..2026-08 (ETFs)", s_etf[s_etf.index >= "2024-07-01"])
ok = res_pre[0] >= 2 and res_post[1] > 0
print("->", "BESTANDEN" if ok else "NICHT BESTANDEN")

"""Runde 98: Value+Qualität bei kleinen, illiquiden US-Aktien (Vorab-Registrierung in PROTOCOL.md).
Fundamentaldaten exakt wie Runde 95 (Funktion übernommen, damit r95.py unverändert reproduzierbar bleibt)."""
import pickle
import time
from pathlib import Path

import numpy as np
import pandas as pd

from tradingbot.research import edgar
from tradingbot.research import ml_rank as ml

OUT = Path("data_cache/r98")
OUT.mkdir(parents=True, exist_ok=True)
PANEL = OUT / "panel.pkl"
COST = 75e-4
PERIODS = {
    "P1 2017-01..2021-06": (pd.Timestamp("2017-01-01"), pd.Timestamp("2021-06-30")),
    "P2 2021-07..2025-09": (pd.Timestamp("2021-07-01"), pd.Timestamp("2025-09-19")),
    "unberührt 2025-09..": (pd.Timestamp("2025-09-22"), pd.Timestamp("2026-12-31")),
}
INSTANT = {"assets": ("Assets", "us-gaap", "USD"), "liabilities": ("Liabilities", "us-gaap", "USD"),
           "equity": ("StockholdersEquity", "us-gaap", "USD"),
           "shares": ("EntityCommonStockSharesOutstanding", "dei", "shares")}
ANNUAL = {"ni": ["NetIncomeLoss"], "rev": ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues"],
          "gp": ["GrossProfit"], "oi": ["OperatingIncomeLoss"], "cfo": ["NetCashProvidedByUsedInOperatingActivities"]}


def by_symbol(frame: pd.DataFrame, sym_cik: pd.Series) -> pd.Series:
    vals = frame.drop_duplicates("cik", keep="last").set_index("cik")["val"].astype(float)
    return sym_cik.map(vals).dropna()


def fundamentals(signals: pd.DatetimeIndex, close: pd.DataFrame) -> dict[str, pd.DataFrame]:
    mapping = edgar.symbol_to_cik(pd.read_pickle("data_cache/edgar/insider_purchases.pkl"))
    sym_cik = pd.Series({s: c for s, c in mapping.items() if s in close.columns})
    print(f"CIK-Zuordnung: {len(sym_cik)} von {close.shape[1]} Symbolen", flush=True)
    q_rows = {k: {} for k in list(INSTANT) + ["assets_1y", "shares_1y"]}
    for y in range(2015, 2027):
        for qq in range(1, 5):
            if (y, qq) > (2026, 1):
                continue
            quarter_end = pd.Timestamp(year=y, month=3 * qq, day=1) + pd.offsets.MonthEnd(0)
            avail = quarter_end + pd.DateOffset(months=3) + pd.offsets.MonthEnd(0)
            for k, (concept, tax, unit) in INSTANT.items():
                q_rows[k][avail] = by_symbol(edgar.xbrl_frame(concept, y, qq, True, taxonomy=tax, unit=unit), sym_cik)
                if k in ("assets", "shares") and y > 2015:
                    q_rows[k + "_1y"][avail] = by_symbol(
                        edgar.xbrl_frame(concept, y - 1, qq, True, taxonomy=tax, unit=unit), sym_cik)
    a_rows = {k: {} for k in list(ANNUAL) + ["rev_1y"]}
    annual_vals = {}
    for y in range(2015, 2026):
        avail = pd.Timestamp(year=y + 1, month=5, day=31)
        for k, concepts in ANNUAL.items():
            s = pd.Series(dtype=float)
            for concept in concepts:
                s = s.combine_first(by_symbol(edgar.xbrl_frame(concept, y, None, False), sym_cik))
            annual_vals[(k, y)] = s
            a_rows[k][avail] = s
        if y > 2015:
            a_rows["rev_1y"][avail] = annual_vals[("rev", y - 1)]
    cols = close.columns
    q = {k: ml.as_of(pd.DataFrame(v).T.reindex(columns=cols), signals, 190) for k, v in q_rows.items()}
    a = {k: ml.as_of(pd.DataFrame(v).T.reindex(columns=cols), signals, 370) for k, v in a_rows.items()}
    splits = pd.read_pickle("data_cache/splits.pkl")
    price = close.loc[signals] * ml.split_factor(splits, signals, cols)
    return ml.fundamental_features(q, a, price)


t0 = time.time()
if PANEL.exists():
    panel = pickle.loads(PANEL.read_bytes())
else:
    wide = ml.load_wide(min_dollar_volume=1e5, min_price=2.0)
    c, v = wide["close"], wide["volume"]
    print("Wide:", c.shape, f"{time.time() - t0:.0f}s", flush=True)
    months = ml.weekly_schedule(c.index, "M")
    signals = pd.DatetimeIndex([m.signal for m in months])
    fund = fundamentals(signals, c)
    dv20 = (c * v).rolling(20).mean()
    mask = ((c > 2) & (dv20 >= 1e5) & (dv20 < 5e6) & (c.notna().cumsum() >= 252)).loc[signals]
    mask &= fund["bm"].notna() & (fund["bm"] > 0)
    panel = ml.build_panel(wide, weeks=months, extra=fund, mask=mask)
    PANEL.write_bytes(pickle.dumps(panel))
    del wide, c, v, dv20
sizes = [len(p.y) for p in panel]
print(f"Panel: {len(panel)} Monate, Ø {np.mean(sizes):.0f} Titel (min {min(sizes)}, max {max(sizes)}), "
      f"{panel[0].week.signal.date()}..{panel[-1].week.signal.date()}, {time.time() - t0:.0f}s", flush=True)

names = ml.FEATURES + ml.FUNDAMENTALS
good = [names.index(k) for k in ("bm", "ep", "cfp", "gpa", "roa")]
bad = [names.index(k) for k in ("ag", "issuance", "accruals")]
test = [p for p in panel if p.week.signal >= pd.Timestamp("2016-12-01")]
mix = {p.week.signal: (p.X[:, good].sum(axis=1) + (1 - p.X[:, bad]).sum(axis=1)) / 8 for p in test}
weeks = set(mix)
ew = ml.simulate(panel, None, weeks=weeks, cost_per_side=COST).frame()


def per(s, a, b):
    return s[(s.index >= a) & (s.index <= b)]


def row(label, df):
    ex = df["net"] - ew["net"].reindex(df.index)
    parts = [f"{label:30s}"]
    for pname, (a, b) in PERIODS.items():
        e, g = per(ex, a, b), per(df["gross"] - ew["gross"].reindex(df.index), a, b)
        parts.append(f"| {pname}: n {len(e)} Überr. netto {e.mean() * 1e4:+.1f} bp/Mo (t {ml.t_stat(e):+.2f}), "
                     f"brutto {g.mean() * 1e4:+.1f}")
    parts.append(f"| Umschlag Ø {df['turnover'].iloc[1:].mean():.2f}/Mo, Titel Ø {df['n'].mean():.0f}")
    print("\n   ".join(parts), flush=True)
    return ex


print(f"\nNetto {COST * 1e4:.0f} bp je Seite. Überrendite = Portfolio - gleichgewichtetes Klein-Universum.")
for pname, (a, b) in PERIODS.items():
    e = per(ew["net"], a, b)
    print(f"EW-Klein-Universum {pname}: {e.mean() * 1e4:+.1f} bp/Mo netto, "
          f"{(np.prod(1 + e) ** (12 / max(len(e), 1)) - 1) * 100:+.1f} % p.a.")
ex = row("PRIMÄR Mix Top-20/40 %", ml.simulate(panel, mix, top=0.20, keep=0.40, cost_per_side=COST).frame())
row("Mix Top-10/20 % (berichtet)", ml.simulate(panel, mix, top=0.10, keep=0.20, cost_per_side=COST).frame())
y = ex.groupby(ex.index.year).apply(lambda s: np.prod(1 + s) - 1)
print("\nPRIMÄR Überrendite je Jahr:", " ".join(f"{k}: {val * 100:+.1f}%" for k, val in y.items()))
p1, p2, u = (per(ex, a, b) for a, b in PERIODS.values())
ok = ml.t_stat(p1) >= 2 and ml.t_stat(p2) >= 2 and u.mean() > 0
print(f"\nKriterien: t P1 {ml.t_stat(p1):+.2f} (>=2), t P2 {ml.t_stat(p2):+.2f} (>=2), "
      f"unberührt {u.mean() * 1e4:+.1f} bp (>0) -> {'BESTANDEN' if ok else 'NICHT BESTANDEN'}")

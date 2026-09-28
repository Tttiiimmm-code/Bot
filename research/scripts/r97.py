"""Runde 97: Vor-Feiertags-Effekt bei Rohöl/Benzin (Vorab-Registrierung in PROTOCOL.md)."""
import pandas as pd
from pandas.tseries.holiday import (Holiday, USLaborDay, USMartinLutherKingJr, USMemorialDay, USPresidentsDay,
                                    USThanksgivingDay, nearest_workday)

from tradingbot.research import ml_rank as ml
from tradingbot.research.anomalies import fetch_fred

COST = 10e-4
PERIODS = {"P1 1986-2005": ("1986-01-01", "2005-12-31"), "P2 2006-2024-08": ("2006-01-01", "2024-08-31"),
           "unberührt 2024-09..": ("2024-09-01", "2026-12-31")}
RULES = {
    "Neujahr": Holiday("NewYear", month=1, day=1, observance=nearest_workday),
    "MLK": USMartinLutherKingJr,
    "Presidents": USPresidentsDay,
    "Memorial": USMemorialDay,
    "Juneteenth": Holiday("Juneteenth", month=6, day=19, start_date="2022-01-01", observance=nearest_workday),
    "Independence": Holiday("July4", month=7, day=4, observance=nearest_workday),
    "Labor": USLaborDay,
    "Thanksgiving": USThanksgivingDay,
    "Weihnachten": Holiday("Christmas", month=12, day=25, observance=nearest_workday),
}


def trades(s: pd.Series) -> pd.DataFrame:
    """Kauf zum Schluss D-5, Verkauf zum Schluss D-1 (letzter Handelstag vor dem Feiertag)."""
    s = s[s > 0].sort_index()
    idx = s.index
    rows = []
    for name, rule in RULES.items():
        for h in rule.dates(idx[0], idx[-1]):
            after = idx.searchsorted(h)
            if after >= len(idx):
                continue  # Feiertag nach Datenende
            pos = after - 1
            if pos - 4 < 0:
                continue
            rows.append({"holiday": name, "date": h, "ret": s.iloc[pos] / s.iloc[pos - 4] - 1 - COST})
    return pd.DataFrame(rows).sort_values("date").reset_index(drop=True)


def summary(label: str, t: pd.DataFrame, s: pd.Series) -> list:
    s = s[s > 0]
    base = (s.shift(-4) / s - 1).dropna()
    out = []
    parts = [f"{label:26s}"]
    for pname, (a, b) in PERIODS.items():
        x = t[(t["date"] >= a) & (t["date"] <= b)]["ret"]
        bb = base[(base.index >= a) & (base.index <= b)]
        out.append(x)
        parts.append(f"{pname}: n {len(x)}, Ø {x.mean() * 1e4:+.0f} bp (t {ml.t_stat(x):+.2f}, "
                     f"Treffer {(x > 0).mean():.0%}), zufällig 4 T brutto Ø {bb.mean() * 1e4:+.0f} bp")
    print("\n   ".join(parts), flush=True)
    return out


wti = fetch_fred("DCOILWTICO")
gas = fetch_fred("DGASNYH")
tw, tg = trades(wti), trades(gas)
p1, p2, u = summary("WTI (PRIMÄR)", tw, wti)
summary("Benzin NY Harbor", tg, gas)
print("\nWTI je Feiertag, Ø netto bp (n):")
for name in RULES:
    x = tw[tw["holiday"] == name]
    cells = []
    for pname, (a, b) in PERIODS.items():
        y = x[(x["date"] >= a) & (x["date"] <= b)]["ret"]
        cells.append(f"{pname.split()[0]} {y.mean() * 1e4:+.0f} ({len(y)})" if len(y) else f"{pname.split()[0]} -")
    print(f"  {name:13s} " + " | ".join(cells))
ok = ml.t_stat(p1) >= 2 and p2.mean() > 0 and u.mean() > 0
print(f"\nKriterien: t P1 {ml.t_stat(p1):+.2f} (>=2), Ø P2 {p2.mean() * 1e4:+.0f} bp (>0), "
      f"Ø unberührt {u.mean() * 1e4:+.0f} bp (>0) -> {'BESTANDEN' if ok else 'NICHT BESTANDEN'}")

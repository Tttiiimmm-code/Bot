"""Runde 149: Nutzer-These "Märkte steigen über Nacht und fallen tagsüber" -- Vorab: PROTOCOL.md Runde 149.

Aufruf aus dem Haupt-Repo (Daten relativ): PYTHONPATH=<worktree> python <worktree>/research/scripts/r149.py
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from tradingbot.research import history

ETFS = ("SPY", "QQQ", "IWM", "DIA")
OLD_END = date(2025, 9, 19)
NEW_UNTIL = date(2026, 10, 9)            # exklusiv -> Daten bis 2026-10-08
U = Path("data_cache/universe/daily")
C_SIDE, SEC = 1e-4, 0.28e-4              # 1 bp je Seite + SEC-Gebühr auf Verkäufe
T_A, T_B = 2.58, 2.64                    # Bonferroni 10 (Teil A) bzw. 12 (Teil B), einseitig


def tstat(x) -> float:
    x = pd.Series(x).dropna()
    return float(x.mean() / x.std(ddof=1) * np.sqrt(len(x))) if len(x) > 2 and x.std() > 0 else float("nan")


def etf(sym: str) -> pd.DataFrame:
    old = pd.read_pickle(f"data_cache/yahoo/{sym}_full.pkl")
    new = history.fetch_yahoo(sym, base=Path("data_cache/yahoo_r149"), until=NEW_UNTIL)
    df = pd.concat([old[old.index <= OLD_END], new[new.index > OLD_END]]).sort_index()
    df = df[~df.index.duplicated(keep="first")]
    df.index = pd.DatetimeIndex([pd.Timestamp(d) for d in df.index])
    pc = df["close"].shift(1)
    df["night"] = (df["open"] + df["dividend"]) / pc - 1
    df["day"] = df["close"] / df["open"] - 1
    df["hold"] = df["adjclose"].pct_change()
    df["stale"] = (df["open"] - pc).abs() < 1e-9            # Eröffnung = Vortagesschluss (Datenfehler-Hinweis)
    return df.dropna(subset=["night", "day"])


def stock_panel() -> pd.DataFrame:
    """Gleichgewichtete Ø Nacht- und Tagesrendite der Top 500 (Universum aus Informationen bis Schluss t-1)."""
    Os, Cs, Vs = [], [], []
    for p in sorted(U.glob("batch_*.pkl")):
        x = pd.read_pickle(p)
        if not len(x):
            continue
        d = pd.to_datetime(x.index.get_level_values("timestamp").tz_convert("America/New_York").date)
        df = pd.DataFrame({"symbol": x.index.get_level_values("symbol"), "date": d, "open": x["open"].to_numpy(),
                           "close": x["close"].to_numpy(), "volume": x["volume"].to_numpy()})
        df = df.drop_duplicates(["date", "symbol"])
        for col, acc in (("open", Os), ("close", Cs), ("volume", Vs)):
            acc.append(df.pivot(index="date", columns="symbol", values=col).astype(np.float32))
    O, C, V = (pd.concat(a, axis=1).sort_index() for a in (Os, Cs, Vs))
    O = O.loc[:, ~O.columns.duplicated()]
    C, V = C.loc[:, ~C.columns.duplicated()][O.columns], V.loc[:, ~V.columns.duplicated()][O.columns]
    O, C, V = (m.to_numpy(np.float64) for m in (O.astype(np.float64), C.astype(np.float64), V.astype(np.float64)))
    dates = pd.DatetimeIndex(sorted(set().union(*[a.index for a in Os])))
    pc = np.vstack([np.full((1, C.shape[1]), np.nan), C[:-1]])
    on, idr = np.clip(O / pc - 1, -0.9, 5), np.clip(C / O - 1, -0.9, 5)
    dv = pd.DataFrame(C * V).rolling(20, min_periods=15).mean().to_numpy()
    elig = (C > 5) & np.isfinite(dv)
    rank = pd.DataFrame(np.where(elig, dv, np.nan)).rank(axis=1, ascending=False).to_numpy()
    univ = np.vstack([np.zeros((1, C.shape[1]), bool), (rank <= 500)[:-1]])   # Auswahl am Schluss t-1
    ok = univ & np.isfinite(on) & np.isfinite(idr)
    n = ok.sum(1)
    night = np.where(ok, on, 0).sum(1) / np.maximum(n, 1)
    day = np.where(ok, idr, 0).sum(1) / np.maximum(n, 1)
    out = pd.DataFrame({"night": night, "day": day, "n": n}, index=dates)
    return out[(out["n"] >= 400) & (out.index >= "2016-01-01")]


def describe(name: str, df: pd.DataFrame, periods: list[tuple[str, str, str]]) -> str:
    lines, signs = [], []
    for label, a, b in periods:
        x = df[(df.index >= a) & (df.index <= b)]
        if not len(x):
            continue
        tn, td = tstat(x["night"]), tstat(x["day"])
        signs.append((x["night"].mean() > 0, x["day"].mean() < 0))
        lines.append(f"  {label:22s} {len(x):5d} Tage  Nacht Ø {x['night'].mean() * 1e4:+6.2f} bp (t {tn:+5.2f})  "
                     f"Tag Ø {x['day'].mean() * 1e4:+6.2f} bp (t {td:+5.2f})")
    tn, td = tstat(df["night"]), tstat(df["day"])
    lines.append(f"  {'gesamt':22s} {len(df):5d} Tage  Nacht Ø {df['night'].mean() * 1e4:+6.2f} bp (t {tn:+5.2f})  "
                 f"Tag Ø {df['day'].mean() * 1e4:+6.2f} bp (t {td:+5.2f})")
    night_ok = tn >= T_A and df["night"].mean() > 0 and all(s[0] for s in signs)
    day_ok = td <= -T_A and df["day"].mean() < 0 and all(s[1] for s in signs)
    verdict = "BESTÄTIGT" if night_ok and day_ok else "TEILWEISE" if night_ok or day_ok else "WIDERLEGT"
    detail = f"Nacht {'erfüllt' if night_ok else 'nicht erfüllt'}, Tag {'erfüllt' if day_ok else 'nicht erfüllt'}"
    return f"{name}: {verdict} ({detail})\n" + "\n".join(lines)


def strategies(df: pd.DataFrame, c_side: float = C_SIDE, sec: float = SEC) -> pd.DataFrame:
    rt = 2 * c_side + sec                               # Kauf + Verkauf (Verkauf mit SEC-Gebühr)
    return pd.DataFrame({
        "S1 Nacht long": df["night"] - rt,
        "S2 Nacht long + Tag short": (1 + df["night"]) * (1 - df["day"]) - 1 - 2 * rt,
        "S3 Tag short": -df["day"] - rt,
    }, index=df.index)


def pa(r: pd.Series) -> float:
    r = r.dropna()
    return float((1 + r).prod() ** (252 / len(r)) - 1) if len(r) else float("nan")


def monthly(r: pd.Series) -> pd.Series:
    return (1 + r).groupby(r.index.to_period("M")).prod() - 1


def evaluate(label: str, r: pd.Series, spy: pd.Series, main=("2008-01-01", "2026-10-08"), pre_end="2007-12-31"):
    m = r[(r.index >= main[0]) & (r.index <= main[1])]
    s = spy.reindex(m.index).fillna(0)
    ex = monthly(m) - monthly(s)
    t = tstat(ex)
    pre = r[r.index <= pre_end]
    pre_ex = pa(pre) - pa(spy.reindex(pre.index).fillna(0)) if len(pre) > 250 else float("nan")
    passed = pa(m) > pa(s) and t >= T_B and (pre_ex > 0)
    return (f"  {label:28s} Haupt {pa(m):+7.1%} p.a. (SPY {pa(s):+6.1%}), t Überrendite {t:+5.2f}, "
            f"Einordnung bis 2007 Überrendite {pre_ex:+7.1%} p.a. -> {'BESTANDEN' if passed else 'nicht bestanden'}")


def main():
    data = {s: etf(s) for s in ETFS}
    spy_hold = data["SPY"]["hold"]
    print("Runde 149 -- Märkte steigen über Nacht und fallen tagsüber?\n")
    for s, df in data.items():
        print(f"{s}: {df.index[0].date()} bis {df.index[-1].date()}, Eröffnung = Vortagesschluss an "
              f"{df['stale'].mean():.1%} der Tage")
    print("\nTeil A -- Beschreibung (bestätigt: gesamt Nacht t >= 2,58 und Tag t <= -2,58, Vorzeichen in jedem Teil)")
    for s, df in data.items():
        print(describe(s, df, [("bis 2007", "1900-01-01", "2007-12-31"), ("2008-2015", "2008-01-01", "2015-12-31"),
                               ("2016-2026", "2016-01-01", "2026-12-31")]))
    stocks = stock_panel()
    print(describe("Aktien Top-500 gleichgew.", stocks, [("2016-2020", "2016-01-01", "2020-12-31"),
                                                          ("2021-2026", "2021-01-01", "2026-12-31")]))
    print("  (ohne Dividenden: Ex-Tag-Abschlag liegt in der Nacht -> Nacht leicht unterschätzt)")

    print("\nJahre (Ø bp je Tag, Nacht / Tag)")
    years = sorted({d.year for d in data["SPY"].index})
    hdr = "  Jahr  " + "  ".join(f"{s:>13s}" for s in ETFS) + "  Aktien-Top500"
    print(hdr)
    for y in years:
        cells = []
        for s in ETFS:
            x = data[s][data[s].index.year == y]
            cells.append(f"{x['night'].mean() * 1e4:+6.1f}/{x['day'].mean() * 1e4:+6.1f}" if len(x) else " " * 13)
        x = stocks[stocks.index.year == y]
        cells.append(f"{x['night'].mean() * 1e4:+6.1f}/{x['day'].mean() * 1e4:+6.1f}" if len(x) else "")
        print(f"  {y}  " + "  ".join(f"{c:>13s}" for c in cells))

    print("\nTeil B -- Umsetzung nach Kosten gegen SPY halten (bestanden: Haupt 2008-2026 > SPY, t >= 2,64, "
          "Einordnung bis 2007 > 0)")
    for s, df in data.items():
        print(f"{s} (ab {df.index[0].date()}):")
        st = strategies(df)
        for col in st:
            print(evaluate(col, st[col], spy_hold))
        print(f"  {'Halten ' + s:28s} Haupt {pa(df['hold'][df.index >= '2008-01-01']):+7.1%} p.a.")

    print("\nInfo (nicht gewertet): Aktien Top-500 gleichgewichtet, 2016-2026-09, gegen SPY halten")
    for c in (2e-4, 10e-4):
        st = strategies(stocks, c_side=c, sec=SEC)
        for col in ("S1 Nacht long", "S2 Nacht long + Tag short"):
            r = st[col]
            ex = monthly(r) - monthly(spy_hold.reindex(r.index).fillna(0))
            print(f"  {c * 1e4:4.0f} bp/Seite  {col:28s} {pa(r):+7.1%} p.a. (SPY {pa(spy_hold.reindex(r.index).fillna(0)):+6.1%}), "
                  f"t Überrendite {tstat(ex):+5.2f}")


if __name__ == "__main__":
    main()

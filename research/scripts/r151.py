"""Runde 151: Kauf zum Schluss nahe Tagestief (IBS), Verkauf 9:30 bzw. 9:35 -- Vorab: PROTOCOL.md Runde 151.

Aufruf aus dem Haupt-Repo (Daten relativ): PYTHONPATH=<worktree> python <worktree>/research/scripts/r151.py
"""
from __future__ import annotations

import itertools
import math
from pathlib import Path

import numpy as np
import pandas as pd

U = Path("data_cache/universe")
SPY = Path("data_cache/yahoo_r149/SPY_full.pkl")     # Runde 149: SPY bis 2026-10-08 (adjclose)
START, END = "2016-01-01", "2026-09-30"
T_B = 2.64                                           # Bonferroni 12, einseitig
MIN_SIGNALS = 5


def tstat(x) -> float:
    x = pd.Series(x).dropna()
    return float(x.mean() / x.std(ddof=1) * np.sqrt(len(x))) if len(x) > 2 and x.std() > 0 else float("nan")


def norm_ppf(p: float) -> float:
    lo, hi = -10.0, 10.0
    for _ in range(100):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if 0.5 * math.erfc(-mid / math.sqrt(2)) < p else (lo, mid)
    return (lo + hi) / 2


def panel():
    frames = {k: [] for k in ("open", "high", "low", "close", "volume")}
    for p in sorted((U / "daily").glob("batch_*.pkl")):
        x = pd.read_pickle(p)
        if not len(x):
            continue
        d = pd.to_datetime(x.index.get_level_values("timestamp").tz_convert("America/New_York").date)
        df = pd.DataFrame({"symbol": x.index.get_level_values("symbol"), "date": d,
                           **{k: x[k].to_numpy() for k in frames}}).drop_duplicates(["date", "symbol"])
        for k in frames:
            frames[k].append(df.pivot(index="date", columns="symbol", values=k).astype(np.float32))
    wide = {k: pd.concat(v, axis=1).sort_index() for k, v in frames.items()}
    cols = wide["close"].columns[~wide["close"].columns.duplicated()]
    wide = {k: v.loc[:, ~v.columns.duplicated()].reindex(columns=cols) for k, v in wide.items()}
    dates = wide["close"].index
    op = pd.concat([pd.read_pickle(p) for p in sorted((U / "opening").glob("*.pkl"))], ignore_index=True)
    op["date"] = pd.to_datetime(op["date"])
    op = op.drop_duplicates(["date", "symbol"]).pivot(index="date", columns="symbol", values="close")
    x935 = op.reindex(index=dates, columns=cols).astype(np.float32)
    return dates, cols, {k: v.to_numpy() for k, v in wide.items()}, x935.to_numpy()


def main():
    dates, cols, w, x935 = panel()
    O, H, L, C, V = w["open"], w["high"], w["low"], w["close"], w["volume"]
    T, M = C.shape
    print(f"Runde 151 -- {M} Symbole, {T} Tage ({dates[0].date()} bis {dates[-1].date()})\n")
    rng = H - L
    with np.errstate(invalid="ignore", divide="ignore"):
        ibs = np.where(rng > 0, (C - L) / rng, np.nan)
        nxt_open = np.vstack([O[1:], np.full((1, M), np.nan)])
        nxt_935 = np.vstack([x935[1:], np.full((1, M), np.nan)])
        ret = {"9:30": np.clip(nxt_open / C - 1, -0.9, 5), "9:35": np.clip(nxt_935 / C - 1, -0.9, 5)}
    dv = pd.DataFrame(C * V).rolling(20, min_periods=15).mean().to_numpy()
    elig = (C > 5) & np.isfinite(dv)
    rank = pd.DataFrame(np.where(elig, dv, np.nan)).rank(axis=1, ascending=False).to_numpy()
    univ = {n: rank <= n for n in (500, 1500)}
    in_period = (dates >= START) & (dates <= END)
    spy = pd.read_pickle(SPY)
    spy.index = pd.DatetimeIndex([pd.Timestamp(d) for d in spy.index])
    spy_r = spy["adjclose"].pct_change()

    def series(sig, r, cost):
        ok = sig & np.isfinite(r)
        n = ok.sum(1)
        gross = np.where(ok, r, 0).sum(1) / np.maximum(n, 1)
        net = np.where(n >= MIN_SIGNALS, gross - 2 * cost, 0.0)
        s = pd.Series(net, index=dates)[in_period]
        return s, pd.Series(n, index=dates)[in_period]

    def pa(r):
        return float((1 + r).prod() ** (252 / len(r)) - 1)

    def monthly(r):
        return (1 + r).groupby(r.index.to_period("M")).prod() - 1

    spy_d = spy_r.reindex(dates[in_period]).fillna(0)
    print(f"SPY halten {START[:4]}-{END[:7]}: {pa(spy_d):+.1%} p.a.\n")
    print("Teil B -- Konfigurationen (5 bp je Seite; bestanden: > SPY, t >= 2,64, beide Hälften > 0)")
    for th, n, ex in itertools.product((0.05, 0.10, 0.20), (500, 1500), ("9:30", "9:35")):
        sig = univ[n] & (ibs <= th)
        s, cnt = series(sig, ret[ex], 5e-4)
        exm = monthly(s) - monthly(spy_d)
        t = tstat(exm)
        h1 = pa(s[s.index < "2021-01-01"]) - pa(spy_d[spy_d.index < "2021-01-01"])
        h2 = pa(s[s.index >= "2021-01-01"]) - pa(spy_d[spy_d.index >= "2021-01-01"])
        passed = pa(s) > pa(spy_d) and t >= T_B and h1 > 0 and h2 > 0
        info = []
        for c in (2e-4, 10e-4):
            info.append(f"{c * 1e4:.0f} bp {pa(series(sig, ret[ex], c)[0]):+6.1%}")
        cover = ""
        if ex == "9:35":
            base = (univ[n] & (ibs <= th) & np.isfinite(ret["9:30"]))[in_period].sum()
            cover = f", Abdeckung 9:35 {(sig & np.isfinite(ret['9:35']))[in_period].sum() / max(base, 1):.0%}"
        print(f"  IBS <= {th:.2f}  Top {n:4d}  Ausstieg {ex}: {pa(s):+7.1%} p.a., t ggü. SPY {t:+5.2f}, "
              f"Hälften {h1:+6.1%} / {h2:+6.1%}, Ø {cnt[cnt > 0].mean():5.1f} Signale/Nacht, "
              f"Nächte investiert {(cnt >= MIN_SIGNALS).mean():.0%} [{', '.join(info)}]{cover} "
              f"-> {'BESTANDEN' if passed else 'nicht bestanden'}")

    print("\nInfo 1 -- brutto: Ø Nacht (Schluss -> 9:30) der Signal-Aktien minus Ø aller Aktien des Universums")
    for th, n in itertools.product((0.05, 0.10, 0.20), (500, 1500)):
        r = ret["9:30"]
        sig = univ[n] & (ibs <= th) & np.isfinite(r)
        allu = univ[n] & np.isfinite(r)
        a = np.where(sig, r, 0).sum(1) / np.maximum(sig.sum(1), 1)
        b = np.where(allu, r, 0).sum(1) / np.maximum(allu.sum(1), 1)
        diff = pd.Series(np.where(sig.sum(1) >= MIN_SIGNALS, a - b, np.nan), index=dates)[in_period].dropna()
        sig_m = pd.Series(np.where(sig.sum(1) >= MIN_SIGNALS, a, np.nan), index=dates)[in_period].dropna()
        print(f"  IBS <= {th:.2f} Top {n:4d}: Signal-Aktien Ø {sig_m.mean() * 1e4:+6.2f} bp/Nacht, "
              f"Universum Ø {pd.Series(b, index=dates)[in_period].mean() * 1e4:+6.2f} bp, "
              f"Differenz {diff.mean() * 1e4:+6.2f} bp (t {tstat(diff):+5.2f}); "
              f"2016-20 {diff[diff.index < '2021-01-01'].mean() * 1e4:+6.2f}, "
              f"2021-26 {diff[diff.index >= '2021-01-01'].mean() * 1e4:+6.2f} bp")

    print("\nInfo 2 -- 'egal welche Aktie': IBS <= 0,10, Top 1.500, Ausstieg 9:30, 5 bp je Seite, >= 50 Signale")
    r = ret["9:30"]
    sig = univ[1500] & (ibs <= 0.10) & np.isfinite(r) & in_period[:, None]
    rows = []
    for j in np.where(sig.sum(0) >= 50)[0]:
        x = r[sig[:, j], j] - 2 * 5e-4
        rows.append((cols[j], len(x), x.mean(), tstat(x)))
    df = pd.DataFrame(rows, columns=["symbol", "n", "mean", "t"]).sort_values("t", ascending=False)
    k = len(df)
    hurdle = norm_ppf(1 - 0.05 / k)
    print(f"  Aktien mit >= 50 Signalen: {k}; Ø netto > 0: {(df['mean'] > 0).sum()} ({(df['mean'] > 0).mean():.0%}); "
          f"t >= 2: {(df['t'] >= 2).sum()} (bei reinem Zufall ~{0.023 * k:.0f}); "
          f"t >= Bonferroni-Hürde {hurdle:.2f}: {(df['t'] >= hurdle).sum()}")
    print("  Höchste t (Kandidaten nur zur Info, keine Bestätigung):")
    for _, row in df.head(8).iterrows():
        print(f"    {row['symbol']:6s} {int(row['n']):4d} Signale, Ø {row['mean'] * 1e4:+7.1f} bp, t {row['t']:+5.2f}")
    print(f"  Median über alle Aktien: Ø {df['mean'].median() * 1e4:+.1f} bp je Trade netto")


if __name__ == "__main__":
    main()

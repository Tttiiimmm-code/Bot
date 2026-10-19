"""Runde 152, Download: Alpaca-SIP-5-Minuten-Balken für das Top-500-Universum (2016-01..2026-09).

Gespeichert je Monat (data_cache/r152/YYYY-MM.pkl) nur die Balken der letzten Stunde (Start 14:55-15:55 ET; 14:55 als
Vorbalken für K2/K3) und
der ersten Stunde (Start 9:30-10:25 ET), jeweils mit laufendem Tageshoch/-tief und VWAP bis einschließlich Balken.
Fortsetzbar (fertige Monate werden übersprungen). Schlüssel: copilot.env (nicht das Momentum-Konto).

Aufruf aus dem Haupt-Repo: PYTHONPATH=<worktree> python <worktree>/research/scripts/r152_fetch.py [--test]
"""
from __future__ import annotations

import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

U = Path("data_cache/universe/daily")
OUT = Path("data_cache/r152")
START, END = pd.Timestamp("2016-01-01"), pd.Timestamp("2026-09-30")
CHUNK = 100
KEEP = [(14, 55)] + [(15, m) for m in range(0, 60, 5)] + [(9, m) for m in range(30, 60, 5)] + [(10, m) for m in range(0, 30, 5)]


UCACHE = Path("data_cache/r152_universe.pkl")


def _batch(p: Path) -> pd.DataFrame:
    x = pd.read_pickle(p)
    if not len(x):
        return pd.DataFrame()
    d = pd.to_datetime(x.index.get_level_values("timestamp").tz_convert("America/New_York").date)
    return pd.DataFrame({"symbol": x.index.get_level_values("symbol"), "date": d, "open": x["open"].to_numpy(),
                         "close": x["close"].to_numpy(), "volume": x["volume"].to_numpy()}).drop_duplicates(["date", "symbol"])


def daily_universe(paths=None, top: int = 500, cache: bool = True) -> tuple[pd.DatetimeIndex, pd.DataFrame]:
    """Top 500 nach Ø-Dollar-Umsatz (20 Tage, Kurs > 5 $), Informationen bis Schluss t-1 -> (alle Handelstage,
    Tabelle date/symbol). Speicherschonend: Batch für Batch, je Tag nur die bisher besten `top` Werte behalten
    (ein Wert unter den globalen Top 500 ist auch unter den Top 500 seines Batches). Symbole kommen in genau einem
    Batch vor (geprüft), Ergebnis gleich der früheren Gesamttabelle (Vergleich auf Teilmenge in r152_fetch --check)."""
    if cache and paths is None and UCACHE.exists():
        return pd.read_pickle(UCACHE)
    paths = list(paths) if paths is not None else sorted(U.glob("batch_*.pkl"))
    dates = set()
    for p in paths:
        x = pd.read_pickle(p)
        if len(x):
            dates.update(x.index.get_level_values("timestamp").tz_convert("America/New_York").date)
        del x
    idx = pd.DatetimeIndex(sorted(pd.Timestamp(d) for d in dates))
    keep = top + 20                                                       # Puffer für Gleichstände am Rand
    best_v = np.full((len(idx), keep), -np.inf)
    best_s = np.full((len(idx), keep), -1, dtype=np.int64)
    names: list[str] = []
    for p in paths:
        df = _batch(p)
        if not len(df):
            continue
        C = df.pivot(index="date", columns="symbol", values="close").astype(np.float32).reindex(idx)
        V = df.pivot(index="date", columns="symbol", values="volume").astype(np.float32).reindex(idx)[C.columns]
        dv = (C * V).rolling(20, min_periods=15).mean().where(C > 5).to_numpy(np.float64, copy=True)
        dv[np.isnan(dv)] = -np.inf
        ids = np.arange(len(names), len(names) + dv.shape[1])
        names.extend(C.columns)
        allv = np.hstack([best_v, dv])
        alls = np.hstack([best_s, np.broadcast_to(ids, dv.shape)])
        k = np.argpartition(-allv, keep - 1, axis=1)[:, :keep]
        best_v, best_s = np.take_along_axis(allv, k, 1), np.take_along_axis(alls, k, 1)
        del df, C, V, dv, allv, alls
    names_a = np.array(names, dtype=object)
    v = best_v[:-1]
    sel = np.zeros(v.shape, dtype=bool)
    for i in range(0, len(v), 100):                                       # Rang wie pandas rank(method="average")
        w = v[i:i + 100]
        gt = (w[:, None, :] > w[:, :, None]).sum(2)
        eq = (w[:, None, :] == w[:, :, None]).sum(2)
        sel[i:i + 100] = np.isfinite(w) & (gt + (eq + 1) / 2 <= top)
    r, c = np.nonzero(sel)                                                # Auswahl am Schluss t-1 -> gilt für Tag t
    univ = pd.DataFrame({"date": idx[r + 1], "symbol": names_a[best_s[:-1][r, c]]})
    univ = univ.sort_values(["date", "symbol"], ignore_index=True)
    if cache and paths == sorted(U.glob("batch_*.pkl")):
        pd.to_pickle((idx, univ), UCACHE)
    return idx, univ


def universe_by_month(paths=None) -> dict[pd.Period, list[str]]:
    """Symbole je Monat (Einstiegstage) plus Vortag des Monats (Ausstieg am Monatsersten)."""
    _, univ = daily_universe(paths, cache=paths is None)
    by_day = univ[(univ["date"] >= START) & (univ["date"] <= END)].groupby("date")["symbol"].apply(set)
    out: dict[pd.Period, set] = {}
    days = by_day.index
    for i, d in enumerate(days):
        syms = by_day.iloc[i]
        out.setdefault(d.to_period("M"), set()).update(syms)
        nxt = days[i + 1] if i + 1 < len(days) else None
        if nxt is not None and nxt.to_period("M") != d.to_period("M"):      # Ausstieg am nächsten Monatsersten
            out.setdefault(nxt.to_period("M"), set()).update(syms)
    return {m: sorted(s) for m, s in out.items()}


def client():
    from alpaca.data.historical import StockHistoricalDataClient
    from dotenv import dotenv_values

    v = dotenv_values("copilot.env")
    return StockHistoricalDataClient(v["ALPACA_API_KEY"], v["ALPACA_SECRET_KEY"])


def fetch_month(dc, month: pd.Period, symbols: list[str]) -> pd.DataFrame:
    from alpaca.data.enums import Adjustment, DataFeed
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

    a = datetime(month.year, month.month, 1, tzinfo=timezone.utc)
    b = (pd.Timestamp(a) + pd.offsets.MonthBegin(1)).to_pydatetime() + timedelta(hours=6)
    parts = []
    for i in range(0, len(symbols), CHUNK):
        req = StockBarsRequest(symbol_or_symbols=symbols[i:i + CHUNK], timeframe=TimeFrame(5, TimeFrameUnit.Minute),
                               start=a, end=b, adjustment=Adjustment.SPLIT, feed=DataFeed.SIP)
        for attempt in range(5):
            try:
                df = dc.get_stock_bars(req).df
                break
            except Exception as exc:  # noqa: BLE001 -- Netz/Limit: warten und erneut
                print(f"  Fehler {exc!r}, Versuch {attempt + 1}/5", flush=True)
                time.sleep(30 * (attempt + 1))
        else:
            raise RuntimeError(f"{month}: Abruf scheitert dauerhaft")
        if len(df):
            parts.append(df)
        time.sleep(0.5)
    if not parts:
        return pd.DataFrame()
    df = pd.concat(parts).reset_index()
    ts = df["timestamp"].dt.tz_convert("America/New_York")
    df["date"], df["hh"], df["mm"] = ts.dt.date, ts.dt.hour, ts.dt.minute
    mins = df["hh"] * 60 + df["mm"]
    df = df[(mins >= 570) & (mins < 960)].sort_values(["symbol", "timestamp"])          # 9:30 bis 15:55 (Start)
    g = df.groupby(["symbol", "date"], sort=False)
    df["cum_high"], df["cum_low"] = g["high"].cummax(), g["low"].cummin()
    pv = df["vwap"] * df["volume"]
    df["cum_vwap"] = pv.groupby([df["symbol"], df["date"]]).cumsum() / g["volume"].cumsum()
    keep = pd.Series(list(zip(df["hh"], df["mm"])), index=df.index).isin(set(KEEP))
    cols = ["symbol", "date", "hh", "mm", "open", "high", "low", "close", "volume", "cum_high", "cum_low", "cum_vwap"]
    out = df.loc[keep, cols].copy()
    for c in ("open", "high", "low", "close", "volume", "cum_high", "cum_low", "cum_vwap"):
        out[c] = out[c].astype(np.float32)
    out["hh"], out["mm"] = out["hh"].astype(np.int8), out["mm"].astype(np.int8)
    return out


def main():
    test = "--test" in sys.argv
    dc = client()
    if test:
        df = fetch_month(dc, pd.Period("2024-03", "M"), ["AAPL", "NVDA", "F"])
        print(df.groupby("symbol").size(), df.head(14).to_string(), sep="\n")
        return
    OUT.mkdir(parents=True, exist_ok=True)
    months = universe_by_month()
    print(f"{len(months)} Monate, Ø {np.mean([len(s) for s in months.values()]):.0f} Symbole je Monat", flush=True)
    t0 = time.time()
    for k, (m, syms) in enumerate(sorted(months.items())):
        path = OUT / f"{m}.pkl"
        if path.exists():
            continue
        df = fetch_month(dc, m, syms)
        tmp = path.with_suffix(".tmp")
        df.to_pickle(tmp)
        tmp.replace(path)
        print(f"{m}: {len(syms)} Symbole, {len(df)} Balken ({(time.time() - t0) / 60:.0f} min)", flush=True)
    print("fertig", flush=True)


if __name__ == "__main__":
    main()

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


def universe_by_month() -> dict[pd.Period, list[str]]:
    """Top 500 nach Ø-Dollar-Umsatz (20 Tage, Kurs > 5 $), Informationen bis Schluss t-1 -> Symbole je Monat
    (Einstiegstage) plus Vortag des Monats (Ausstieg am Monatsersten)."""
    Cs, Vs = [], []
    for p in sorted(U.glob("batch_*.pkl")):
        x = pd.read_pickle(p)
        if not len(x):
            continue
        d = pd.to_datetime(x.index.get_level_values("timestamp").tz_convert("America/New_York").date)
        df = pd.DataFrame({"symbol": x.index.get_level_values("symbol"), "date": d,
                           "close": x["close"].to_numpy(), "volume": x["volume"].to_numpy()}).drop_duplicates(["date", "symbol"])
        Cs.append(df.pivot(index="date", columns="symbol", values="close").astype(np.float32))
        Vs.append(df.pivot(index="date", columns="symbol", values="volume").astype(np.float32))
    C, V = pd.concat(Cs, axis=1).sort_index(), pd.concat(Vs, axis=1).sort_index()
    C, V = C.loc[:, ~C.columns.duplicated()], V.loc[:, ~V.columns.duplicated()][C.loc[:, ~C.columns.duplicated()].columns]
    dv = (C * V).rolling(20, min_periods=15).mean()
    rank = dv.where(C > 5).rank(axis=1, ascending=False).shift(1)       # Auswahl am Schluss t-1
    univ = rank <= 500
    out: dict[pd.Period, set] = {}
    days = univ.index[(univ.index >= START) & (univ.index <= END)]
    for i, d in enumerate(days):
        syms = set(univ.columns[univ.loc[d].to_numpy()])
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

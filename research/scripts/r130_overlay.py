"""ETF halten vs. ETF + Nikkei-Nacht/Gotobi als Futures-Zusatz (2017-01 bis 2026-09, Kosten wie Vorwärtstest)."""
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from tradingbot import forward_test as ft
from tradingbot.report import read_account_env
import importlib.util as _iu; _sp = _iu.spec_from_file_location("gold", r"C:/Users/Nutzer/AppData/Local/Temp/claude/C--Users-Nutzer-Bot/eddba411-ddfd-4e86-81fb-6468504973ba/scratchpad/gold_mod.py"); gold = _iu.module_from_spec(_sp); _sp.loader.exec_module(gold)
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.data.enums import DataFeed, Adjustment

NOW = pd.Timestamp("2026-09-26", tz="UTC")
S, E = date(2017, 1, 1), date(2026, 9, 25)
nk = pd.concat([gold.load_minutes(Path("data_cache/dukascopy/idx"), "jpnidxjpy_*.csv"),
                gold.load_minutes(Path("data_cache/dukascopy/unseen"), "jpnidxjpy_*.csv")])["open"]
nk = nk[~nk.index.duplicated()].sort_index()
bid = pd.concat([gold.load_fx("usdjpy"), gold.load_fx("usdjpy", Path("data_cache/dukascopy/unseen_fx"))])
bid = bid[~bid.index.duplicated()].sort_index()
ask = gold.load_fx("usdjpy", Path("data_cache/dukascopy/fx_ask"))
n = pd.DataFrame(ft.nikkei_trades(nk, S, E, 0.5e-4, 0.0075, NOW))
g = pd.DataFrame(ft.gotobi_trades(bid, ask, S, E, 0.35e-4, NOW))
rn = n.groupby(pd.to_datetime(n["date"]))["net_bp"].sum() / 1e4
rg = g.groupby(pd.to_datetime(g["date"]))["net_bp"].sum() / 1e4

k, s, _ = read_account_env("copilot.env")
spy = StockHistoricalDataClient(k, s).get_stock_bars(StockBarsRequest(
    symbol_or_symbols="SPY", timeframe=TimeFrame.Day, start=datetime(2016, 12, 20, tzinfo=timezone.utc),
    end=datetime(2026, 9, 26, tzinfo=timezone.utc), adjustment=Adjustment.ALL, feed=DataFeed.SIP)).df.xs("SPY")
rs = spy.close.pct_change().dropna()
rs.index = rs.index.tz_convert(None).normalize()
days = pd.date_range("2017-01-01", "2026-09-25", freq="D")
df = pd.DataFrame({"spy": rs.reindex(days).fillna(0), "n": rn.reindex(days).fillna(0), "g": rg.reindex(days).fillna(0)})


def show(label, r):
    eq = (1 + r).cumprod()
    yrs = len(r) / 365.25
    cagr = eq.iloc[-1] ** (1 / yrs) - 1
    dd = (eq / eq.cummax() - 1).min()
    yearly = eq.resample("YE").last().pct_change()
    yearly.iloc[0] = eq.resample("YE").last().iloc[0] - 1
    print(f"{label:38s} {cagr * 100:6.1f} % p.a.  MaxDD {dd * 100:6.1f} %  Verlustjahre {(yearly < 0).sum()}/10")
    return yearly


base = show("S&P-500-ETF halten", df.spy)
for Ln, Lg in [(0.5, 0), (1, 0), (1, 3), (1, 5), (0.5, 3)]:
    y = show(f"ETF + Nikkei {Ln}x + Gotobi {Lg}x", df.spy + Ln * df.n + Lg * df.g)
    beat = (y > base).sum()
    print(f"{'':38s} besser als ETF in {beat} von 10 Jahren; Zusatz Ø {(Ln * df.n + Lg * df.g).mean() * 365.25 * 100:+.1f} %-Punkte p.a.")
for label, a, b in (("2017-2021", "2017", "2021"), ("2022-2026/09", "2022", "2026")):
    sub = df.loc[a:b]
    add = (sub.n + 3 * sub.g)
    print(f"Zusatz Nikkei 1x + Gotobi 3x {label}: {add.mean() * 365.25 * 100:+.1f} %-Punkte p.a.")

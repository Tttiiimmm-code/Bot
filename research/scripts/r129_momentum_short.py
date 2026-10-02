"""Was wäre, wenn der Momentum-Bot geshortet hätte? Nur lesend (Orders, Kurse, Quotes)."""
import math
from datetime import datetime, timedelta, timezone

import pandas as pd
from alpaca.data.enums import DataFeed
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest, StockQuotesRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import QueryOrderStatus
from alpaca.trading.requests import GetOrdersRequest

from tradingbot.report import read_account_env

k, s, p = read_account_env(".env")
tc, dc = TradingClient(k, s, paper=p), StockHistoricalDataClient(k, s)
orders = []
after = datetime(2026, 9, 20, tzinfo=timezone.utc)
while True:
    batch = tc.get_orders(GetOrdersRequest(status=QueryOrderStatus.CLOSED, after=after, limit=500, direction="asc"))
    batch = [o for o in batch if o.submitted_at > after]
    if not batch:
        break
    orders += batch
    after = batch[-1].submitted_at
fills = sorted([o for o in orders if o.filled_at and float(o.filled_qty or 0) > 0], key=lambda o: o.filled_at)

# Runde: Kauf -> folgende Verkäufe desselben Symbols bis Menge glatt
trades, open_ = [], {}
for o in fills:
    q, px = float(o.filled_qty), float(o.filled_avg_price)
    if o.side.value == "buy":
        open_.setdefault(o.symbol, {"t": o.filled_at, "px": px, "q": 0.0, "sold": []})["q"] += q
    elif o.symbol in open_:
        t = open_[o.symbol]
        t["sold"].append((o.filled_at, px, q))
        if sum(x[2] for x in t["sold"]) >= t["q"] - 1e-9:
            exit_px = sum(x[1] * x[2] for x in t["sold"]) / sum(x[2] for x in t["sold"])
            trades.append(dict(sym=o.symbol, t_in=t["t"], px_in=t["px"], t_out=t["sold"][-1][0], px_out=exit_px))
            del open_[o.symbol]
print(f"{len(trades)} abgeschlossene Long-Trades ({trades[0]['t_in']:%d.%m.} bis {trades[-1]['t_in']:%d.%m.})")


def spread_at(sym, t):
    q = dc.get_stock_quotes(StockQuotesRequest(symbol_or_symbols=sym, start=t - timedelta(seconds=30), end=t,
                                               feed=DataFeed.SIP)).df
    if q.empty:
        return float("nan")
    q = q.iloc[-1]
    mid = (q.ask_price + q.bid_price) / 2
    return (q.ask_price - q.bid_price) / mid if mid > 0 and q.ask_price > q.bid_price else float("nan")


def nz(x, default=0.0):
    return default if math.isnan(x) else x


rows = []
for tr in trades:
    sym, t0 = tr["sym"], tr["t_in"]
    long_ret = tr["px_out"] / tr["px_in"] - 1
    sp_in, sp_out = spread_at(sym, t0), spread_at(sym, tr["t_out"])
    day_end = pd.Timestamp(t0).tz_convert("America/New_York").normalize() + pd.Timedelta(hours=16)
    bars = dc.get_stock_bars(StockBarsRequest(symbol_or_symbols=sym, timeframe=TimeFrame.Minute, start=t0,
                                              end=day_end.tz_convert("UTC"), feed=DataFeed.SIP)).df
    b = bars.xs(sym, level=0) if not bars.empty else bars
    b = b[b.index > t0]
    row = dict(sym=sym, day=f"{t0:%m-%d}", price=tr["px_in"], long=long_ret, sp_in=sp_in, sp_out=sp_out,
               mirror=-long_ret - nz(sp_in) - nz(sp_out))
    if len(b):
        e = b.open.iloc[0]
        cost = nz(sp_in, 0.01)                         # Round-Trip = ein voller Spread (2 x halber)
        for name, mins in (("15", 15), ("30", 30), ("60", 60), ("Schluss", 10_000)):
            for stop in (0.10, 0.20):
                w = b[b.index <= t0 + timedelta(minutes=mins)]
                hit = w[w.high >= e * (1 + stop)]
                if len(hit):
                    ex = max(hit.open.iloc[0], e * (1 + stop))   # Kurslücke über Stop -> Eröffnungskurs
                else:
                    ex = w.close.iloc[-1]
                row[f"short_{name}_{int(stop * 100)}"] = e / ex - 1 - cost
        row["mfe_up_60"] = b[b.index <= t0 + timedelta(minutes=60)].high.max() / e - 1
    rows.append(row)

df = pd.DataFrame(rows)
df.to_csv("/tmp/momentum_short.csv", index=False)


def show(col, label):
    x = df[col].dropna()
    t = x.mean() / x.std(ddof=1) * math.sqrt(len(x)) if len(x) > 2 and x.std() > 0 else float("nan")
    print(f"{label:34s} n {len(x):3d}  Ø {x.mean():+.2%}  Median {x.median():+.2%}  im Plus {(x > 0).mean():.0%}  "
          f"t {t:+.2f}  schlechtester {x.min():+.1%}")


print(f"Kurs Median {df.price.median():.2f} $, Spread beim Einstieg Median {df.sp_in.median():.2%}, Ø {df.sp_in.mean():.2%}")
show("long", "Long (echt, Fills)")
show("mirror", "Short gespiegelt (gleiche Zeiten)")
for name in ("15", "30", "60", "Schluss"):
    for stop in (10, 20):
        label = f"Short {name} Min, Stop +{stop} %" if name != "Schluss" else f"Short bis Schluss, Stop +{stop} %"
        show(f"short_{name}_{stop}", label)
print(f"Anstieg nach Einstieg (60 Min, bester Punkt): Ø {df.mfe_up_60.mean():+.1%}, >= +20 %: {(df.mfe_up_60 >= 0.2).sum()}")
by_day = df.groupby("day")["short_Schluss_20"].mean()
print("Short bis Schluss (+20 % Stop) je Tag:", ", ".join(f"{d} {v:+.1%}" for d, v in by_day.items()))
syms = sorted(df.sym.unique())
sh = {a.symbol: (a.shortable, a.easy_to_borrow) for a in (tc.get_asset(x) for x in syms)}
print(f"Heute leihbar (Alpaca): shortable {sum(bool(v[0]) for v in sh.values())}/{len(syms)}, "
      f"easy_to_borrow {sum(bool(v[1]) for v in sh.values())}/{len(syms)}")

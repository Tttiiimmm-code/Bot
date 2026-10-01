"""Erster beschreibender Blick auf die Liquidationsdaten vom VPS (kein Test, keine Vorab-Registrierung nötig)."""
import json
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

D = Path("data_cache/liquidations_vps")
frames = []
for f in sorted(D.glob("*_2026-*.csv")):
    x = pd.read_csv(f)
    x["exchange"] = f.name.split("_")[0]
    frames.append(x)
liq = pd.concat(frames, ignore_index=True)
liq["t"] = pd.to_datetime(liq["trade_ms"], unit="ms", utc=True)
liq["usd"] = liq["price"] * liq["qty"]
# Binance-Coin-Kontrakte (z.B. BTCUSD_PERP): Menge = Kontrakte zu 100 $ (BTC) bzw. 10 $ (andere), nicht Coins
coinm = liq["symbol"].str.contains("USD_")
liq.loc[coinm, "usd"] = liq.loc[coinm, "qty"] * np.where(liq.loc[coinm, "symbol"].str.startswith("BTC"), 100, 10)
print(f"Zeitraum {liq.t.min():%Y-%m-%d %H:%M} bis {liq.t.max():%Y-%m-%d %H:%M} UTC, {len(liq):,} Liquidationen")
for ex, g in liq.groupby("exchange"):
    print(f"\n== {ex}: {len(g):,} Ereignisse, {g.usd.sum() / 1e6:,.0f} Mio. $ (long {g[g.liquidated == 'long'].usd.sum() / 1e6:,.0f}"
          f" / short {g[g.liquidated == 'short'].usd.sum() / 1e6:,.0f}), {g.symbol.nunique()} Symbole")
    top = g.groupby("symbol").usd.sum().sort_values(ascending=False).head(8)
    print("  größte Symbole (Mio. $): " + ", ".join(f"{s} {v / 1e6:.1f}" for s, v in top.items()))
by_day = liq.groupby([liq.t.dt.date, "exchange"]).usd.sum().unstack() / 1e6
print("\nJe Tag (Mio. $):\n" + by_day.round(1).to_string())
hour = liq.groupby(liq.t.dt.hour).usd.sum() / 1e6
print("\nJe Stunde UTC (Mio. $, alle Tage): " + ", ".join(f"{h}h {v:.0f}" for h, v in hour.items()))


def klines(sym, start_ms, end_ms):
    out, s = [], start_ms
    while s < end_ms:
        url = f"https://fapi.binance.com/fapi/v1/klines?symbol={sym}&interval=1m&startTime={s}&limit=1500"
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "research"}), timeout=30) as r:
            rows = json.load(r)
        if not rows:
            break
        out += rows
        s = rows[-1][0] + 60_000
    k = pd.DataFrame(out, columns=list(range(len(out[0]))))
    s = pd.Series(k[4].astype(float).to_numpy(), index=pd.to_datetime(k[0], unit="ms", utc=True))
    return s[~s.index.duplicated()]


print("\n== Kurs nach großen Liquidationswellen (5-Minuten-Summe, Binance+Bybit, oberste 2 % der 5-Min-Fenster)")
t0, t1 = int(liq.trade_ms.min()), int(liq.trade_ms.max())
pooled = {}
for sym in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
    px = klines(sym, t0, t1 + 3_600_000)
    g = liq[liq.symbol == sym]
    w = g.set_index("t").groupby("liquidated").usd.resample("5min").sum().unstack(0).fillna(0).reindex(
        px.resample("5min").last().index, fill_value=0)
    fwd = {h: (px.shift(-h) / px - 1).resample("5min").last() for h in (15, 60, 240)}
    for side in ("long", "short"):
        if side not in w:
            continue
        thr = w[side].quantile(0.98)
        ev = w.index[(w[side] >= thr) & (w[side] > 0)]
        ev = ev.as_unit("ns")
        ev = ev[np.r_[True, np.diff(ev.asi8) > 30 * 60 * 10**9]]          # Wellen mind. 30 Min. auseinander
        parts = []
        for h, f in fwd.items():
            # Einstieg zum Schluss des 5-Min-Fensters, Rendite in bp; Vergleich: alle Fenster
            e = (f.reindex(ev + pd.Timedelta(minutes=5)).dropna() * 1e4)
            pooled.setdefault((side, h), []).extend(e.tolist())
            parts.append(f"{h} Min: Ø {e.mean():+.0f} bp (alle Fenster {f.mean() * 1e4:+.1f})")
        print(f"  {sym} {side}-Liquidationen >= {thr / 1e3:,.0f} Tsd. $/5 Min: {len(ev)} Wellen | " + " | ".join(parts))
print("\n== Zusammen (BTC, ETH, SOL)")
for (side, h), v in sorted(pooled.items()):
    v = np.array(v)
    t = v.mean() / v.std(ddof=1) * np.sqrt(len(v)) if len(v) > 2 and v.std() > 0 else float("nan")
    print(f"  nach {side}-Welle, {h:3d} Min: n {len(v):2d}, Ø {v.mean():+.0f} bp, positiv {(v > 0).mean():.0%}, t {t:+.2f}")
print("\nHinweis: 5 Tage, wenige Wellen -- nur Beschreibung, kein Beleg. Long-Liquidation = Zwangsverkauf (Kurs fiel).")

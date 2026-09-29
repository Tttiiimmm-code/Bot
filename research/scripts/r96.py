"""Runde 96: News-Momentum (Chan 2003) -- Vorab-Registrierung in PROTOCOL.md."""
import collections
import json
from pathlib import Path

import numpy as np
import pandas as pd

from tradingbot.research import ml_rank as ml

COST = 20e-4
PERIODS = {
    "P1 2016-2020": (pd.Timestamp("2016-01-01"), pd.Timestamp("2020-12-31")),
    "P2 2021-2025-09": (pd.Timestamp("2021-01-01"), pd.Timestamp("2025-09-19")),
    "unberührt 2025-09..": (pd.Timestamp("2025-09-22"), pd.Timestamp("2026-12-31")),
}

wide = ml.load_wide()
c, v = wide["close"], wide["volume"]
del wide
days = c.index
cols = c.columns
col_idx = {s: i for i, s in enumerate(cols)}
C = c.to_numpy(float)
Cf = c.ffill().to_numpy(float)  # für Delisting: letzter bekannter Schluss
prev_close = c.shift(1)
dv20_prev = (c * v).rolling(20).mean().shift(1)
U = ((prev_close > 5) & (dv20_prev >= 5e6)).to_numpy(bool)
del v, dv20_prev, prev_close

# Nachrichtenzahl je (Tag, Symbol) im Nacht-Fenster vor dem Tag
counts = np.zeros(C.shape, dtype=np.int16)
day_idx = {d: i for i, d in enumerate(days)}
has_news_file = np.zeros(len(days), bool)
for p in sorted(Path("data_cache/r92/news").glob("*.json")):
    d = pd.Timestamp(p.stem)
    if d not in day_idx:
        continue
    i = day_idx[d]
    has_news_file[i] = True
    cnt = collections.Counter()
    for r in json.loads(p.read_text()):
        for s in set(r["sym"]):
            if s in col_idx:
                cnt[s] += 1
    for s, n in cnt.items():
        counts[i, col_idx[s]] = min(n, 32000)

with np.errstate(invalid="ignore", divide="ignore"):
    R = C / np.vstack([np.full(C.shape[1], np.nan), C[:-1]]) - 1
    ew_day = np.nanmean(np.where(U, R, np.nan), axis=1)
reaction = R - ew_day[:, None]


def forward(i: int, h: int, js: np.ndarray) -> np.ndarray:
    """Buy-and-hold-Rendite Schluss i -> Schluss i+h (Delisting: letzter bekannter Schluss)."""
    k = min(i + h, len(days) - 1)
    return Cf[k, js] / C[i, js] - 1


def study(sel_fn, h: int) -> pd.DataFrame:
    """Je Kauftag: Ø Überrendite (netto) der ausgewählten Titel ggü. dem Ø aller Universums-Titel."""
    out = {}
    for i in range(1, len(days) - h):
        if not has_news_file[i]:
            continue
        uni = np.flatnonzero(U[i] & np.isfinite(C[i]))
        if len(uni) < 50:
            continue
        sel = uni[sel_fn(i, uni)]
        if len(sel) == 0:
            continue
        with np.errstate(invalid="ignore", divide="ignore"):
            bench = np.nanmean(forward(i, h, uni))
            r = forward(i, h, sel) - bench - COST
        r = r[np.isfinite(r)]
        if len(r):
            out[days[i]] = (float(r.mean()), len(r))
    return pd.DataFrame(out, index=["ret", "n"]).T


def report(label: str, s: pd.DataFrame) -> pd.DataFrame:
    parts = [f"{label:46s}"]
    for pname, (a, b) in PERIODS.items():
        x = s[(s.index >= a) & (s.index <= b)]
        parts.append(f"{pname}: Tage {len(x)}, Ereign. {int(x['n'].sum())}, "
                     f"Ø {x['ret'].mean() * 1e4:+.1f} bp (t {ml.t_stat(x['ret']):+.2f})")
    print(" | ".join(parts), flush=True)
    return s


ev = (counts >= 3) & U
print("Ereignisse (>=3 Artikel, im Universum) je Jahr:",
      {int(y): int(ev[days.year == y].sum()) for y in sorted(set(days.year))}, flush=True)
res = {}
for h in (5, 1, 20):
    tag = "PRIMÄR " if h == 5 else ""
    res[h] = report(f"{tag}News >=3, Reaktion >= +2 %, halten {h} T",
                    study(lambda i, uni: (counts[i, uni] >= 3) & (reaction[i, uni] >= 0.02), h))
report("News >=3, Reaktion <= -2 % (Info), 5 T",
       study(lambda i, uni: (counts[i, uni] >= 3) & (reaction[i, uni] <= -0.02), 5))
report("OHNE News, Reaktion >= +2 % (Chan: Umkehr), 5 T",
       study(lambda i, uni: (counts[i, uni] == 0) & (reaction[i, uni] >= 0.02), 5))
report("News >=3, alle Reaktionen (Info), 5 T", study(lambda i, uni: counts[i, uni] >= 3, 5))

s = res[5]
p1, p2, u = (s[(s.index >= a) & (s.index <= b)]["ret"] for a, b in PERIODS.values())
ok = ml.t_stat(p1) >= 2 and ml.t_stat(p2) >= 2 and u.mean() > 0
yr = s["ret"].groupby(s.index.year).mean() * 1e4
print("PRIMÄR Ø bp je Jahr:", " ".join(f"{k}: {val:+.0f}" for k, val in yr.items()))
print(f"Kriterien: t P1 {ml.t_stat(p1):+.2f}, t P2 {ml.t_stat(p2):+.2f}, unberührt {u.mean() * 1e4:+.1f} bp -> "
      f"{'BESTANDEN' if ok else 'NICHT BESTANDEN'}")

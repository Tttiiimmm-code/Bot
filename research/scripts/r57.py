"""Runde 57: NT-Verhältnis vor den japanischen Dividendenstichtagen."""
from datetime import date, timedelta
from pathlib import Path
import numpy as np, pandas as pd
from tradingbot.research import history

base = Path("data_cache/yahoo_unseen")
px = {}
for s in ("1306.T", "1321.T"):
    df = history.fetch_yahoo(s, base=base, until=date(2026, 9, 26))
    px[s] = pd.Series(df["adjclose"].to_numpy(), index=[d + timedelta(days=1) for d in df.index])
P = pd.DataFrame(px).dropna()
idx = list(P.index)
rows = []
for y in range(2009, 2027):
    for m in (3, 9):
        month_days = [d for d in idx if d.year == y and d.month == m]
        if not month_days or month_days[-1].day < 25:
            continue  # Monat unvollständig in den Daten
        rec = month_days[-1]
        lag = 3 if rec < date(2019, 7, 15) else 2
        i_rec = idx.index(rec)
        i_cum = i_rec - lag
        for K in (5, 10):
            i0 = i_cum - K
            r_t = P["1306.T"].iloc[i_cum] / P["1306.T"].iloc[i0] - 1
            r_n = P["1321.T"].iloc[i_cum] / P["1321.T"].iloc[i0] - 1
            rows.append({"event": idx[i_cum], "K": K, "r": r_t - r_n - 4 * 0.0001})
ev = pd.DataFrame(rows)
res = {}
for K in (5, 10):
    e = ev[ev["K"] == K].set_index("event")["r"]
    full = e[e.index <= date(2025, 9, 19)]
    h1, h2 = full[full.index < date(2017, 1, 1)], full[full.index >= date(2017, 1, 1)]
    new = e[e.index > date(2025, 9, 19)]
    t = full.mean() / full.std() * np.sqrt(len(full))
    res[K] = (t, h1.mean(), h2.mean(), new.mean() if len(new) else np.nan)
    print(f"K={K:2d}: 2009-2025 {len(full)} Ereignisse Ø {full.mean() * 1e4:6.1f} bp Treffer {(full > 0).mean():.0%} t {t:5.2f} | "
          f"2009-2016 Ø {h1.mean() * 1e4:6.1f} bp ({len(h1)}) | 2017-2025 Ø {h2.mean() * 1e4:6.1f} bp ({len(h2)}) | "
          f"unberührt {[(str(d), round(v * 1e4, 1)) for d, v in new.items()]}")
best = max(res, key=lambda k: res[k][0])
t, a, b, n = res[best]
ok = t >= 2.24 and a > 0 and b > 0 and n > 0
print(f"gewählt K={best} -> {'BESTANDEN' if ok else 'NICHT BESTANDEN'}")

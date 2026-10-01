"""FINRA Reg SHO Daily Short Sale Volume (FNSQ + FNYX), 2016-01 bis 2026-09 -> data_cache/finra_short/YYYY-MM.pkl."""
import io
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

OUT = Path("data_cache/finra_short")
OUT.mkdir(parents=True, exist_ok=True)
URL = "https://cdn.finra.org/equity/regsho/daily/{f}shvol{d}.txt"
z = np.load(Path(__file__).with_name("r114_wide.npz"), allow_pickle=True)
DAYS = pd.DatetimeIndex(z["dates"])


def get(f, d):
    url = URL.format(f=f, d=d.strftime("%Y%m%d"))
    for attempt in range(5):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "research-script"}),
                                        timeout=60) as r:
                raw = r.read()
            df = pd.read_csv(io.BytesIO(raw), sep="|", usecols=["Symbol", "ShortVolume", "TotalVolume"],
                             dtype={"Symbol": str})
            return df.dropna()
        except urllib.error.HTTPError as e:
            if e.code == 403:
                return None
            time.sleep(2 ** attempt)
        except Exception:  # noqa: BLE001
            time.sleep(2 ** attempt)
    return None


def day(d):
    parts = [x for x in (get("FNSQ", d), get("FNYX", d)) if x is not None]
    if not parts:
        return None
    df = pd.concat(parts).groupby("Symbol", as_index=False)[["ShortVolume", "TotalVolume"]].sum()
    df.columns = ["symbol", "short", "total"]
    df.insert(0, "date", d)
    return df


for month, ds in pd.Series(DAYS, index=DAYS).groupby(DAYS.to_period("M")):
    f = OUT / f"{month}.pkl"
    if f.exists():
        continue
    with ThreadPoolExecutor(6) as ex:
        res = [r for r in ex.map(day, list(ds)) if r is not None]
    if res:
        pd.concat(res, ignore_index=True).to_pickle(f)
    print(month, len(res), "Tage", flush=True)
print("fertig")

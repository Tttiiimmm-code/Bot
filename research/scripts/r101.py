"""Runde 101: 9:30-ORB bei EUR/USD und Gold (YouTube IRONCLAD) -- Vorab-Registrierung in PROTOCOL.md."""
from pathlib import Path

import numpy as np
import pandas as pd

from tradingbot.research import gold
from tradingbot.research import ml_rank as ml

D = Path("data_cache/dukascopy")
COMMISSION = 0.4e-4
RR = 1.5
PERIODS = {"P1 2008-2014": ("2008-01-01", "2014-12-31"), "P2 2015-2020": ("2015-01-01", "2020-12-31"),
           "Quelle 2021-2026": ("2021-01-01", "2026-12-31")}


def load(bid_dirs: list[tuple[Path, str]], ask_dir: Path, ask_pattern: str) -> tuple[pd.DataFrame, pd.Series]:
    bid = pd.concat([gold.load_minutes(d, p) for d, p in bid_dirs])
    bid = bid[~bid.index.duplicated()].sort_index().tz_convert("America/New_York")
    ask = gold.load_minutes(ask_dir, ask_pattern)["open"].tz_convert("America/New_York")
    return bid, ask[~ask.index.duplicated()].sort_index()


def trades(bid: pd.DataFrame, ask: pd.Series) -> pd.DataFrame:
    rows = []
    sess = bid.between_time("09:30", "15:59")
    for day, g in sess.groupby(sess.index.date):
        if pd.Timestamp(day).weekday() >= 5:
            continue
        rng = g.between_time("09:30", "09:44")
        after = g.between_time("09:45", "15:59")
        if len(rng) < 10 or after.empty:
            continue
        hi, lo = rng["high"].max(), rng["low"].min()
        risk = hi - lo
        if risk <= 0:
            continue
        up = after["high"].to_numpy() > hi
        dn = after["low"].to_numpy() < lo
        hit = np.flatnonzero(up | dn)
        if not len(hit) or (up[hit[0]] and dn[hit[0]]):
            continue
        k = hit[0]
        side = 1 if up[k] else -1
        entry = hi if side > 0 else lo
        stop, target = entry - side * risk, entry + side * RR * risk
        rest = after.iloc[k:]
        exit_px, reason = None, "Zeit"
        for i, (h, l_) in enumerate(zip(rest["high"].to_numpy(), rest["low"].to_numpy())):
            if i == 0:  # Einstiegsminute: nur Stop prüfen, wenn Kurs bereits durch die ganze Range lief
                if (side > 0 and l_ <= stop) or (side < 0 and h >= stop):
                    exit_px, reason = stop, "Stop"
                    break
                continue
            stop_hit = l_ <= stop if side > 0 else h >= stop
            tgt_hit = h >= target if side > 0 else l_ <= target
            if stop_hit:
                exit_px, reason = stop, "Stop"
                break
            if tgt_hit:
                exit_px, reason = target, "Ziel"
                break
        if exit_px is None:
            exit_px = rest["close"].iloc[-1]
        t_entry = rest.index[0]
        a = ask.get(t_entry)
        spread = (a - rest["open"].iloc[0]) if a is not None and np.isfinite(a) else np.nan
        gross = side * (exit_px / entry - 1)
        cost = (spread / entry if np.isfinite(spread) and spread >= 0 else np.nan) + COMMISSION
        rows.append({"day": pd.Timestamp(day), "side": side, "gross": gross, "net": gross - cost, "reason": reason})
    return pd.DataFrame(rows).set_index("day")


def report(label: str, t: pd.DataFrame) -> None:
    print(label)
    for pname, (a, b) in PERIODS.items():
        x = t[(t.index >= a) & (t.index <= b)]
        n = x["net"].dropna()
        pf = n[n > 0].sum() / -n[n < 0].sum() if (n < 0).any() else float("nan")
        share = x["reason"].value_counts(normalize=True)
        print(f"   {pname}: n {len(n)}, netto Ø {n.mean() * 1e4:+.1f} bp (t {ml.t_stat(n):+.2f}), brutto "
              f"{x['gross'].mean() * 1e4:+.1f} bp, Treffer {(n > 0).mean():.0%}, PF {pf:.2f}, "
              f"Ziel/Stop/Zeit {share.get('Ziel', 0):.0%}/{share.get('Stop', 0):.0%}/{share.get('Zeit', 0):.0%}", flush=True)
    yr = t["net"].groupby(t.index.year).sum() * 100
    print("   Summe % je Jahr:", " ".join(f"{k}: {v:+.1f}" for k, v in yr.items()), flush=True)


verdict = []
for name, bid_dirs, ask_dir, ask_pat in [
    ("EUR/USD", [(D / "fx", "eurusd_*.csv"), (D / "unseen_fx", "eurusd_*.csv")], D / "fx_ask", "eurusd_*.csv"),
    ("Gold", [(D / "xau", "xau_*.csv"), (D / "unseen_xau", "xau_*.csv")], D / "xau_ask", "xau_*.csv"),
]:
    bid, ask = load(bid_dirs, ask_dir, ask_pat)
    t = trades(bid, ask)
    report(f"{name}: {len(t)} Trades", t)
    p1 = t["net"][(t.index >= "2008-01-01") & (t.index <= "2014-12-31")].dropna()
    p2 = t["net"][(t.index >= "2015-01-01") & (t.index <= "2020-12-31")].dropna()
    verdict.append(f"{name}: t P1 {ml.t_stat(p1):+.2f}, t P2 {ml.t_stat(p2):+.2f} -> "
                   f"{'BESTANDEN' if ml.t_stat(p1) >= 2.24 and ml.t_stat(p2) >= 2.24 else 'NICHT BESTANDEN'}")
print("Kriterien (t >= 2,24 in P1 und P2):", " | ".join(verdict))

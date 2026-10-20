"""Vorwärtstest "gold_breakout" (Papier, keine Orders) -- Nachbau des MQL5-Bestsellers "The Gold Reaper",
Runde 134/Vorab-Regel in research/PROTOCOL.md (eigene Familie, Auswertung 2028-10-01).

Regeln: Zu Beginn jeder Stunde (UTC), wenn flach und keine Order offen: Buy-Stop 0,1 ATR über dem höchsten Hoch der
letzten 48 abgeschlossenen H1-Kerzen (Füllung zum Briefkurs), gültig 12 Stunden; Stop 2 ATR, Ziel 4 ATR ab Füllung;
nur long. ATR14 (Wilder) auf H1-Geldkursen. Keine neuen Orders Fr ab 20:00 UTC, offene Orders Fr 20:55 gelöscht.
Ausstieg auf Geldkurs; Stop vor Ziel in derselben Minute; Kurslücke -> Eröffnungskurs; Einstiegsminute: nur Stop.
Swap 6,3 % p.a. auf den Positionswert je gehaltenem Tag (CFD).

Kurse (seit 2026-10-20; Dukascopy blockt seit 2026-10-09, Nutzer: nicht weiter versuchen): CME-Gold-Future von Yahoo,
Einzelkontrakte verkettet (intraday_backup.continuous, Wechsel am 20. des Vormonats der Lieferung), 1-Minuten-Kerzen,
ältere Lücken mit 5-Minuten-Kerzen. Mittelkurs +- halbe Spanne (2,04 bp = Dukascopy-Mittel Aug/Sep 2026) als
Brief/Geld. Im Future steckt die Finanzierung schon (Abstand zum Spot schrumpfte Aug/Sep 2026 um 4,3 % p.a.) ->
Swap 6,3 % - 4,3 % = 2,0 % p.a. Abgleich mit Dukascopy Aug/Sep 2026: 9 statt 10 Trades, gleiche Ergebnisse je Trade
(research/PROTOCOL.md, Eintrag vom 2026-10-20). Der Lauf rechnet jedes Mal ab first_day - 14 Tagen (Vorlauf für
Level und ATR) neu und schreibt alle abgeschlossenen Trades (idempotent).
"""

from __future__ import annotations

import csv
import logging
import math
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

FIELDS = ["entry_time", "exit_time", "entry", "exit", "risk", "r", "swap_r", "r_net"]
SWAP_RATE = 0.063            # CFD-Swap (OANDA, Backtest)
FUTURES_CARRY = 0.043        # im Future-Kurs enthaltene Finanzierung
EXPECTED_R = 0.165


@dataclass(frozen=True)
class GoldConfig:
    first_day: date = date(2026, 10, 5)
    ledger: Path = Path("forward_gold.csv")
    yahoo_dir: Path = Path("data_cache") / "yahoo_intraday"
    swap_rate: float = SWAP_RATE - FUTURES_CARRY
    spread: float = 2.04e-4
    n_lvl: int = 48
    expiry_h: int = 12
    sl_atr: float = 2.0
    tp_atr: float = 4.0
    buffer_atr: float = 0.1
    warmup_days: int = 14


def prepare(bid: pd.DataFrame, ask: pd.DataFrame) -> pd.DataFrame:
    """Wie Runde 134: gemeinsame Minuten, Samstag/Sonntag vor 22 UTC und Flachminuten raus, Brief >= Geld."""
    idx = bid.index.intersection(ask.index)
    b, a = bid.loc[idx].sort_index(), ask.loc[idx].sort_index()
    t = b.index
    keep = (a["close"].to_numpy() >= b["close"].to_numpy()) & ~((t.weekday == 5) | ((t.weekday == 6) & (t.hour < 22)))
    keep &= ~((b["high"] == b["low"]).to_numpy() & (b["open"] == b["close"]).to_numpy())
    return b[keep].add_prefix("b").join(a[keep].add_prefix("a"))


def simulate(m: pd.DataFrame, cfg: GoldConfig) -> list[dict]:
    """m: Minuten (UTC-Index) mit bopen/bhigh/blow/bclose/aopen/ahigh/alow/aclose. Abgeschlossene Trades."""
    t = m.index
    hk = t.as_unit("ns").asi8 // 3_600_000_000_000
    _, h_of_m = np.unique(hk, return_inverse=True)
    hb = pd.DataFrame({"h": m["bhigh"].to_numpy(float), "l": m["blow"].to_numpy(float),
                       "c": m["bclose"].to_numpy(float), "k": h_of_m}).groupby("k").agg(
        h=("h", "max"), l=("l", "min"), c=("c", "last"))
    pc = hb["c"].shift(1)
    tr = np.maximum(hb["h"] - hb["l"], np.maximum((hb["h"] - pc).abs(), (hb["l"] - pc).abs()))
    atr = tr.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean().to_numpy()
    hh = hb["h"].to_numpy()
    bo, bh, bl = (m[c].to_numpy(float) for c in ("bopen", "bhigh", "blow"))
    ao, ah = m["aopen"].to_numpy(float), m["ahigh"].to_numpy(float)
    wd, hr, mi = t.weekday, t.hour, t.minute
    fri_stop = (wd == 4) & (hr >= 20)
    fri_cancel = (wd == 4) & ((hr > 20) | ((hr == 20) & (mi >= 55)))
    trades = []
    pos = pend = False
    buy_lvl = pend_atr = entry = sl = tp = risk = 0.0
    pend_until = -1
    e_idx = 0

    def close(i, price):
        trades.append({"e": e_idx, "x": i, "entry": entry, "exit": price, "risk": risk, "r": (price - entry) / risk})

    for i in range(1, len(m)):
        if h_of_m[i] != h_of_m[i - 1] and not pos and not pend and not fri_stop[i]:
            kk = h_of_m[i]
            if kk - cfg.n_lvl >= 15 and not math.isnan(atr[kk - 1]):
                a = atr[kk - 1]
                buy_lvl, pend_atr = float(hh[kk - cfg.n_lvl:kk].max()) + cfg.buffer_atr * a, a
                pend, pend_until = True, kk + cfg.expiry_h
        if pend:
            if h_of_m[i] >= pend_until or fri_cancel[i]:
                pend = False
            elif ah[i] >= buy_lvl:
                entry = max(ao[i], buy_lvl)
                pos, pend = True, False
                risk = cfg.sl_atr * pend_atr
                sl, tp = entry - risk, entry + cfg.tp_atr * pend_atr
                e_idx = i
                if bl[i] <= sl:                              # Einstiegsminute: nur Stop prüfen
                    close(i, sl)
                    pos = False
                continue
        if pos:
            if bo[i] <= sl or bo[i] >= tp:
                close(i, bo[i])
                pos = False
            elif bl[i] <= sl:
                close(i, sl)
                pos = False
            elif bh[i] >= tp:
                close(i, tp)
                pos = False
    out = []
    for tr_ in trades:
        te, tx = t[tr_["e"]], t[tr_["x"]]
        days = (tx - te).total_seconds() / 86400
        swap_r = cfg.swap_rate * days / 365 * tr_["entry"] / tr_["risk"]
        out.append({"entry_time": te.isoformat(), "exit_time": tx.isoformat(), "entry": round(tr_["entry"], 3),
                    "exit": round(tr_["exit"], 3), "risk": round(tr_["risk"], 3), "r": round(tr_["r"], 4),
                    "swap_r": round(swap_r, 4), "r_net": round(tr_["r"] - swap_r, 4)})
    return out


def load_minutes(cfg: GoldConfig, now: pd.Timestamp) -> pd.DataFrame:
    from tradingbot import intraday_backup

    start = pd.Timestamp(cfg.first_day - timedelta(days=cfg.warmup_days), tz="UTC")
    mid = intraday_backup.continuous("gc", start, now, cfg.yahoo_dir)
    h = cfg.spread / 2
    return prepare(mid * (1 - h), mid * (1 + h))


def write_ledger(path: Path, trades: list[dict], first_day: date) -> int:
    rows = [t for t in trades if t["entry_time"] >= pd.Timestamp(first_day, tz="UTC").isoformat()]
    old = 0
    if path.exists():
        with path.open(newline="", encoding="utf-8") as f:
            old = sum(1 for _ in csv.DictReader(f))
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    tmp.replace(path)
    return len(rows) - old


def summarize(path: Path) -> str:
    if not path.exists():
        return "gold_breakout: noch keine Trades"
    with path.open(newline="", encoding="utf-8") as f:
        r = [float(x["r_net"]) for x in csv.DictReader(f)]
    if not r:
        return "gold_breakout: noch keine Trades"
    m = sum(r) / len(r)
    sd = math.sqrt(sum((x - m) ** 2 for x in r) / (len(r) - 1)) if len(r) > 1 else 0.0
    t = m / sd * math.sqrt(len(r)) if sd > 0 else float("nan")
    return (f"gold_breakout: {len(r)} Trades, Ø {m:+.3f} R netto (Erwartung {EXPECTED_R:+.3f}), Treffer "
            f"{sum(x > 0 for x in r) / len(r):.0%}, Summe {sum(r):+.1f} R, t {t:.2f}")


def run(cfg: GoldConfig, now: pd.Timestamp | None = None, refresh=None) -> str:
    from tradingbot import intraday_backup

    now = now or pd.Timestamp.now(tz="UTC")
    try:
        logger.info((refresh or intraday_backup.run)(cfg.yahoo_dir))
    except Exception as exc:  # noqa: BLE001 -- dann mit den bereits gespeicherten Kursen rechnen
        logger.warning("Yahoo-Aufzeichnung unvollständig: %s", exc)
    m = load_minutes(cfg, now)
    new = write_ledger(cfg.ledger, simulate(m, cfg), cfg.first_day)
    logger.info("gold_breakout: Minuten bis %s, %d neue Trades.", m.index[-1] if len(m) else "-", new)
    return summarize(cfg.ledger)

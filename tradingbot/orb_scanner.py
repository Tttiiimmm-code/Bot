"""Setup-Melder für den Copilot: Eröffnungsausbruch (ORB) auf den aktivsten Aktien des Tages.

Auswahl wie im Vorwärtstest und in den Forschungsrunden 107/107b: Grundfilter (Vortagesschluss > 5 $, Ø-Volumen
der 14 Vortage > 1 Mio., ATR14 > 0,50 $), Rang nach relativem Volumen der ersten 5 Minuten (9:30-9:35 ET) gegenüber
dem Ø der 14 Vortage, Top 5. Die erste 5-Minuten-Kerze bestimmt Richtung (grün = long, rot = short) und Range;
Einstieg beim Ausbruch über das Range-Hoch (long), Stop auf der Gegenseite der Range, Ziel 2 R, gültig bis 15:00 ET.

Ehrliche Einordnung (Backtest 2016-2026): nach Kosten leicht positiv (+0,03 R je Trade), statistisch NICHT
gesichert. Klar belegt ist nur: Stops auf der Gegenseite der Range schlagen enge Stops deutlich.
Der Copilot handelt nur long -- Short-Setups werden nur angezeigt.

Das erste Laden eines Tages holt Tageskurse aller US-Aktien und die Eröffnungskerzen der letzten 14 Tage
(einige Minuten); danach liegt alles im Tages-Cache (data_cache/copilot_orb/<Datum>).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

logger = logging.getLogger(__name__)

NY = ZoneInfo("America/New_York")
CACHE_DIR = Path("data_cache") / "copilot_orb"
TOP_N = 5
LOOKBACK = 14
MIN_HISTORY = 10
CUTOFF_ET = time(15, 0)
READY_ET = time(9, 52)        # erste 5-Minuten-Kerze + 15 Min. SIP-Verzögerung
MIN_DOLLAR_VOLUME = 20e6      # Ø-Tagesumsatz in $ (nur Melder; der Vorwärtstest orb_or5 bleibt unverändert)


@dataclass(frozen=True)
class OrbSetup:
    symbol: str
    relvol: float
    side: str             # "long", "short" oder "" (ohne Richtung)
    or_high: float
    or_low: float
    entry: float          # Ausbruchs-Level bzw. tatsächlicher Ausbruchskurs
    stop: float
    target: float
    status: str
    state: str            # "wartet", "läuft", "ziel", "stop", "abgelaufen", "keine"
    triggered_at: datetime | None = None
    r_now: float | None = None


# ------------------------------------------------------------ Auswahl (rein, testbar)

def daily_filter(panel: pd.DataFrame) -> pd.DataFrame:
    """panel: Tages-Bars (Index symbol, date) bis einschließlich Vortag. Je Symbol die Kennzahlen zum heutigen
    Handelstag: avg_volume und atr über die letzten 14 Tage, prev_close; eligible nach den Grundfiltern."""
    g = panel.groupby(level="symbol", group_keys=False)
    prev_close = g["close"].shift(1)
    tr = pd.concat([panel["high"] - panel["low"], (panel["high"] - prev_close).abs(),
                    (panel["low"] - prev_close).abs()], axis=1).max(axis=1)
    last = panel.groupby(level="symbol").tail(LOOKBACK)
    trl = tr.loc[last.index]
    out = pd.DataFrame({
        "avg_volume": last["volume"].groupby(level="symbol").mean(),
        "atr": trl.groupby(level="symbol").mean(),
        "prev_close": last["close"].groupby(level="symbol").last(),
        "n": last["volume"].groupby(level="symbol").size(),
    })
    out["eligible"] = (out["n"] >= LOOKBACK) & (out["avg_volume"] > 1e6) & (out["atr"] > 0.5) & (out["prev_close"] > 5) \
        & (out["avg_volume"] * out["prev_close"] >= MIN_DOLLAR_VOLUME)
    return out


def rank_candidates(hist_opening: pd.DataFrame, today_opening: pd.DataFrame, feats: pd.DataFrame,
                    top: int = TOP_N) -> pd.DataFrame:
    """hist_opening: Eröffnungskerzen der Vortage (Index date, symbol); today_opening: heutige (Index symbol).
    Rang nach Volumen heute / Ø der letzten 14 Vortage (mind. 10)."""
    vol = hist_opening["volume"].unstack("symbol").sort_index().tail(LOOKBACK)
    ref = vol.mean().where(vol.notna().sum() >= MIN_HISTORY)
    df = today_opening.join(ref.rename("ref"), how="inner").join(feats[["eligible", "atr"]], how="inner")
    df["relvol"] = df["volume"] / df["ref"]
    df = df[df["eligible"] & (df["open"] > 5) & (df["relvol"] >= 1.0)]
    return df.sort_values("relvol", ascending=False).head(top)


# ------------------------------------------------------------ Status (rein, testbar)

def evaluate(symbol: str, relvol: float, opening, bars5: pd.DataFrame, price: float | None,
             now_et: datetime, target_r: float = 2.0) -> OrbSetup:
    """opening: erste 5-Minuten-Kerze (open/high/low/close). bars5: heutige 5-Minuten-Kerzen (Index NY).
    Stop und Ziel in einer Kerze -> Stop (vorsichtig, wie im Backtest)."""
    o, h, l, c = (float(opening[k]) for k in ("open", "high", "low", "close"))
    side = 1 if c > o else -1 if c < o else 0
    if side == 0:
        return OrbSetup(symbol, relvol, "", h, l, h, l, h, "keine Richtung (erste Kerze ohne Bewegung)", "keine")
    level, stop = (h, l) if side > 0 else (l, h)
    name = "long" if side > 0 else "short"
    tp = level + side * target_r * abs(level - stop)
    start = datetime.combine(now_et.date(), time(9, 35), tzinfo=NY)
    after = bars5[bars5.index >= start] if len(bars5) else bars5
    trig, entry = None, level
    for ts, b in after.iterrows():
        if ts.time() > CUTOFF_ET:
            break
        if (side > 0 and b["high"] > level) or (side < 0 and b["low"] < level):
            trig, entry = ts, (max(b["open"], level) if side > 0 else min(b["open"], level))
            break
    if trig is None:
        if now_et.time() > CUTOFF_ET:
            return OrbSetup(symbol, relvol, name, h, l, level, stop, tp, "abgelaufen: kein Ausbruch bis 15:00 ET",
                            "abgelaufen")
        word = "über" if side > 0 else "unter"
        return OrbSetup(symbol, relvol, name, h, l, level, stop, tp, f"wartet: Ausbruch {word} {level:.2f}", "wartet")
    sd = abs(entry - stop)
    tp = entry + side * target_r * sd
    for ts, b in after[after.index >= trig].iterrows():
        hit_stop = b["low"] <= stop if side > 0 else b["high"] >= stop
        hit_tp = (b["high"] >= tp if side > 0 else b["low"] <= tp) and ts > trig
        if hit_stop:
            return OrbSetup(symbol, relvol, name, h, l, entry, stop, tp, "ausgestoppt (-1 R)", "stop", trig, -1.0)
        if hit_tp:
            return OrbSetup(symbol, relvol, name, h, l, entry, stop, tp, f"Ziel erreicht (+{target_r:.0f} R)", "ziel",
                            trig, target_r)
    r_now = side * ((price if price else entry) - entry) / sd if sd > 0 else None
    status = f"ausgelöst {trig:%H:%M} ET, läuft ({r_now:+.1f} R)" if r_now is not None else "ausgelöst"
    return OrbSetup(symbol, relvol, name, h, l, entry, stop, tp, status, "läuft", trig, r_now)


# ------------------------------------------------------------ Laden (Alpaca)

NOT_COMMON = (r"(?i)preferred|warrants?\b|\bunits?\b|\brights?\b|convertible|notes? due|debentures?|"
              r"exchange[- ]traded notes?|\betns?\b|\bsubordinated\b|"
              # Fonds/ETFs wie im Forschungs-Universum (u.a. NOBL am 2.10.2026 als Kandidat)
              r"\betf\b|\bfund\b|ishares|spdr|proshares|direxion|invesco|vanguard|vaneck|\bultra|\b[23]x\b|"
              r"\bbull\b|\bbear\b|\bindex\b")


def only_common_stock(symbols: list[str], assets: pd.DataFrame) -> list[str]:
    """Nur Stammaktien (auch ADRs): Vorzugs-/Wandelpapiere, Optionsscheine, Units, Rights und Anleihen raus.
    Anlass: GOOGN (Depotschein auf eine Alphabet-Wandelvorzugsaktie, kaum gehandelt) erschien am 2.10.2026 als
    "Ausbruch", weil schon wenig Umsatz bei einem neuen Papier ein hohes relatives Volumen ergibt."""
    names = assets.assign(sym=assets["symbol"].str.replace(r"_DELISTED$", "", regex=True)).set_index("sym")["name"]
    names = names[~names.index.duplicated()].fillna("")
    bad = set(names.index[names.str.contains(NOT_COMMON, regex=True)])
    return [s for s in symbols if s not in bad]


def load_candidates(data_client, trading_client, today: date, base: Path = CACHE_DIR, top: int = TOP_N) -> pd.DataFrame:
    """Top-N des Tages (Spalten open/high/low/close/volume der ersten 5-Minuten-Kerze, relvol, atr); Tages-Cache."""
    from tradingbot.research import universe as uni

    day_dir = base / today.isoformat()
    path = day_dir / "candidates.pkl"
    if path.exists():
        return pd.read_pickle(path)
    symbols = uni.fetch_assets(trading_client, day_dir)
    symbols = only_common_stock(symbols, pd.read_pickle(day_dir / "assets.pkl"))
    panel = uni.fetch_daily(data_client, symbols, today - timedelta(days=40), today - timedelta(days=1), day_dir)
    panel = panel[panel.index.get_level_values("date") < today]
    feats = daily_filter(panel)
    eligible = list(feats.index[feats["eligible"]])
    hist_days = sorted(set(panel.index.get_level_values("date")))[-LOOKBACK:]
    uni.fetch_opening_bars(data_client, {d: eligible for d in hist_days}, day_dir / "hist")
    uni.fetch_opening_bars(data_client, {today: eligible}, day_dir / "today")
    hist = uni.load_opening(day_dir / "hist")
    tod = uni.load_opening(day_dir / "today")
    if tod.empty or today not in tod.index.get_level_values("date"):
        return pd.DataFrame()
    cand = rank_candidates(hist, tod.loc[today], feats, top)
    cand.to_pickle(path)
    return cand


def orb_setups(cp, now: datetime, base: Path = CACHE_DIR) -> list[OrbSetup]:
    """Aktueller Stand der Top-5-Setups. `cp`: Copilot (data_client, trading_client, today_bars, latest_price)."""
    now_et = now.astimezone(NY)
    cand = load_candidates(cp.data_client, cp.trading_client, now_et.date(), base)
    out = []
    for sym, row in cand.iterrows():
        try:
            bars = cp.today_bars(sym, now)
            price = cp.latest_price(sym)
        except Exception as e:  # Daten fehlen für ein Symbol: die anderen trotzdem zeigen
            logger.warning("ORB-Melder %s: %s", sym, e)
            bars, price = pd.DataFrame(), None
        out.append(evaluate(sym, float(row["relvol"]), row, bars, price, now_et))
    return out

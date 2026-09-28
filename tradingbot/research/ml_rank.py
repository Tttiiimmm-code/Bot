"""Runde 93: ML-Ranking US-Aktien, wöchentlich, long-only (siehe research/PROTOCOL.md).

Ablauf:
1. `load_wide` -- Tageskerzen (Alpaca, split-bereinigt) als Wide-Matrizen (Tage x Symbole),
   nur Symbole, die irgendwann die Liquiditätsgrenze erreichen.
2. `raw_features` / `universe_mask` -- nur Daten bis zum Schluss des Signaltags.
3. `weekly_schedule` -- Signaltag (letzter Handelstag der Woche), Kauf zum nächsten Open,
   Verkauf zum Open nach dem nächsten Signal.
4. `build_panel` -- je Signaltag: querschnittliche Perzentil-Merkmale, Zielgröße, Rendite.
5. `walk_forward` -- expandierendes Fenster, Neutraining alle `retrain_every` Signaltage,
   nur Beispiele, deren Ausstieg vor dem Signaltag liegt (Purge).
6. `simulate` -- Top-Anteil kaufen, halten solange im Puffer, gleichgewichtet, Kosten auf den
   tatsächlichen Umschlag inkl. Gewichtsdrift.

"Aus Fehlern lernen" heißt hier: das Modell wird regelmäßig auf alle bis dahin bekannten
Ergebnisse neu trainiert -- nicht nach jedem einzelnen Verlust angepasst.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

UNIVERSE_DIR = Path("data_cache") / "universe"
_NY = "America/New_York"

MIN_PRICE = 5.0
MIN_DOLLAR_VOLUME = 5e6
MIN_HISTORY = 252
COST_PER_SIDE = 10e-4

FEATURES = [
    "r5", "r21", "mom12_1", "mom6_1", "vol21", "vol63", "ldv20", "dv5_63",
    "hi52", "lo52", "max21", "on21", "in21", "amihud21", "hl21",
]


# ---------------------------------------------------------------- Daten

def load_wide(base: Path = UNIVERSE_DIR, min_dollar_volume: float = MIN_DOLLAR_VOLUME,
              until: pd.Timestamp | None = None) -> dict[str, pd.DataFrame]:
    """Wide-Matrizen open/high/low/close/volume (Index: Datum, Spalten: Symbole).
    Symbole ohne einen einzigen Tag mit Schluss > 5 USD und Ø-Dollarvolumen >= Grenze
    werden schon beim Laden verworfen (Speicher)."""
    parts: dict[str, list[pd.DataFrame]] = {k: [] for k in ("open", "high", "low", "close", "volume")}
    for p in sorted((base / "daily").glob("batch_*.pkl")):
        d = pd.read_pickle(p)
        if d.empty:
            continue
        d = d[["open", "high", "low", "close", "volume"]]
        ts = d.index.get_level_values("timestamp").tz_convert(_NY).normalize().tz_localize(None)
        d.index = pd.MultiIndex.from_arrays([d.index.get_level_values("symbol"), ts], names=["symbol", "date"])
        d = d[~d.index.duplicated()]
        dv = (d["close"] * d["volume"]).groupby(level="symbol").transform(lambda s: s.rolling(20).mean())
        ok = (dv >= min_dollar_volume) & (d["close"] > MIN_PRICE)
        keep = ok.groupby(level="symbol").any()
        d = d[d.index.get_level_values("symbol").isin(keep[keep].index)]
        if d.empty:
            continue
        for k in parts:
            parts[k].append(d[k].unstack("symbol"))
    out = {}
    for k, frames in parts.items():
        w = pd.concat(frames, axis=1).sort_index()
        w = w.loc[:, ~w.columns.duplicated()]
        if until is not None:
            w = w[w.index <= until]
        out[k] = w.astype("float32")  # halber Speicher; Genauigkeit reicht für Ränge und Wochenrenditen
    cols = out["close"].columns
    return {k: v.reindex(columns=cols) for k, v in out.items()}


# ---------------------------------------------------------------- Merkmale

def feature(name: str, o: pd.DataFrame, h: pd.DataFrame, lo: pd.DataFrame, c: pd.DataFrame,
            v: pd.DataFrame) -> pd.DataFrame:
    """Ein Merkmal für alle Tage; Tag t nutzt nur Kurse bis einschließlich Schluss t.
    Einzeln berechnet, damit nie alle 15 Matrizen gleichzeitig im Speicher liegen."""
    ret = lambda: c / c.shift(1) - 1  # noqa: E731
    dv = lambda: c * v  # noqa: E731
    if name == "r5":
        return c / c.shift(5) - 1
    if name == "r21":
        return c / c.shift(21) - 1
    if name == "mom12_1":
        return c.shift(21) / c.shift(252) - 1
    if name == "mom6_1":
        return c.shift(21) / c.shift(126) - 1
    if name == "vol21":
        return ret().rolling(21).std()
    if name == "vol63":
        return ret().rolling(63).std()
    if name == "ldv20":
        dv20 = dv().rolling(20).mean()
        return np.log(dv20.where(dv20 > 0))
    if name == "dv5_63":
        d = dv()
        return d.rolling(5).mean() / d.rolling(63).mean()
    if name == "hi52":
        return c / h.rolling(252).max()
    if name == "lo52":
        return c / lo.rolling(252).min()
    if name == "max21":
        return ret().rolling(21).max()
    if name == "on21":
        return (o / c.shift(1) - 1).rolling(21).sum()
    if name == "in21":
        return (c / o - 1).rolling(21).sum()
    if name == "amihud21":
        d = dv()
        return (ret().abs() / d.where(d > 0)).rolling(21).mean()
    if name == "hl21":
        return ((h - lo) / c).rolling(21).mean()
    raise KeyError(name)


def raw_features(o: pd.DataFrame, h: pd.DataFrame, lo: pd.DataFrame, c: pd.DataFrame,
                 v: pd.DataFrame, at: pd.DatetimeIndex | None = None,
                 chunk: int = 1000) -> dict[str, pd.DataFrame]:
    """Alle Merkmale; mit `at` nur diese Zeilen (Signaltage) behalten. Jedes Merkmal hängt nur
    von der eigenen Spalte ab -> blockweise über die Symbole rechnen (Spitzenspeicher klein)."""
    if at is None:
        return {k: feature(k, o, h, lo, c, v) for k in FEATURES}
    parts: dict[str, list[pd.DataFrame]] = {k: [] for k in FEATURES}
    for i in range(0, c.shape[1], chunk):
        cols = c.columns[i:i + chunk]
        args = [x[cols].astype("float64") for x in (o, h, lo, c, v)]
        for k in FEATURES:
            parts[k].append(feature(k, *args).loc[at].astype("float32"))
    return {k: pd.concat(p, axis=1) for k, p in parts.items()}


def universe_mask(c: pd.DataFrame, v: pd.DataFrame, min_price: float = MIN_PRICE,
                  min_dollar_volume: float = MIN_DOLLAR_VOLUME, min_history: int = MIN_HISTORY) -> pd.DataFrame:
    dv20 = (c * v).rolling(20).mean()
    history = c.notna().cumsum()
    return (c > min_price) & (dv20 >= min_dollar_volume) & (history >= min_history)


# ---------------------------------------------------------------- Takt

@dataclass(frozen=True)
class Week:
    signal: pd.Timestamp
    entry: pd.Timestamp
    exit: pd.Timestamp


def weekly_schedule(days: pd.DatetimeIndex, freq: str = "W") -> list[Week]:
    """Signal = letzter Handelstag jeder Kalenderwoche (freq "W") bzw. jedes Monats ("M");
    Kauf am nächsten Handelstag (Open); Verkauf am Handelstag nach dem nächsten Signal (Open)."""
    days = pd.DatetimeIndex(days).sort_values()
    pos = pd.Series(np.arange(len(days)), index=days)
    signals = pos.groupby(days.to_period(freq)).max().to_numpy()
    weeks = []
    for a, b in zip(signals[:-1], signals[1:]):
        if b + 1 >= len(days):
            break
        weeks.append(Week(days[a], days[a + 1], days[b + 1]))
    return weeks


def holding_returns(o: pd.DataFrame, c: pd.DataFrame, week: Week) -> pd.Series:
    """Open(entry) -> Open(exit); fehlt der Ausstiegs-Open (Delisting/Lücke), zählt der letzte
    bekannte Schluss zwischen Kauf und Ausstieg. Ohne Kauf-Open: NaN (nicht handelbar)."""
    entry = o.loc[week.entry]
    exit_ = o.loc[week.exit]
    window = c.loc[week.entry:week.exit].iloc[:-1]
    last_close = window.ffill().iloc[-1] if len(window) else pd.Series(np.nan, index=c.columns)
    exit_ = exit_.where(exit_.notna(), last_close)
    r = exit_ / entry - 1
    return r.where(entry.notna() & (entry > 0))


# ---------------------------------------------------------------- Panel

@dataclass
class WeekData:
    week: Week
    symbols: np.ndarray
    X: np.ndarray       # (n, len(FEATURES)) Perzentile 0..1, fehlend 0,5
    ret: np.ndarray     # Open->Open-Rendite
    y: np.ndarray       # Perzentilrang der Rendite


def cross_rank(values: np.ndarray) -> np.ndarray:
    """Perzentilrang in (0, 1) (Mittelwert-Ränge), NaN -> 0,5."""
    s = pd.Series(values, dtype=float)
    n = int(s.notna().sum())
    r = (s.rank(method="average") - 0.5) / max(n, 1)
    return r.fillna(0.5).to_numpy()


def build_panel(wide: dict[str, pd.DataFrame], feats: dict[str, pd.DataFrame] | None = None,
                mask: pd.DataFrame | None = None, weeks: list[Week] | None = None,
                extra: dict[str, pd.DataFrame] | None = None) -> list[WeekData]:
    """`extra`: zusätzliche Merkmale (Signaltage x Symbole), werden nach FEATURES angehängt."""
    o, c = wide["open"], wide["close"]
    if weeks is None:
        weeks = weekly_schedule(c.index)
    signals = pd.DatetimeIndex([w.signal for w in weeks])
    if feats is None:
        feats = raw_features(o, wide["high"], wide["low"], c, wide["volume"], at=signals)
    if mask is None:
        mask = universe_mask(c, wide["volume"]).loc[signals]
    out = []
    cols = c.columns.to_numpy()
    for w in weeks:
        m = mask.loc[w.signal].to_numpy(bool)
        r = holding_returns(o, c, w).to_numpy(float)
        m = m & np.isfinite(r)
        if m.sum() < 20:
            continue
        cols_x = [cross_rank(feats[k].loc[w.signal].to_numpy(float)[m]) for k in FEATURES]
        for f in (extra or {}).values():
            row = f.loc[w.signal] if w.signal in f.index else pd.Series(np.nan, index=c.columns)
            cols_x.append(cross_rank(row.reindex(c.columns).to_numpy(float)[m]))
        X = np.column_stack(cols_x)
        rr = r[m]
        out.append(WeekData(w, cols[m], X.astype("float32"), rr, cross_rank(rr)))
    return out


# ---------------------------------------------------------------- Fundamentaldaten (Runde 95)

FUNDAMENTALS = ["bm", "ep", "sp", "cfp", "roe", "roa", "gpa", "opm", "lev", "ag", "accruals", "issuance",
                "sgrowth"]


def split_factor(splits: pd.DataFrame, dates: pd.DatetimeIndex, symbols) -> pd.DataFrame:
    """Faktor, mit dem der split-bereinigte Kurs multipliziert den damals gehandelten Kurs ergibt:
    Produkt new_rate/old_rate aller Splits mit Ex-Tag NACH dem jeweiligen Datum."""
    f = pd.DataFrame(1.0, index=pd.DatetimeIndex(dates), columns=pd.Index(symbols))
    sub = splits[splits["symbol"].isin(f.columns)]
    for sym, ex, old, new in sub[["symbol", "ex_date", "old_rate", "new_rate"]].itertuples(index=False):
        if old and new:
            f.loc[f.index < pd.Timestamp(ex), sym] *= float(new) / float(old)
    return f


def as_of(rows: pd.DataFrame, at: pd.DatetimeIndex, max_age_days: int) -> pd.DataFrame:
    """rows: Index = Verfügbarkeitsdatum, Spalten = Symbole. Je Tag in `at` der letzte bis dahin
    verfügbare Wert, höchstens `max_age_days` alt (nie ein Wert mit Verfügbarkeit nach dem Tag)."""
    rows = rows.sort_index()
    rows = rows[~rows.index.duplicated(keep="last")]
    out = pd.DataFrame(np.nan, index=pd.DatetimeIndex(at), columns=rows.columns)
    valid = rows.notna()
    for col in rows.columns:
        s = rows[col][valid[col]]
        if s.empty:
            continue
        pos = s.index.searchsorted(out.index, side="right") - 1
        ok = pos >= 0
        vals = np.full(len(out), np.nan)
        dates = s.index.to_numpy()
        vals[ok] = s.to_numpy(float)[pos[ok]]
        age = (out.index.to_numpy() - dates[np.clip(pos, 0, None)]) / np.timedelta64(1, "D")
        vals[~ok | (age > max_age_days)] = np.nan
        out[col] = vals
    return out


def fundamental_features(q: dict[str, pd.DataFrame], a: dict[str, pd.DataFrame],
                         price: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Kennzahlen je Signaltag x Symbol. q: Stichtagswerte assets, liabilities, equity, shares sowie
    assets_1y, shares_1y (Vorjahr); a: Jahreswerte ni, rev, gp, oi, cfo, rev_1y; price: damals
    gehandelter Schlusskurs. Alle Eingaben bereits as-of auf dieselben Zeilen/Spalten gebracht."""
    def pos(x):
        return x.where(x > 0)
    mcap = pos(price * q["shares"])
    assets = pos(q["assets"])
    return {
        "bm": q["equity"] / mcap,
        "ep": a["ni"] / mcap,
        "sp": a["rev"] / mcap,
        "cfp": a["cfo"] / mcap,
        "roe": a["ni"] / pos(q["equity"]),
        "roa": a["ni"] / assets,
        "gpa": a["gp"] / assets,
        "opm": a["oi"] / pos(a["rev"]),
        "lev": q["liabilities"] / assets,
        "ag": assets / pos(q["assets_1y"]) - 1,
        "accruals": (a["ni"] - a["cfo"]) / assets,
        "issuance": q["shares"] / pos(q["shares_1y"]) - 1,
        "sgrowth": a["rev"] / pos(a["rev_1y"]) - 1,
    }


# ---------------------------------------------------------------- Modelle

def ridge_fit(X: np.ndarray, y: np.ndarray, alpha: float = 1.0) -> Callable[[np.ndarray], np.ndarray]:
    X = np.asarray(X, dtype=float)
    xm, ym = X.mean(axis=0), y.mean()
    Xc = X - xm
    beta = np.linalg.solve(Xc.T @ Xc + alpha * np.eye(X.shape[1]), Xc.T @ (y - ym))
    return lambda Z: (np.asarray(Z, dtype=float) - xm) @ beta + ym


def lgbm_fit(params: dict) -> Callable[[np.ndarray, np.ndarray], Callable[[np.ndarray], np.ndarray]]:
    def fit(X: np.ndarray, y: np.ndarray):
        import lightgbm as lgb
        p = {"objective": "regression", "verbosity": -1, "seed": 93, "deterministic": True,
             "num_threads": 4, **{k: v for k, v in params.items() if k != "num_boost_round"}}
        booster = lgb.train(p, lgb.Dataset(X, y), num_boost_round=params["num_boost_round"])
        return booster.predict
    return fit


def walk_forward(panel: list[WeekData], fit: Callable, first_test: pd.Timestamp,
                 train_start: pd.Timestamp, retrain_every: int = 4) -> dict[pd.Timestamp, np.ndarray]:
    """Prognosen je Signaltag ab `first_test`. Trainiert nur auf Wochen mit
    train_start <= Signal und Ausstieg < aktuellem Signaltag (kein Blick in die Zukunft)."""
    preds: dict[pd.Timestamp, np.ndarray] = {}
    model = None
    since = retrain_every
    for wd in panel:
        s = wd.week.signal
        if s < first_test:
            continue
        if model is None or since >= retrain_every:
            train = [t for t in panel if t.week.signal >= train_start and t.week.exit < s]
            model = fit(np.vstack([t.X for t in train]), np.concatenate([t.y for t in train]))
            since = 0
        preds[s] = np.asarray(model(wd.X), dtype=float)
        since += 1
    return preds


# ---------------------------------------------------------------- Portfolio

def select(symbols: np.ndarray, score: np.ndarray, held: set, n_top: int, n_keep: int) -> list:
    """Behalte gehaltene Titel unter den besten `n_keep`, fülle mit den Besten auf `n_top` auf."""
    order = np.argsort(-np.asarray(score, dtype=float), kind="stable")
    ranked = list(np.asarray(symbols)[order])
    keep_zone = set(ranked[:n_keep])
    chosen = [s for s in ranked if s in held and s in keep_zone]
    chosen_set = set(chosen)
    for s in ranked:
        if len(chosen) >= n_top:
            break
        if s not in chosen_set:
            chosen.append(s)
            chosen_set.add(s)
    return chosen


@dataclass
class SimResult:
    weeks: list[pd.Timestamp] = field(default_factory=list)   # Kauftage
    gross: list[float] = field(default_factory=list)
    net: list[float] = field(default_factory=list)
    turnover: list[float] = field(default_factory=list)
    n_held: list[int] = field(default_factory=list)

    def frame(self) -> pd.DataFrame:
        return pd.DataFrame({"gross": self.gross, "net": self.net, "turnover": self.turnover,
                             "n": self.n_held}, index=pd.DatetimeIndex(self.weeks, name="entry"))


def simulate(panel: list[WeekData], scores: dict[pd.Timestamp, np.ndarray] | None,
             top: float = 0.10, keep: float = 0.20, cost_per_side: float = COST_PER_SIDE,
             weeks: set | None = None) -> SimResult:
    """scores None -> gleichgewichtetes Universum. top/keep als Anteil (<1) oder Anzahl (>=1).
    `weeks`: nur diese Signaltage handeln (z.B. dieselben wie das Modell)."""
    res = SimResult()
    drifted: dict = {}
    for wd in panel:
        s = wd.week.signal
        if scores is not None and s not in scores:
            continue
        if weeks is not None and s not in weeks:
            continue
        n = len(wd.symbols)
        if scores is None:
            chosen = list(wd.symbols)
        else:
            n_top = int(top) if top >= 1 else max(1, math.ceil(top * n))
            n_keep = int(keep) if keep >= 1 else max(n_top, math.ceil(keep * n))
            chosen = select(wd.symbols, scores[s], set(drifted), n_top, n_keep)
        w = 1.0 / len(chosen)
        target = {sym: w for sym in chosen}
        turnover = sum(abs(target.get(k, 0.0) - drifted.get(k, 0.0)) for k in set(target) | set(drifted))
        idx = {sym: i for i, sym in enumerate(wd.symbols)}
        r = np.array([wd.ret[idx[sym]] for sym in chosen])
        gross = float(r.mean())
        growth = 1 + gross
        drifted = {sym: w * (1 + ri) / growth for sym, ri in zip(chosen, r)} if growth > 0 else {}
        res.weeks.append(wd.week.entry)
        res.gross.append(gross)
        res.net.append(gross - turnover * cost_per_side)
        res.turnover.append(turnover)
        res.n_held.append(len(chosen))
    return res


def rank_ic(panel: list[WeekData], scores: dict[pd.Timestamp, np.ndarray]) -> pd.Series:
    vals = {}
    for wd in panel:
        if wd.week.signal in scores:
            vals[wd.week.entry] = float(np.corrcoef(cross_rank(scores[wd.week.signal]), wd.y)[0, 1])
    return pd.Series(vals, dtype=float)


def t_stat(x) -> float:
    x = pd.Series(x, dtype=float).dropna()
    if len(x) < 3 or x.std(ddof=1) == 0:
        return float("nan")
    return float(x.mean() / x.std(ddof=1) * math.sqrt(len(x)))

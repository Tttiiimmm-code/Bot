"""Runde 8: bekannte Anomalien (Familien P-T in research/PROTOCOL.md).

Alle Funktionen liefern Gewichte (Tage x Assets bzw. Tage), festgelegt zum
Schlusskurs von Tag t und gültig für die Rendite t -> t+1; ausgewertet mit
crypto.run_weights (Umschlagskosten) bzw. financed_returns (Hebelzins).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

HALLOWEEN_MONTHS = {11, 12, 1, 2, 3, 4}


def _month_ends(index) -> np.ndarray:
    days = pd.DatetimeIndex([pd.Timestamp(d) for d in index])
    nxt = np.append(days.month[1:], -1)
    return np.asarray(days.month != nxt)


def vol_managed_weights(close: pd.Series, cap: float, target_vol: float = 0.15,
                        window: int = 21) -> pd.Series:
    """P: Gewicht = min(cap, target_vol / annualisierte Vola der letzten
    `window` Tagesrenditen bis einschließlich t)."""
    vol = close.pct_change().rolling(window).std() * np.sqrt(252)
    return (target_vol / vol).clip(upper=cap).where(vol.notna(), 0.0)


def halloween_weights(index) -> pd.Series:
    """Q: investiert für die Rendite t -> t+1, wenn t+1 in November-April liegt."""
    months = pd.Series([d.month for d in index], index=index)
    return months.shift(-1).isin(HALLOWEEN_MONTHS).astype(float)


def financed_returns(weight: pd.Series, close: pd.Series, cost_per_side: float,
                     borrow_rate: float = 0.06) -> pd.Series:
    """Einzel-Asset mit Hebel: Rendite t+1 = w_t * r_{t+1} - Zins auf (w_t - 1)+
    - Kosten auf |w_t - w_{t-1}|."""
    r = close.pct_change()
    w = weight.reindex(close.index).fillna(0.0)
    held = w.shift(1).fillna(0.0)
    financing = (held - 1).clip(lower=0) * borrow_rate / 252
    turnover = (w - held).abs().shift(1).fillna(0.0)
    return (held * r - financing - cost_per_side * turnover).iloc[1:].fillna(0.0)


def cross_section_weights(close: pd.DataFrame, universe: pd.DataFrame, score: pd.DataFrame,
                          n: int, highest: bool) -> pd.DataFrame:
    """S/T: an jedem Monatsende die n Titel mit höchstem (bzw. niedrigstem)
    Score im Universum, gleichgewichtet bis zum nächsten Monatsende; ohne
    Kurs (Delisting) fällt die Position weg."""
    is_end = _month_ends(close.index)
    S, U = score.to_numpy(float), universe.to_numpy(bool)
    avail = close.notna().to_numpy()
    W = np.zeros(close.shape)
    current = np.zeros(close.shape[1])
    for t in range(len(close.index)):
        if is_end[t]:
            s = np.where(U[t] & np.isfinite(S[t]), S[t], np.nan)
            valid = np.flatnonzero(~np.isnan(s))
            current = np.zeros(close.shape[1])
            if len(valid) >= n:
                order = valid[np.argsort(s[valid])]
                pick = order[-n:] if highest else order[:n]
                current[pick] = 1.0 / n
        W[t] = np.where(avail[t], current, 0.0)
    return pd.DataFrame(W, index=close.index, columns=close.columns)


def momentum_12_1(close: pd.DataFrame) -> pd.DataFrame:
    return close.shift(21) / close.shift(252) - 1


def low_volatility(close: pd.DataFrame) -> pd.DataFrame:
    return close.pct_change(fill_method=None).rolling(63, min_periods=50).std()


# ------------------------------------------------------------ Runde 14 (Devisen, Auktionen)

FX_PAIRS = {"EUR": ("EURUSD=X", False), "GBP": ("GBPUSD=X", False), "JPY": ("USDJPY=X", True),
            "AUD": ("AUDUSD=X", False), "CHF": ("USDCHF=X", True), "CAD": ("USDCAD=X", True),
            "NZD": ("NZDUSD=X", False)}
FRED_3M = {"USD": "IR3TIB01USM156N", "EUR": "IR3TIB01EZM156N", "GBP": "IR3TIB01GBM156N",
           "JPY": "IR3TIB01JPM156N", "AUD": "IR3TIB01AUM156N", "CHF": "IR3TIB01CHM156N",
           "CAD": "IR3TIB01CAM156N", "NZD": "IR3TIB01NZM156N"}


def fetch_fred(series: str, cache_dir: str = "data_cache/fred") -> pd.Series:
    """Monatsreihe von FRED (Prozent p.a.), Index = Monatsanfang."""
    import urllib.request
    from pathlib import Path

    path = Path(cache_dir) / f"{series}.pkl"
    if path.exists():
        return pd.read_pickle(path)
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}"
    raw = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}),
                                 timeout=60).read().decode()
    df = pd.read_csv(__import__("io").StringIO(raw))
    s = pd.to_numeric(df.iloc[:, 1], errors="coerce")
    s.index = pd.to_datetime(df.iloc[:, 0])
    s = s.dropna()
    path.parent.mkdir(parents=True, exist_ok=True)
    s.to_pickle(path)
    return s


def fx_excess_returns(spot: dict[str, pd.Series], rates: dict[str, pd.Series]) -> pd.DataFrame:
    """Tägliche Überschussrendite je Währung aus USD-Sicht: Kursänderung der
    Währung ggü. USD + (Zins Währung - Zins USD)/252. Zins des Vormonats
    (vermeidet Veröffentlichungsverzug). USD selbst: 0."""
    idx = sorted(set().union(*[set(s.index) for s in spot.values()]))
    idx = pd.Index(idx)
    out = {}
    for cur, s in spot.items():
        s = s.reindex(idx).ffill()
        out[cur] = s.pct_change()
    fx = pd.DataFrame(out)
    months = pd.DatetimeIndex([pd.Timestamp(d) for d in idx]).to_period("M")
    def daily_rate(cur):
        r = rates[cur].copy()
        r.index = r.index.to_period("M")
        return pd.Series(r.shift(1).reindex(months).to_numpy(), index=idx) / 100
    usd = daily_rate("USD")
    for cur in spot:
        fx[cur] = fx[cur] + (daily_rate(cur) - usd) / 252
    fx["USD"] = 0.0
    return fx


def fx_rate_levels(rates: dict[str, pd.Series], index) -> pd.DataFrame:
    months = pd.DatetimeIndex([pd.Timestamp(d) for d in index]).to_period("M")
    cols = {}
    for cur, r in rates.items():
        r = r.copy()
        r.index = r.index.to_period("M")
        cols[cur] = r.shift(1).reindex(months).to_numpy()
    return pd.DataFrame(cols, index=index)


def rank_long_short(score: pd.DataFrame, k: int = 3, short: bool = True) -> pd.DataFrame:
    """Monatlich: Top k long (+1/k), Bottom k short (-1/k) bzw. nur long."""
    is_end = _month_ends(score.index)
    W = np.zeros(score.shape)
    cur = np.zeros(score.shape[1])
    S = score.to_numpy(float)
    for t in range(len(score.index)):
        if is_end[t] and np.isfinite(S[t]).sum() >= 2 * k:
            order = np.argsort(np.where(np.isfinite(S[t]), S[t], -np.inf))
            cur = np.zeros(score.shape[1])
            cur[order[-k:]] = 1.0 / k
            if short:
                valid = [j for j in order if np.isfinite(S[t, j])]
                cur[valid[:k]] = -1.0 / k
        W[t] = cur
    return pd.DataFrame(W, index=score.index, columns=score.columns)


def fx_portfolio_returns(weights: pd.DataFrame, excess: pd.DataFrame, cost_per_side: float = 2e-4,
                         financing: float = 0.01) -> pd.Series:
    held = weights.shift(1).fillna(0.0)
    gross_non_usd = held.drop(columns="USD").abs().sum(axis=1)
    turnover = (weights - held).drop(columns="USD").abs().sum(axis=1).shift(1).fillna(0.0)
    r = (held * excess.fillna(0.0)).sum(axis=1) - financing / 252 * gross_non_usd - cost_per_side * turnover
    return r.iloc[1:]


def auction_positions(index, auction_days, k: int) -> pd.Series:
    """AF: investiert für die Renditen der k Handelstage nach dem Auktionstag."""
    days = pd.Index(index)
    pos = np.zeros(len(days))
    for d in auction_days:
        t = days.searchsorted(d)
        if t < len(days) and days[t] == d:
            pos[t:t + k] = 1.0  # Position zum Schluss t .. t+k-1 -> Renditen t+1 .. t+k
    return pd.Series(pos, index=index)


# ------------------------------------------------------------ Runde 13 (Swing mit Einzelaktien)

def slot_weights(close: pd.DataFrame, entry: pd.DataFrame, exit_: pd.DataFrame, rank: pd.DataFrame,
                 max_positions: int = 20, stop: float | None = None, max_hold: int = 126) -> pd.DataFrame:
    """Konto mit festen Plätzen: je Position 1/max_positions des Kapitals, freie
    Plätze Cash. Ausstieg zum Schluss bei exit_, Stop (Schluss <= Einstieg x
    (1 - stop)), Haltedauer max_hold oder fehlendem Kurs. Neue Einstiege nach
    `rank` (höchster zuerst), solange Plätze frei sind."""
    C = close.to_numpy(float)
    E, X, R = entry.to_numpy(bool), exit_.to_numpy(bool), rank.to_numpy(float)
    W = np.zeros(C.shape)
    held: dict[int, tuple[int, float]] = {}  # Spalte -> (Einstiegstag, Einstiegskurs)
    w = 1.0 / max_positions
    for t in range(C.shape[0]):
        for j in list(held):
            t0, px = held[j]
            c = C[t, j]
            if (not np.isfinite(c) or X[t, j] or t - t0 >= max_hold
                    or (stop is not None and c <= px * (1 - stop))):
                del held[j]
        free = max_positions - len(held)
        if free > 0:
            cand = [j for j in np.flatnonzero(E[t] & np.isfinite(C[t])) if j not in held]
            if cand:
                order = sorted(cand, key=lambda j: -np.nan_to_num(R[t, j], nan=-np.inf))
                for j in order[:free]:
                    held[j] = (t, C[t, j])
        for j in held:
            W[t, j] = w
    return pd.DataFrame(W, index=close.index, columns=close.columns)


def minervini_entry(close: pd.DataFrame, volume: pd.DataFrame) -> pd.DataFrame:
    """AB: Trendvorlage + frisches 20-Tage-Schlusshoch (Vortag noch keins) mit
    Volumen > 1,5 x Ø50."""
    s50, s150, s200 = (close.rolling(n, min_periods=n).mean() for n in (50, 150, 200))
    hi252, lo252 = close.rolling(252, min_periods=200).max(), close.rolling(252, min_periods=200).min()
    template = ((close > s50) & (s50 > s150) & (s150 > s200) & (s200 > s200.shift(21))
                & (close >= 1.25 * lo252) & (close >= 0.75 * hi252))
    breakout = close >= close.rolling(20).max()
    fresh = close.shift(1) < close.shift(1).rolling(20).max()
    vol_ok = volume > 1.5 * volume.rolling(50, min_periods=40).mean()
    return template & breakout & fresh & vol_ok


def pullback_entry(close: pd.DataFrame) -> pd.DataFrame:
    """AC: im Aufwärtstrend erstmals unter SMA50 (Vortag darüber)."""
    s50, s200 = close.rolling(50, min_periods=50).mean(), close.rolling(200, min_periods=200).mean()
    return (close > s200) & (s50 > s200) & (close < s50) & (close.shift(1) >= s50.shift(1))


# ------------------------------------------------------------ Runde 12 (r/algotrading)

def _entry_exit(entry: np.ndarray, exit_: np.ndarray) -> np.ndarray:
    pos, out = 0.0, np.zeros(len(entry))
    for t in range(len(entry)):
        if pos and exit_[t]:
            pos = 0.0
        elif not pos and entry[t]:
            pos = 1.0
        out[t] = pos
    return out


def ibs_band_positions(df: pd.DataFrame) -> pd.Series:
    """Z1: Kauf, wenn Schluss < max(Hoch, 10) - 2,5 x Ø(Hoch-Tief, 25) und IBS < 0,3;
    Verkauf, sobald Schluss > Hoch des Vortags. df: high, low, close."""
    h, lo, c = df["high"], df["low"], df["close"]
    band = h.rolling(10).max() - 2.5 * (h - lo).rolling(25).mean()
    rng = (h - lo).replace(0, np.nan)
    ibs = (c - lo) / rng
    entry = ((c < band) & (ibs < 0.3)).to_numpy()
    exit_ = (c > h.shift(1)).to_numpy()
    return pd.Series(_entry_exit(entry, exit_), index=df.index)


def double7_positions(close: pd.Series) -> pd.Series:
    """Z2: Kauf bei Schluss > SMA200 und 7-Tage-Tiefststand, Verkauf bei 7-Tage-Höchststand."""
    entry = ((close > close.rolling(200).mean()) & (close <= close.rolling(7).min())).to_numpy()
    exit_ = (close >= close.rolling(7).max()).to_numpy()
    return pd.Series(_entry_exit(entry, exit_), index=close.index)


# ------------------------------------------------------------ Runde 9

_MONTHS = {m: i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
     "November", "December"], 1)}
_SHORT = {"Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6, "Jul": 7, "Aug": 8, "Sep": 9,
          "Oct": 10, "Nov": 11, "Dec": 12}


def parse_fomc_historical(lines: list[str]) -> list:
    """Zeilen wie 'January 26-27 Meeting - 2010' oder 'January 31-February 1
    Meeting - 2012' -> Entscheidungstag (letzter Sitzungstag). Telefonkonferenzen
    und unplanmäßige Sitzungen zählen nicht."""
    import re
    from datetime import date

    out = []
    pat = re.compile(r"^([A-Za-z/]+) (\d+)(?:-(?:([A-Z][a-z]+) )?(\d+))? Meeting - (\d{4})$")
    for line in lines:
        m = pat.match(" ".join(line.split()))
        if not m:
            continue
        # "Jan/Feb 31-1", "July 31-August 1" oder "March 16": Monat des letzten Tags
        last_month = (m.group(3) or m.group(1).split("/")[-1])[:3]
        if last_month not in _SHORT:
            continue
        month = _SHORT[last_month]
        day = int(m.group(4) or m.group(2))
        out.append(date(int(m.group(5)), month, day))
    return out


def parse_fomc_current(lines: list[str]) -> list:
    """Aktuelle Kalenderseite: '2023 FOMC Meetings', dann Monat ('Jan/Feb',
    'March') und Tage ('31-1', '21-22*')."""
    import re
    from datetime import date

    out, year = [], None
    for i, line in enumerate(lines):
        y = re.match(r"^(\d{4}) FOMC Meetings$", line)
        if y:
            year = int(y.group(1))
            continue
        if year is None or i + 1 >= len(lines):
            continue
        months = [part[:3] for part in line.split("/")]
        days = re.match(r"^(\d+)(?:-(\d+))?\*?$", lines[i + 1])
        if days and all(mo in _SHORT for mo in months):
            out.append(date(year, _SHORT[months[-1]], int(days.group(2) or days.group(1))))
    return out


def fomc_decision_days(cache: str = "data_cache/fomc.json") -> list:
    import html as _html
    import json as _json
    import re
    import urllib.request
    from datetime import date
    from pathlib import Path

    path = Path(cache)
    if path.exists():
        return [date.fromisoformat(d) for d in _json.loads(path.read_text())]

    def lines(url):
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        raw = urllib.request.urlopen(req, timeout=60).read().decode()
        text = _html.unescape(re.sub(r"<[^>]+>", "\n", raw))
        return [ln.strip() for ln in text.splitlines() if ln.strip()]

    days = []
    for year in range(1994, 2021):
        days += parse_fomc_historical(lines(f"https://www.federalreserve.gov/monetarypolicy/fomchistorical{year}.htm"))
    days += parse_fomc_current(lines("https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"))
    days = sorted(set(days))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_json.dumps([d.isoformat() for d in days]))
    return days


def event_day_weights(index, event_days) -> pd.Series:
    """V: investiert für die Rendite t -> t+1, wenn t+1 ein Ereignistag ist."""
    events = set(event_days)
    nxt = pd.Series(list(index[1:]) + [None], index=index)
    return nxt.map(lambda d: 1.0 if d in events else 0.0)


def pairs_trading(close: pd.DataFrame, universe: pd.DataFrame, n_pairs: int = 20, k: float = 2.0,
                  formation: int = 252, trading: int = 126, cost_per_side: float = 3e-4) -> pd.Series:
    """U: Paarhandel nach Gatev et al. (nicht überlappende Perioden). Tägliche
    Portfoliorendite; je offenes Paar 1/n_pairs des Kapitals pro Seite.
    Einstieg/Ausstieg zum Schlusskurs, Rendite ab dem Folgetag."""
    C = close.to_numpy(float)
    U = universe.to_numpy(bool)
    R = np.vstack([np.full(C.shape[1], np.nan), C[1:] / C[:-1] - 1])
    daily = np.zeros(len(close.index))
    w = 1.0 / n_pairs
    for t0 in range(formation, len(close.index) - 1, trading):
        window = C[t0 - formation:t0]
        cand = np.flatnonzero(U[t0 - 1] & np.isfinite(window).all(axis=0) & (window > 0).all(axis=0))
        if len(cand) < 2 * n_pairs:
            continue
        X = window[:, cand] / window[0, cand]
        sq = (X ** 2).sum(axis=0)
        ssd = sq[:, None] + sq[None, :] - 2 * X.T @ X
        iu = np.triu_indices(len(cand), 1)
        order = np.argsort(ssd[iu])[:n_pairs]
        pairs = [(cand[iu[0][o]], cand[iu[1][o]]) for o in order]
        end = min(t0 + trading, len(close.index) - 1)
        for a, b in pairs:
            sigma = np.std(X[:, np.searchsorted(cand, a)] - X[:, np.searchsorted(cand, b)])
            if not sigma > 0:
                continue
            base_a, base_b = C[t0 - 1, a], C[t0 - 1, b]
            pos = 0  # +1: long a / short b, -1: short a / long b
            for t in range(t0, end + 1):
                if pos != 0:
                    ra, rb = R[t, a], R[t, b]
                    if not (np.isfinite(ra) and np.isfinite(rb)):
                        pos = 0  # Delisting: Paar zum letzten Kurs geschlossen
                        continue
                    daily[t] += w * pos * (ra - rb)
                if not (np.isfinite(C[t, a]) and np.isfinite(C[t, b])):
                    continue
                spread = C[t, a] / base_a - C[t, b] / base_b
                if pos == 0 and abs(spread) > k * sigma and t < end:
                    pos = -1 if spread > 0 else 1
                    daily[t] -= w * 2 * cost_per_side
                elif pos != 0 and (np.sign(spread) == pos or t == end):
                    pos = 0
                    daily[t] -= w * 2 * cost_per_side
    return pd.Series(daily[formation + 1:], index=close.index[formation + 1:])

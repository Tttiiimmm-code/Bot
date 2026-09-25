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

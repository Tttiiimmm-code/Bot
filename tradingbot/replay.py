"""Übungsmodus ("Replay"): einen vergangenen Handelstag Kerze für Kerze abspielen und mit Stop
und Ziel "handeln" -- ohne Geld, ohne Warten auf die Börse.

Ausführung wie live, eher vorsichtig gerechnet:
- Kauf/Verkauf zum ERÖFFNUNGSKURS der nächsten Kerze (man sieht nur fertige Kerzen).
- Berührt eine Kerze Stop UND Ziel, zählt der Stop (Reihenfolge innerhalb der Kerze unbekannt).
- Öffnet eine Kerze schon unter dem Stop / über dem Ziel, gilt ihr Eröffnungskurs (Kurslücke).
- Stop auf Einstand: erst NACH der Kerze, die +1 R erreicht hat.
- Glattstellen mit der Kerze ab 15:50 ET bzw. mit der letzten Kerze eines verkürzten Tages.

Kursdaten: vollständige SIP-5-Minuten-Kerzen (für vergangene Tage im kostenlosen Zugang verfügbar).
Ergebnisse landen in einem eigenen Journal (replay_journal.jsonl), getrennt vom echten Journal.
"""

from __future__ import annotations

import json
import random
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path

from tradingbot.copilot import NY

REPLAY_STARTS_ET = {
    "18:00 · Mittag in New York": time(12, 0),
    "19:30 · Nachmittag": time(13, 30),
    "21:00 · Power Hour": time(15, 0),
    "15:30 · Börsenstart": time(9, 30),
}
FLATTEN_BAR_ET = time(15, 50)
# gut gehandelte Werte: Chart und Kurse sauber, typische "Aktien im Spiel" für den Copilot
PRACTICE_SYMBOLS = ("NVDA", "AAPL", "MSFT", "AMZN", "META", "GOOGL", "TSLA", "AMD", "NFLX", "AVGO", "PLTR",
                    "COIN", "HOOD", "UBER", "SHOP", "MU", "INTC", "CRWD", "PANW", "SMCI", "HIMS", "RKLB",
                    "HPE", "MDB", "ASTS", "SOFI", "MSTR", "ARM", "SNOW", "DELL")


@dataclass
class Position:
    entry_idx: int
    entry: float
    stop: float
    target: float | None
    setup: str
    note: str = ""
    breakeven: bool = False
    initial_stop: float = 0.0

    @property
    def one_r(self) -> float:
        return self.entry - self.initial_stop


@dataclass
class Result:
    symbol: str
    day: str
    setup: str
    entry_time: str
    entry: float
    stop: float
    target: float | None
    exit_time: str
    exit: float
    reason: str
    r: float
    note: str = ""
    above_vwap: bool | None = None   # Einstieg über der VWAP der Kerzen davor
    goal: str = ""                   # gewähltes Übungsziel


# Übungsziele: Prüfung je Übungstrade (True = eingehalten)
GOALS = {
    "nur über VWAP kaufen": lambda r: r.above_vwap is True,
    "Stop mindestens 1 % entfernt": lambda r: r.entry > 0 and (r.entry - r.stop) / r.entry >= 0.01,
    "beides": lambda r: r.above_vwap is True and r.entry > 0 and (r.entry - r.stop) / r.entry >= 0.01,
}


def goal_stats(results: list, goal: str, last: int = 10) -> dict | None:
    """Für die letzten `last` Übungstrades mit diesem Ziel: eingehalten, Ø R eingehalten / gebrochen."""
    check = GOALS.get(goal)
    rs = [r for r in results if r.goal == goal][-last:]
    if check is None or not rs:
        return None
    kept = [r.r for r in rs if check(r)]
    broken = [r.r for r in rs if not check(r)]
    avg = (lambda xs: sum(xs) / len(xs) if xs else None)
    return {"n": len(rs), "kept": len(kept), "avg_kept": avg(kept), "avg_broken": avg(broken)}


def open_position(bars, idx: int, stop: float, target: float | None, setup: str, note: str = "",
                  breakeven: bool = False) -> Position:
    """Kauf zum Eröffnungskurs der Kerze idx (der nächsten, noch unsichtbaren)."""
    entry = float(bars["open"].iloc[idx])
    if stop >= entry:
        raise ValueError(f"Stop {stop:.2f} liegt nicht unter dem Einstieg {entry:.2f} (Eröffnung der nächsten Kerze).")
    if target is not None and target <= entry:
        raise ValueError(f"Ziel {target:.2f} liegt nicht über dem Einstieg {entry:.2f}.")
    return Position(idx, entry, stop, target, setup, note, breakeven, initial_stop=stop)


def check_exit(bars, pos: Position, idx: int) -> tuple[float, str] | None:
    """Prüft Kerze idx für eine offene Position: (Ausstiegskurs, Grund) oder None."""
    o, h, l, c = (float(bars[k].iloc[idx]) for k in ("open", "high", "low", "close"))
    stop_reason = "Stop auf Einstand" if pos.stop >= pos.entry else "Stop"
    if idx != pos.entry_idx:  # in der Einstiegskerze ist die Eröffnung der Einstieg selbst
        if o <= pos.stop:
            return o, f"{stop_reason} (Kurslücke)"
        if pos.target is not None and o >= pos.target:
            return o, "Ziel (Kurslücke)"
    if l <= pos.stop:
        return pos.stop, stop_reason
    if pos.target is not None and h >= pos.target:
        return pos.target, "Ziel"
    if pos.breakeven and h >= pos.entry + pos.one_r:
        pos.stop = max(pos.stop, pos.entry)
    if bars.index[idx].astimezone(NY).time() >= FLATTEN_BAR_ET or idx == len(bars) - 1:
        return c, "Handelsschluss"
    return None


def make_result(symbol: str, day: str, bars, pos: Position, idx: int, exit_price: float, reason: str,
                goal: str = "") -> Result:
    fmt = "%H:%M"
    before = bars.iloc[:pos.entry_idx]
    above = None
    if len(before):
        from tradingbot.copilot import vwap
        above = bool(pos.entry >= float(vwap(before)[-1]))
    return Result(symbol=symbol, day=day, setup=pos.setup, above_vwap=above, goal=goal,
                  entry_time=bars.index[pos.entry_idx].astimezone(NY).strftime(fmt), entry=round(pos.entry, 4),
                  stop=round(pos.initial_stop, 4), target=pos.target,
                  exit_time=bars.index[idx].astimezone(NY).strftime(fmt), exit=round(exit_price, 4), reason=reason,
                  r=round((exit_price - pos.entry) / pos.one_r, 2), note=pos.note)


def review(bars, pos: Position, exit_idx: int, reason: str, wide_stop: float | None,
           min_stop_pct: float = 0.01) -> list[tuple[str, str]]:
    """Nachbesprechung eines Übungstrades: (Art, Text) mit Art "gut" / "achtung" / "info".
    wide_stop: Stop unter dem letzten Rücksetzer, wie er zum Einstieg vorgeschlagen worden wäre."""
    out: list[tuple[str, str]] = []
    before = bars.iloc[:pos.entry_idx]
    if len(before):
        from tradingbot.copilot import vwap
        v = float(vwap(before)[-1])
        if pos.entry >= v:
            out.append(("gut", f"Einstieg {pos.entry:.2f} über der VWAP ({v:.2f}) -- mit dem Trend des Tages."))
        else:
            out.append(("info", f"Einstieg {pos.entry:.2f} unter der VWAP ({v:.2f}). In unseren Daten kein messbarer "
                                "Nachteil (Runde 133) -- entscheidend sind Stop-Abstand und Plan."))
    dist = (pos.entry - pos.initial_stop) / pos.entry
    if dist < min_stop_pct:
        out.append(("achtung", f"Stop nur {dist:.2%} unter dem Einstieg (Mindestabstand {min_stop_pct:.1%}) -- "
                               "normales Kerzen-Rauschen reicht, um ihn auszulösen."))
    if reason.startswith("Stop") and wide_stop is not None and wide_stop < pos.initial_stop - 1e-9:
        alt = Position(pos.entry_idx, pos.entry, wide_stop, pos.target, pos.setup, initial_stop=wide_stop)
        hit = None
        for i in range(pos.entry_idx, len(bars)):
            hit = check_exit(bars, alt, i)
            if hit:
                break
        if hit:
            price, why = hit
            r_alt = (price - pos.entry) / alt.one_r
            if why.startswith("Ziel") or r_alt > 0:
                out.append(("achtung", f"Mit dem Stop unter dem letzten Rücksetzer ({wide_stop:.2f}) hättest du "
                                       f"{why} erreicht: {r_alt:+.2f} R (bei gleichem Geldrisiko). Der Stop war zu eng."))
            else:
                out.append(("info", f"Auch ein Stop unter dem letzten Rücksetzer ({wide_stop:.2f}) wäre gerissen "
                                    f"({r_alt:+.2f} R) -- die Idee war falsch, nicht der Stop."))
    elif reason.startswith("Ziel"):
        out.append(("gut", "Ziel erreicht -- Plan eingehalten."))
    after = bars.iloc[exit_idx + 1:]
    if reason.startswith("Stop") and pos.target is not None and len(after) and float(after["high"].max()) >= pos.target:
        t = after.index[int((after["high"] >= pos.target).to_numpy().argmax())].astimezone(NY)
        out.append(("info", f"Nach deinem Stop lief der Kurs noch bis zu deinem Ziel {pos.target:.2f} "
                            f"(um {t:%H:%M} New York)."))
    return out


# ------------------------------------------------------------ Journal

def append_result(path: Path, result: Result) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(asdict(result), ensure_ascii=False) + "\n")


def load_results(path: Path) -> list[Result]:
    if not path.exists():
        return []
    return [Result(**json.loads(line)) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


# ------------------------------------------------------------ Kursdaten

def _sessions(trading_client, start: date, end: date) -> list:
    from alpaca.trading.requests import GetCalendarRequest

    return list(trading_client.get_calendar(GetCalendarRequest(start=start, end=end)))


def _session_time(value) -> time:
    return value.time() if isinstance(value, datetime) else value


def load_day(data_client, trading_client, symbol: str, day: date):
    """5-Minuten-SIP-Kerzen des Tages (Kernhandelszeit) und Schlusskurs des Vortags."""
    import pandas as pd
    from alpaca.data.enums import DataFeed
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

    sessions = [s for s in _sessions(trading_client, day - timedelta(days=10), day) if s.date <= day]
    if len(sessions) < 2 or sessions[-1].date != day:
        raise ValueError(f"{day:%d.%m.%Y} war kein Handelstag.")
    prev, cur = sessions[-2], sessions[-1]
    close_et = _session_time(cur.close)
    start = datetime.combine(prev.date, time(9, 30), tzinfo=NY)
    end = datetime.combine(cur.date, close_et, tzinfo=NY)
    df = data_client.get_stock_bars(StockBarsRequest(symbol_or_symbols=symbol.upper(),
                                                     timeframe=TimeFrame(5, TimeFrameUnit.Minute), start=start,
                                                     end=end, feed=DataFeed.SIP)).df
    if df.empty:
        raise ValueError(f"Keine Kursdaten für {symbol} am {day:%d.%m.%Y}.")
    df = df.xs(symbol.upper(), level="symbol")
    df.index = df.index.tz_convert(NY)
    t, d = df.index.time, df.index.date
    prev_bars = df[(d == prev.date) & (t >= time(9, 30)) & (t < _session_time(prev.close))]
    today = df[(d == day) & (t >= time(9, 30)) & (t < close_et)]
    if today.empty or prev_bars.empty:
        raise ValueError(f"Unvollständige Kursdaten für {symbol} am {day:%d.%m.%Y}.")
    return pd.DataFrame(today[["open", "high", "low", "close", "volume"]]), float(prev_bars["close"].iloc[-1])


def start_index(bars, start_et: time) -> int:
    """Anzahl der Kerzen, die zu Beginn sichtbar sind (alle vor start_et, mindestens eine)."""
    return max(1, int((bars.index.time < start_et).sum()))


def pick_random_day(data_client, trading_client, today: date, rng: random.Random | None = None,
                    symbols=PRACTICE_SYMBOLS, min_change_pct: float = 2.0, start_et: time = time(12, 0),
                    lookback_days: int = 180, tries: int = 12):
    """Zufälliger vergangener Tag + Aktie, die zum Startzeitpunkt mindestens min_change_pct im Plus
    lag -- wie ein Treffer der Kandidatensuche. Wie es weitergeht, weiß man dabei nicht."""
    rng = rng or random.Random()
    days = [s.date for s in _sessions(trading_client, today - timedelta(days=lookback_days), today - timedelta(days=1))]
    if not days:
        raise ValueError("Kein vergangener Handelstag gefunden.")
    fallback = None
    for _ in range(tries):
        symbol, day = rng.choice(symbols), rng.choice(days)
        try:
            bars, prev_close = load_day(data_client, trading_client, symbol, day)
        except ValueError:
            continue
        visible = bars.iloc[:start_index(bars, start_et)]
        change = (float(visible["close"].iloc[-1]) / prev_close - 1) * 100
        if change >= min_change_pct:
            return symbol, day, bars, prev_close
        fallback = fallback or (symbol, day, bars, prev_close)
    if fallback is None:
        raise ValueError("Keine Kursdaten gefunden -- später noch einmal versuchen.")
    return fallback


def summarize(results: list[Result]) -> dict:
    rs = [x.r for x in results]
    wins = sum(r for r in rs if r > 0)
    losses = -sum(r for r in rs if r < 0)
    return {"n": len(rs), "win_rate": (sum(r > 0 for r in rs) / len(rs)) if rs else 0.0,
            "avg_r": (sum(rs) / len(rs)) if rs else 0.0, "sum_r": sum(rs),
            "profit_factor": (wins / losses) if losses > 0 else (float("inf") if wins > 0 else 0.0)}

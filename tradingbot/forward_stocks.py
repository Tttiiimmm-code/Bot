"""Vorwärtstest (Papier, keine Orders) der zwei stabilsten Aktien-Beinahe-Treffer der Forschung
(research/PROTOCOL.md, Branch research/ideas):

- orb_or5 (Runden 107/107b): je Handelstag die 5 Aktien mit dem höchsten relativen Volumen der ersten
  5 Minuten (Grundfilter Kurs > 5 $, Ø-Volumen > 1 Mio., ATR > 0,50 $). Richtung = Farbe der ersten
  5-Minuten-Kerze; Stop-Einstieg am Hoch (long) bzw. Tief (short) bis 15:00 ET; Stop auf der Gegenseite
  der Range; Ziel 2 R, sonst Ausstieg zum letzten Minutenschluss. Kosten 1 bp + 0,01 $/Aktie je Seite.
  Backtest: Bestätigung 2020-22 +0,047 R/Trade, Endtest 2023-26 +0,026 R (t 1,52, nicht bestanden).
- quality_top50 (Runden 118/118b): monatlich die 50 Aktien mit dem besten Mittel aus hohem Rang der
  operativen Marge (Jahres-OperatingIncomeLoss / Umsatz) und niedrigem Rang der Aktien-Neuausgabe
  (Aktienzahl / Vorjahr - 1), SEC-XBRL point-in-time; Universum Kurs > 5 $, Ø-$-Umsatz 20 T >= 5 Mio.,
  >= 252 Handelstage Historie. Kauf zur Eröffnung des ersten Handelstags nach Monatsende, Verkauf zur
  Eröffnung des ersten Handelstags nach dem nächsten Monatsende; 10 bp je Seite. Kennzahl: Rendite minus
  gleichgewichtetes Universum. Backtest Endtest 2023-26 +0,38 %/Monat (t 1,17, nicht bestanden).
- smallvq_top20 (Runde 98): Value + Qualität bei kleinen, illiquiden Aktien. Kandidaten Schluss > 2 $,
  Ø-$-Umsatz 20 T 0,1-5 Mio., >= 252 Tage, Eigenkapital > 0 und B/M vorhanden. Score = Ø-Perzentil aus
  B/M, E/P, CF/P, Bruttogewinn/Vermögen, ROA sowie invertiert Vermögenswachstum, Aktien-Neuausgabe, Accruals
  (Verfügbarkeit wie Runde 95). Kauf ab Top 20 %, halten solange Top 40 %; gleichgewichtet; Termine wie
  quality_top50; 75 bp je Seite. Backtest P1 -0,42 %, P2 +1,00 % (t 2,76), ungesehen +1,48 %/Monat.

Alle nutzen Alpaca-Marktdaten (Schlüssel aus einer .env-Datei, nur Lesezugriff) und schreiben je eine
CSV; gleiche Schlüssel werden ersetzt (idempotent). Nur Tage/Monate ab `first_day` zählen. Der Lauf
verarbeitet Daten bis einschließlich Vortag (der kostenlose SIP-Zugang erlaubt keine Abfrage bis jetzt).
"""

from __future__ import annotations

import csv
import json
import logging
import math
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

NY = "America/New_York"
ORB_FIELDS = ["date", "symbol", "side", "entry_time", "entry", "stop", "target", "exit_time", "exit", "r_net"]
QUALITY_FIELDS = ["signal", "entry_date", "exit_date", "holdings", "port_ret", "bench_ret", "turnover",
                  "net_excess", "spy_ret"]   # spy_ret: SPY Eröffnung -> Eröffnung im selben Fenster (Maßstab "besser als ETF")
ORB_EXPECTED_R = 0.026          # Endtest 2023-26 je Trade
QUALITY_EXPECTED = 0.0038       # Endtest 2023-26 je Monat (Überschuss)
SMALLVQ_EXPECTED = 0.0100       # Runde 98, P2 je Monat netto (ungesehen +1,48 %, P1 -0,42 %)
SEC_UA = {"User-Agent": "tradingbot-research-script"}


@dataclass(frozen=True)
class StockForwardConfig:
    first_day: date
    orb_ledger: Path = Path("forward_orb.csv")
    quality_ledger: Path = Path("forward_quality.csv")
    sec_dir: Path = Path("data_cache") / "forward" / "sec"
    lookback_days: int = 7
    orb_top: int = 5
    orb_or_minutes: int = 5
    orb_cutoff_minute: int = 330     # 15:00 ET
    orb_target_r: float = 2.0
    quality_top: int = 50
    quality_cost_per_side: float = 10e-4
    smallvq_ledger: Path = Path("forward_smallvq.csv")
    smallvq_cost_per_side: float = 75e-4


# ------------------------------------------------------------ ORB (eine Aktie, ein Tag)

def orb_trade(bars: pd.DataFrame, or_minutes: int = 5, cutoff_minute: int = 330,
              target_r: float = 2.0) -> dict | None:
    """`bars`: Minuten-Bars EINER Aktie an EINEM Tag (Index NY-Zeit, Spalten open/high/low/close).
    Regeln wie Runde 107 (Einstiegsminute: nur Stop prüfen; danach Stop vor Ziel, Kurslücke -> Open)."""
    if bars.empty:
        return None
    idx = bars.index.tz_convert(NY)
    minute = np.asarray(idx.hour * 60 + idx.minute - 570)
    keep = (minute >= 0) & (minute < 390)
    bars, minute, idx = bars[keep], minute[keep], idx[keep]
    if len(bars) < 2 or minute[0] != 0:
        return None
    o, h, l, c = (bars[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    in_or = minute < or_minutes
    after = np.flatnonzero(~in_or)
    if len(after) == 0:
        return None
    orh, orl = h[in_or].max(), l[in_or].min()
    oro, orc = o[0], c[in_or][-1]
    if orc > oro:
        side = 1
    elif orc < oro:
        side = -1
    else:
        return None
    level = orh if side > 0 else orl
    e = entry = None
    for k in after:
        if minute[k] > cutoff_minute:
            break
        if side > 0 and h[k] > level:
            e, entry = k, max(o[k], level)
            break
        if side < 0 and l[k] < level:
            e, entry = k, min(o[k], level)
            break
    if e is None:
        return None
    stop = orl if side > 0 else orh
    sd = (entry - stop) * side
    if not sd > 0:
        return None
    tp = entry + side * target_r * sd
    ex, xk = c[-1], len(c) - 1
    for j in range(e, len(c)):
        if side > 0:
            if j > e and (o[j] <= stop or o[j] >= tp):
                ex, xk = o[j], j
                break
            if l[j] <= stop:
                ex, xk = stop, j
                break
            if j > e and h[j] >= tp:
                ex, xk = tp, j
                break
        else:
            if j > e and (o[j] >= stop or o[j] <= tp):
                ex, xk = o[j], j
                break
            if h[j] >= stop:
                ex, xk = stop, j
                break
            if j > e and l[j] <= tp:
                ex, xk = tp, j
                break
    cost = 2.0 * (0.0001 * entry + 0.01) / sd
    return {"side": "long" if side > 0 else "short", "entry_time": idx[e].isoformat(), "entry": round(entry, 4),
            "stop": round(stop, 4), "target": round(tp, 4), "exit_time": idx[xk].isoformat(), "exit": round(ex, 4),
            "r_net": round(side * (ex - entry) / sd - cost, 4)}


# ------------------------------------------------------------ Qualität (Querschnitt)

def cross_rank(values: pd.Series) -> pd.Series:
    """Perzentilrang in (0, 1), fehlend 0,5 -- wie ml_rank.cross_rank in Runde 95/118."""
    n = int(values.notna().sum())
    return ((values.rank(method="average") - 0.5) / max(n, 1)).fillna(0.5)


def quality_pick(opm: pd.Series, issuance: pd.Series, universe: list[str], top: int) -> list[str]:
    """Top-N nach (Rang opm - 0,5) - (Rang issuance - 0,5) innerhalb des Universums (Runde 118)."""
    u = pd.Index(universe)
    score = (cross_rank(opm.reindex(u)) - 0.5) - (cross_rank(issuance.reindex(u)) - 0.5)
    return list(score.sort_values(ascending=False, kind="stable").index[:top])


def month_schedule(days: pd.DatetimeIndex) -> list[tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp | None]]:
    """(Signal = letzter Handelstag des Monats, Kauf = nächster Handelstag, Verkauf = Handelstag nach dem
    nächsten Signal oder None, solange noch nicht erreicht). Der letzte (evtl. laufende) Monat ist kein Signal."""
    days = pd.DatetimeIndex(days).sort_values()
    pos = pd.Series(np.arange(len(days)), index=days)
    sig = pos.groupby(days.to_period("M")).max().to_numpy()[:-1]
    out = []
    for i, a in enumerate(sig):
        nxt = sig[i + 1] + 1 if i + 1 < len(sig) and sig[i + 1] + 1 < len(days) else None
        if a + 1 < len(days):
            out.append((days[a], days[a + 1], days[nxt] if nxt is not None else None))
    return out


def _sec_get(url: str) -> dict | None:
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=SEC_UA), timeout=120) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def sec_frame(concept: str, period: str, base: Path, taxonomy: str = "us-gaap", unit: str = "USD") -> pd.Series:
    """XBRL-Frame aller Firmen (Wert je CIK, zehnstellig)."""
    path = base / f"{concept}_{period}.json"
    if path.exists():
        data = json.loads(path.read_text())
    else:
        raw = _sec_get(f"https://data.sec.gov/api/xbrl/frames/{taxonomy}/{concept}/{unit}/{period}.json")
        data = {str(r["cik"]).zfill(10): r["val"] for r in (raw or {}).get("data", [])}
        base.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data))
    return pd.Series(data, dtype=float)


def available_quarter(signal: pd.Timestamp) -> pd.Period | None:
    """Letztes Quartal, dessen Stichtagswerte zum Signaltag verfügbar sind (Quartalsende + 3 Monate,
    Monatsende; höchstens 190 Tage alt) -- wie Runde 95."""
    for back in range(8):
        cand = (signal - pd.DateOffset(months=3 + 3 * back)).to_period("Q")
        avail = cand.end_time.normalize() + pd.DateOffset(months=3) + pd.offsets.MonthEnd(0)
        if avail <= signal:
            return cand if (signal - avail).days <= 190 else None
    return None


def annual_year(signal: pd.Timestamp) -> int:
    """Letztes Kalenderjahr, dessen Jahreswerte verfügbar sind (ab 31.5. des Folgejahres)."""
    return signal.year - 1 if signal >= pd.Timestamp(year=signal.year, month=5, day=31) else signal.year - 2


def fundamentals_as_of(signal: pd.Timestamp, base: Path) -> tuple[pd.Series, pd.Series]:
    """opm und issuance je CIK, wie zum Signaltag verfügbar."""
    y = annual_year(signal)
    oi = sec_frame("OperatingIncomeLoss", f"CY{y}", base)
    rev = sec_frame("RevenueFromContractWithCustomerExcludingAssessedTax", f"CY{y}", base).combine_first(
        sec_frame("Revenues", f"CY{y}", base))
    opm = (oi / rev.where(rev > 0)).dropna()
    q = available_quarter(signal)
    if q is None:
        return opm, pd.Series(dtype=float)
    cur = sec_frame("EntityCommonStockSharesOutstanding", f"CY{q.year}Q{q.quarter}I", base, "dei", "shares")
    prev = sec_frame("EntityCommonStockSharesOutstanding", f"CY{q.year - 1}Q{q.quarter}I", base, "dei", "shares")
    return opm, (cur / prev.where(prev > 0) - 1).dropna()


def ticker_map() -> dict[str, str]:
    """CIK -> Ticker (aktuelle SEC-Liste)."""
    raw = _sec_get("https://www.sec.gov/files/company_tickers.json") or {}
    out: dict[str, str] = {}
    for v in raw.values():
        out.setdefault(str(v["cik_str"]).zfill(10), v["ticker"].upper())
    return out


def by_ticker(s: pd.Series, cik2t: dict[str, str]) -> pd.Series:
    s = s.copy()
    s.index = [cik2t.get(k) for k in s.index]
    s = s[s.index.notna()]
    return s.groupby(level=0).last()


# ------------------------------------------------------------ Ledger

def _read(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _write(path: Path, rows: list[dict], fields: list[str], key) -> int:
    existing = {key(r): r for r in _read(path)}
    new = sum(key(r) not in existing for r in rows)
    for r in rows:
        existing[key(r)] = {k: r[k] for k in fields}
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(sorted(existing.values(), key=lambda r: tuple(str(x) for x in key(r))))
    tmp.replace(path)
    return new


def update_orb_ledger(path: Path, rows: list[dict]) -> int:
    return _write(path, rows, ORB_FIELDS, lambda r: (r["date"], r["symbol"]))


def update_quality_ledger(path: Path, rows: list[dict]) -> int:
    return _write(path, rows, QUALITY_FIELDS, lambda r: (r["signal"],))


def _t(x: list[float]) -> float:
    n = len(x)
    if n < 3:
        return float("nan")
    m = sum(x) / n
    sd = math.sqrt(sum((v - m) ** 2 for v in x) / (n - 1))
    return m / sd * math.sqrt(n) if sd > 0 else float("nan")


def summarize(cfg: StockForwardConfig) -> str:
    lines = []
    orb = _read(cfg.orb_ledger)
    if orb:
        r = [float(x["r_net"]) for x in orb]
        by_day: dict[str, float] = {}
        for x in orb:
            by_day[x["date"]] = by_day.get(x["date"], 0.0) + float(x["r_net"])
        lines.append(f"orb_or5: {len(r)} Trades an {len(by_day)} Tagen ({min(by_day)} bis {max(by_day)}), "
                     f"Ø {sum(r) / len(r):+.3f} R (Backtest-Endtest {ORB_EXPECTED_R:+.3f}), Treffer "
                     f"{sum(v > 0 for v in r) / len(r):.0%}, Summe {sum(r):+.1f} R, t(Tage) {_t(list(by_day.values())):.2f}")
    else:
        lines.append("orb_or5: noch keine Trades")
    for name, path, expected in (("quality_top50", cfg.quality_ledger, QUALITY_EXPECTED),
                                 ("smallvq_top20", cfg.smallvq_ledger, SMALLVQ_EXPECTED)):
        rows = _read(path)
        done = [x for x in rows if x["net_excess"] != ""]
        if done:
            ex = [float(x["net_excess"]) for x in done]
            lines.append(f"{name}: {len(ex)} Monate, Ø Überschuss {sum(ex) / len(ex):+.2%}/Monat "
                         f"(Backtest {expected:+.2%}), Monate positiv {sum(v > 0 for v in ex)}/{len(ex)}")
        else:
            lines.append(f"{name}: noch kein abgeschlossener Monat")
        open_rows = [x for x in rows if x["net_excess"] == ""]
        if open_rows:
            h = [s for s in open_rows[-1]["holdings"].split(";") if s]
            lines.append(f"  laufendes Papierdepot seit {open_rows[-1]['entry_date']} ({len(h)} Aktien): "
                         f"{', '.join(h[:15])}" + (" ..." if len(h) > 15 else ""))
    lines.append("Hinweis: ORB braucht ~1 Jahr, Monatsdepots mehrere Jahre, bis sich etwas Belastbares zeigt.")
    return "\n".join(lines)


# ------------------------------------------------------------ Läufe

def run_orb(cfg: StockForwardConfig, data_client, trading_client, last_day: date) -> int:
    from tradingbot.research import universe as uni

    start = max(cfg.first_day, last_day - timedelta(days=cfg.lookback_days))
    if start > last_day:
        return 0
    with tempfile.TemporaryDirectory(prefix="forward_orb_") as tmp:
        base = Path(tmp)
        cand = uni.build_all(data_client, trading_client, start - timedelta(days=30), last_day, base=base, top_n=20)
        days = sorted(d for d in cand.index.get_level_values("date").unique() if start <= d <= last_day) \
            if len(cand) else []
        if not days:
            return 0
        months = sorted({(d.year, d.month) for d in days})
        intraday = pd.concat([uni.load_intraday_month(y, m, base) for y, m in months])
    rows = []
    for d in days:
        top = cand.loc[d].sort_values("relvol", ascending=False).head(cfg.orb_top)
        for sym in top.index:
            if sym not in intraday.index.get_level_values("symbol"):
                continue
            bars = intraday.loc[sym]
            bars = bars[bars.index.date == d]
            t = orb_trade(bars, cfg.orb_or_minutes, cfg.orb_cutoff_minute, cfg.orb_target_r)
            if t is not None:
                rows.append({"date": d.isoformat(), "symbol": sym, **t})
    return update_orb_ledger(cfg.orb_ledger, rows)


def quality_rows(cfg: StockForwardConfig, o: pd.DataFrame, c: pd.DataFrame, v: pd.DataFrame,
                 ledger: dict[str, dict], pick) -> list[dict]:
    """Je Monat ab first_day: Depot festlegen (pick(signal, mitglieder) -> Ticker) und, sobald der
    Verkaufstag erreicht ist, Rendite abrechnen. o/c/v: Wide-Matrizen (Tage x Symbole)."""
    dv20 = (c * v).rolling(20).mean()
    univ = (c > 5) & (dv20 >= 5e6) & (c.notna().cumsum() >= 252)
    rows = []
    for signal, entry, exit_ in month_schedule(c.index):
        if entry.date() < cfg.first_day:
            continue
        key = signal.date().isoformat()
        if key in ledger and ledger[key]["net_excess"] != "":
            continue
        members = list(univ.columns[univ.loc[signal].to_numpy(bool)])
        holdings = ledger[key]["holdings"].split(";") if key in ledger else pick(signal, members)
        row = {"signal": key, "entry_date": entry.date().isoformat(), "exit_date": "", "holdings": ";".join(holdings),
               "port_ret": "", "bench_ret": "", "turnover": "", "net_excess": "", "spy_ret": ""}
        if exit_ is not None and holdings:
            r = (o.loc[exit_] / o.loc[entry] - 1).where(o.loc[entry] > 0)
            port = float(r.reindex(holdings).fillna(0.0).mean())
            bench = float(r.reindex(members).mean())
            prev = [x for k, x in sorted(ledger.items()) if k < key]
            prev_h = set(prev[-1]["holdings"].split(";")) if prev else set()
            turn = len(set(holdings) ^ prev_h) / len(holdings)
            net = port - bench - cfg.quality_cost_per_side * turn
            row.update(exit_date=exit_.date().isoformat(), port_ret=round(port, 6), bench_ret=round(bench, 6),
                       turnover=round(turn, 3), net_excess=round(net, 6))
            row.update(spy_ret=_spy_ret(o, entry, exit_))
        rows.append(row)
        ledger[key] = row
    return rows


def _spy_ret(o: pd.DataFrame, entry, exit_):
    """SPY Eröffnung (Kauftag) -> Eröffnung (Verkaufstag); "" ohne SPY-Kurse."""
    if "SPY" not in o.columns or not (o.loc[entry, "SPY"] > 0) or not (o.loc[exit_, "SPY"] > 0):
        return ""                                  # fehlender Kurs -> leer statt "nan" im Ledger
    return round(float(o.loc[exit_, "SPY"] / o.loc[entry, "SPY"] - 1), 6)


def quality_due(ledger: dict[str, dict], last_day: date) -> bool:
    """Monatliche Arbeit (Depot festlegen, Vormonat abrechnen) fällt nur nach einem Monatsende an. Nach der ersten
    Monatswoche ist sie erledigt, sobald es eine Zeile zum letzten Monatsende gibt -- dann den teuren
    Datenabruf (ein Jahr Kurse aller Aktien) überspringen."""
    prev_month = (last_day.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
    return last_day.day <= 7 or not any(k.startswith(prev_month) for k in ledger)


VQ_KEYS = ("bm", "ep", "cfp", "gpa", "roa", "ag", "iss", "acc")


def value_quality_metrics(signal: pd.Timestamp, base: Path, cik2t: dict[str, str], close_row: pd.Series) -> pd.DataFrame:
    """Runde 98/95: 8 Kennzahlen je Ticker (hoch = gut; Wachstum/Neuausgabe/Accruals invertiert) + equity.
    Stichtagswerte des verfügbaren Quartals, Jahreswerte des verfügbaren Jahres (wie Runde 95)."""
    q = available_quarter(signal)
    if q is None:
        return pd.DataFrame(columns=[*VQ_KEYS, "equity"])
    y = annual_year(signal)

    def inst(concept, yy, tax="us-gaap", unit="USD"):
        return by_ticker(sec_frame(concept, f"CY{yy}Q{q.quarter}I", base, tax, unit), cik2t)

    def ann(concept):
        return by_ticker(sec_frame(concept, f"CY{y}", base), cik2t)

    assets, assets1 = inst("Assets", q.year), inst("Assets", q.year - 1)
    equity = inst("StockholdersEquity", q.year)
    shares = inst("EntityCommonStockSharesOutstanding", q.year, "dei", "shares")
    shares1 = inst("EntityCommonStockSharesOutstanding", q.year - 1, "dei", "shares")
    ni, cfo, gp = ann("NetIncomeLoss"), ann("NetCashProvidedByUsedInOperatingActivities"), ann("GrossProfit")
    mcap = close_row * shares
    mcap = mcap.where(mcap > 0)
    pa = assets.where(assets > 0)
    return pd.DataFrame({"bm": equity / mcap, "ep": ni / mcap, "cfp": cfo / mcap, "gpa": gp / pa, "roa": ni / pa,
                         "ag": -(assets / assets1.where(assets1 > 0) - 1),
                         "iss": -(shares / shares1.where(shares1 > 0) - 1),
                         "acc": -((ni - cfo) / pa), "equity": equity})


def smallvq_pick(metrics: pd.DataFrame, candidates: list[str], prev: set[str]) -> tuple[list[str], list[str]]:
    """(Depot, Universum): Universum = Kandidaten mit Eigenkapital > 0 und B/M vorhanden; Score = Ø-Perzentil
    der 8 Kennzahlen; kaufen ab Top 20 %, halten solange Top 40 % (Runde 98)."""
    m = metrics.reindex(candidates)
    m = m[(m["equity"] > 0) & m["bm"].notna()]
    if m.empty:
        return [], []
    score = sum(cross_rank(m[k]) for k in VQ_KEYS) / len(VQ_KEYS)
    pct = score.rank(pct=True)
    hold = set(pct.index[pct > 0.8]) | {s for s in prev if pct.get(s, 0.0) > 0.6}
    return sorted(hold), list(m.index)


def smallvq_rows(cfg: StockForwardConfig, o: pd.DataFrame, c: pd.DataFrame, v: pd.DataFrame,
                 ledger: dict[str, dict], metrics_fn) -> list[dict]:
    """Runde 98 (value+quality, kleine illiquide Aktien): Kandidaten Schluss > 2 $, Ø-$-Umsatz 20 T 0,1-5 Mio.,
    >= 252 Tage Historie; Kauf/Verkauf zur Eröffnung wie quality_top50; 75 bp je Seite auf den Umschlag;
    Vergleich: gleichgewichtetes Universum. metrics_fn(signal, schlusskurse) -> value_quality_metrics."""
    dv20 = (c * v).rolling(20).mean()
    cand_mask = (c > 2) & (dv20 >= 1e5) & (dv20 <= 5e6) & (c.notna().cumsum() >= 252)
    rows = []
    for signal, entry, exit_ in month_schedule(c.index):
        if entry.date() < cfg.first_day:
            continue
        key = signal.date().isoformat()
        if key in ledger and ledger[key]["net_excess"] != "":
            continue
        before = [x for k, x in sorted(ledger.items()) if k < key]
        prev_h = set(before[-1]["holdings"].split(";")) - {""} if before else set()
        cand = list(cand_mask.columns[cand_mask.loc[signal].to_numpy(bool)])
        holdings, members = smallvq_pick(metrics_fn(signal, c.loc[signal]), cand, prev_h)
        if key in ledger:   # Depot einmal festgelegt -> nicht neu berechnen (SEC-Daten können nachträglich wachsen)
            holdings = [h for h in ledger[key]["holdings"].split(";") if h]
        row = {"signal": key, "entry_date": entry.date().isoformat(), "exit_date": "", "holdings": ";".join(holdings),
               "port_ret": "", "bench_ret": "", "turnover": "", "net_excess": "", "spy_ret": ""}
        if exit_ is not None and holdings:
            r = (o.loc[exit_] / o.loc[entry] - 1).where(o.loc[entry] > 0)
            port = float(r.reindex(holdings).fillna(0.0).mean())
            bench = float(r.reindex(members).mean()) if members else float(r.reindex(cand).mean())
            turn = len(set(holdings) ^ prev_h) / len(holdings)
            row.update(exit_date=exit_.date().isoformat(), port_ret=round(port, 6), bench_ret=round(bench, 6),
                       turnover=round(turn, 3), net_excess=round(port - bench - cfg.smallvq_cost_per_side * turn, 6))
            row.update(spy_ret=_spy_ret(o, entry, exit_))
        rows.append(row)
        ledger[key] = row
    return rows


def run_quality(cfg: StockForwardConfig, data_client, trading_client, last_day: date) -> int:
    from tradingbot.research import universe as uni

    ledger = {r["signal"]: r for r in _read(cfg.quality_ledger)}
    vq_ledger = {r["signal"]: r for r in _read(cfg.smallvq_ledger)}
    if not (quality_due(ledger, last_day) or quality_due(vq_ledger, last_day)):
        return 0
    with tempfile.TemporaryDirectory(prefix="forward_quality_") as tmp:
        base = Path(tmp)
        symbols = uni.fetch_assets(trading_client, base)
        panel = uni.fetch_daily(data_client, symbols, last_day - timedelta(days=420), last_day, base)
    o, c, v = (panel[k].unstack("symbol") for k in ("open", "close", "volume"))
    for w in (o, c, v):
        w.index = pd.DatetimeIndex(w.index)
    cache: dict = {}

    def pick(signal, members):
        if "cik2t" not in cache:
            cache["cik2t"] = ticker_map()
        opm, iss = fundamentals_as_of(signal, cfg.sec_dir)
        return quality_pick(by_ticker(opm, cache["cik2t"]), by_ticker(iss, cache["cik2t"]), members, cfg.quality_top)

    n = update_quality_ledger(cfg.quality_ledger, quality_rows(cfg, o, c, v, ledger, pick))

    def vq_metrics(signal, close_row):
        if "cik2t" not in cache:
            cache["cik2t"] = ticker_map()
        return value_quality_metrics(signal, cfg.sec_dir, cache["cik2t"], close_row)

    return n + update_quality_ledger(cfg.smallvq_ledger, smallvq_rows(cfg, o, c, v, vq_ledger, vq_metrics))


def run(cfg: StockForwardConfig, env_file: str, last_day: date | None = None) -> str:
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.trading.client import TradingClient

    from tradingbot.report import read_account_env

    last_day = last_day or datetime.now(timezone.utc).date() - timedelta(days=1)
    key, secret, paper = read_account_env(env_file)
    data_client = StockHistoricalDataClient(key, secret)
    trading_client = TradingClient(key, secret, paper=paper)
    n_orb = run_orb(cfg, data_client, trading_client, last_day)
    n_q = run_quality(cfg, data_client, trading_client, last_day)
    logger.info("Vorwärtstest Aktien bis %s: %d neue ORB-Trades, %d neue Monatszeilen (Qualität + Small-Value).", last_day, n_orb, n_q)
    return summarize(cfg)

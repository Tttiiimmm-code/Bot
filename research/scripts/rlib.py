"""Gemeinsame Auswertung der Forschungsrunden (ab Runde 171), Kriterien wie CLAUDE.md / PROTOCOL.md:
Rendite p.a. > Maßstab UND t der monatlichen Überrendite >= Hürde UND (beide Hälften und/oder Einordnungszeitraum)
Überrendite > 0. Nachträgliche Varianten mit binding=False ("Info"), sie zählen nie fürs Urteil.

Ältere Skripte bleiben unverändert (Reproduzierbarkeit); rlib übernimmt deren geprüfte Bausteine.
Aufruf der Rundenskripte aus dem Haupt-Repo (data_cache): PYTHONPATH=<worktree> python <worktree>/research/scripts/rNNN.py
oder `python tools/runde.py rechnen NNN`. Die letzte Zeile "URTEIL: ..." liest tools/runde.py aus.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from statistics import NormalDist

import numpy as np
import pandas as pd

from r153 import spy_daily, tstat                     # noqa: F401 -- Wiederverwendung
from r158 import fred                                 # noqa: F401


def hurdle(k: int = 1) -> float:
    """t-Hürde bei k Thesen: Bonferroni einseitig 5 %, mindestens 2,0 (k=3 -> 2,13, k=4 -> 2,24, k=9 -> 2,54)."""
    return max(2.0, NormalDist().inv_cdf(1 - 0.05 / k))


def pa(r: pd.Series, per_year: int = 252) -> float:
    """Rendite p.a. aus Periodenrenditen (252 Handelstage, 12 Monate, 365 Krypto-Tage)."""
    r = pd.Series(r).dropna()
    return float((1 + r).prod() ** (per_year / len(r)) - 1) if len(r) else float("nan")


def monthly(r: pd.Series) -> pd.Series:
    """Tagesrenditen -> Monatsrenditen (PeriodIndex, verzinst)."""
    r = pd.Series(r).dropna()
    return (1 + r).groupby(r.index.to_period("M")).prod() - 1


def switch_costs(pos: pd.Series, bp: float) -> pd.Series:
    """Kosten je Tag aus Positionswechseln: |Δ Position| x bp (Basispunkte je Seite)."""
    return pos.diff().abs().fillna(pos.abs()) * bp * 1e-4


@dataclass
class Result:
    label: str
    binding: bool
    pa: float
    pa_bench: float
    t: float
    hurdle: float
    parts: dict = field(default_factory=dict)              # Teilzeitraum -> Überrendite p.a.
    passed: bool = False


def judge(r: pd.Series, bench: pd.Series, a: str, b: str, *, label: str, k: int = 1, binding: bool = True,
          split: str | None = "mitte", einordnung: tuple[str, str] | None = None, per_year: int = 252,
          bench_name: str = "SPY", ohne_besten_monat: bool = False) -> Result:
    """Kriterium prüfen und eine Zeile ausgeben. r/bench: Tagesrenditen (per_year=12: Monatsrenditen mit
    PeriodIndex oder DatetimeIndex). split: Datum der Hälftengrenze, "mitte" (Kalendermitte) oder None (keine
    Hälften). einordnung: zusätzlicher Zeitraum, dessen Überrendite p.a. > 0 sein muss (mit Renditen aus r/bench).
    ohne_besten_monat: Überrendite p.a. ohne den Monat mit der größten Überrendite muss ebenfalls > 0 sein
    (hängt der Vorteil an einem Monat?)."""
    rr, bb = r[a:b].dropna(), bench[a:b].dropna()
    idx = rr.index.intersection(bb.index)
    rr, bb = rr.loc[idx], bb.loc[idx]
    mr, mb = (rr, bb) if per_year == 12 else (monthly(rr), monthly(bb))
    ex = mr - mb
    res = Result(label, binding, pa(rr, per_year), pa(bb, per_year), tstat(ex), hurdle(k))
    if split is not None:
        ts = idx.to_timestamp() if isinstance(idx, pd.PeriodIndex) else idx
        cut = (ts[0] + (ts[-1] - ts[0]) / 2) if split == "mitte" else pd.Timestamp(split)
        h1 = ts < cut
        res.parts["1. Hälfte"] = pa(rr[h1], per_year) - pa(bb[h1], per_year)
        res.parts["2. Hälfte"] = pa(rr[~h1], per_year) - pa(bb[~h1], per_year)
    if einordnung is not None:
        er, eb = r[einordnung[0]:einordnung[1]].dropna(), bench[einordnung[0]:einordnung[1]].dropna()
        ei = er.index.intersection(eb.index)
        res.parts[f"Einordnung {einordnung[0][:4]}-{einordnung[1][:4]}"] = (pa(er.loc[ei], per_year)
                                                                           - pa(eb.loc[ei], per_year))
    if ohne_besten_monat:
        rest = ex.index != ex.idxmax()
        res.parts["ohne besten Monat"] = pa(mr[rest], 12) - pa(mb[rest], 12)
    res.passed =bool(res.pa > res.pa_bench and res.t >= res.hurdle and all(v > 0 for v in res.parts.values()))
    parts = ", ".join(f"{n} {v:+.1%}" for n, v in res.parts.items())
    tail = f" -> {'BESTANDEN' if res.passed else 'NICHT BESTANDEN'}" if binding else " (Info)"
    print(f"  {label}: {res.pa:+6.1%} p.a. vs {bench_name} {res.pa_bench:+6.1%}, t {res.t:+.2f} (Hürde {res.hurdle:.2f})"
          + (f", {parts}" if parts else "") + tail)
    return res


@dataclass
class ArmResult:
    label: str
    binding: bool
    real: float
    random: list
    better: int
    min_better: int
    passed: bool = False


def random_arm(sim, signals: pd.Series, eligible: pd.Series | None = None, *, label: str, runs: int = 25,
               min_better: int = 23, seed: int = 0, strata=None, metric=np.mean, binding: bool = True) -> ArmResult:
    """Zufalls-Einstiege als Vergleich: Ist das Signal besser als irgendein Einstieg im selben Marktzustand?
    Je Lauf so viele Einstiege wie Signale je Schicht (Standard: Kalenderjahr), zufällig gezogen aus den erlaubten
    Zeitpunkten, ausgeführt mit derselben Funktion (gleicher Stop, gleiches Ziel, gleiche Kosten).
    Bestanden, wenn das echte Signal in mindestens min_better von runs Läufen besser ist (Standard 23 von 25).

    signals, eligible: bool-Series auf demselben Index. eligible = Zeitpunkte, an denen ein Einstieg erlaubt wäre
    (z. B. derselbe Trendfilter); muss wie das Signal nur aus abgeschlossenen Kerzen berechnet sein, sonst trägt
    der Zufallsarm Zukunftswissen. Fehlt eligible, ist jeder Zeitpunkt erlaubt.
    sim(entries: bool-Series) -> Ergebnisse je Trade (z. B. R netto); metric verdichtet sie (Standard Ø)."""
    sig = signals.fillna(False).astype(bool).to_numpy()
    elig = sig | (eligible.fillna(False).astype(bool).to_numpy() if eligible is not None else True)
    strata = np.asarray(signals.index.year if strata is None else strata)
    real = float(metric(np.asarray(sim(signals.fillna(False).astype(bool)), dtype=float)))
    rng = np.random.default_rng(seed)
    pos = np.arange(len(sig))
    vals = []
    for _ in range(runs):
        pick = np.zeros(len(sig), dtype=bool)
        for s in np.unique(strata[sig]):
            cand = pos[(strata == s) & elig]
            n = int((sig & (strata == s)).sum())
            pick[rng.choice(cand, size=min(n, len(cand)), replace=False)] = True
        vals.append(float(metric(np.asarray(sim(pd.Series(pick, index=signals.index)), dtype=float))))
    better = int(sum(real > v for v in vals))
    res = ArmResult(label, binding, real, vals, better, min_better, better >= min_better)
    tail = f" -> {'BESTANDEN' if res.passed else 'NICHT BESTANDEN'}" if binding else " (Info)"
    print(f"  {label}: Signal {real:+.3f} vs Zufall Median {np.median(vals):+.3f} ({min(vals):+.3f} bis "
          f"{max(vals):+.3f}), besser in {better}/{runs} (nötig {min_better})" + tail)
    return res


def verdict(results: list) -> str:
    """Schlusszeile: bestanden, wenn mindestens eine gewertete These besteht (Hürde enthält Bonferroni).
    results: Result und/oder ArmResult; soll eine These beides bestehen, im Skript vorher verknüpfen."""
    binding = [r for r in results if r.binding]
    if not binding:
        raise ValueError("keine gewertete These")
    ok = [r.label for r in binding if r.passed]
    text = "BESTANDEN (" + ", ".join(ok) + ")" if ok else "NICHT BESTANDEN"
    print(f"\nURTEIL: {text}")
    return text


def _selftest():
    days = pd.bdate_range("2016-01-01", "2025-12-31")
    rng = np.random.default_rng(0)
    bench = pd.Series(rng.normal(4e-4, 0.01, len(days)), index=days)
    good = bench + rng.normal(4e-4, 0.003, len(days))
    assert abs(hurdle(3) - 2.128) < 1e-3 and abs(hurdle(4) - 2.241) < 1e-3 and hurdle(1) == 2.0
    r1 = judge(good, bench, "2016", "2025", label="gut", k=1)
    r2 = judge(bench - 1e-4, bench, "2016", "2025", label="schlecht", k=1)
    r3 = judge(good, bench, "2016", "2025", label="Info", binding=False)
    assert r1.passed and not r2.passed and r3.passed
    assert verdict([r1, r2, r3]).startswith("BESTANDEN (gut)")
    assert verdict([r2, r3]) == "NICHT BESTANDEN"
    m = judge(monthly(good), monthly(bench), "2016-01", "2025-12", label="monatlich", per_year=12)
    assert m.passed and abs(m.t - r1.t) < 1e-9
    # Vorteil nur in einem Monat -> fällt ohne besten Monat durch
    lucky = bench.copy()
    lucky["2020-03"] += 0.03
    l1 = judge(lucky, bench, "2016", "2025", label="ein Monat", split=None)
    l2 = judge(lucky, bench, "2016", "2025", label="ein Monat, ohne besten", split=None, ohne_besten_monat=True)
    assert l1.parts == {} and l2.parts["ohne besten Monat"] <= 1e-12 and not l2.passed
    # Zufallsarm: Signal mit echtem Vorteil vs zufällige Signale
    fwd = bench.shift(-1).rolling(5).sum().shift(-4)                      # Rendite der 5 Tage nach dem Einstieg
    sim = lambda e: fwd[e.to_numpy()].dropna()                           # noqa: E731
    trend = pd.Series(rng.random(len(days)) < 0.6, index=days)
    edge = trend & (fwd > 0) & (rng.random(len(days)) < 0.3)             # kennt die Zukunft -> muss bestehen
    noise = trend & (rng.random(len(days)) < 0.15)
    a1 = random_arm(sim, edge, trend, label="Vorteil")
    a2 = random_arm(sim, noise, trend, label="Zufall")
    assert a1.passed and a1.better == 25 and not a2.passed
    assert verdict([r2, a2]) == "NICHT BESTANDEN" and verdict([a1]).startswith("BESTANDEN")
    print("rlib Selbsttest ok")


if __name__ == "__main__":
    _selftest()

"""Monte-Carlo-Simulation von Gold-Scalping-/Grid-Bots mit extremem Hebel,
wie sie in TikTok-Werbung gezeigt werden ("$6 -> $4.340 in 5 Minuten").

Keine Strategie-Forschung im Sinne des Protokolls, sondern eine Risiko-
Demonstration: wie oft erreicht so ein Bot das Video-Ergebnis, wie oft
geht das Konto verloren? Preisbasis: GLD-Minuten-Bars (folgt dem Goldpreis
während der US-Sitzung). Kosten: typischer XAUUSD-Spread ~0,25 $ je Unze
bei ~4.000 $ = 0,6 bp je Round-Trip. Liquidation, sobald das Eigenkapital
im ungünstigsten Minutenpreis (Hoch/Tief) auf 0 fällt ("unlimited leverage"
ohne Margin-Call vorher).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

SPREAD = 0.6 / 10_000


@dataclass(frozen=True)
class RunResult:
    final_equity: float
    blown_up: bool
    hit_target: bool
    trades: int


def scalper(o, h, l, c, start: int, equity: float, leverage: float, target: float,
            take_profit: float = 2e-4, max_hold: int = 5) -> RunResult:
    """Kompoundierender Scalper: Richtung der letzten Minutenkerze, Nominale =
    leverage x aktuelles Eigenkapital (Stückzahl wächst mit dem Konto), Ziel
    +take_profit, sonst Ausstieg nach max_hold Minuten."""
    t, n, trades = start, len(c), 0
    while t < n - 1:
        side = 1.0 if c[t] >= o[t] else -1.0
        entry = c[t]
        k = t + 1
        exit_ret = 0.0
        while k < n:
            worst = (l[k] / entry - 1) if side > 0 else -(h[k] / entry - 1)
            if equity * (1 + leverage * (worst - SPREAD)) <= 0:
                return RunResult(0.0, True, False, trades + 1)
            best = (h[k] / entry - 1) if side > 0 else -(l[k] / entry - 1)
            if best >= take_profit:
                exit_ret = take_profit
                break
            if k - t >= max_hold or k == n - 1:
                exit_ret = side * (c[k] / entry - 1)
                break
            k += 1
        equity *= 1 + leverage * (exit_ret - SPREAD)
        trades += 1
        if equity <= 0:
            return RunResult(0.0, True, False, trades)
        if equity >= target:
            return RunResult(equity, False, True, trades)
        t = k
    return RunResult(equity, False, False, trades)


def grid_martingale(o, h, l, c, start: int, equity: float, leverage: float, target: float,
                    step: float = 3e-4, take_profit: float = 2e-4, max_adds: int = 5) -> RunResult:
    """Grid/Martingale: Startposition mit Nominale leverage x Eigenkapital;
    läuft der Kurs um `step` dagegen, wird die Gesamtposition verdoppelt (bis
    max_adds). Alles schließt, sobald der Kurs `take_profit` über dem
    Durchschnittseinstand liegt, spätestens zum Sitzungsende."""
    t, n, trades = start, len(c), 0
    while t < n - 1:
        side = 1.0 if c[t] >= o[t] else -1.0
        units, cost_basis, last = leverage * equity / c[t], leverage * equity, c[t]
        adds, k = 0, t + 1
        while k < n:
            avg = cost_basis / units
            worst_px = l[k] if side > 0 else h[k]
            if equity + side * units * (worst_px - avg) - SPREAD * cost_basis <= 0:
                return RunResult(0.0, True, False, trades + 1)
            tp_px = avg * (1 + side * take_profit)
            if (side > 0 and h[k] >= tp_px) or (side < 0 and l[k] <= tp_px):
                equity += side * units * (tp_px - avg) - SPREAD * cost_basis
                break
            if k == n - 1:
                equity += side * units * (c[k] - avg) - SPREAD * cost_basis
                break
            add_px = last * (1 - side * step)
            if adds < max_adds and ((side > 0 and l[k] <= add_px) or (side < 0 and h[k] >= add_px)):
                cost_basis += units * add_px  # Stückzahl verdoppeln
                units *= 2
                last, adds = add_px, adds + 1
            k += 1
        trades += 1
        if equity <= 0:
            return RunResult(0.0, True, False, trades)
        if equity >= target:
            return RunResult(equity, False, True, trades)
        t = k
    return RunResult(equity, False, False, trades)


def monte_carlo(sessions: list[pd.DataFrame], bot, leverage: float, n_runs: int = 2000,
                start_equity: float = 10.0, target: float = 4000.0, seed: int = 0) -> dict:
    """Zufällige Handelstage und Startminuten (9:45-14:00 ET), Lauf bis
    Handelsschluss, Liquidation oder Ziel (dann Stopp, wie im Video)."""
    rng = np.random.default_rng(seed)
    finals, blown, hit = [], 0, 0
    for _ in range(n_runs):
        day = sessions[rng.integers(len(sessions))]
        o, h, l, c = (day[x].to_numpy(float) for x in ("open", "high", "low", "close"))
        start = int(rng.integers(15, min(270, len(c) - 2)))
        r = bot(o, h, l, c, start, start_equity, leverage, target)
        finals.append(r.final_equity)
        blown += r.blown_up
        hit += r.hit_target
    finals = np.array(finals)
    return {
        "leverage": leverage,
        "p_target": hit / n_runs,
        "p_blown": blown / n_runs,
        "median_final": float(np.median(finals)),
        "mean_final": float(finals.mean()),
        "ev_multiple": float(finals.mean() / start_equity),
    }

"""Trading-Copilot: DU entscheidest (Symbol, Stop, Setup), der Copilot erzwingt Regeln,
berechnet die Positionsgröße, legt den Stop direkt bei Alpaca an und führt ein Journal.

Ziel ist ein ehrlicher Test, ob diskretionäre Entscheidungen einen Vorteil haben: nach
>= 100 Trades wertet `copilot report` je Setup in R-Vielfachen aus (1 R = geplantes Risiko).

Nur long. Tageszustand (realisierter P&L, Verlustserie) wird aus Alpacas ausgeführten
Orders abgeleitet -- kein lokaler Zustand, der auseinanderlaufen kann. Das Journal
(JSON-Zeilen) speichert nur, was Alpaca nicht kennt: Setup, Notiz, geplanter Stop/Risiko.

WICHTIG: eigenes Alpaca-Paper-Konto (z.B. copilot.env). Der Momentum-Bot stellt fremde
Positionen in seinem Konto glatt.
"""

from __future__ import annotations

import json
import math
import statistics
from dataclasses import asdict, dataclass, field
from datetime import datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
BERLIN = ZoneInfo("Europe/Berlin")


@dataclass(frozen=True)
class CopilotRules:
    risk_per_trade: float = 50.0            # $ Verlust, wenn der Stop greift
    max_position_dollars: float = 10_000.0
    max_daily_loss: float = 150.0           # realisiert; danach keine neuen Einstiege
    max_trades_per_day: int = 6
    loss_streak: int = 2                    # nach so vielen Verlusten in Folge ...
    cooldown_minutes: int = 20              # ... so lange Pause
    min_stop_pct: float = 0.003             # Stop enger als 0,3 % = Rauschen
    first_entry_et: time = time(9, 35)
    last_entry_et: time = time(15, 45)
    flatten_et: time = time(15, 55)


@dataclass
class JournalEntry:
    time: str        # ISO, UTC
    symbol: str
    setup: str
    shares: int
    price: float     # Kurs bei der Entscheidung
    stop: float
    target: float | None
    risk: float      # shares * (price - stop)
    note: str = ""
    order_id: str = ""

    @property
    def dt(self) -> datetime:
        return datetime.fromisoformat(self.time)


@dataclass
class DayState:
    realized_pnl: float = 0.0
    entries_today: int = 0
    loss_streak: int = 0
    last_loss_exit: datetime | None = None
    open_symbols: set[str] = field(default_factory=set)


# ------------------------------------------------------------ Regeln

def check_entry(rules: CopilotRules, state: DayState, now: datetime, symbol: str,
                price: float, stop: float) -> list[str]:
    """Liste der Regelverstöße (leer = Einstieg erlaubt)."""
    problems = []
    t = now.astimezone(NY).time()
    if not (rules.first_entry_et <= t <= rules.last_entry_et):
        problems.append(f"Einstiege nur {rules.first_entry_et:%H:%M}-{rules.last_entry_et:%H:%M} ET "
                        f"(jetzt {t:%H:%M} ET)")
    if state.realized_pnl <= -rules.max_daily_loss:
        problems.append(f"Tagesverlustgrenze erreicht ({state.realized_pnl:.2f} $ <= -{rules.max_daily_loss:.0f} $)")
    if state.entries_today >= rules.max_trades_per_day:
        problems.append(f"Maximal {rules.max_trades_per_day} Trades pro Tag erreicht")
    if state.loss_streak >= rules.loss_streak and state.last_loss_exit is not None:
        until = state.last_loss_exit + timedelta(minutes=rules.cooldown_minutes)
        if now < until:
            problems.append(f"{state.loss_streak} Verluste in Folge: Pause bis "
                            f"{until.astimezone(BERLIN):%H:%M} (deutsche Zeit)")
    if symbol in state.open_symbols:
        problems.append(f"{symbol} ist bereits offen")
    if stop >= price:
        problems.append(f"Stop {stop:.2f} muss unter dem Kurs {price:.2f} liegen (nur long)")
    elif (price - stop) / price < rules.min_stop_pct:
        problems.append(f"Stop zu eng: {(price - stop) / price:.2%} < {rules.min_stop_pct:.1%} (Rauschen)")
    return problems


def position_size(rules: CopilotRules, price: float, stop: float, buying_power: float,
                  risk: float | None = None) -> int:
    """Ganze Stück: Risiko / (Kurs - Stop), begrenzt durch Positions-Obergrenze und Kaufkraft."""
    if price <= 0 or stop >= price:
        return 0
    risk = rules.risk_per_trade if risk is None else risk
    by_risk = math.floor(risk / (price - stop))
    by_cap = math.floor(rules.max_position_dollars / price)
    by_cash = math.floor(max(buying_power, 0.0) / price)
    return max(0, min(by_risk, by_cap, by_cash))


def day_state(closed_trades: list, open_symbols: set[str], entries_today: int, now: datetime) -> DayState:
    """Tageszustand aus den heute abgeschlossenen Trades (report.MatchedTrade)."""
    today = now.astimezone(NY).date()
    todays = sorted((t for t in closed_trades if t.exit_time.astimezone(NY).date() == today),
                    key=lambda t: t.exit_time)
    streak, last_loss = 0, None
    for t in reversed(todays):
        if t.pnl < 0:
            streak += 1
            last_loss = last_loss or t.exit_time
        else:
            break
    return DayState(realized_pnl=sum(t.pnl for t in todays), entries_today=entries_today,
                    loss_streak=streak, last_loss_exit=last_loss, open_symbols=set(open_symbols))


# ------------------------------------------------------------ Journal

def append_journal(path: Path, entry: JournalEntry) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(asdict(entry), ensure_ascii=False) + "\n")


def load_journal(path: Path) -> list[JournalEntry]:
    if not path.exists():
        return []
    return [JournalEntry(**json.loads(line)) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


# ------------------------------------------------------------ Auswertung

def attach_setups(trades: list, journal: list[JournalEntry], window_minutes: int = 10) -> list[dict]:
    """Ordnet jedem abgeschlossenen Trade den Journal-Eintrag desselben Symbols zu, der
    höchstens `window_minutes` vor dem Einstieg lag (nächstgelegener). R = P&L / geplantes Risiko."""
    rows, used = [], set()
    for t in sorted(trades, key=lambda x: x.entry_time):
        best, best_gap = None, None
        for i, e in enumerate(journal):
            if i in used or e.symbol != t.symbol:
                continue
            gap = (t.entry_time - e.dt).total_seconds()
            if -60 <= gap <= window_minutes * 60 and (best_gap is None or abs(gap) < best_gap):
                best, best_gap = i, abs(gap)
        e = journal[best] if best is not None else None
        if best is not None:
            used.add(best)
        risk = e.risk if e and e.risk > 0 else None
        rows.append({"symbol": t.symbol, "entry_time": t.entry_time, "exit_time": t.exit_time,
                     "setup": e.setup if e else "(ohne Journal)", "pnl": t.pnl,
                     "r": t.pnl / risk if risk else None})
    return rows


def setup_stats(rows: list[dict]) -> list[dict]:
    """Je Setup (und gesamt): Anzahl, Trefferquote, Ø R, Summe $, Profit-Faktor, t auf R."""
    groups: dict[str, list[dict]] = {}
    for r in rows:
        groups.setdefault(r["setup"], []).append(r)
    groups["GESAMT"] = list(rows)
    out = []
    for name, rs in groups.items():
        rr = [r["r"] for r in rs if r["r"] is not None]
        pnl = [r["pnl"] for r in rs]
        wins, losses = sum(p for p in pnl if p > 0), -sum(p for p in pnl if p < 0)
        t = (statistics.mean(rr) / statistics.stdev(rr) * math.sqrt(len(rr))
             if len(rr) >= 3 and statistics.stdev(rr) > 0 else float("nan"))
        out.append({"setup": name, "n": len(rs), "win_rate": sum(p > 0 for p in pnl) / len(rs) if rs else 0.0,
                    "avg_r": statistics.mean(rr) if rr else float("nan"), "pnl": sum(pnl),
                    "profit_factor": wins / losses if losses > 0 else float("inf") if wins > 0 else 0.0,
                    "t_r": t})
    return out


def format_stats(stats: list[dict]) -> str:
    lines = [f"{'Setup':22s} {'n':>4s} {'Treffer':>8s} {'Ø R':>7s} {'P&L $':>10s} {'PF':>6s} {'t (R)':>7s}"]
    for s in stats:
        lines.append(f"{s['setup'][:22]:22s} {s['n']:4d} {s['win_rate']:8.0%} {s['avg_r']:7.2f} "
                     f"{s['pnl']:10.2f} {s['profit_factor']:6.2f} {s['t_r']:7.2f}")
    lines.append("Bewertung (vorab festgelegt): erst ab 100 Trades; bestanden bei Profit-Faktor >= 1,3 "
                 "UND t (R) >= 2 nach Kosten.")
    return "\n".join(lines)


# ------------------------------------------------------------ Alpaca

def _round_price(price: float) -> float:
    """Alpaca: ab 1 $ nur Cent-Schritte, darunter bis zu 4 Nachkommastellen."""
    return round(price, 2) if price >= 1 else round(price, 4)


class Copilot:
    def __init__(self, trading_client, data_client, rules: CopilotRules, journal_path: Path):
        self.trading_client = trading_client
        self.data_client = data_client
        self.rules = rules
        self.journal_path = journal_path

    def latest_price(self, symbol: str) -> float:
        from alpaca.data.enums import DataFeed
        from alpaca.data.requests import StockLatestTradeRequest

        res = self.data_client.get_stock_latest_trade(StockLatestTradeRequest(symbol_or_symbols=symbol,
                                                                                feed=DataFeed.IEX))
        return float(res[symbol].price)

    def _closed_trades(self, now: datetime, days: int = 1) -> tuple[list, list]:
        from tradingbot.report import fetch_closed_orders, match_trades

        start = datetime.combine(now.astimezone(NY).date() - timedelta(days=days - 1), time(0), tzinfo=NY)
        trades, open_positions, _ = match_trades(fetch_closed_orders(self.trading_client, start, now))
        return trades, open_positions

    def state(self, now: datetime) -> DayState:
        trades, _ = self._closed_trades(now)
        open_symbols = {p.symbol for p in self.trading_client.get_all_positions()}
        today = now.astimezone(NY).date()
        entries = sum(1 for e in load_journal(self.journal_path) if e.dt.astimezone(NY).date() == today)
        return day_state(trades, open_symbols, entries, now)

    def buy(self, symbol: str, stop: float, setup: str, now: datetime, target: float | None = None,
            note: str = "", risk: float | None = None) -> str:
        """Prüft die Regeln, rechnet die Stückzahl und sendet eine Market-Order mit Stop (und optional
        Ziel) bei Alpaca. Gibt eine Meldung zurück; bei Regelverstoß wird NICHT gehandelt."""
        from alpaca.trading.enums import OrderClass, OrderSide, TimeInForce
        from alpaca.trading.requests import MarketOrderRequest, StopLossRequest, TakeProfitRequest

        symbol = symbol.upper()
        price = self.latest_price(symbol)
        problems = check_entry(self.rules, self.state(now), now, symbol, price, stop)
        if target is not None and target <= price:
            problems.append(f"Ziel {target:.2f} muss über dem Kurs {price:.2f} liegen")
        if problems:
            return "KEIN TRADE:\n  - " + "\n  - ".join(problems)
        buying_power = float(self.trading_client.get_account().buying_power)
        shares = position_size(self.rules, price, stop, buying_power, risk)
        if shares <= 0:
            return f"KEIN TRADE: Stückzahl 0 (Kurs {price:.2f}, Stop {stop:.2f}, Kaufkraft {buying_power:.0f} $)"
        req = MarketOrderRequest(
            symbol=symbol, qty=shares, side=OrderSide.BUY, time_in_force=TimeInForce.DAY,
            order_class=OrderClass.BRACKET if target is not None else OrderClass.OTO,
            stop_loss=StopLossRequest(stop_price=_round_price(stop)),
            take_profit=TakeProfitRequest(limit_price=_round_price(target)) if target is not None else None,
        )
        order = self.trading_client.submit_order(req)
        planned_risk = shares * (price - stop)
        append_journal(self.journal_path, JournalEntry(
            time=now.astimezone(ZoneInfo("UTC")).isoformat(), symbol=symbol, setup=setup, shares=shares,
            price=price, stop=stop, target=target, risk=round(planned_risk, 2), note=note, order_id=str(order.id)))
        return (f"GEKAUFT (Market): {symbol} {shares} Stück @ ~{price:.2f}, Stop {stop:.2f} bei Alpaca"
                + (f", Ziel {target:.2f}" if target is not None else "")
                + f" -- Risiko {planned_risk:.2f} $ = 1 R, Setup '{setup}'")

    def close(self, symbol: str | None = None) -> str:
        """Offene Orders des Symbols stornieren (Stop-Bein) und Position per Market schließen."""
        if symbol is None:
            self.trading_client.close_all_positions(cancel_orders=True)
            return "Alle Positionen geschlossen, offene Orders storniert."
        from alpaca.trading.enums import QueryOrderStatus
        from alpaca.trading.requests import GetOrdersRequest

        symbol = symbol.upper()
        for o in self.trading_client.get_orders(filter=GetOrdersRequest(status=QueryOrderStatus.OPEN,
                                                                        symbols=[symbol])):
            self.trading_client.cancel_order_by_id(o.id)
        self.trading_client.close_position(symbol)
        return f"{symbol} geschlossen (Market), Stop-Order storniert."

    def status(self, now: datetime) -> str:
        st = self.state(now)
        lines = [f"Stand {now.astimezone(BERLIN):%H:%M} (deutsche Zeit) / {now.astimezone(NY):%H:%M} ET"]
        unreal = 0.0
        for p in self.trading_client.get_all_positions():
            u = float(p.unrealized_pl)
            unreal += u
            lines.append(f"  offen: {p.symbol} {p.qty} Stück @ {float(p.avg_entry_price):.2f}, "
                         f"aktuell {float(p.current_price):.2f}, {u:+.2f} $")
        lines.append(f"Heute realisiert {st.realized_pnl:+.2f} $, offen {unreal:+.2f} $, "
                     f"Einstiege {st.entries_today}/{self.rules.max_trades_per_day}, Verlustserie {st.loss_streak}")
        left = self.rules.max_daily_loss + st.realized_pnl
        lines.append(f"Verlustbudget bis zur Tagesgrenze: {max(left, 0):.2f} $ "
                     f"(1 R = {self.rules.risk_per_trade:.0f} $)")
        return "\n".join(lines)

    def report(self, now: datetime, days: int) -> str:
        trades, _ = self._closed_trades(now, days)
        rows = attach_setups(trades, load_journal(self.journal_path))
        if not rows:
            return f"Keine abgeschlossenen Trades in den letzten {days} Tagen."
        return format_stats(setup_stats(rows))

    def watch_step(self, now: datetime) -> str | None:
        """Ein Durchlauf der Überwachung: glattstellen zur Schlusszeit oder bei Tagesverlust
        (realisiert + offen) über der Grenze. Gibt eine Meldung zurück, wenn gehandelt wurde."""
        positions = self.trading_client.get_all_positions()
        if not positions:
            return None
        if now.astimezone(NY).time() >= self.rules.flatten_et:
            self.close(None)
            return f"{self.rules.flatten_et:%H:%M} ET erreicht: alles glattgestellt."
        st = self.state(now)
        total = st.realized_pnl + sum(float(p.unrealized_pl) for p in positions)
        if total <= -self.rules.max_daily_loss:
            self.close(None)
            return f"Tagesverlust {total:.2f} $ über der Grenze: alles glattgestellt."
        return None

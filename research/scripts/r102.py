"""Runde 102: Backtest der veröffentlichten @tagebuchmillion-Bots (Vorab-Registrierung: r102_prereg.md).

Signale für C/D direkt aus strategy.signals_vectorized der Bots (deren config.py), A/B mit den Formeln aus
deren strategy.py. Ausstiege auf H1-Bid/Ask-Kerzen (Dukascopy), Portfolio-Regeln wie in bot.py.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd

H1 = Path(r"C:\Users\Nutzer\Bot\data_cache\dukascopy\h1")
TB = Path("data_cache/r102_bots")  # entpackte Discord-Uploads (nicht im Repo)
BROKER_TZ = "Europe/Athens"          # MT5-Serverzeit GMT+2/+3 -> H4/D1-Grenzen
COMMISSION = 0.5e-4
PERIODS = {"P1 2012-2018": ("2012-01-01", "2018-12-31"), "P2 2019-2026": ("2019-01-01", "2026-12-31")}


# ------------------------------------------------------------ Daten

def _read(sym: str, side: str) -> pd.DataFrame:
    frames = []
    f = H1 / f"{sym}_{side}.csv"
    if f.exists() and f.stat().st_size > 0:
        frames.append(pd.read_csv(f))
    for p in sorted((H1 / "parts").glob(f"{sym}_{side}_*.csv")):
        if p.stat().st_size > 0:
            frames.append(pd.read_csv(p))
    if not frames:
        return pd.DataFrame(columns=["open", "high", "low", "close"])
    df = pd.concat(frames).drop_duplicates("timestamp").sort_values("timestamp")
    df.index = pd.to_datetime(df.pop("timestamp"), unit="ms", utc=True)
    return df[["open", "high", "low", "close"]].astype(float)


def load(sym: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    bid, ask = _read(sym, "bid"), _read(sym, "ask")
    idx = bid.index.union(ask.index)
    bid, ask = bid.reindex(idx), ask.reindex(idx)
    spread = (ask["close"] - bid["close"]).where(lambda s: s > 0)
    med = float(spread.median())
    for col in ("open", "high", "low", "close"):          # fehlende Seite über den mittleren Spread ergänzen
        bid[col] = bid[col].fillna(ask[col] - med)
        ask[col] = ask[col].fillna(bid[col] + med)
    keep = (bid["high"] > bid["low"]) & bid.notna().all(axis=1)   # Wochenend-/Feiertags-Flachkerzen raus
    return bid[keep], ask[keep]


def resample(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    """H4/D1 in Broker-Zeit; Index = Kerzenbeginn (UTC)."""
    loc = df.tz_convert(BROKER_TZ)
    out = loc.resample(rule).agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    return out.tz_convert("UTC")


def tf(df: pd.DataFrame, name: str) -> pd.DataFrame:
    return df if name == "H1" else resample(df, {"H4": "4h", "D1": "1D"}[name])


# ------------------------------------------------------------ Bot-Module laden

def load_bot(folder: Path):
    cfg_spec = importlib.util.spec_from_file_location("config", folder / "config.py")
    cfg = importlib.util.module_from_spec(cfg_spec)
    cfg_spec.loader.exec_module(cfg)
    sys.modules["config"] = cfg
    st_spec = importlib.util.spec_from_file_location(f"strategy_{folder.name}", folder / "strategy.py")
    st = importlib.util.module_from_spec(st_spec)
    st_spec.loader.exec_module(st)
    return cfg, st


# ------------------------------------------------------------ Signale je Bot

def signals_A(cfg, st, bars: pd.DataFrame) -> pd.DataFrame:
    close = bars["close"]
    e, r, a = st.ema(close, cfg.TREND_LEN), st.rsi(close, cfg.RSI_LEN), st.atr(bars, cfg.ATR_LEN)
    sig = (close > e) & (r > cfg.RSI_OVERSOLD) & (r.shift(1) <= cfg.RSI_OVERSOLD)
    sig &= np.arange(len(bars)) >= max(cfg.TREND_LEN, cfg.RSI_LEN, cfg.ATR_LEN) + 5
    return pd.DataFrame({"dir": 1, "stop_dist": a * cfg.ATR_STOP_MULT}, index=bars.index)[sig]


def signals_B(cfg, st, xau: pd.DataFrame, xag: pd.DataFrame) -> pd.DataFrame:
    d, band = st._diff_und_band(xau, xag)
    e = st.ema(xau["close"], cfg.TREND_LEN)
    a = st.atr(xau, cfg.ATR_LEN)
    cross = (d > band) & (d.shift(1) <= band.shift(1))
    sig = cross & (xau["close"] > e) & d.notna() & band.notna() & band.shift(1).notna()
    return pd.DataFrame({"dir": 1, "stop_dist": a * cfg.ATR_STOP_MULT}, index=xau.index)[sig]


def higher_trend(cfg, st, higher: pd.DataFrame, at: pd.DatetimeIndex, higher_rule: str) -> pd.Series:
    """Trend des höheren Zeitrahmens aus der zuletzt GESCHLOSSENEN höheren Kerze (wie _higher_tf_trend)."""
    e = st.ema(higher["close"], cfg.MTF_TREND_LEN)
    a = st.atr(higher, cfg.ATR_LEN)
    buf = a * cfg.TREND_BUFFER_ATR
    trend = pd.Series("neutral", index=higher.index, dtype=object)
    trend[higher["close"] > e + buf] = "up"
    trend[higher["close"] < e - buf] = "down"
    trend[e.isna() | (np.arange(len(higher)) < cfg.MTF_TREND_LEN * 2)] = None
    step = pd.Timedelta(hours=4) if higher_rule == "H4" else pd.Timedelta(days=1)
    trend.index = trend.index + step          # verfügbar erst ab Ende der höheren Kerze
    return trend[~trend.index.duplicated()].reindex(at, method="ffill")


def signals_CD(cfg, st, bars: pd.DataFrame, higher: pd.DataFrame | None, higher_rule: str | None,
               bar_step: pd.Timedelta) -> pd.DataFrame:
    s = st.signals_vectorized(bars)
    sig = s[s["signal"]].copy()
    if getattr(cfg, "MTF_CONFIRM", False) and higher is not None and len(sig):
        ht = higher_trend(cfg, st, higher, sig.index + bar_step, higher_rule)   # Zeitpunkt: Ende der Signalkerze
        ht.index = sig.index
        against = (sig["long"] & (ht == "down")) | (sig["short"] & (ht == "up"))
        sig = sig[~against]
    return pd.DataFrame({"dir": np.where(sig["long"], 1, -1), "stop_dist": sig["stop_dist"]}, index=sig.index)


# ------------------------------------------------------------ Ausführung

def simulate(arr: dict, entry_pos: int, side: int, stop_dist: float, rr: float, secure: tuple | None,
             spread_filter: bool):
    """Einstieg zur Eröffnung der H1-Kerze entry_pos. Gibt (exit_pos, R, entry) oder None (Spread-Filter)."""
    bo, bh, bl, ao, ah, al = (arr[k] for k in ("bo", "bh", "bl", "ao", "ah", "al"))
    spread = ao[entry_pos] - bo[entry_pos]
    if spread_filter:
        if spread > 0.15 * stop_dist:
            return None
        stop_dist = max(stop_dist, spread * 2 * 1.1)
    entry = ao[entry_pos] if side > 0 else bo[entry_pos]
    sl, tp = entry - side * stop_dist, entry + side * rr * stop_dist
    secured = False
    for i in range(entry_pos, len(bo)):
        if side > 0:
            o, h, l_ = bo[i], bh[i], bl[i]
            if i > entry_pos and (o <= sl or o >= tp):
                return i, (o - entry) / stop_dist, entry, stop_dist
            if l_ <= sl:
                return i, (sl - entry) / stop_dist, entry, stop_dist
            if h >= tp:
                return i, (tp - entry) / stop_dist, entry, stop_dist
            if secure and not secured and h >= entry + secure[0] * stop_dist:
                sl, secured = entry + secure[1] * stop_dist, True
        else:
            o, h, l_ = ao[i], ah[i], al[i]
            if i > entry_pos and (o >= sl or o <= tp):
                return i, (entry - o) / stop_dist, entry, stop_dist
            if h >= sl:
                return i, (entry - sl) / stop_dist, entry, stop_dist
            if l_ <= tp:
                return i, (entry - tp) / stop_dist, entry, stop_dist
            if secure and not secured and l_ <= entry - secure[0] * stop_dist:
                sl, secured = entry - secure[1] * stop_dist, True
    return None


def run_bot(name: str, markets: dict, signal_frames: dict, cfg, secure, daily_loss_r,
            spread_filter: bool) -> pd.DataFrame:
    """Portfolio: 1 Position je Symbol, max. MAX_OPEN_POSITIONS, Tagesverlust-Sperre (UTC-Tag)."""
    cands = []
    for sym, sigs in signal_frames.items():
        bid, _, step, _ = markets[sym]
        pos = bid.index.searchsorted(sigs.index + step)      # erste H1-Kerze ab Ende der Signalkerze
        for (t, row), p in zip(sigs.iterrows(), pos):
            if p < len(bid):
                cands.append((bid.index[p], sym, int(row["dir"]), float(row["stop_dist"]), int(p)))
    cands.sort(key=lambda c: c[0])
    open_until: dict[str, pd.Timestamp] = {}
    trades = []
    for t_entry, sym, side, sd, p in cands:
        if not np.isfinite(sd) or sd <= 0:
            continue
        if sym in open_until and open_until[sym] > t_entry:
            continue
        if sum(1 for v in open_until.values() if v > t_entry) >= cfg.MAX_OPEN_POSITIONS:
            continue
        if daily_loss_r is not None:
            day = t_entry.normalize()
            lost = sum(tr["r"] for tr in trades[-50:] if tr["exit"].normalize() == day and tr["exit"] <= t_entry)
            if lost <= -daily_loss_r:
                continue
        bid, ask, _, arr = markets[sym]
        res = simulate(arr, p, side, sd, cfg.RR_RATIO, secure, spread_filter)
        if res is None:
            continue
        exit_pos, r_gross, entry_px, sd_eff = res
        r = r_gross - COMMISSION * entry_px / sd_eff
        exit_t = bid.index[exit_pos] + pd.Timedelta(hours=1)
        open_until[sym] = exit_t
        trades.append({"bot": name, "sym": sym, "side": side, "entry": t_entry, "exit": exit_t, "r": r})
    return pd.DataFrame(trades)


# ------------------------------------------------------------ Auswertung

def stats(r: pd.Series, years: float) -> str:
    if len(r) < 2:
        return f"n {len(r)}"
    t = r.mean() / r.std() * np.sqrt(len(r))
    wins, losses = r[r > 0].sum(), -r[r < 0].sum()
    pf = wins / losses if losses > 0 else float("inf")
    return (f"n {len(r):4d} ({len(r) / years:5.1f}/J)  Ø R {r.mean():+.3f}  t {t:+.2f}  Treffer {(r > 0).mean():.0%}  "
            f"PF {pf:.2f}  Summe {r.sum():+.1f} R")


def ftmo(trades: pd.DataFrame, risk_pct: float) -> str:
    """Start an jedem Monatsanfang: +10 % vor -10 % gesamt bzw. -5 % an einem Tag (realisiert)."""
    starts = pd.date_range("2012-06-01", "2026-06-01", freq="MS", tz="UTC")
    tr_all = trades.sort_values("exit")
    res = []
    for s in starts:
        tr = tr_all[tr_all["entry"] >= s]
        eq, day, day_start, outcome, days = 0.0, None, 0.0, "offen", None
        for x_exit, x_r in zip(tr["exit"], tr["r"]):
            d = x_exit.normalize()
            if d != day:
                day, day_start = d, eq
            eq += x_r * risk_pct
            if eq - day_start <= -5.0 or eq <= -10.0:
                outcome, days = "durchgefallen", (x_exit - s).days
                break
            if eq >= 10.0:
                outcome, days = "bestanden", (x_exit - s).days
                break
        res.append((outcome, days))
    df = pd.DataFrame(res, columns=["o", "d"])
    done = df[df["o"] != "offen"]
    passed = done[done["o"] == "bestanden"]
    if not len(passed):
        return f"0/{len(done)} bestanden"
    return (f"{len(passed)}/{len(done)} bestanden ({len(passed) / len(done):.0%}), "
            f"Median bis Bestehen {passed['d'].median():.0f} Tage")


def main() -> None:
    folders = {"A": TB / "1-Haupt-Bot" / "1-Haupt-Bot", "B": TB / "3-Divergenz-Gold-Silber" / "3-Divergenz-Gold-Silber",
               "C": TB / "2-David-V2" / "2-David-V2", "D": TB / "David-V2.0-BenV0.5.1"}
    sym_map = {"XAUUSD": "xauusd", "XAGUSD": "xagusd", "CHFJPY": "chfjpy", "USDJPY": "usdjpy", "EURUSD": "eurusd",
               "GBPUSD": "gbpusd", "USDCHF": "usdchf", "USDCNH": "usdcnh", "AUDUSD": "audusd", "NZDUSD": "nzdusd",
               "USDSEK": "usdsek", "GBPJPY": "gbpjpy", "EURJPY": "eurjpy", "USTEC": "usatechidxusd"}
    cache = {}

    def data(sym):
        if sym not in cache:
            bid, ask = load(sym_map[sym])
            arr = {"bo": bid["open"].to_numpy(), "bh": bid["high"].to_numpy(), "bl": bid["low"].to_numpy(),
                   "ao": ask["open"].to_numpy(), "ah": ask["high"].to_numpy(), "al": ask["low"].to_numpy()}
            cache[sym] = (bid, ask, arr)
        return cache[sym]

    all_trades = []
    for bot, folder in folders.items():
        cfg, st = load_bot(folder)
        markets, sigs = {}, {}
        if bot == "B":
            bid, ask, arr = data("XAUUSD")
            xau, xag = tf(bid, "H4"), tf(data("XAGUSD")[0], "H4")
            sigs["XAUUSD"] = signals_B(cfg, st, xau, xag)
            markets["XAUUSD"] = (bid, ask, pd.Timedelta(hours=4), arr)
        else:
            for sym, frame in cfg.MARKETS.items():
                if sym not in sym_map:
                    print(f"{bot}: {sym} nicht verfügbar -- ausgelassen")
                    continue
                bid, ask, arr = data(sym)
                bars = tf(bid, frame)
                step = pd.Timedelta(hours={"H1": 1, "H4": 4, "D1": 24}[frame])
                if bot == "A":
                    sigs[sym] = signals_A(cfg, st, bars)
                else:
                    higher_rule = {"H1": "H4", "H4": "D1"}[frame]
                    sigs[sym] = signals_CD(cfg, st, bars, tf(bid, higher_rule), higher_rule, step)
                markets[sym] = (bid, ask, step, arr)
        secure = None
        if getattr(cfg, "SECURE_PROFIT_ENABLED", False):
            secure = (cfg.SECURE_PROFIT_TRIGGER_PCT / cfg.RISK_PERCENT, cfg.SECURE_PROFIT_LOCK_PCT / cfg.RISK_PERCENT)
        daily = (cfg.DAILY_LOSS_LIMIT_PCT / cfg.RISK_PERCENT) if hasattr(cfg, "DAILY_LOSS_LIMIT_PCT") else None
        trades = run_bot(bot, markets, sigs, cfg, secure, daily, spread_filter=bot in "CD")
        all_trades.append(trades)
        print(f"\n=== Bot {bot} ({folder.name}), Risiko {cfg.RISK_PERCENT} % je Trade", flush=True)
        verdict = []
        for name, (a, b) in PERIODS.items():
            m = (trades["entry"] >= a) & (trades["entry"] <= b + " 23:59")
            years = (min(pd.Timestamp(b), pd.Timestamp("2026-09-30")) - pd.Timestamp(a)).days / 365.25
            r = trades.loc[m, "r"]
            print(f"  {name}: {stats(r, years)}")
            verdict.append(len(r) > 1 and r.mean() > 0 and r.mean() / r.std() * np.sqrt(len(r)) >= 2)
        print(f"  Letzte 12 Monate: {stats(trades[trades['entry'] >= '2025-10-01']['r'], 1.0)}")
        print("  je Markt: " + " | ".join(f"{s} {g['r'].mean():+.2f}R n{len(g)}" for s, g in trades.groupby("sym")))
        print(f"  FTMO-Prüfung (+10 % / -10 % / -5 % Tag): {ftmo(trades, cfg.RISK_PERCENT)}")
        print(f"  Urteil: {'BESTANDEN' if all(verdict) else 'NICHT BESTANDEN'}", flush=True)
    pd.concat(all_trades).to_pickle(Path(__file__).with_name("r102_trades.pkl"))


if __name__ == "__main__":
    main()

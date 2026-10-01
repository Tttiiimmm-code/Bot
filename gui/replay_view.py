"""Tab "Üben": ein vergangener Handelstag läuft Kerze für Kerze ab (Logik: tradingbot/replay.py).

Läuft als Streamlit-Fragment: Klicks hier bauen nur diesen Tab neu auf, nicht die ganze Seite
(die Seite fragt sonst bei jedem Klick Alpaca nach Live-Kursen). Nichts hier geht an Alpaca als Order.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st

from gui.chart import CHART_CONFIG, CHART_CONFIG_MOBILE, DOWN, UP, build_chart, is_mobile
from tradingbot import replay as rpl
from tradingbot.copilot import BERLIN, NY, entry_warnings, suggest_stop

SS = st.session_state


def _suggest(rules) -> float | None:
    bars, idx = SS.rp_bars, SS.rp["idx"]
    visible = bars.iloc[:idx]
    return suggest_stop(visible, float(visible["close"].iloc[-1]), rules)


def _msg(kind: str, text: str) -> None:
    SS.rp["msg"] = (kind, text)


# ------------------------------------------------------------ Aktionen (on_click: laufen vor dem Neuaufbau)

def _load(cp, rules) -> None:
    SS.pop("rp_error", None)
    symbol = (SS.get("rp_sym_in") or "").strip().upper()
    day = SS.get("rp_day_in")
    start_et = rpl.REPLAY_STARTS_ET[SS.get("rp_start_in") or next(iter(rpl.REPLAY_STARTS_ET))]
    try:
        if symbol and day:
            bars, prev_close = rpl.load_day(cp.data_client, cp.trading_client, symbol, day)
        else:
            symbols = (symbol,) if symbol else rpl.PRACTICE_SYMBOLS
            symbol, day, bars, prev_close = rpl.pick_random_day(cp.data_client, cp.trading_client, date.today(),
                                                                symbols=symbols, start_et=start_et)
    except Exception as e:  # Netz, kein Handelstag, keine Daten
        SS.rp_error = f"Tag konnte nicht geladen werden: {e}"
        return
    SS.rp_bars = bars
    SS.rp = {"symbol": symbol, "day": day.isoformat(), "prev_close": prev_close,
             "idx": rpl.start_index(bars, start_et), "pos": None, "trades": [], "msg": None}
    SS.rp_stop = _suggest(rules) or round(float(bars["close"].iloc[SS.rp["idx"] - 1]) * 0.99, 2)


def _close(journal: Path, rules, idx: int, price: float, reason: str) -> None:
    rp, bars = SS.rp, SS.rp_bars
    pos = rp["pos"]
    goal = SS.get("rp_goal", "frei")
    res = rpl.make_result(rp["symbol"], rp["day"], bars, pos, idx, price, reason, "" if goal == "frei" else goal)
    rpl.append_result(journal, res)
    rp["trades"] += [(bars.index[pos.entry_idx], "buy", pos.entry), (bars.index[idx], "sell", price)]
    rp["pos"] = None
    _msg("success" if res.r > 0 else "error" if res.r < 0 else "info",
         f"{reason} um {(bars.index[idx] + timedelta(minutes=5)).astimezone(BERLIN):%H:%M}: "
         f"{res.r:+.2f} R (Einstieg {res.entry:.2f}, Ausstieg {res.exit:.2f})")
    SS.rp_stop = _suggest(rules) or SS.get("rp_stop")


def _step(journal: Path, rules, n: int = 1, until_exit: bool = False) -> None:
    rp, bars = SS.rp, SS.rp_bars
    rp["msg"] = None
    for _ in range(len(bars) if until_exit else n):
        i = rp["idx"]
        if i >= len(bars):
            break
        rp["idx"] = i + 1
        if rp["pos"] is not None:
            hit = rpl.check_exit(bars, rp["pos"], i)
            if hit:
                _close(journal, rules, i, *hit)
                break  # nach einem Ausstieg anhalten, damit man ihn sieht
        elif until_exit:
            break
    if rp["idx"] >= len(bars) and rp["msg"] is None:
        _msg("info", "Der Handelstag ist vorbei.")


def _buy(journal: Path, rules) -> None:
    rp, bars = SS.rp, SS.rp_bars
    i = rp["idx"]
    if i >= len(bars):
        return _msg("error", "Der Handelstag ist vorbei.")
    stop = round(float(SS.rp_stop), 2)
    entry = float(bars["open"].iloc[i])
    target = round(entry + float(SS.rp_target_r) * (entry - stop), 2) if SS.get("rp_use_target", True) else None
    try:
        rp["pos"] = rpl.open_position(bars, i, stop, target, SS.get("rp_setup") or "vwap-pullback",
                                      SS.get("rp_note", ""), bool(SS.get("rp_be", False)))
    except ValueError as e:
        return _msg("error", f"Kein Kauf: {e}")
    rp["msg"] = None
    rp["idx"] = i + 1
    hit = rpl.check_exit(bars, rp["pos"], i)
    if hit:
        _close(journal, rules, i, *hit)
    else:
        _msg("info", f"Gekauft zu {entry:.2f} (Eröffnung der nächsten Kerze)"
                     + (f", Ziel {target:.2f}" if target else ""))


def _sell(journal: Path, rules) -> None:
    rp, bars = SS.rp, SS.rp_bars
    i = rp["idx"]
    if rp["pos"] is None or i >= len(bars):
        return
    rp["idx"] = i + 1
    _close(journal, rules, i, float(bars["open"].iloc[i]), "Verkauft")


def _use_suggestion(value: float) -> None:
    SS.rp_stop = value


# ------------------------------------------------------------ Anzeige

def _stats(journal: Path) -> None:
    results = rpl.load_results(journal)
    with st.container(border=True):
        st.subheader("Deine Übungs-Statistik")
        goal = st.selectbox("Übungsziel", ["frei", *rpl.GOALS], key="rp_goal",
                            help="Trainiere gezielt deine Schwächen aus dem Wochenbericht. Ziel: 8 von 10 eingehalten.")
        gs = rpl.goal_stats(results, goal)
        if gs:
            fmt = (lambda x: "–" if x is None else f"{x:+.2f} R")
            (st.success if gs["kept"] >= 0.8 * gs["n"] else st.info)(
                f"Ziel '{goal}': in den letzten {gs['n']} Übungstrades {gs['kept']}x eingehalten "
                f"(eingehalten Ø {fmt(gs['avg_kept'])}, gebrochen Ø {fmt(gs['avg_broken'])}).",
                icon=":material/flag:")
        elif goal != "frei":
            st.caption("Noch keine Übungstrades mit diesem Ziel -- los geht's: Tag laden und handeln.")
        if not results:
            st.caption("Noch keine Übungs-Trades. Ziel: 30 Trades, dann siehst du erste Muster.")
            return
        s = rpl.summarize(results)
        k = st.columns(4)
        k[0].metric("Übungs-Trades", s["n"], border=True)
        k[1].metric("Trefferquote", f"{s['win_rate']:.0%}", border=True)
        k[2].metric("Ø R je Trade", f"{s['avg_r']:+.2f}", border=True)
        k[3].metric("Summe R", f"{s['sum_r']:+.1f}", border=True)
        by_setup = pd.DataFrame([{"Setup": x.setup, "R": x.r} for x in results]).groupby("Setup")["R"]
        table = pd.DataFrame({"Trades": by_setup.size(), "Trefferquote": by_setup.apply(lambda r: (r > 0).mean()),
                              "Ø R": by_setup.mean(), "Summe R": by_setup.sum()}).reset_index()
        color = lambda v: f"color: {UP if v > 0 else DOWN if v < 0 else '#9598A1'}"  # noqa: E731
        st.dataframe(table.style.map(color, subset=["Ø R", "Summe R"]).format(
            {"Trefferquote": "{:.0%}", "Ø R": "{:+.2f}", "Summe R": "{:+.1f}"}), hide_index=True, width="stretch")
        last = pd.DataFrame([{"Tag": x.day, "Symbol": x.symbol, "Setup": x.setup, "Einstieg": x.entry_time,
                              "Ausstieg": x.exit_time, "Grund": x.reason, "R": x.r, "Notiz": x.note}
                             for x in results[-10:][::-1]])
        st.caption("Letzte 10 Übungs-Trades (Uhrzeiten New York)")
        st.dataframe(last.style.map(color, subset=["R"]).format({"R": "{:+.2f}"}), hide_index=True, width="stretch")


def render(cp, rules, journal: Path, setups: dict[str, str], checklist: str) -> None:
    st.caption("Ein echter vergangener Handelstag läuft Kerze für Kerze ab -- du siehst nie, was als Nächstes kommt. "
               "Kauf und Verkauf zum Eröffnungskurs der nächsten Kerze; liegen Stop und Ziel in derselben Kerze, "
               "zählt der Stop. Reine Übung: nichts geht an Alpaca.")
    with st.container(border=True):
        c = st.columns([1.1, 1, 1.4, 1.1], vertical_alignment="bottom")
        c[0].text_input("Symbol", key="rp_sym_in", placeholder="leer = zufällig")
        c[1].date_input("Tag", key="rp_day_in", value=None, max_value=date.today() - timedelta(days=1),
                        format="DD.MM.YYYY", help="Leer = zufälliger Tag, an dem die Aktie zum Start im Plus lag.")
        c[2].selectbox("Start (deutsche Zeit)", list(rpl.REPLAY_STARTS_ET), key="rp_start_in")
        c[3].button("Tag laden", type="primary", icon=":material/casino:", width="stretch", on_click=_load, args=(cp, rules))
    if SS.get("rp_error"):
        st.error(SS.rp_error)

    rp = SS.get("rp")
    if rp is None:
        st.info("Lade einen Tag: leer lassen für eine zufällige Aktie an einem zufälligen Tag, an dem sie zu "
                "deinem Start mindestens 2 % im Plus war -- wie ein Treffer der Kandidatensuche.", icon=":material/school:")
        _stats(journal)
        return

    bars, i = SS.rp_bars, rp["idx"]
    visible = bars.iloc[:i]
    price = float(visible["close"].iloc[-1])
    pos = rp["pos"]
    now_berlin = (visible.index[-1] + timedelta(minutes=5)).astimezone(BERLIN)
    day_over = i >= len(bars)

    chart_col, side = st.columns([2.3, 1], gap="medium")
    with chart_col, st.container(border=True):
        st.subheader(f"{rp['symbol']} · {pd.Timestamp(rp['day']):%d.%m.%Y}")
        markers = list(rp["trades"]) + ([(bars.index[pos.entry_idx], "buy", pos.entry)] if pos else [])
        stop_line = pos.stop if pos else SS.get("rp_stop")
        mobile = is_mobile()
        move = mobile and st.toggle("Chart mit dem Finger bewegen", key="rp_chart_move",
                                    help="An: Wischen verschiebt den Chart. Aus: Wischen scrollt die Seite. "
                                         "Zoomen geht immer mit + / - oben rechts im Chart.")
        st.plotly_chart(build_chart(visible, rp["symbol"], stop_line, pos.target if pos else None, markers=markers,
                                    uirevision=f"replay_{rp['symbol']}_{rp['day']}", mobile=mobile, move=move),
                        width="stretch", config=CHART_CONFIG_MOBILE if mobile else CHART_CONFIG, key="replay_chart")
        if not mobile:
            st.caption("Mausrad: zoomen · Ziehen: verschieben · Doppelklick: ganzer Tag")

    with side, st.container(border=True):
        m = st.columns(2)
        m[0].metric("Uhrzeit", f"{now_berlin:%H:%M}", f"New York {now_berlin.astimezone(NY):%H:%M}",
                    delta_color="off", delta_arrow="off")
        m[1].metric("Kurs", f"{price:.2f}", f"{(price / rp['prev_close'] - 1) * 100:+.1f} % heute")
        if rp["msg"]:
            kind, text = rp["msg"]
            {"success": st.success, "error": st.error, "info": st.info}[kind](text)

        if day_over:
            st.button("Nächster zufälliger Tag", icon=":material/casino:", type="primary", width="stretch", on_click=_load,
                      args=(cp, rules))
        elif pos:
            r_now = (price - pos.entry) / pos.one_r
            st.metric("Offener Trade", f"{r_now:+.2f} R", f"{(price - pos.entry):+.2f} je Aktie")
            st.caption(f"Einstieg {pos.entry:.2f} · Stop {pos.stop:.2f}"
                       + (f" · Ziel {pos.target:.2f}" if pos.target else " · ohne Ziel")
                       + (" · Stop wandert bei +1 R auf Einstand" if pos.breakeven else ""))
            b = st.columns(2)
            b[0].button("Nächste Kerze", icon=":material/play_arrow:", width="stretch", on_click=_step, args=(journal, rules))
            b[1].button("Bis Trade-Ende", icon=":material/skip_next:", width="stretch", on_click=_step, args=(journal, rules),
                        kwargs={"until_exit": True})
            st.button("Verkaufen (nächste Eröffnung)", icon=":material/close:", width="stretch", on_click=_sell,
                      args=(journal, rules))
        else:
            b = st.columns(2)
            b[0].button("Nächste Kerze", icon=":material/play_arrow:", width="stretch", on_click=_step, args=(journal, rules))
            b[1].button("30 Minuten", icon=":material/fast_forward:", width="stretch", on_click=_step, args=(journal, rules),
                        kwargs={"n": 6})
            st.divider()
            st.markdown("**Kauf planen**")
            if "rp_stop" not in SS:
                SS.rp_stop = _suggest(rules) or round(price * 0.99, 2)
            st.number_input("Stop", min_value=0.0, step=0.01, format="%.2f", key="rp_stop")
            suggestion = suggest_stop(visible, price, rules)
            if suggestion:
                st.button(f"Vorschlag übernehmen ({suggestion:.2f})", icon=":material/my_location:", key="rp_use",
                          on_click=_use_suggestion, args=(suggestion,))
            t = st.columns([1, 1], vertical_alignment="bottom")
            t[0].checkbox("Kursziel", value=True, key="rp_use_target")
            t[1].number_input("Ziel in R", min_value=0.5, max_value=10.0, value=2.0, step=0.5, key="rp_target_r")
            setup = st.selectbox("Setup", list(setups), key="rp_setup")
            st.caption(setups[setup])
            st.checkbox("Stop auf Einstand bei +1 R", key="rp_be")
            st.text_input("Warum dieser Trade?", key="rp_note", placeholder="kurz begründen")
            for w in entry_warnings(visible, price, float(SS.rp_stop)):
                st.warning(w, icon=":material/warning:")
            with st.expander("Checkliste vor dem Kauf", icon=":material/checklist:"):
                st.markdown(checklist)
            st.button("Kaufen", type="primary", icon=":material/shopping_cart:", width="stretch", on_click=_buy, args=(journal, rules))

    _stats(journal)

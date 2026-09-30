"""Grafische Oberfläche für den Trading-Copilot (Paper-Konto aus copilot.env).

Start: Doppelklick auf "Copilot starten.bat" im Bot-Ordner (startet auch die Sicherheits-
überwachung) oder `.venv\\Scripts\\python -m streamlit run gui\\copilot_app.py`.
Alle Regeln und Orders laufen über tradingbot/copilot.py -- die Oberfläche zeigt nur an und fragt ab.
Farbschema: .streamlit/config.toml.
"""

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from gui.chart import CHART_CONFIG, DOWN, UP, build_chart  # noqa: E402
from tradingbot.copilot import (  # noqa: E402
    BERLIN, NY, Copilot, CopilotRules, attach_setups, de_weekday, entry_warnings, load_journal, setup_stats, suggest_stop,
)

ENV_FILE = Path(os.environ.get("COPILOT_ENV", ROOT / "copilot.env"))
JOURNAL = Path(os.environ.get("COPILOT_JOURNAL", ROOT / "copilot_journal.jsonl"))
REPLAY_JOURNAL = Path(os.environ.get("COPILOT_REPLAY_JOURNAL", ROOT / "replay_journal.jsonl"))
SETUPS = {
    "vwap-pullback": "Aktie ist heute deutlich im Plus, läuft auf die VWAP-Linie zurück und dreht wieder nach oben.",
    "trend-continuation": "Nach einer ruhigen Mittagsphase bricht die Aktie über ihr Tageshoch aus.",
    "power-hour": "Starker Ausbruch in der letzten Handelsstunde (ab 15:00 New Yorker Zeit, meist 21:00 bei uns).",
}
NEUTRAL = "#9598A1"
ENTRY_CHECKLIST = """\
1. **Trend passt:** Kurs liegt **über der VWAP**, und die Hochs und Tiefs werden höher.
2. **Setup erkennbar:** Du kannst es in einem Satz benennen (VWAP-Rücksetzer, Ausbruch übers Tageshoch, Power Hour).
3. **Bestätigung da:** Nicht in eine fallende Kerze kaufen -- warten, bis eine Kerze über das Hoch der vorherigen steigt.
4. **Klarer Stop-Punkt:** Stop unter einem sichtbaren Tief oder der VWAP, nicht willkürlich.
5. **Chance mindestens 2 R:** Bis zum Tageshoch bzw. zum nächsten Widerstand ist Platz für das Doppelte des Stop-Abstands.
6. **Kopf frei:** Kein Frust vom letzten Trade, kein "ich muss heute noch was verdienen".
"""

st.set_page_config(page_title="Trading-Copilot (Paper)", page_icon=":material/candlestick_chart:", layout="wide")

st.markdown("""
<style>
  .block-container {padding-top: 1.6rem; padding-bottom: 2rem; max-width: 1500px;}
  h1 {font-size: 1.7rem !important; margin-bottom: 0 !important;}
  h3 {font-size: 1.15rem !important;}
  [data-testid="stMetricValue"] {font-size: 1.5rem;}
  [data-testid="stMetricLabel"] p {font-size: 0.78rem; text-transform: uppercase; letter-spacing: .04em; opacity: .75;}
  .stTabs [data-baseweb="tab"] p {font-size: 1.0rem;}
  .copilot-sub {opacity: .65; font-size: .9rem; margin: -0.2rem 0 0.8rem 0;}
  .copilot-rule {display: flex; justify-content: space-between; padding: .3rem 0;
                 border-bottom: 1px solid rgba(128,128,128,.15); font-size: .9rem;}
</style>
""", unsafe_allow_html=True)


def now() -> datetime:
    return datetime.now(timezone.utc)


def berlin_time(t_et) -> str:
    """Uhrzeit New York (heute) in deutscher Zeit -- stimmt auch in den Wochen, in denen
    die Zeitumstellung in den USA und Europa nicht gleichzeitig ist."""
    return datetime.combine(now().astimezone(NY).date(), t_et, tzinfo=NY).astimezone(BERLIN).strftime("%H:%M")


def color_pnl(v) -> str:
    """Pandas-Styler: Gewinne grün, Verluste rot."""
    try:
        v = float(v)
    except (TypeError, ValueError):
        return ""
    return f"color: {UP if v > 0 else DOWN if v < 0 else NEUTRAL}"


def safe(action) -> None:
    """Order-Aktion ausführen; Fehler von Alpaca als Meldung statt Programmabsturz zeigen."""
    try:
        msg = action()
    except Exception as e:
        st.error(f"Alpaca hat abgelehnt oder ist nicht erreichbar: {e}")
        return
    (st.success if msg.startswith("GEKAUFT") else st.warning)(msg)


@st.cache_resource
def get_copilot() -> Copilot:
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.trading.client import TradingClient

    from tradingbot.report import read_account_env

    key, secret, paper = read_account_env(str(ENV_FILE))
    if not paper:
        raise RuntimeError("copilot.env: ALPACA_PAPER muss true sein -- der Copilot ist nur für Paper-Trading.")
    return Copilot(TradingClient(key, secret, paper=True), StockHistoricalDataClient(key, secret),
                   CopilotRules(), JOURNAL)


if not ENV_FILE.exists():
    st.title("Trading-Copilot")
    st.error("copilot.env fehlt.")
    st.markdown("""
1. Im Alpaca-Dashboard ein **neues Paper-Konto** anlegen (nicht das des Momentum- oder Overnight-Bots).
2. Im Bot-Ordner die Datei **copilot.env** anlegen mit:
```
ALPACA_API_KEY=...
ALPACA_SECRET_KEY=...
ALPACA_PAPER=true
```
3. Diese Seite neu laden.""")
    st.stop()

try:
    cp = get_copilot()
except Exception as e:  # z.B. falsche Keys
    st.error(f"Verbindung zu Alpaca fehlgeschlagen: {e}")
    st.stop()
rules = cp.rules

# ------------------------------------------------------------ Seitenleiste

with st.sidebar:
    st.subheader(":material/rule: Regeln")
    rule_rows = [
        ("1 R (Verlust am Stop)", f"{rules.risk_per_trade:.0f} $"),
        ("Tagesverlust max.", f"{rules.max_daily_loss:.0f} $"),
        ("Einstiege pro Tag", f"max. {rules.max_trades_per_day}"),
        (f"Pause nach {rules.loss_streak} Verlusten", f"{rules.cooldown_minutes} Min."),
        ("Stop-Mindestabstand", f"{rules.min_stop_pct:.1%}"),
        ("Letzter Einstieg", f"{berlin_time(rules.last_entry_et)} Uhr"),
        ("Alles schließen", f"{berlin_time(rules.flatten_et)} Uhr"),
    ]
    st.markdown("".join(f'<div class="copilot-rule"><span>{k}</span><b>{v}</b></div>' for k, v in rule_rows),
                unsafe_allow_html=True)
    st.caption("Nur Kaufen (long) · nur Paper-Geld · Uhrzeiten deutsch, heute")
    st.info("Das Fenster **Copilot-Sicherheit** muss offen bleiben: es stellt bei der Tagesgrenze und "
            f"um {berlin_time(rules.flatten_et)} glatt und zieht Stops nach. Jede Position hat zusätzlich "
            "einen Stop direkt bei Alpaca.", icon=":material/shield:")
    if st.button("Notfall: alles schließen", icon=":material/dangerous:", width="stretch"):
        safe(lambda: cp.close(None))


# ------------------------------------------------------------ Kopfzeile (aktualisiert sich selbst)

@st.fragment(run_every="15s")
def header():
    t = now()
    try:
        clock = cp.trading_client.get_clock()
        st_ = cp.state(t)
        positions = cp.trading_client.get_all_positions()
    except Exception as e:
        st.error(f"Alpaca nicht erreichbar: {e}")
        return
    unreal = sum(float(p.unrealized_pl) for p in positions)
    c = st.columns(5)
    c[0].metric("Zeit", f"{t.astimezone(BERLIN):%H:%M}", f"New York {t.astimezone(NY):%H:%M}", delta_color="off", delta_arrow="off",
                border=True)
    # grün "Handel läuft" bzw. grau mit nächster Öffnung
    c[1].metric("Markt", "offen" if clock.is_open else "geschlossen",
                "Handel läuft" if clock.is_open else f"öffnet {de_weekday(clock.next_open)} {clock.next_open.astimezone(BERLIN):%H:%M}",
                delta_color="normal" if clock.is_open else "off", delta_arrow="off", border=True)
    # Streamlit färbt das Delta nach dem führenden Vorzeichen -- darum steht der Betrag vorne
    c[2].metric("Heute realisiert", f"{st_.realized_pnl:+.2f} $", f"{unreal:+.2f} $ offen",
                delta_color="normal" if round(unreal, 2) != 0 else "off", border=True)
    c[3].metric("Einstiege", f"{st_.entries_today} / {rules.max_trades_per_day}",
                f"Verlustserie {st_.loss_streak}", delta_color="off", delta_arrow="off", border=True)
    budget = max(rules.max_daily_loss + st_.realized_pnl, 0.0)
    c[4].metric("Verlustbudget", f"{budget:.0f} $", f"von {rules.max_daily_loss:.0f} $", delta_color="off", delta_arrow="off",
                border=True)
    left = budget / rules.max_daily_loss
    st.progress(min(left, 1.0), text=("Verlustbudget: reichlich Luft" if left > 0.5 else
                                      "Verlustbudget wird knapp -- jetzt besonders wählerisch sein" if left > 0 else
                                      "Verlustbudget aufgebraucht -- Schluss für heute"))


CHART_REFRESH = os.environ.get("COPILOT_CHART_REFRESH", "5m")  # nur zum Testen änderbar


@st.fragment(run_every=CHART_REFRESH)
def chart_view(symbol: str, stop: float, target: float | None) -> None:
    """Chart mit VWAP, Stop und Ziel; lädt sich alle 5 Minuten selbst neu (neue 5-Minuten-Kerze).
    Stop/Ziel kommen aus dem letzten vollständigen Seitenaufbau -- ändern sie sich, wird die Seite
    ohnehin neu aufgebaut."""
    t = now()
    try:
        bars = cp.today_bars(symbol, t)
    except Exception as e:
        st.error(f"Kursdaten für {symbol} nicht abrufbar: {e}")
        return
    if bars.empty:
        st.info("Noch keine 5-Minuten-Kerzen für heute (Markt geschlossen?).")
        return
    try:
        markers = cp.fills_today(symbol, t)  # Pfeile für heutige Käufe/Verkäufe
    except Exception:
        markers = []
    st.plotly_chart(build_chart(bars, symbol, stop, target, markers=markers), width="stretch", config=CHART_CONFIG,
                    key=f"chart_{symbol}")
    share = bars.attrs.get("iex_share")
    if share is not None and share < 0.01:
        st.warning(f"IEX sieht nur {share:.1%} des Handels in {symbol}: die letzten 15 Minuten im Chart "
                   "(rechts der gepunkteten Linie) und der Kurs für die Stückzahl sind lückenhaft. "
                   "Links der Linie ist der Chart vollständig, aber 15 Minuten verzögert.")
    info, link = st.columns([3, 1], vertical_alignment="center")
    info.caption("Mausrad: zoomen · Ziehen: verschieben · Doppelklick: ganzer Tag  \n"
                 "Links der gepunkteten Linie: alle Börsen (15 Min. verzögert) · rechts: live, nur IEX  \n"
                 f"Chart-Stand {t.astimezone(BERLIN):%H:%M:%S} -- aktualisiert sich alle 5 Minuten selbst.")
    link.link_button("TradingView", f"https://www.tradingview.com/chart/?symbol={symbol}", icon=":material/open_in_new:",
                     width="stretch")


st.title(":material/candlestick_chart: Trading-Copilot")
st.markdown('<div class="copilot-sub">Paper-Konto · jeder Trade mit Stop bei Alpaca · '
            'Auswertung nach 100 Trades</div>', unsafe_allow_html=True)
header()
tab_trade, tab_pos, tab_practice, tab_eval, tab_help = st.tabs(
    [":material/candlestick_chart: Handeln", ":material/work: Positionen", ":material/school: Üben", ":material/monitoring: Auswertung", ":material/menu_book: Anleitung"])

# ------------------------------------------------------------ Handeln

with tab_trade:
    left, right = st.columns([1, 2.3], gap="medium")
    with left, st.container(border=True):
        st.subheader("1. Kandidaten")
        st.caption("Große, viel gehandelte Aktien (Ø Umsatz über 200 Mio. $ am Tag), die heute mindestens 2 % "
                   "im Plus sind und mehr Volumen als üblich haben.")
        if st.button("Kandidaten suchen", icon=":material/search:", width="stretch"):
            from types import SimpleNamespace

            from tradingbot.report import read_account_env
            from tradingbot.scanner import ScanCriteria, Scanner

            key, secret, _ = read_account_env(str(ENV_FILE))
            with st.spinner("Suche läuft ..."):
                try:
                    found = Scanner(SimpleNamespace(api_key=key, secret_key=secret, paper=True)).scan(
                        # Nur viel gehandelte Werte: bei kleinen Aktien sieht der kostenlose Echtzeit-Feed (IEX)
                        # kaum Handel -- Chart lückenhaft, Kurs veraltet (siehe Copilot._price_problems).
                        ScanCriteria(min_price=10.0, max_price=5000.0, min_percent_change=2.0, min_relative_volume=1.2,
                                     top_movers=50, top_actives=100, min_avg_dollar_volume=200e6,
                                     include_actives_by_trades=True))
                    st.session_state["scan"] = pd.DataFrame(
                        [{"Symbol": c.symbol, "Kurs $": round(c.price, 2), "Heute %": round(c.percent_change, 1),
                          "Rel. Volumen": round(c.relative_volume, 1)} for c in found])
                    if found:
                        st.session_state["symbol_input"] = found[0].symbol
                except Exception as e:
                    st.error(f"Scanner-Fehler: {e}")
        scan = st.session_state.get("scan")
        if scan is not None and not scan.empty:
            st.caption("Auf eine Zeile klicken, um den Chart zu sehen.")
            current = st.session_state.get("symbol_input", "").strip().upper()
            for r in scan.itertuples(index=False):
                sym, kurs, heute, relvol = r
                # "\\$": sonst liest Streamlit $...$ als Formel
                label = f"**{sym}**  ·  {kurs:.2f} \\$  ·  :green[{heute:+.1f} %]  ·  Vol. {relvol:.1f}x"
                if st.button(label, key=f"pick_{sym}", width="stretch",
                             type="primary" if sym == current else "secondary"):
                    st.session_state["symbol_input"] = sym
                    st.rerun()
        else:
            st.caption("Noch keine Suche (oder keine Treffer).")
        symbol = st.text_input("Symbol", key="symbol_input", placeholder="z.B. NVDA").strip().upper()

    with right, st.container(border=True):
        st.subheader(f"2. Chart {symbol}" if symbol else "2. Chart")
        bars, price = pd.DataFrame(), None
        if symbol:
            try:
                bars = cp.today_bars(symbol, now())
                price = cp.latest_price(symbol)
            except Exception as e:
                st.error(f"Kursdaten für {symbol} nicht abrufbar: {e}")
        else:
            st.info("Links Kandidaten suchen oder ein Symbol eingeben.", icon=":material/arrow_back:")
        stop_default = suggest_stop(bars, price, rules) if price and not bars.empty else None
        chart_slot = st.empty()

    if symbol and price:
        with st.container(border=True):
            st.subheader(f"3. Kauf planen · {symbol} @ {price:.2f} $")
            a, b, c = st.columns(3, gap="large")
            with a:
                st.markdown("**Stop & Setup**")
                # Feste Widget-Keys je Symbol: sonst setzt jede Aktualisierung (neuer Kurs -> neuer Vorschlag)
                # den eingegebenen Stop still auf den Vorschlag zurück.
                stop_key = f"stop_{symbol}"
                if stop_key not in st.session_state:
                    st.session_state[stop_key] = float(stop_default or round(price * 0.98, 2))
                stop = st.number_input("Stop (Verkauf, wenn der Kurs hierhin fällt)", min_value=0.0, key=stop_key,
                                       step=0.01, format="%.2f",
                                       help="Vorschlag: knapp unter dem letzten Rücksetzer. Dort ist die Idee widerlegt.")
                if stop_default:
                    # on_click läuft VOR dem Neuaufbau -- danach darf das Stop-Feld nicht mehr geändert werden
                    st.button(f"Vorschlag übernehmen ({stop_default:.2f})", key=f"use_{symbol}", icon=":material/my_location:",
                              on_click=st.session_state.__setitem__, args=(stop_key, float(stop_default)))
                setup = st.selectbox("Setup", list(SETUPS), help="Welches Muster siehst du?")
                st.caption(SETUPS[setup])
            with b:
                st.markdown("**Ziel & Begründung**")
                use_target = st.checkbox("Kursziel setzen (empfohlen: 2 R)")
                target_key = f"target_{symbol}"
                if use_target and target_key not in st.session_state:
                    st.session_state[target_key] = round(price + 2 * max(price - stop, 0.01), 2)
                target = st.number_input("Kursziel", min_value=0.0, key=target_key, step=0.01,
                                         format="%.2f") if use_target else None
                breakeven = st.checkbox("Stop auf Einstand nachziehen, sobald +1 R erreicht",
                                        help="Liegt der Trade 1 R im Plus, setzt das Fenster 'Copilot-Sicherheit' den "
                                             "Stop auf deinen Kaufkurs. Aus einem Gewinner wird dann kein Verlierer "
                                             "mehr -- dafür wirst du öfter bei +/-0 ausgestoppt.")
                note = st.text_area("Warum dieser Trade?", height=90,
                                    placeholder="z.B. Rücksetzer auf VWAP, Volumen steigt wieder")
            with c:
                st.markdown("**Vorschau**")
                try:
                    pv = cp.preview(symbol, stop, now(), target)
                except Exception as e:
                    pv = None
                    st.error(f"Vorschau nicht möglich: {e}")
                if pv:
                    m1, m2 = st.columns(2)
                    m1.metric("Stückzahl", f"{pv['shares']}", f"Wert {pv['value']:.0f} $", delta_color="off", delta_arrow="off",
                              border=True)
                    m2.metric("Risiko = 1 R", f"{pv['risk']:.2f} $",
                              f"Chance {pv['reward_r']:.1f} R" if pv["reward_r"] else "ohne Kursziel",
                              delta_color="off", delta_arrow="off", border=True)
                    if pv["problems"]:
                        for p in pv["problems"]:
                            st.error(p, icon=":material/block:")
                    else:
                        st.success("Alle Regeln erfüllt.", icon=":material/check_circle:")
                    # Hinweise zu typischen Anfängerfehlern -- sperren nicht, sollen aber zum Nachdenken bringen
                    if not bars.empty:
                        for w in entry_warnings(bars, pv["price"], stop):
                            st.warning(w, icon=":material/warning:")
                with st.expander("Checkliste vor dem Kauf", icon=":material/checklist:"):
                    st.markdown(ENTRY_CHECKLIST)
                confirmed = st.checkbox("Ich habe Stop und Setup geprüft.", key="confirmed")
                blocked = not pv or bool(pv["problems"]) or pv["shares"] <= 0 or not confirmed
                if st.button("Kaufen", type="primary", disabled=blocked, icon=":material/shopping_cart:", width="stretch"):
                    try:
                        msg = cp.buy(symbol, stop, setup, now(), target=target, note=note, breakeven=breakeven)
                    except Exception as e:
                        msg = f"Alpaca hat abgelehnt oder ist nicht erreichbar: {e}"
                    # Häkchen zurücksetzen: ein zweiter Klick darf nicht versehentlich ein zweites Mal kaufen
                    st.session_state["last_buy_msg"] = msg
                    del st.session_state["confirmed"]
                    st.rerun()
            if "last_buy_msg" in st.session_state:
                msg = st.session_state["last_buy_msg"]
                (st.success if msg.startswith("GEKAUFT") else st.error)(msg)

        with chart_slot.container():
            chart_view(symbol, stop, target)

# ------------------------------------------------------------ Positionen

with tab_pos:
    @st.fragment(run_every="15s")
    def positions_view():
        t = now()
        try:
            positions = cp.trading_client.get_all_positions()
        except Exception as e:
            st.error(f"Alpaca nicht erreichbar: {e}")
            return
        st.subheader("Offene Positionen")
        if not positions:
            st.info("Keine offenen Positionen.", icon=":material/inbox:")
        for p in positions:
            risk = cp.journal_risk(p.symbol, t)
            pl = float(p.unrealized_pl)
            with st.container(border=True):
                cols = st.columns([1.3, 1, 1, 1.3, 0.9], vertical_alignment="center")
                cols[0].markdown(f"#### {p.symbol}\n{p.qty} Stück")
                cols[1].metric("Einstieg", f"{float(p.avg_entry_price):.2f}")
                cols[2].metric("Aktuell", f"{float(p.current_price):.2f}")
                cols[3].metric("Gewinn/Verlust", f"{pl:+.2f} $", f"{pl / risk:+.2f} R" if risk else None)
                if cols[4].button("Schließen", key=f"close_{p.symbol}", icon=":material/close:", width="stretch"):
                    safe(lambda s=p.symbol: cp.close(s))
        st.subheader("Heute abgeschlossen")
        try:
            trades, _ = cp._closed_trades(t)
            rows = attach_setups(trades, load_journal(JOURNAL))
        except Exception as e:
            st.error(f"Trades nicht abrufbar: {e}")
            return
        if rows:
            df = pd.DataFrame([{"Symbol": r["symbol"], "Setup": r["setup"],
                                "Ausstieg": r["exit_time"].astimezone(BERLIN).strftime("%H:%M"),
                                "P&L $": r["pnl"], "R": r["r"]} for r in rows])
            df["R"] = pd.to_numeric(df["R"])  # None (Trade ohne Journal) -> NaN, damit "–" erscheint
            st.dataframe(df.style.map(color_pnl, subset=["P&L $", "R"])
                         .format({"P&L $": "{:+.2f}", "R": "{:+.2f}"}, na_rep="–"),
                         hide_index=True, width="stretch", placeholder="–")
        else:
            st.caption("Heute noch keine abgeschlossenen Trades.")

    positions_view()

# ------------------------------------------------------------ Üben (Replay)

with tab_practice:
    from gui import replay_view

    @st.fragment
    def practice_view():
        replay_view.render(cp, rules, REPLAY_JOURNAL, SETUPS, ENTRY_CHECKLIST)

    practice_view()

# ------------------------------------------------------------ Auswertung

with tab_eval:
    days = st.select_slider("Zeitraum", options=[7, 14, 30, 60, 90, 180], value=90,
                            format_func=lambda d: f"letzte {d} Tage")
    try:
        trades, _ = cp._closed_trades(now(), days)
        rows = attach_setups(trades, load_journal(JOURNAL))
    except Exception as e:
        rows = []
        st.error(f"Trades nicht abrufbar: {e}")
    n = len(rows)
    st.progress(min(n / 100, 1.0), text=f"{n} von 100 Trades bis zur ersten ehrlichen Bewertung")
    if rows:
        stats = setup_stats(rows)
        total = next(s for s in stats if s["setup"] == "GESAMT")
        k = st.columns(5)
        k[0].metric("Trades", total["n"], border=True)
        k[1].metric("Trefferquote", f"{total['win_rate']:.0%}", border=True)
        k[2].metric("Ø R je Trade", f"{total['avg_r']:+.2f}", border=True)
        k[3].metric("Profit-Faktor", f"{total['profit_factor']:.2f}", "Ziel ab 1,3", delta_color="off", delta_arrow="off", border=True)
        k[4].metric("Gewinn/Verlust", f"{total['pnl']:+.2f} $", border=True)

        with st.container(border=True):
            st.subheader("Summe der R über alle Trades")
            curve = pd.DataFrame({"Summe R": pd.Series([r["r"] or 0.0 for r in rows]).cumsum()})
            curve.index = range(1, len(curve) + 1)
            st.area_chart(curve, height=240, color=UP if curve["Summe R"].iloc[-1] >= 0 else DOWN)

        with st.container(border=True):
            st.subheader("Je Setup")
            table = pd.DataFrame(stats).rename(columns={
                "setup": "Setup", "n": "Trades", "win_rate": "Trefferquote", "avg_r": "Ø R", "pnl": "P&L $",
                "profit_factor": "Profit-Faktor", "t_r": "t (R)"})
            st.dataframe(table.style.map(color_pnl, subset=["Ø R", "P&L $"]).format(
                {"Trefferquote": "{:.0%}", "Ø R": "{:+.2f}", "P&L $": "{:+.2f}", "Profit-Faktor": "{:.2f}",
                 "t (R)": "{:.2f}"}, na_rep="–"), hide_index=True, width="stretch", placeholder="–")
            st.caption("Bestanden (vorab festgelegt) erst ab 100 Trades bei Profit-Faktor >= 1,3 UND t (R) >= 2 "
                       "nach Kosten.")
    else:
        st.info("Noch keine abgeschlossenen Trades.")

# ------------------------------------------------------------ Anleitung

with tab_help:
    g1, g2 = st.columns(2, gap="large")
    with g1:
        with st.container(border=True):
            st.markdown(f"""
### Worum es geht
Du übst mit **Spielgeld** (Paper-Konto). Der Copilot sorgt dafür, dass jeder Fehler klein bleibt, und
schreibt alles mit. Nach **100 Trades** zeigt die Auswertung ehrlich, ob deine Entscheidungen besser sind
als Zufall. Die meisten Anfänger sind es anfangs nicht -- das ist normal und kostet hier nichts.

### Die wichtigsten Begriffe
- **Stop:** Der Kurs, bei dem du automatisch verkaufst, weil deine Idee falsch war. Er liegt direkt bei
  Alpaca -- auch wenn dein PC ausgeht.
- **R:** Dein geplanter Verlust je Trade ({rules.risk_per_trade:.0f} $). +2 R = doppelt so viel gewonnen wie riskiert.
  Der Copilot rechnet die Stückzahl so, dass ein Stop immer ~1 R kostet.
- **VWAP (orange Linie):** Durchschnittspreis des Tages, gewichtet nach Volumen. Große Käufer orientieren
  sich daran; über dem VWAP haben die Käufer die Oberhand.
- **Kerze:** Ein 5-Minuten-Abschnitt. Grün = gestiegen, rot = gefallen; die Striche zeigen Hoch und Tief.
""")
        with st.container(border=True):
            st.markdown("### Die drei Setups\n" + "\n".join(f"- **{k}:** {v}" for k, v in SETUPS.items()))
    with g2:
        with st.container(border=True):
            st.markdown(f"""
### Ablauf an einem Abend (18:00-22:00)
1. **Kandidaten suchen** -- Aktien, die heute stark steigen und viel Volumen haben.
2. Chart ansehen: Liegt der Kurs **über dem VWAP**? Gibt es einen klaren Rücksetzer oder ein Tageshoch?
3. Passt eins der drei Setups? Wenn nicht: **nichts tun**. Nicht handeln ist oft der beste Trade.
4. **Stop** unter den letzten Rücksetzer (der Vorschlag hilft), Setup wählen, Grund aufschreiben.
5. **Kursziel** bei 2 R setzen, auf Wunsch den Stop auf Einstand nachziehen lassen.
6. Vorschau prüfen: Alles grün? Dann kaufen. Danach **nicht** den Stop nach unten verschieben.
7. Verkauft wird, wenn Stop oder Ziel greifen -- spätestens um {berlin_time(rules.flatten_et)} automatisch.
""")
        with st.container(border=True):
            st.markdown("""
### Goldene Regeln
- Keine Rache-Trades nach Verlusten -- nach einem Verlust 15 Minuten aufstehen.
- Wenige, gute Gelegenheiten statt vieler mittelmäßiger. 0 Trades an einem Abend ist völlig in Ordnung.
- In den ersten Wochen höchstens 2 Trades pro Abend.
- Erst nach bestandener Auswertung (100 Trades) über Echtgeld nachdenken.
""")

    st.subheader(":material/my_location: Gute Einstiege finden")
    e1, e2 = st.columns(2, gap="large")
    with e1:
        with st.container(border=True):
            st.markdown("### Checkliste vor jedem Kauf\nNur kaufen, wenn **alle sechs** Punkte stimmen:\n\n"
                        + ENTRY_CHECKLIST)
        with st.container(border=True):
            st.markdown("""
### Beispiel: VWAP-Rücksetzer Schritt für Schritt
1. Aktie ist heute +4 %, der Kurs lag den ganzen Nachmittag **über der orangen VWAP-Linie**.
2. Der Kurs fällt in 3-4 Kerzen von 52,00 auf 51,20 -- **knapp über die VWAP (51,10)**. Die roten Kerzen
   werden kleiner, das Volumen nimmt ab (Verkäufer werden müde).
3. **Nicht in die fallende Kerze kaufen.** Warten, bis eine Kerze **über das Hoch der vorherigen Kerze**
   steigt, z.B. über 51,35. Erst das zeigt: Käufer übernehmen wieder.
4. **Stop** unter das Tief des Rücksetzers und unter die VWAP: 51,05. Abstand 0,30 $ = 1 R.
5. **Ziel** 2 R = 51,35 + 0,60 = 51,95 -- das liegt noch unter dem Tageshoch (52,00). Passt.
6. Kaufen, Ziel setzen, **dann nichts mehr anfassen**. Stop oder Ziel entscheiden.
""")
    with e2:
        with st.container(border=True):
            st.markdown(f"""
### Timing an deinem Abend
- **18:00-19:30 (Mittag in New York):** oft ruhig und zäh, viele Fehlausbrüche. Gut zum **Beobachten**
  und Kandidaten vormerken -- beim Handeln besonders wählerisch sein.
- **19:30-21:00:** Bewegung kommt zurück, Trends vom Vormittag setzen sich oft fort. Gute Zeit für
  VWAP-Rücksetzer.
- **21:00-{berlin_time(rules.last_entry_et)} (Power Hour):** mehr Volumen, schnellere Bewegungen. Wenig Zeit
  bis zum automatischen Schließen um {berlin_time(rules.flatten_et)} -- das Ziel muss schnell erreichbar sein.
- **Vor Zahlen/Nachrichten** (z.B. Zinsentscheid um 20:00 an Fed-Tagen): lieber abwarten.
""")
        with st.container(border=True):
            st.markdown("""
### Typische Anfängerfehler
- **Hinterherlaufen (FOMO):** Nach 3-4 grünen Kerzen in Folge ist der beste Einstieg vorbei. Auf den
  nächsten Rücksetzer warten -- es kommt fast immer einer.
- **Stop zu eng:** Ein Stop direkt unter dem Kurs wird vom normalen Hin und Her ausgelöst. Der Stop gehört
  unter einen **sichtbaren Punkt** (letztes Tief, VWAP) -- die Stückzahl passt der Copilot an.
- **Stop nach unten verschieben:** Macht aus einem kleinen Verlust einen großen. Nie.
- **Gewinn laufen lassen "bis es mehr wird":** Ohne Ziel wird aus +1 R oft wieder 0 oder -1 R.
  Ziel setzen oder Stop auf Einstand nachziehen lassen.
- **Gegen den Markt kaufen:** Fallen die großen Indizes (QQQ/SPY) gerade deutlich, scheitern auch gute
  Einzel-Setups öfter. Kurz den QQQ-Chart ansehen.
- **Rache-Trade nach einem Verlust:** Der nächste Trade soll ein guter sein, nicht ein schneller.
""")
        with st.container(border=True):
            st.markdown("""
### Nach jedem Trade (2 Minuten)
Schreib dir auf: **Hätte ich diesen Trade mit der Checkliste wieder genommen?** Ein Verlust mit
eingehaltener Checkliste ist ein **guter Trade** -- Verluste gehören dazu. Ein Gewinn ohne Plan ist
ein schlechter Trade, der zufällig aufging. Nur die Trades mit Plan zeigen dir, ob du einen Vorteil hast.
""")

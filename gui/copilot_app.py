"""Grafische Oberfläche für den Trading-Copilot (Paper-Konto aus copilot.env).

Start: Doppelklick auf "Copilot starten.bat" im Bot-Ordner (startet auch die Sicherheits-
überwachung) oder `.venv\\Scripts\\python -m streamlit run gui\\copilot_app.py`.
Alle Regeln und Orders laufen über tradingbot/copilot.py -- die Oberfläche zeigt nur an und fragt ab.
"""

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402
import plotly.graph_objects as go  # noqa: E402
import streamlit as st  # noqa: E402

from tradingbot.copilot import (  # noqa: E402
    BERLIN, NY, Copilot, CopilotRules, attach_setups, load_journal, setup_stats, suggest_stop, vwap,
)

ENV_FILE = Path(os.environ.get("COPILOT_ENV", ROOT / "copilot.env"))
JOURNAL = Path(os.environ.get("COPILOT_JOURNAL", ROOT / "copilot_journal.jsonl"))
SETUPS = {
    "vwap-pullback": "Aktie ist heute deutlich im Plus, läuft auf die VWAP-Linie zurück und dreht wieder nach oben.",
    "trend-continuation": "Nach einer ruhigen Mittagsphase bricht die Aktie über ihr Tageshoch aus.",
    "power-hour": "Starker Ausbruch in der letzten Handelsstunde (ab 15:00 New Yorker Zeit, meist 21:00 bei uns).",
}

st.set_page_config(page_title="Trading-Copilot (Paper)", page_icon="📈", layout="wide")


def now() -> datetime:
    return datetime.now(timezone.utc)


def berlin_time(t_et) -> str:
    """Uhrzeit New York (heute) in deutscher Zeit -- stimmt auch in den Wochen, in denen
    die Zeitumstellung in den USA und Europa nicht gleichzeitig ist."""
    return datetime.combine(now().astimezone(NY).date(), t_et, tzinfo=NY).astimezone(BERLIN).strftime("%H:%M")


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
    st.header("Regeln (fest)")
    st.markdown(f"""
- **1 R = {rules.risk_per_trade:.0f} $** Verlust, wenn der Stop greift
- Tagesverlust max. **{rules.max_daily_loss:.0f} $**, dann Schluss für heute
- Max. **{rules.max_trades_per_day}** Einstiege pro Tag
- Nach **{rules.loss_streak}** Verlusten in Folge **{rules.cooldown_minutes} Min.** Pause
- Stop mind. **{rules.min_stop_pct:.1%}** unter dem Kurs
- Einstiege bis **{berlin_time(rules.last_entry_et)}**, alles zu um **{berlin_time(rules.flatten_et)}** (deutsche Zeit, heute)
- Nur Kaufen (long), nur Paper-Geld""")
    st.info("Das Fenster **Copilot-Sicherheit** muss geöffnet bleiben: es stellt bei der Tagesgrenze und "
            f"um {berlin_time(rules.flatten_et)} automatisch glatt. Jede Position hat zusätzlich einen Stop direkt bei Alpaca.")
    if st.button("🛑 Notfall: alles schließen", width="stretch"):
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
    c[0].metric("Zeit", f"{t.astimezone(BERLIN):%H:%M}", f"New York {t.astimezone(NY):%H:%M}", delta_color="off")
    c[1].metric("Markt", "offen" if clock.is_open else "geschlossen",
                None if clock.is_open else f"öffnet {clock.next_open.astimezone(BERLIN):%a %H:%M}",
                delta_color="off")
    c[2].metric("Heute realisiert", f"{st_.realized_pnl:+.2f} $", f"offen {unreal:+.2f} $")
    c[3].metric("Einstiege", f"{st_.entries_today} / {rules.max_trades_per_day}",
                f"Verlustserie {st_.loss_streak}", delta_color="off")
    budget = max(rules.max_daily_loss + st_.realized_pnl, 0.0)
    c[4].metric("Verlustbudget", f"{budget:.0f} $", f"von {rules.max_daily_loss:.0f} $", delta_color="off")
    st.progress(min(budget / rules.max_daily_loss, 1.0))


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
    fig = go.Figure(go.Candlestick(x=bars.index, open=bars["open"], high=bars["high"], low=bars["low"],
                                   close=bars["close"], name=symbol))
    fig.add_trace(go.Scatter(x=bars.index, y=vwap(bars), name="VWAP", line=dict(color="orange", width=2)))
    fig.add_hline(y=stop, line_dash="dash", line_color="red", annotation_text="Stop")
    if target:
        fig.add_hline(y=target, line_dash="dash", line_color="green", annotation_text="Ziel")
    live_from = bars.attrs.get("live_from")
    if live_from is not None and live_from > bars.index[0]:
        fig.add_vline(x=live_from, line_dash="dot", line_color="gray")
        fig.add_annotation(x=live_from, y=1, yref="paper", text="ab hier live (nur IEX)",
                           showarrow=False, xanchor="left", font=dict(color="gray"))
    fig.update_layout(height=420, margin=dict(l=10, r=10, t=10, b=10), xaxis_rangeslider_visible=False,
                      legend=dict(orientation="h"))
    st.plotly_chart(fig, width="stretch")
    share = bars.attrs.get("iex_share")
    if share is not None and share < 0.01:
        st.warning(f"IEX sieht nur {share:.1%} des Handels in {symbol}: die letzten 15 Minuten im Chart "
                   "(rechts der gepunkteten Linie) und der Kurs für die Stückzahl sind lückenhaft. "
                   "Links der Linie ist der Chart vollständig, aber 15 Minuten verzögert.")
    else:
        st.caption("Links der gepunkteten Linie: vollständige Kurse aller Börsen (15 Min. verzögert). "
                   "Rechts davon: live, aber nur von der Börse IEX.")
    st.caption(f"Chart-Stand {t.astimezone(BERLIN):%H:%M:%S} -- aktualisiert sich alle 5 Minuten selbst.")
    st.link_button(f"{symbol} live bei TradingView öffnen", f"https://www.tradingview.com/chart/?symbol={symbol}")


st.title("📈 Trading-Copilot  ·  Paper-Konto")
header()
tab_trade, tab_pos, tab_eval, tab_help = st.tabs(["Handeln", "Positionen", "Auswertung", "Anleitung"])

# ------------------------------------------------------------ Handeln

with tab_trade:
    left, right = st.columns([1, 2])
    with left:
        st.subheader("1. Kandidaten")
        st.caption("Große, viel gehandelte Aktien (Ø Umsatz über 200 Mio. $ am Tag), die heute mindestens 2 % "
                   "im Plus sind und mehr Volumen als üblich haben.")
        if st.button("Kandidaten suchen"):
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
            st.caption("Auf eine Zeile klicken, um den Chart rechts zu sehen.")
            current = st.session_state.get("symbol_input", "").strip().upper()
            for r in scan.itertuples(index=False):
                sym, kurs, heute, relvol = r
                # "\\$": sonst liest Streamlit $...$ als Formel
                label = f"**{sym}**  ·  {kurs:.2f} \\$  ·  {heute:+.1f} %  ·  Volumen {relvol:.1f}x"
                if st.button(label, key=f"pick_{sym}", width="stretch",
                             type="primary" if sym == current else "secondary"):
                    st.session_state["symbol_input"] = sym
                    st.rerun()
        else:
            st.caption("Noch keine Suche (oder keine Treffer).")
        symbol = st.text_input("Symbol", key="symbol_input").strip().upper()

    with right:
        st.subheader(f"2. Chart {symbol}" if symbol else "2. Chart")
        bars, price = pd.DataFrame(), None
        if symbol:
            try:
                bars = cp.today_bars(symbol, now())
                price = cp.latest_price(symbol)
            except Exception as e:
                st.error(f"Kursdaten für {symbol} nicht abrufbar: {e}")
        stop_default = suggest_stop(bars, price, rules) if price and not bars.empty else None
        chart_slot = st.empty()

    if symbol and price:
        st.subheader("3. Kauf planen")
        a, b, c = st.columns(3)
        with a:
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
                st.button(f"Vorschlag übernehmen ({stop_default:.2f})", key=f"use_{symbol}",
                          on_click=st.session_state.__setitem__, args=(stop_key, float(stop_default)))
            setup = st.selectbox("Setup", list(SETUPS), help="Welches Muster siehst du?")
            st.caption(SETUPS[setup])
        with b:
            use_target = st.checkbox("Kursziel setzen (optional)")
            target_key = f"target_{symbol}"
            if use_target and target_key not in st.session_state:
                st.session_state[target_key] = round(price + 2 * max(price - stop, 0.01), 2)
            target = st.number_input("Kursziel", min_value=0.0, key=target_key, step=0.01,
                                     format="%.2f") if use_target else None
            note = st.text_area("Warum dieser Trade?", placeholder="z.B. Rücksetzer auf VWAP, Volumen steigt wieder")
        with c:
            try:
                pv = cp.preview(symbol, stop, now(), target)
            except Exception as e:
                pv = None
                st.error(f"Vorschau nicht möglich: {e}")
            if pv:
                st.metric("Stückzahl", f"{pv['shares']}", f"Positionswert {pv['value']:.0f} $", delta_color="off")
                st.metric("Risiko (= 1 R)", f"{pv['risk']:.2f} $",
                          f"Chance {pv['reward_r']:.1f} R" if pv["reward_r"] else "ohne Kursziel", delta_color="off")
                if pv["problems"]:
                    for p in pv["problems"]:
                        st.error(p)
                else:
                    st.success("Alle Regeln erfüllt.")
        confirmed = st.checkbox("Ich habe Stop und Setup geprüft.", key="confirmed")
        blocked = not pv or bool(pv["problems"]) or pv["shares"] <= 0 or not confirmed
        if st.button("Kaufen", type="primary", disabled=blocked):
            try:
                msg = cp.buy(symbol, stop, setup, now(), target=target, note=note)
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
        if not positions:
            st.info("Keine offenen Positionen.")
        for p in positions:
            risk = cp.journal_risk(p.symbol, t)
            pl = float(p.unrealized_pl)
            cols = st.columns([2, 2, 2, 2, 1])
            cols[0].markdown(f"**{p.symbol}**  \n{p.qty} Stück")
            cols[1].metric("Einstieg", f"{float(p.avg_entry_price):.2f}")
            cols[2].metric("Aktuell", f"{float(p.current_price):.2f}")
            cols[3].metric("Gewinn/Verlust", f"{pl:+.2f} $", f"{pl / risk:+.2f} R" if risk else None)
            if cols[4].button("Schließen", key=f"close_{p.symbol}"):
                safe(lambda s=p.symbol: cp.close(s))
        st.divider()
        st.subheader("Heute abgeschlossen")
        try:
            trades, _ = cp._closed_trades(t)
            rows = attach_setups(trades, load_journal(JOURNAL))
        except Exception as e:
            st.error(f"Trades nicht abrufbar: {e}")
            return
        if rows:
            st.dataframe(pd.DataFrame([{"Symbol": r["symbol"], "Setup": r["setup"],
                                        "Ausstieg": r["exit_time"].astimezone(BERLIN).strftime("%H:%M"),
                                        "P&L $": round(r["pnl"], 2), "R": None if r["r"] is None else round(r["r"], 2)}
                                       for r in rows]), hide_index=True, width="stretch")
        else:
            st.caption("Heute noch keine abgeschlossenen Trades.")

    positions_view()

# ------------------------------------------------------------ Auswertung

with tab_eval:
    days = st.slider("Zeitraum (Tage)", 7, 180, 90)
    try:
        trades, _ = cp._closed_trades(now(), days)
        rows = attach_setups(trades, load_journal(JOURNAL))
    except Exception as e:
        rows = []
        st.error(f"Trades nicht abrufbar: {e}")
    n = len(rows)
    st.progress(min(n / 100, 1.0), text=f"{n} von 100 Trades bis zur ersten ehrlichen Bewertung")
    if rows:
        stats = pd.DataFrame(setup_stats(rows)).rename(columns={
            "setup": "Setup", "n": "Trades", "win_rate": "Trefferquote", "avg_r": "Ø R", "pnl": "P&L $",
            "profit_factor": "Profit-Faktor", "t_r": "t (R)"})
        st.dataframe(stats.style.format({"Trefferquote": "{:.0%}", "Ø R": "{:.2f}", "P&L $": "{:.2f}",
                                         "Profit-Faktor": "{:.2f}", "t (R)": "{:.2f}"}),
                     hide_index=True, width="stretch")
        curve = pd.Series([r["r"] or 0.0 for r in rows]).cumsum()
        st.line_chart(curve, height=250)
        st.caption("Summe der R-Vielfachen über alle Trades. Bestanden (vorab festgelegt) erst ab 100 Trades bei "
                   "Profit-Faktor >= 1,3 UND t (R) >= 2 nach Kosten.")
    else:
        st.info("Noch keine abgeschlossenen Trades.")

# ------------------------------------------------------------ Anleitung

with tab_help:
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

### Ablauf an einem Abend (18:00-22:00)
1. **Kandidaten suchen** -- Aktien, die heute stark steigen und viel Volumen haben.
2. Chart ansehen: Liegt der Kurs **über dem VWAP**? Gibt es einen klaren Rücksetzer oder ein Tageshoch?
3. Passt eins der drei Setups? Wenn nicht: **nichts tun**. Nicht handeln ist oft der beste Trade.
4. **Stop** unter den letzten Rücksetzer (der Vorschlag hilft), Setup wählen, Grund aufschreiben.
5. Vorschau prüfen: Alles grün? Dann kaufen. Danach **nicht** den Stop nach unten verschieben.
6. Verkaufen: wenn der Stop greift, das Ziel erreicht ist, das Setup kaputtgeht -- spätestens 21:55 automatisch (in der Woche 25.10.-1.11.2026 schon 20:55, weil die USA die Uhr später umstellen).

### Die drei Setups
""" + "\n".join(f"- **{k}:** {v}" for k, v in SETUPS.items()) + """

### Goldene Regeln
- Keine Rache-Trades nach Verlusten -- der Copilot erzwingt eine Pause.
- Wenige, gute Gelegenheiten statt vieler mittelmäßiger. 0 Trades an einem Abend ist völlig in Ordnung.
- Erst nach bestandener Auswertung (100 Trades) über Echtgeld nachdenken.
""")

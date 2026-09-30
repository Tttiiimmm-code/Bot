"""Kerzenchart im Stil von TradingView (Plotly): Mausrad zoomt, Ziehen verschiebt, Fadenkreuz,
Volumen unter dem Chart, Kursachse rechts mit Marke für den letzten Kurs. Doppelklick setzt den
Zoom zurück. `uirevision` hält Zoom und Ausschnitt, wenn sich der Chart alle 5 Minuten neu lädt."""

from __future__ import annotations

import plotly.graph_objects as go
from plotly.subplots import make_subplots

from tradingbot.copilot import vwap

UP, DOWN = "#26a69a", "#ef5350"          # TradingView-Farben
GRID = "rgba(128,128,128,0.15)"

# Plotly-Bedienung wie bei TradingView
CHART_CONFIG = {
    "scrollZoom": True,
    "displaylogo": False,
    "modeBarButtonsToRemove": ["select2d", "lasso2d", "autoScale2d", "toImage"],
}


def build_chart(bars, symbol: str, stop: float | None, target: float | None, markers=(),
                uirevision: str | None = None) -> go.Figure:
    """markers: [(Zeit, "buy"/"sell", Kurs)] -- Käufe als grüne, Verkäufe als rote Pfeile an der Kerze."""
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.78, 0.22], vertical_spacing=0.02)
    fig.add_trace(go.Candlestick(
        x=bars.index, open=bars["open"], high=bars["high"], low=bars["low"], close=bars["close"], name=symbol,
        increasing=dict(line=dict(color=UP), fillcolor=UP), decreasing=dict(line=dict(color=DOWN), fillcolor=DOWN),
    ), row=1, col=1)
    fig.add_trace(go.Scatter(x=bars.index, y=vwap(bars), name="VWAP", line=dict(color="orange", width=1.5),
                             hovertemplate="VWAP %{y:.2f}<extra></extra>"), row=1, col=1)
    colors = [UP if c >= o else DOWN for o, c in zip(bars["open"], bars["close"])]
    fig.add_trace(go.Bar(x=bars.index, y=bars["volume"], name="Volumen", marker_color=colors, opacity=0.5,
                         hovertemplate="Volumen %{y:,.0f}<extra></extra>"), row=2, col=1)

    if markers:
        import pandas as pd

        for side, color, symbol_shape, label in (("buy", UP, "triangle-up", "Kauf"),
                                                  ("sell", DOWN, "triangle-down", "Verkauf")):
            pts = [(pd.Timestamp(t).tz_convert(bars.index.tz).floor("5min"), px) for t, sd, px in markers if sd == side]
            if pts:
                fig.add_trace(go.Scatter(
                    x=[p[0] for p in pts], y=[p[1] for p in pts], mode="markers", name=label,
                    marker=dict(symbol=symbol_shape, size=13, color=color, line=dict(color="white", width=1)),
                    hovertemplate=f"{label} %{{y:.2f}}<extra></extra>"), row=1, col=1)
    if stop:
        fig.add_hline(y=stop, line_dash="dash", line_color=DOWN, line_width=1, row=1, col=1,
                      annotation_text=f"Stop {stop:.2f}", annotation_position="bottom left")
    if target:
        fig.add_hline(y=target, line_dash="dash", line_color=UP, line_width=1, row=1, col=1,
                      annotation_text=f"Ziel {target:.2f}", annotation_position="top left")
    last = float(bars["close"].iloc[-1])
    last_up = last >= float(bars["open"].iloc[-1])
    fig.add_hline(y=last, line_dash="dot", line_width=1, line_color=UP if last_up else DOWN, row=1, col=1)
    fig.add_annotation(x=1, xref="paper", y=last, yref="y", text=f" {last:.2f} ", showarrow=False, xanchor="left",
                       font=dict(color="white", size=11), bgcolor=UP if last_up else DOWN)

    live_from = bars.attrs.get("live_from")
    if live_from is not None and live_from > bars.index[0]:
        fig.add_vline(x=live_from, line_dash="dot", line_color="gray", line_width=1)
        fig.add_annotation(x=live_from, y=1, yref="paper", text="ab hier live (nur IEX)", showarrow=False,
                           xanchor="left", font=dict(color="gray", size=10))

    spikes = dict(showspikes=True, spikemode="across", spikesnap="cursor", spikethickness=1, spikedash="dot",
                  spikecolor="gray")
    fig.update_xaxes(gridcolor=GRID, rangeslider_visible=False, **spikes)
    fig.update_yaxes(gridcolor=GRID, side="right", **spikes)
    fig.update_yaxes(tickformat=".2f", row=1, col=1)
    fig.update_yaxes(showticklabels=False, row=2, col=1)
    fig.update_layout(
        height=520, margin=dict(l=10, r=60, t=10, b=10), dragmode="pan", hovermode="x",
        uirevision=uirevision or symbol,  # Zoom/Ausschnitt bleiben beim automatischen Neuladen erhalten
        showlegend=False, bargap=0.1,
    )
    return fig

# ──────────────────────────────────────────────────────────────
# app.py  –  Comm Prices – Dashboard de Ativos em Tempo Real
# ──────────────────────────────────────────────────────────────
from __future__ import annotations

import json
import traceback

import dash
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
from dash import ALL, MATCH, Input, Output, State, ctx, dcc, html
from plotly.subplots import make_subplots

from concurrent.futures import ThreadPoolExecutor, as_completed

from config import (
    ASSET_TYPES,
    DEFAULT_ASSETS,
    PERIODS,
    REFRESH_INTERVAL_MS,
)
from data import (
    add_bollinger_bands,
    add_rsi,
    fmt_price,
    get_current_price,
    get_history,
    get_usd_brl,
)

# ─── Inicialização ────────────────────────────────────────────
app = dash.Dash(
    __name__,
    external_stylesheets=[dbc.themes.DARKLY],
    title="Comm Prices",
    meta_tags=[{"name": "viewport", "content": "width=device-width, initial-scale=1"}],
)
server = app.server  # para deploy

# ─── Constantes visuais ───────────────────────────────────────
PLOT_BASE = dict(
    paper_bgcolor="#0d1117",
    plot_bgcolor="#0d1117",
    font=dict(family="JetBrains Mono, monospace", color="#8b949e", size=11),
    margin=dict(l=60, r=20, t=36, b=40),
    legend=dict(
        bgcolor="#161b22",
        bordercolor="#30363d",
        borderwidth=1,
        font_color="#e6edf3",
    ),
    hoverlabel=dict(
        bgcolor="#161b22",
        bordercolor="#30363d",
        font_color="#e6edf3",
        font_family="JetBrains Mono",
    ),
)

AXIS_STYLE = dict(
    gridcolor="#21262d",
    showgrid=True,
    zeroline=False,
    linecolor="#30363d",
    tickfont=dict(color="#8b949e", size=10),
)


# ─── Layout helpers ───────────────────────────────────────────

def _modal_add_asset():
    return dbc.Modal(
        id="modal-add",
        className="add-modal",
        size="md",
        is_open=False,
        children=[
            dbc.ModalHeader(dbc.ModalTitle("Adicionar Ativo"), close_button=True),
            dbc.ModalBody([
                dbc.Row([
                    dbc.Col([
                        dbc.Label("Ticker Yahoo Finance *", className="form-label"),
                        dbc.Input(
                            id="inp-ticker", placeholder="Ex: MSFT, BTC-USD, ^GSPC",
                            className="mb-3",
                        ),
                    ], width=8),
                    dbc.Col([
                        dbc.Label("Ícone (4 chars)", className="form-label"),
                        dbc.Input(
                            id="inp-icon", placeholder="MSFT",
                            maxLength=6, className="mb-3",
                        ),
                    ], width=4),
                ]),
                dbc.Row([
                    dbc.Col([
                        dbc.Label("Nome do ativo *", className="form-label"),
                        dbc.Input(
                            id="inp-name", placeholder="Ex: Microsoft",
                            className="mb-3",
                        ),
                    ], width=7),
                    dbc.Col([
                        dbc.Label("Tipo", className="form-label"),
                        dbc.Select(
                            id="sel-type",
                            options=[{"label": t.capitalize(), "value": t} for t in ASSET_TYPES],
                            value="stock",
                            className="mb-3",
                        ),
                    ], width=5),
                ]),
                dbc.Row([
                    dbc.Col([
                        dbc.Label("Moeda base", className="form-label"),
                        dbc.Select(
                            id="sel-currency",
                            options=[
                                {"label": "USD (dólar)", "value": "USD"},
                                {"label": "BRL (real)",  "value": "BRL"},
                            ],
                            value="USD",
                            className="mb-3",
                        ),
                    ], width=6),
                    dbc.Col([
                        dbc.Label("CoinGecko ID (crypto)", className="form-label"),
                        dbc.Input(
                            id="inp-cg-id",
                            placeholder="Ex: solana (opcional)",
                            className="mb-3",
                        ),
                    ], width=6),
                ]),
                dbc.Checklist(
                    id="chk-gram",
                    options=[{"label": " Preço original em oz troy → converter para grama", "value": "gram"}],
                    value=[],
                    switch=True,
                    className="mb-2",
                    style={"color": "#8b949e", "fontSize": "13px"},
                ),
                html.Div(id="add-asset-feedback", className="mt-2",
                         style={"fontSize": "12px", "color": "#f85149"}),
            ]),
            dbc.ModalFooter([
                dbc.Button("Cancelar", id="btn-cancel-add", color="secondary",
                           outline=True, size="sm", className="me-2"),
                dbc.Button("Adicionar", id="btn-confirm-add", color="primary",
                           size="sm"),
            ]),
        ],
    )


def _header():
    return html.Div(className="app-header", children=[
        html.Div([
            html.Div("◈ Comm Prices", className="app-title"),
            html.Div("Preços em tempo real · Séries temporais · Indicadores técnicos",
                     className="app-subtitle"),
        ]),
        html.Div(style={"display": "flex", "alignItems": "center", "gap": "12px"}, children=[
            html.Div(className="currency-toggle", children=[
                html.Button("USD", id="btn-usd",
                            className="currency-btn active", n_clicks=0),
                html.Button("BRL", id="btn-brl",
                            className="currency-btn inactive", n_clicks=0),
            ]),
            dbc.Button(
                [html.Span("+ ", style={"fontWeight": "800"}), "Ativo"],
                id="btn-open-add",
                color="primary",
                size="sm",
                style={"borderRadius": "8px", "fontWeight": "600"},
            ),
            dbc.Button(
                "↺ Restaurar",
                id="btn-reset-assets",
                color="secondary",
                outline=True,
                size="sm",
                style={"borderRadius": "8px", "fontWeight": "500",
                       "fontSize": "12px", "color": "#8b949e"},
                title="Restaurar ativos padrão",
            ),
        ]),
    ])


def _price_section():
    return html.Div(style={"padding": "28px 32px 0"}, children=[
        html.Div(style={"display": "flex", "justifyContent": "space-between",
                        "alignItems": "center", "marginBottom": "16px"}, children=[
            html.Div("Preços em Tempo Real", className="section-title"),
            html.Div(id="live-clock", style={"fontSize": "11px", "color": "#484f58",
                                              "fontFamily": "JetBrains Mono"}),
        ]),
        html.Div(id="price-cards-container",
                 style={"display": "grid",
                        "gridTemplateColumns": "repeat(auto-fill, minmax(200px, 1fr))",
                        "gap": "14px"}),
    ])


def _chart_section():
    period_buttons = [
        dbc.Button(
            p, id={"type": "period-btn", "index": p},
            size="sm", outline=True, color="secondary",
            className="period-btn me-1",
            n_clicks=0,
        )
        for p in PERIODS
    ]

    return html.Div(style={"padding": "28px 32px"}, children=[
        html.Div("Séries Temporais", className="section-title"),
        dbc.Row([
            # ── Controles ──────────────────────────
            dbc.Col(width=3, children=[
                html.Div(className="chart-controls", children=[
                    dbc.Label("Ativo", style={"color": "#8b949e", "fontSize": "12px",
                                               "fontWeight": "600", "marginBottom": "6px"}),
                    dcc.Dropdown(
                        id="dd-chart-asset",
                        clearable=False,
                        style={"marginBottom": "16px"},
                    ),

                    dbc.Label("Período", style={"color": "#8b949e", "fontSize": "12px",
                                                 "fontWeight": "600", "marginBottom": "6px"}),
                    html.Div(style={"display": "flex", "flexWrap": "wrap", "gap": "4px",
                                    "marginBottom": "16px"},
                             children=period_buttons),

                    dbc.Label("Tipo de gráfico", style={"color": "#8b949e", "fontSize": "12px",
                                                          "fontWeight": "600", "marginBottom": "6px"}),
                    dbc.RadioItems(
                        id="radio-chart-type",
                        options=[
                            {"label": " Linha",       "value": "line"},
                            {"label": " Candlestick", "value": "candle"},
                        ],
                        value="line",
                        inline=True,
                        style={"fontSize": "13px", "color": "#8b949e", "marginBottom": "16px"},
                    ),

                    dbc.Label("Indicadores", style={"color": "#8b949e", "fontSize": "12px",
                                                     "fontWeight": "600", "marginBottom": "6px"}),
                    dbc.Checklist(
                        id="chk-indicators",
                        options=[
                            {"label": " Bandas de Bollinger (BB 20,2)", "value": "bb"},
                            {"label": " RSI (14)",                       "value": "rsi"},
                        ],
                        value=[],
                        switch=True,
                        style={"fontSize": "13px", "color": "#8b949e"},
                    ),
                ]),
            ]),

            # ── Gráfico ────────────────────────────
            dbc.Col(width=9, children=[
                dcc.Graph(
                    id="main-chart",
                    config={
                        "displaylogo":     False,
                        "modeBarButtons":  [["pan2d", "zoom2d", "zoomIn2d",
                                             "zoomOut2d", "autoScale2d", "toImage"]],
                    },
                    style={"height": "520px"},
                ),
            ]),
        ]),
    ])


# ─── Layout principal ─────────────────────────────────────────
app.layout = html.Div(
    style={"minHeight": "100vh", "backgroundColor": "#0d1117"},
    children=[
        # Stores persistentes
        dcc.Store(id="assets-store",   storage_type="local",
                  data=DEFAULT_ASSETS),
        dcc.Store(id="currency-store", storage_type="local",
                  data="USD"),
        dcc.Store(id="period-store",   storage_type="session",
                  data="1M"),

        # Intervalo de atualização de preços
        dcc.Interval(id="price-interval", interval=REFRESH_INTERVAL_MS, n_intervals=0),

        _header(),
        _price_section(),
        _chart_section(),
        _modal_add_asset(),

        # Barra de status
        html.Div(
            className="status-bar",
            style={"display": "flex", "alignItems": "center", "gap": "16px",
                   "padding": "10px 32px"},
            children=[
                html.Div([
                    html.Span(className="status-dot"),
                    html.Span("Ao vivo", style={"color": "#3fb950"}),
                ]),
                html.Span(id="status-info", style={"color": "#484f58"}),
            ],
        ),
    ],
)


# ─── CALLBACKS ────────────────────────────────────────────────

# 1 · Toggle de moeda (USD ↔ BRL) ─────────────────────────────
@app.callback(
    Output("currency-store", "data"),
    Output("btn-usd", "className"),
    Output("btn-brl", "className"),
    Input("btn-usd", "n_clicks"),
    Input("btn-brl", "n_clicks"),
    State("currency-store", "data"),
    prevent_initial_call=True,
)
def toggle_currency(n_usd, n_brl, current):
    triggered = ctx.triggered_id
    if triggered == "btn-usd":
        val = "USD"
    elif triggered == "btn-brl":
        val = "BRL"
    else:
        val = current or "USD"
    usd_cls = "currency-btn active"   if val == "USD" else "currency-btn inactive"
    brl_cls = "currency-btn active"   if val == "BRL" else "currency-btn inactive"
    return val, usd_cls, brl_cls


# 2 · Restaurar / mesclar ativos padrão ao carregar ─────────────
@app.callback(
    Output("assets-store", "data", allow_duplicate=True),
    Input("assets-store", "data"),
    Input("btn-reset-assets", "n_clicks"),
    prevent_initial_call="initial_duplicate",
)
def restore_default_assets(current_assets, reset_clicks):
    triggered = ctx.triggered_id

    # Botão restaurar: volta para os padrões completos
    if triggered == "btn-reset-assets" and reset_clicks:
        return DEFAULT_ASSETS

    # Na carga inicial ou quando store muda: mescla defaults ausentes
    if not current_assets:
        return DEFAULT_ASSETS

    current_ids = {a["id"] for a in current_assets}
    missing = [a for a in DEFAULT_ASSETS if a["id"] not in current_ids]
    if missing:
        return missing + current_assets  # defaults primeiro
    return dash.no_update


# 2b · Restaurar botões de moeda ao iniciar ─────────────────────
@app.callback(
    Output("btn-usd", "className", allow_duplicate=True),
    Output("btn-brl", "className", allow_duplicate=True),
    Input("currency-store", "data"),
    prevent_initial_call="initial_duplicate",
)
def sync_currency_buttons(currency):
    val = currency or "USD"
    usd_cls = "currency-btn active"   if val == "USD" else "currency-btn inactive"
    brl_cls = "currency-btn active"   if val == "BRL" else "currency-btn inactive"
    return usd_cls, brl_cls


# 3 · Período selecionado ─────────────────────────────────────
@app.callback(
    Output("period-store", "data"),
    Input({"type": "period-btn", "index": ALL}, "n_clicks"),
    State("period-store", "data"),
    prevent_initial_call=True,
)
def update_period(n_clicks_list, current):
    triggered = ctx.triggered_id
    if triggered and isinstance(triggered, dict):
        return triggered["index"]
    return current or "1M"


# 4 · Cards de preço ──────────────────────────────────────────
@app.callback(
    Output("price-cards-container", "children"),
    Output("status-info", "children"),
    Output("live-clock", "children"),
    Input("price-interval", "n_intervals"),
    Input("currency-store", "data"),
    Input("assets-store", "data"),
)
def update_price_cards(_, currency, assets):
    if not assets:
        return html.Div("Nenhum ativo cadastrado.", style={"color": "#484f58"}), "", ""

    display_brl = (currency == "BRL")
    fx = get_usd_brl() if display_brl else 1.0
    cards = []

    # Busca todos os preços em paralelo
    results: dict = {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(get_current_price, asset): asset["id"] for asset in assets}
        for fut in as_completed(futures, timeout=12):
            aid = futures[fut]
            try:
                results[aid] = fut.result()
            except Exception:
                results[aid] = {"price": None, "change": 0, "change_pct": 0,
                                "base_currency": "USD", "timestamp": "--:--:--", "error": "timeout"}

    for asset in assets:
        data = results.get(asset["id"], {"price": None, "change": 0, "change_pct": 0,
                                         "base_currency": asset["base_currency"],
                                         "timestamp": "--:--:--"})
        price_str = fmt_price(
            data["price"],
            asset["base_currency"],
            display_brl,
            fx,
            asset.get("gram_convert", False),
        )

        chg     = data.get("change", 0) or 0
        chg_pct = data.get("change_pct", 0) or 0
        if chg_pct > 0:
            chg_cls = "card-change change-pos"
            arrow   = "▲"
        elif chg_pct < 0:
            chg_cls = "card-change change-neg"
            arrow   = "▼"
        else:
            chg_cls = "card-change change-neu"
            arrow   = "–"

        # Converter variação para BRL se necessário
        chg_display = chg * fx if (display_brl and asset["base_currency"] == "USD") else chg
        chg_abs_str = fmt_price(abs(chg_display), asset["base_currency"], display_brl, fx)

        cards.append(
            html.Div(className="price-card", children=[
                html.Button(
                    "×",
                    className="remove-btn",
                    id={"type": "del-asset", "index": asset["id"]},
                    n_clicks=0,
                ),
                html.Div(asset["icon"], className="card-icon"),
                html.Div(asset["name"], className="card-name"),
                html.Div(price_str, className="card-price"),
                html.Div(
                    f"{arrow} {chg_abs_str}  ({chg_pct:+.2f}%)",
                    className=chg_cls,
                ),
                html.Div(f"↺ {data['timestamp']}", className="card-timestamp"),
            ])
        )

    import datetime as dt
    now_str = dt.datetime.now().strftime("%H:%M:%S")
    status  = f"Última atualização: {now_str}  ·  {len(assets)} ativo(s)"
    clock   = f"🕐 {now_str}"
    return cards, status, clock


# 5 · Dropdown do gráfico (sincroniza com assets-store) ────────
@app.callback(
    Output("dd-chart-asset", "options"),
    Output("dd-chart-asset", "value"),
    Input("assets-store", "data"),
    State("dd-chart-asset", "value"),
)
def sync_chart_dropdown(assets, current_val):
    if not assets:
        return [], None
    options = [{"label": a["name"], "value": a["id"]} for a in assets]
    # Manter seleção atual se ainda existir
    ids = [a["id"] for a in assets]
    value = current_val if current_val in ids else ids[0]
    return options, value


# 6 · Gráfico principal ───────────────────────────────────────
@app.callback(
    Output("main-chart", "figure"),
    Input("dd-chart-asset", "value"),
    Input("period-store", "data"),
    Input("chk-indicators", "value"),
    Input("radio-chart-type", "value"),
    Input("currency-store", "data"),
    State("assets-store", "data"),
)
def update_chart(asset_id, period, indicators, chart_type, currency, assets):
    fig_empty = go.Figure(layout=go.Layout(
        **PLOT_BASE,
        xaxis=AXIS_STYLE,
        yaxis=AXIS_STYLE,
        annotations=[dict(
            text="Selecione um ativo e aguarde os dados...",
            x=0.5, y=0.5, xref="paper", yref="paper",
            showarrow=False, font=dict(color="#484f58", size=14),
        )],
    ))

    if not asset_id or not assets:
        return fig_empty

    asset = next((a for a in assets if a["id"] == asset_id), None)
    if asset is None:
        return fig_empty

    p_cfg   = PERIODS.get(period or "1M", PERIODS["1M"])
    df = get_history(asset, p_cfg["yf_period"], p_cfg["yf_interval"])

    if df.empty:
        return fig_empty

    indicators = indicators or []
    show_bb    = "bb"  in indicators
    show_rsi   = "rsi" in indicators

    # Converter para BRL se necessário
    display_brl = (currency == "BRL")
    if display_brl and asset["base_currency"] == "USD":
        fx = get_usd_brl()
        for col in ("Open", "High", "Low", "Close"):
            if col in df.columns:
                df[col] = df[col] * fx

    # Adicionar indicadores
    if show_bb:
        df = add_bollinger_bands(df)
    if show_rsi:
        df = add_rsi(df)

    # Títulos dos eixos
    currency_lbl = "BRL" if (display_brl or asset["base_currency"] == "BRL") else "USD"
    y_title = f"Preço ({currency_lbl}/{'g' if asset.get('gram_convert') else 'un.'})"

    # Subplots
    if show_rsi:
        fig = make_subplots(
            rows=2, cols=1,
            shared_xaxes=True,
            row_heights=[0.75, 0.25],
            vertical_spacing=0.04,
        )
        rsi_row = 2
    else:
        fig = make_subplots(rows=1, cols=1)
        rsi_row = None

    # ── Série de preço ────────────────────────────────────────
    if chart_type == "candle":
        fig.add_trace(go.Candlestick(
            x=df.index,
            open=df["Open"], high=df["High"],
            low=df["Low"],   close=df["Close"],
            name=asset["name"],
            increasing_line_color="#3fb950",
            decreasing_line_color="#f85149",
            increasing_fillcolor="#1e3a2a",
            decreasing_fillcolor="#3d1a1a",
        ), row=1, col=1)
    else:
        fig.add_trace(go.Scatter(
            x=df.index, y=df["Close"],
            name=asset["name"],
            line=dict(color="#58a6ff", width=1.8),
            fill="tozeroy",
            fillcolor="rgba(88, 166, 255, 0.06)",
        ), row=1, col=1)

    # ── Bollinger Bands ───────────────────────────────────────
    if show_bb and "BB_Upper" in df.columns:
        fig.add_trace(go.Scatter(
            x=df.index, y=df["BB_Upper"],
            name="BB Superior",
            line=dict(color="#d2a8ff", width=1, dash="dot"),
            showlegend=True,
        ), row=1, col=1)
        fig.add_trace(go.Scatter(
            x=df.index, y=df["BB_Mid"],
            name="BB Média",
            line=dict(color="#a371f7", width=1, dash="dash"),
            showlegend=True,
        ), row=1, col=1)
        fig.add_trace(go.Scatter(
            x=df.index, y=df["BB_Lower"],
            name="BB Inferior",
            line=dict(color="#d2a8ff", width=1, dash="dot"),
            fill="tonexty",
            fillcolor="rgba(163, 113, 247, 0.06)",
            showlegend=True,
        ), row=1, col=1)

    # ── RSI ───────────────────────────────────────────────────
    if show_rsi and "RSI" in df.columns:
        fig.add_trace(go.Scatter(
            x=df.index, y=df["RSI"],
            name="RSI (14)",
            line=dict(color="#ffa657", width=1.5),
        ), row=rsi_row, col=1)
        # Linhas de referência RSI
        for level, color in [(70, "#f85149"), (30, "#3fb950"), (50, "#484f58")]:
            fig.add_hline(
                y=level, line_dash="dot",
                line_color=color, opacity=0.5,
                row=rsi_row, col=1,
            )

    # ── Styling ───────────────────────────────────────────────
    axis_shared = dict(**AXIS_STYLE)
    title_text  = f"{asset['name']} · {period or '1M'}"

    fig.update_layout(
        **PLOT_BASE,
        title=dict(text=title_text, font=dict(color="#e6edf3", size=14), x=0.01),
        xaxis_rangeslider_visible=False,
        hovermode="x unified",
    )

    fig.update_xaxes(**axis_shared)
    fig.update_yaxes(**axis_shared)
    fig.update_yaxes(title_text=y_title, row=1, col=1)
    if show_rsi:
        fig.update_yaxes(title_text="RSI", row=2, col=1, range=[0, 100])

    return fig


# 7 · Modal (abrir / fechar) ──────────────────────────────────
@app.callback(
    Output("modal-add", "is_open"),
    Output("add-asset-feedback", "children"),
    Output("inp-ticker", "value"),
    Output("inp-name",   "value"),
    Output("inp-icon",   "value"),
    Output("inp-cg-id",  "value"),
    Output("chk-gram",   "value"),
    Input("btn-open-add",    "n_clicks"),
    Input("btn-cancel-add",  "n_clicks"),
    Input("btn-confirm-add", "n_clicks"),
    State("modal-add", "is_open"),
    prevent_initial_call=True,
)
def toggle_modal(open_c, cancel_c, confirm_c, is_open):
    triggered = ctx.triggered_id
    blank = ("", "", "", "", [])
    if triggered == "btn-open-add":
        return True,  "",  *blank
    if triggered in ("btn-cancel-add", "btn-confirm-add"):
        return False, "",  *blank
    return is_open, "", *blank


# 8 · Gerenciar ativos (adicionar / remover) ───────────────────
@app.callback(
    Output("assets-store", "data"),
    Output("add-asset-feedback", "children", allow_duplicate=True),
    Input({"type": "del-asset", "index": ALL}, "n_clicks"),
    Input("btn-confirm-add", "n_clicks"),
    State("assets-store", "data"),
    State("inp-ticker",   "value"),
    State("inp-name",     "value"),
    State("sel-type",     "value"),
    State("inp-icon",     "value"),
    State("sel-currency", "value"),
    State("inp-cg-id",    "value"),
    State("chk-gram",     "value"),
    prevent_initial_call=True,
)
def manage_assets(del_clicks, add_click, assets,
                  ticker, name, atype, icon, base_currency, cg_id, gram):
    triggered = ctx.triggered_id

    # Remoção por botão × no card — só executa se houve clique real (n_clicks > 0)
    if isinstance(triggered, dict) and triggered.get("type") == "del-asset":
        asset_id = triggered["index"]
        # Encontrar o n_clicks do botão disparado e garantir que é > 0
        triggered_clicks = ctx.triggered[0].get("value", 0) if ctx.triggered else 0
        if not triggered_clicks:
            return assets, ""
        new_assets = [a for a in assets if a["id"] != asset_id]
        return new_assets, ""

    # Adição via modal
    if triggered == "btn-confirm-add":
        if not ticker or not name:
            return assets, "Ticker e Nome são obrigatórios."

        ticker_clean = ticker.strip().upper()
        asset_id = ticker_clean.lower().replace("^", "idx-").replace("=", "-")
        if any(a["id"] == asset_id for a in assets):
            return assets, f"Ativo '{ticker_clean}' já cadastrado."

        new_asset = {
            "id":            asset_id,
            "name":          name.strip(),
            "ticker":        ticker_clean,
            "type":          atype or "stock",
            "icon":          (icon or ticker_clean[:4]).strip().upper(),
            "base_currency": base_currency or "USD",
            "gram_convert":  "gram" in (gram or []),
            "coingecko_id":  cg_id.strip().lower() if cg_id else None,
        }
        return assets + [new_asset], ""

    return assets, ""


# ─── Execução ─────────────────────────────────────────────────
if __name__ == "__main__":
    app.run(debug=False, host="0.0.0.0", port=8050, use_reloader=False, threaded=True)

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
import db as _db
from data import (
    add_bollinger_bands,
    add_rsi,
    fmt_price,
    get_asset_lens,
    get_current_price,
    get_dividend_simulation,
    get_history,
    get_usd_brl,
)

# ─── Inicialização ────────────────────────────────────────────
_db.init_db()

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

def _modal_lens():
    return dbc.Modal(
        id="modal-lens",
        className="add-modal",
        size="xl",
        is_open=False,
        scrollable=True,
        children=[
            dbc.ModalHeader(
                dbc.ModalTitle(id="lens-title", children="◈ Comm Lens"),
                close_button=True,
            ),
            dbc.ModalBody(
                dcc.Loading(
                    type="dot",
                    color="#58a6ff",
                    children=html.Div(id="lens-content"),
                )
            ),
        ],
    )


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
                        style={
                            "marginBottom": "16px",
                            "backgroundColor": "#21262d",
                            "color": "#e6edf3",
                            "border": "1px solid #30363d",
                            "borderRadius": "8px",
                        },
                        className="dash-dropdown-dark",
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


_SIM_EXCLUDED = {"crypto", "commodity", "index"}


def _simulation_section(init_options=None, init_value=None):
    return html.Div(style={"padding": "28px 32px"}, children=[
        html.Div("Simulador de Dividendos", className="section-title"),
        dbc.Row([
            # ── Controles ──────────────────────────
            dbc.Col(width=3, children=[
                html.Div(className="chart-controls", children=[
                    dbc.Label("Ativo", style={"color": "#8b949e", "fontSize": "12px",
                                              "fontWeight": "600", "marginBottom": "6px"}),
                    dcc.Dropdown(
                        id="dd-sim-asset",
                        options=init_options or [],
                        value=init_value,
                        clearable=False,
                        style={
                            "marginBottom": "16px",
                            "backgroundColor": "#21262d",
                            "color": "#e6edf3",
                            "border": "1px solid #30363d",
                            "borderRadius": "8px",
                        },
                        className="dash-dropdown-dark",
                    ),
                    dbc.Label("Valor a investir", style={"color": "#8b949e", "fontSize": "12px",
                                                          "fontWeight": "600", "marginBottom": "6px"}),
                    dcc.Input(
                        id="inp-sim-amount",
                        type="text",
                        placeholder="Ex: 5000",
                        style={
                            "width": "100%",
                            "backgroundColor": "#0d1117",
                            "border": "1px solid #30363d",
                            "color": "#e6edf3",
                            "borderRadius": "8px",
                            "padding": "8px 12px",
                            "fontSize": "14px",
                            "fontFamily": "Inter, sans-serif",
                            "marginBottom": "16px",
                            "outline": "none",
                            "boxSizing": "border-box",
                        },
                    ),
                    dbc.Button(
                        "Simular",
                        id="btn-simulate",
                        color="primary",
                        size="sm",
                        className="w-100",
                        style={"borderRadius": "8px", "fontWeight": "600"},
                    ),
                    html.Div(
                        "Disponível para ações, ETFs e FIIs.",
                        style={"fontSize": "11px", "color": "#484f58",
                               "marginTop": "12px", "lineHeight": "1.5"},
                    ),
                ]),
            ]),
            # ── Resultados ────────────────────────
            dbc.Col(width=9, children=[
                html.Div(
                    id="sim-results",
                    children=[
                        html.Div(
                            "Selecione um ativo e informe o valor para simular.",
                            style={"color": "#484f58", "fontSize": "14px",
                                   "padding": "60px 0", "textAlign": "center"},
                        ),
                    ],
                ),
            ]),
        ]),
    ])


# ─── Layout principal (dinâmico: carrega ativos do DB a cada acesso) ────────
def serve_layout():
    _assets = _db.load_assets()
    _sim_supported = [a for a in _assets if a.get("type", "stock") not in _SIM_EXCLUDED]
    _sim_opts  = [{"label": a["name"], "value": a["id"]} for a in _sim_supported]
    _sim_value = _sim_opts[0]["value"] if _sim_opts else None

    return html.Div(
        style={"minHeight": "100vh", "backgroundColor": "#0d1117"},
        children=[
            # assets-store em memória: fonte da verdade é o Postgres
            dcc.Store(id="assets-store",   storage_type="memory",
                      data=_assets),
            dcc.Store(id="currency-store", storage_type="local",
                      data="USD"),
            dcc.Store(id="period-store",   storage_type="session",
                      data="1M"),

            # Intervalo de atualização de preços
            dcc.Interval(id="price-interval", interval=REFRESH_INTERVAL_MS, n_intervals=0),

            _header(),

            dbc.Tabs(
                id="main-tabs",
                active_tab="tab-dashboard",
                className="main-tabs",
                style={"padding": "0 32px", "backgroundColor": "#161b22",
                       "borderBottom": "1px solid #30363d"},
                children=[
                    dbc.Tab(
                        label="Dashboard",
                        tab_id="tab-dashboard",
                        label_style={"color": "#8b949e",
                                     "fontFamily": "JetBrains Mono, monospace",
                                     "fontSize": "13px"},
                        active_label_style={"color": "#e6edf3",
                                            "fontFamily": "JetBrains Mono, monospace",
                                            "fontSize": "13px"},
                        children=[_price_section(), _chart_section()],
                    ),
                    dbc.Tab(
                        label="Simulador",
                        tab_id="tab-sim",
                        label_style={"color": "#8b949e",
                                     "fontFamily": "JetBrains Mono, monospace",
                                     "fontSize": "13px"},
                        active_label_style={"color": "#e6edf3",
                                            "fontFamily": "JetBrains Mono, monospace",
                                            "fontSize": "13px"},
                        children=[_simulation_section(_sim_opts, _sim_value)],
                    ),
                ],
            ),

            _modal_add_asset(),
            _modal_lens(),

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

app.layout = serve_layout


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


# 2 · Restaurar ativos padrão ─────────────────────────────────
@app.callback(
    Output("assets-store", "data", allow_duplicate=True),
    Input("btn-reset-assets", "n_clicks"),
    prevent_initial_call=True,
)
def restore_default_assets(reset_clicks):
    """Restaura DEFAULT_ASSETS no DB e na store."""
    _db.replace_all_assets(DEFAULT_ASSETS)
    return DEFAULT_ASSETS


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
                html.Button(
                    "◈",
                    className="lens-btn",
                    id={"type": "lens-btn", "index": asset["id"]},
                    n_clicks=0,
                    title="Comm Lens",
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

    # Warm-up para indicadores: busca período maior, calcula e corta de volta
    BB_WINDOW  = 20
    RSI_WINDOW = 14
    WARMUP     = max(BB_WINDOW, RSI_WINDOW)  # 20 candles extras
    if (show_bb or show_rsi) and len(df) < WARMUP * 2:
        _warmup_map = {
            "1d":  "5d",   "5d":  "1mo",  "1mo": "3mo",
            "3mo": "6mo",  "6mo": "1y",   "1y":  "2y",
            "2y":  "5y",   "5y":  "max",
        }
        _longer = _warmup_map.get(p_cfg["yf_period"], p_cfg["yf_period"])
        df_warm = get_history(asset, _longer, p_cfg["yf_interval"])
        if not df_warm.empty and len(df_warm) > len(df):
            cutoff = df.index[0]
            df_full = df_warm
        else:
            df_full = df
            cutoff  = None
    else:
        df_full = df
        cutoff  = None

    # Converter para BRL se necessário
    display_brl = (currency == "BRL")
    if display_brl and asset["base_currency"] == "USD":
        fx = get_usd_brl()
        for col in ("Open", "High", "Low", "Close"):
            if col in df_full.columns:
                df_full[col] = df_full[col] * fx

    # Calcular indicadores no df completo (com warm-up) e depois cortar
    if show_bb:
        df_full = add_bollinger_bands(df_full)
    if show_rsi:
        df_full = add_rsi(df_full)

    # Cortar de volta para o período original
    if cutoff is not None:
        df = df_full[df_full.index >= cutoff]
    else:
        df = df_full

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
            fill="tonexty",
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

    # Range Y dinâmico: margem de 1% ao redor do min/max real dos dados
    _close = df["Close"].dropna()
    if not _close.empty:
        _lo, _hi = float(_close.min()), float(_close.max())
        _pad = (_hi - _lo) * 0.01 if _hi != _lo else _hi * 0.005
        _y_range = [_lo - _pad, _hi + _pad]
    else:
        _y_range = None

    fig.update_xaxes(**axis_shared)
    fig.update_yaxes(**axis_shared)
    fig.update_yaxes(title_text=y_title, row=1, col=1,
                     range=_y_range if chart_type == "line" else None)
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
        triggered_clicks = ctx.triggered[0].get("value", 0) if ctx.triggered else 0
        if not triggered_clicks:
            return dash.no_update, ""
        current_assets = assets or _db.load_assets()
        new_assets = [a for a in current_assets if a["id"] != asset_id]
        _db.delete_asset(asset_id)
        return new_assets, ""

    # Adição via modal
    if triggered == "btn-confirm-add":
        if not ticker or not name:
            return dash.no_update, "Ticker e Nome são obrigatórios."

        # Garantir que assets está carregado (fallback DB)
        current_assets = assets or _db.load_assets()

        ticker_clean = ticker.strip().upper()
        asset_id = ticker_clean.lower().replace("^", "idx-").replace("=", "-")
        if any(a["id"] == asset_id for a in current_assets):
            return dash.no_update, f"Ativo '{ticker_clean}' já cadastrado."

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
        _db.upsert_asset(new_asset, sort_order=len(current_assets))
        return current_assets + [new_asset], ""

    # Nenhuma ação real — não sobrescreve a store
    return dash.no_update, ""


# 9 · Dropdown do simulador (sincroniza com assets-store) ──────
@app.callback(
    Output("dd-sim-asset", "options"),
    Output("dd-sim-asset", "value"),
    Input("assets-store", "data"),
    State("dd-sim-asset", "value"),
)
def sync_sim_dropdown(assets, current_val):
    if not assets:
        return dash.no_update, dash.no_update
    supported = [a for a in assets if a.get("type", "stock") not in _SIM_EXCLUDED]
    if not supported:
        return [], None
    options = [{"label": a["name"], "value": a["id"]} for a in supported]
    ids     = [a["id"] for a in supported]
    value   = current_val if current_val in ids else ids[0]
    return options, value


# 10 · Simulação ──────────────────────────────────────────────
@app.callback(
    Output("sim-results", "children"),
    Input("btn-simulate", "n_clicks"),
    State("dd-sim-asset",   "value"),
    State("inp-sim-amount", "value"),
    State("currency-store", "data"),
    State("assets-store",   "data"),
    prevent_initial_call=True,
)
def run_simulation(n_clicks, asset_id, amount, currency, assets):
    _warn = lambda msg: html.Div(msg, style={"color": "#ffa657", "fontSize": "13px",
                                              "padding": "24px 0"})
    _err  = lambda msg: html.Div(msg, style={"color": "#f85149", "fontSize": "13px",
                                              "padding": "24px 0"})

    # Fallback para DB se a store foi corrompida por race condition
    assets = assets or _db.load_assets()

    if not asset_id:
        return _warn("Selecione um ativo.")
    try:
        # aceita tanto ponto quanto vírgula como separador decimal
        amount_clean = str(amount or "").strip().replace(",", ".")
        amount = float(amount_clean)
        if amount <= 0:
            raise ValueError
    except (TypeError, ValueError):
        return _warn("Informe um valor válido a investir (ex: 5000).")
    if not assets:
        return _warn("Erro ao carregar ativos. Recarregue a página.")

    asset = next((a for a in assets if a["id"] == asset_id), None)
    if asset is None:
        return _err("Ativo não encontrado.")

    display_brl = (currency == "BRL")
    fx          = get_usd_brl() if display_brl else 1.0
    sym         = "R$" if (display_brl or asset["base_currency"] == "BRL") else "US$"

    sim = get_dividend_simulation(asset, float(amount), display_brl, fx)

    if not sim["supported"]:
        return html.Div([
            html.Div("—", style={"fontSize": "36px", "color": "#484f58", "marginBottom": "8px"}),
            html.Div(
                f"Tipo '{asset.get('type', '')}' não suporta simulação de dividendos."
                " Disponível para: ações, ETFs e FIIs.",
                style={"color": "#8b949e", "fontSize": "13px"},
            ),
        ], style={"textAlign": "center", "padding": "60px 0"})

    def _fmt(v):
        if v is None:
            return "—"
        if v >= 1_000_000:
            return f"{sym} {v / 1_000_000:.2f}M"
        if v >= 1_000:
            s = f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
            return f"{sym} {s}"
        if v >= 1:
            return f"{sym} {v:.4f}".rstrip("0").rstrip(".")
        return f"{sym} {v:.6f}".rstrip("0").rstrip(".")

    def _metric(label, value, sub=None, color="#e6edf3"):
        return html.Div(className="price-card", style={"minWidth": "0"}, children=[
            html.Div(label, className="card-name"),
            html.Div(value, className="card-price", style={"color": color, "fontSize": "18px"}),
            html.Div(sub or "", className="card-timestamp"),
        ])

    # ── Row 1 – investimento ─────────────────────────────────
    row1 = html.Div(
        style={"display": "grid",
               "gridTemplateColumns": "repeat(4, 1fr)",
               "gap": "14px", "marginBottom": "16px"},
        children=[
            _metric("Preço por cota",  _fmt(sim["price"])),
            _metric("Cotas compradas", str(sim["units"]),        "unidades"),
            _metric("Custo total",     _fmt(sim["actual_cost"]), "efetivo"),
            _metric("Sobra",           _fmt(sim["remainder"]),   "não investido"),
        ],
    )

    if sim["error"]:
        return html.Div([
            row1,
            html.Div(sim["error"],
                     style={"color": "#ffa657", "fontSize": "13px", "marginTop": "8px"}),
        ])

    # ── Row 2 – rendimento ───────────────────────────────────
    dy_color = "#3fb950" if sim["dividend_yield"] > 0 else "#8b949e"
    row2 = html.Div(
        style={"display": "grid",
               "gridTemplateColumns": "repeat(3, 1fr)",
               "gap": "14px", "marginBottom": "24px"},
        children=[
            _metric("Rend. anual projetado", _fmt(sim["projected_annual"]),
                    f"{sim['units']} cotas × dividendos", "#3fb950"),
            _metric("Dividend Yield",         f"{sim['dividend_yield']:.2f}%",
                    "projetado 12m", dy_color),
            _metric("Frequência",             sim["freq_label"], "de pagamento"),
        ],
    )

    # ── Gráfico de dividendos ─────────────────────────────────
    import datetime as dt
    hist          = sim["dividends_hist"]
    dates_hist    = [h["date"]                 for h in hist]
    vals_hist     = [h["value"] * sim["units"] for h in hist]
    n             = len(hist)
    interval_days = int(365 / max(n, 1))
    last_date     = dt.date.fromisoformat(dates_hist[-1]) if dates_hist else dt.date.today()
    dates_proj    = [str(last_date + dt.timedelta(days=interval_days * (i + 1))) for i in range(n)]
    avg_payment   = sim["projected_annual"] / max(n, 1)
    vals_proj     = [avg_payment] * n

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=dates_hist, y=vals_hist,
        name="Histórico (12m)",
        marker_color="#58a6ff",
    ))
    fig.add_trace(go.Bar(
        x=dates_proj, y=vals_proj,
        name="Projeção (próx. 12m)",
        marker_color="#3fb950",
        opacity=0.75,
    ))
    fig.update_layout(
        **PLOT_BASE,
        title=dict(
            text=f"Dividendos · {asset['name']}  ({sym}/pagamento)  ·  {sim['units']} cotas",
            font=dict(color="#e6edf3", size=13), x=0.01,
        ),
        xaxis=dict(**AXIS_STYLE),
        yaxis=dict(**AXIS_STYLE, title_text=f"Valor ({sym})"),
        barmode="group",
        bargap=0.25,
        height=320,
    )

    return html.Div([row1, row2, dcc.Graph(
        figure=fig,
        config={"displaylogo": False, "modeBarButtons": [["toImage"]]},
    )])


# 11 · Comm Lens ───────────────────────────────────────────
@app.callback(
    Output("modal-lens", "is_open"),
    Output("lens-title",  "children"),
    Output("lens-content", "children"),
    Input({"type": "lens-btn", "index": ALL}, "n_clicks"),
    State("assets-store", "data"),
    prevent_initial_call=True,
)
def open_lens(clicks_list, assets):
    triggered = ctx.triggered_id
    if not isinstance(triggered, dict) or triggered.get("type") != "lens-btn":
        return dash.no_update, dash.no_update, dash.no_update
    if not any(c for c in (clicks_list or []) if c):
        return dash.no_update, dash.no_update, dash.no_update

    asset_id = triggered["index"]
    assets   = assets or _db.load_assets()
    asset    = next((a for a in assets if a["id"] == asset_id), None)
    if not asset:
        return True, "◈ Comm Lens", html.Div("Ativo não encontrado.")

    lens = get_asset_lens(asset)
    info = lens["info"]
    news = lens["news"]
    curr = info.get("currency", asset.get("base_currency", ""))

    def _fmt_num(v, prefix="", suffix="", decimals=2):
        if v is None:
            return "—"
        if isinstance(v, float) and v > 1_000_000_000:
            return f"{prefix}{v/1_000_000_000:.2f}B{suffix}"
        if isinstance(v, float) and v > 1_000_000:
            return f"{prefix}{v/1_000_000:.2f}M{suffix}"
        return f"{prefix}{v:,.{decimals}f}{suffix}"

    def _card(label, value, sub=None):
        return html.Div(
            style={"background": "#161b22", "border": "1px solid #30363d",
                   "borderRadius": "10px", "padding": "14px 16px"},
            children=[
                html.Div(label, style={"fontSize": "11px", "color": "#484f58",
                                       "fontWeight": "600", "textTransform": "uppercase",
                                       "letterSpacing": "0.5px", "marginBottom": "6px"}),
                html.Div(value, style={"fontSize": "16px", "fontWeight": "700",
                                       "color": "#e6edf3",
                                       "fontFamily": "JetBrains Mono, monospace"}),
                html.Div(sub or "", style={"fontSize": "11px", "color": "#8b949e",
                                            "marginTop": "3px"}),
            ],
        )

    # ── Métricas ────────────────────────────────────────
    metrics = []
    if info.get("trailingPE"):
        metrics.append(_card("P/L", _fmt_num(info["trailingPE"]), "trailing"))
    if info.get("forwardPE"):
        metrics.append(_card("P/L Fwd", _fmt_num(info["forwardPE"]), "forward"))
    if info.get("priceToBook"):
        metrics.append(_card("P/VP", _fmt_num(info["priceToBook"])))
    if info.get("dividendYield"):
        metrics.append(_card("Div. Yield", f"{info['dividendYield']:.2f}%", "12m"))
    if info.get("beta"):
        metrics.append(_card("Beta", _fmt_num(info["beta"])))
    if info.get("marketCap"):
        metrics.append(_card("Market Cap", _fmt_num(info["marketCap"], prefix=f"{curr} "), curr))
    if info.get("fiftyTwoWeekHigh"):
        metrics.append(_card("Máx 52s", _fmt_num(info["fiftyTwoWeekHigh"], prefix=f"{curr} "), curr))
    if info.get("fiftyTwoWeekLow"):
        metrics.append(_card("Mín 52s", _fmt_num(info["fiftyTwoWeekLow"], prefix=f"{curr} "), curr))
    if info.get("volume"):
        metrics.append(_card("Volume",     _fmt_num(float(info["volume"]), decimals=0), "hoje"))
    if info.get("averageVolume"):
        metrics.append(_card("Vol. Médio", _fmt_num(float(info["averageVolume"]), decimals=0), "média"))
    if info.get("sector"):
        metrics.append(_card("Setor", info["sector"]))
    if info.get("industry"):
        metrics.append(_card("Segmento", info["industry"]))
    if info.get("exchange"):
        metrics.append(_card("Bolsa", info["exchange"]))

    metrics_grid = html.Div(
        style={"display": "grid",
               "gridTemplateColumns": "repeat(auto-fill, minmax(160px, 1fr))",
               "gap": "10px", "marginBottom": "24px"},
        children=metrics,
    ) if metrics else html.Div(
        "Métricas não disponíveis para este tipo de ativo.",
        style={"color": "#484f58", "fontSize": "13px", "marginBottom": "24px"},
    )

    # ── Descrição ────────────────────────────────────────
    desc_block = []
    if info.get("longBusinessSummary"):
        desc_block = [
            html.Div("Sobre", className="section-title", style={"marginBottom": "8px"}),
            html.P(
                info["longBusinessSummary"],
                style={"color": "#8b949e", "fontSize": "13px", "lineHeight": "1.7",
                       "marginBottom": "24px"},
            ),
        ]

    # ── Notícias ────────────────────────────────────────
    if news:
        news_items = []
        for n in news:
            news_items.append(
                html.A(
                    href=n["url"] or "#",
                    target="_blank",
                    style={"textDecoration": "none"},
                    children=html.Div(
                        style={"background": "#161b22", "border": "1px solid #30363d",
                               "borderRadius": "10px", "padding": "14px 18px",
                               "marginBottom": "8px",
                               "transition": "border-color 0.15s"},
                        children=[
                            html.Div(
                                style={"display": "flex", "justifyContent": "space-between",
                                       "alignItems": "flex-start", "gap": "12px"},
                                children=[
                                    html.Div(n["title"],
                                             style={"color": "#58a6ff", "fontWeight": "500",
                                                    "fontSize": "13px"}),
                                    html.Div(n["pubDate"],
                                             style={"color": "#484f58", "fontSize": "11px",
                                                    "whiteSpace": "nowrap",
                                                    "fontFamily": "JetBrains Mono, monospace"}),
                                ],
                            ),
                            html.Div(n["summary"],
                                     style={"color": "#8b949e", "fontSize": "12px",
                                            "marginTop": "5px", "lineHeight": "1.5"})
                            if n["summary"] else html.Span(),
                        ],
                    ),
                )
            )
        news_block = [
            html.Div("Notícias Recentes", className="section-title", style={"marginBottom": "12px"}),
            html.Div(news_items),
        ]
    else:
        news_block = [
            html.Div("Notícias Recentes", className="section-title", style={"marginBottom": "8px"}),
            html.Div("Sem notícias disponíveis para este ativo.",
                     style={"color": "#484f58", "fontSize": "13px"}),
        ]

    title = f"◈ Comm Lens · {info.get('longName') or asset['name']}"
    content = html.Div([
        metrics_grid,
        *desc_block,
        *news_block,
    ])
    return True, title, content


# 11 · Comm Lens ──────────────────────────────────────────────
@app.callback(
    Output("modal-lens",  "is_open"),
    Output("lens-title",  "children"),
    Output("lens-content", "children"),
    Input({"type": "lens-btn", "index": ALL}, "n_clicks"),
    State("assets-store", "data"),
    prevent_initial_call=True,
)
def open_lens(clicks_list, assets):
    triggered = ctx.triggered_id
    if not isinstance(triggered, dict) or triggered.get("type") != "lens-btn":
        return dash.no_update, dash.no_update, dash.no_update
    if not any(c for c in (clicks_list or []) if c):
        return dash.no_update, dash.no_update, dash.no_update

    asset_id = triggered["index"]
    assets   = assets or _db.load_assets()
    asset    = next((a for a in assets if a["id"] == asset_id), None)
    if not asset:
        return True, "◈ Comm Lens", html.Div("Ativo não encontrado.")

    lens = get_asset_lens(asset)
    info = lens["info"]
    news = lens["news"]
    curr = info.get("currency", asset.get("base_currency", ""))

    def _fmt_num(v, prefix="", suffix="", decimals=2):
        if v is None:
            return "—"
        if isinstance(v, (int, float)) and float(v) > 1_000_000_000:
            return f"{prefix}{float(v)/1_000_000_000:.2f}B{suffix}"
        if isinstance(v, (int, float)) and float(v) > 1_000_000:
            return f"{prefix}{float(v)/1_000_000:.2f}M{suffix}"
        return f"{prefix}{float(v):,.{decimals}f}{suffix}"

    def _card(label, value, sub=None):
        return html.Div(
            style={"background": "#161b22", "border": "1px solid #30363d",
                   "borderRadius": "10px", "padding": "14px 16px"},
            children=[
                html.Div(label, style={"fontSize": "11px", "color": "#484f58",
                                       "fontWeight": "600", "textTransform": "uppercase",
                                       "letterSpacing": "0.5px", "marginBottom": "6px"}),
                html.Div(value, style={"fontSize": "16px", "fontWeight": "700",
                                       "color": "#e6edf3",
                                       "fontFamily": "JetBrains Mono, monospace"}),
                html.Div(sub or "", style={"fontSize": "11px", "color": "#8b949e",
                                            "marginTop": "3px"}),
            ],
        )

    # ── Métricas ──────────────────────────────────────────────
    metrics = []
    if info.get("trailingPE"):
        metrics.append(_card("P/L",        _fmt_num(info["trailingPE"]),  "trailing"))
    if info.get("forwardPE"):
        metrics.append(_card("P/L Fwd",    _fmt_num(info["forwardPE"]),   "forward"))
    if info.get("priceToBook"):
        metrics.append(_card("P/VP",       _fmt_num(info["priceToBook"])))
    if info.get("dividendYield"):
        metrics.append(_card("Div. Yield", f"{info['dividendYield']:.2f}%", "12m"))
    if info.get("beta"):
        metrics.append(_card("Beta",       _fmt_num(info["beta"])))
    if info.get("marketCap"):
        metrics.append(_card("Market Cap", _fmt_num(info["marketCap"], prefix=f"{curr} "), curr))
    if info.get("fiftyTwoWeekHigh"):
        metrics.append(_card("Máx 52s",    _fmt_num(info["fiftyTwoWeekHigh"], prefix=f"{curr} "), curr))
    if info.get("fiftyTwoWeekLow"):
        metrics.append(_card("Mín 52s",    _fmt_num(info["fiftyTwoWeekLow"],  prefix=f"{curr} "), curr))
    if info.get("volume"):
        metrics.append(_card("Volume",     _fmt_num(float(info["volume"]),        decimals=0), "hoje"))
    if info.get("averageVolume"):
        metrics.append(_card("Vol. Médio", _fmt_num(float(info["averageVolume"]), decimals=0), "média"))
    if info.get("sector"):
        metrics.append(_card("Setor",      info["sector"]))
    if info.get("industry"):
        metrics.append(_card("Segmento",   info["industry"]))
    if info.get("exchange"):
        metrics.append(_card("Bolsa",      info["exchange"]))

    metrics_grid = html.Div(
        style={"display": "grid",
               "gridTemplateColumns": "repeat(auto-fill, minmax(160px, 1fr))",
               "gap": "10px", "marginBottom": "24px"},
        children=metrics,
    ) if metrics else html.Div(
        "Métricas não disponíveis para este tipo de ativo.",
        style={"color": "#484f58", "fontSize": "13px", "marginBottom": "24px"},
    )

    # ── Descrição ─────────────────────────────────────────────
    desc_block = []
    if info.get("longBusinessSummary"):
        desc_block = [
            html.Div("Sobre", className="section-title", style={"marginBottom": "8px"}),
            html.P(
                info["longBusinessSummary"],
                style={"color": "#8b949e", "fontSize": "13px", "lineHeight": "1.7",
                       "marginBottom": "24px"},
            ),
        ]

    # ── Notícias ──────────────────────────────────────────────
    if news:
        news_items = []
        for n in news:
            news_items.append(
                html.A(
                    href=n["url"] or "#",
                    target="_blank",
                    style={"textDecoration": "none"},
                    children=html.Div(
                        style={"background": "#161b22", "border": "1px solid #30363d",
                               "borderRadius": "10px", "padding": "14px 18px",
                               "marginBottom": "8px"},
                        children=[
                            html.Div(
                                style={"display": "flex", "justifyContent": "space-between",
                                       "alignItems": "flex-start", "gap": "12px"},
                                children=[
                                    html.Div(n["title"],
                                             style={"color": "#58a6ff", "fontWeight": "500",
                                                    "fontSize": "13px"}),
                                    html.Div(n["pubDate"],
                                             style={"color": "#484f58", "fontSize": "11px",
                                                    "whiteSpace": "nowrap",
                                                    "fontFamily": "JetBrains Mono, monospace"}),
                                ],
                            ),
                            html.Div(n["summary"],
                                     style={"color": "#8b949e", "fontSize": "12px",
                                            "marginTop": "5px", "lineHeight": "1.5"})
                            if n["summary"] else html.Span(),
                        ],
                    ),
                )
            )
        news_block = [
            html.Div("Notícias Recentes", className="section-title", style={"marginBottom": "12px"}),
            html.Div(news_items),
        ]
    else:
        news_block = [
            html.Div("Notícias Recentes", className="section-title", style={"marginBottom": "8px"}),
            html.Div("Sem notícias disponíveis para este ativo.",
                     style={"color": "#484f58", "fontSize": "13px"}),
        ]

    title   = f"◈ Comm Lens · {info.get('longName') or asset['name']}"
    content = html.Div([metrics_grid, *desc_block, *news_block])
    return True, title, content


# ─── Execução ─────────────────────────────────────────────────
if __name__ == "__main__":
    app.run(debug=False, host="0.0.0.0", port=8050, use_reloader=False, threaded=True)

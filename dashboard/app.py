# dashboard/app.py
import sys
import requests
import pandas as pd
import numpy as np
from datetime import datetime
from dash import Dash, html, dcc, Input, Output, State, ctx, ALL
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import dash_bootstrap_components as dbc

sys.stdout.reconfigure(line_buffering=True)

# ---------------------------------------------------------
# API CONFIG
# ---------------------------------------------------------
DATA_API_BASE = "http://data:8003"
GATEWAY_API   = "http://gateway:8000/api"

LABEL_LOCAL = "Local Sentiment"
LABEL_REMOTE = "Remote Sentiment"

MAX_SYMBOLS = 12

app = Dash(__name__, external_stylesheets=[dbc.themes.CYBORG])
server = app.server

# ---------------------------------------------------------
# CUSTOM STYLING
# ---------------------------------------------------------
app.index_string = '''
<!DOCTYPE html>
<html>
<head>
    {%metas%}
    <title>SentimentCompare</title>
    {%favicon%}
    {%css%}
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link href="https://fonts.googleapis.com/css2?family=Space+Mono:wght@400;700&family=Syne:wght@400;700;800&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg:        #080c10;
            --bg2:       #0d1117;
            --bg3:       #111820;
            --border:    #1e2d3d;
            --border2:   #243447;
            --text:      #c9d1d9;
            --text-dim:  #586069;
            --accent:    #e6a817;
            --accent2:   #22d3ee;
            --green:     #3fb950;
            --red:       #f85149;
            --purple:    #bc8cff;
        }
        *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            background: var(--bg);
            color: var(--text);
            font-family: 'Space Mono', monospace;
            font-size: 13px;
        }
        .sc-header { display: flex; align-items: center; justify-content: space-between; padding: 14px 28px; border-bottom: 1px solid var(--border); background: var(--bg2); }
        .sc-header-logo { font-family: 'Syne', sans-serif; font-weight: 800; font-size: 20px; letter-spacing: -0.5px; color: #fff; }
        .sc-header-meta { font-size: 11px; color: var(--text-dim); text-align: right; }
        .sc-tabs { display: flex; gap: 0; border-bottom: 1px solid var(--border); background: var(--bg2); padding: 0 28px; }
        .sc-tab { padding: 10px 20px; font-size: 11px; font-weight: 700; letter-spacing: 1.5px; text-transform: uppercase; cursor: pointer; color: var(--text-dim); border-bottom: 2px solid transparent; transition: all 0.15s; }
        .sc-tab:hover { color: var(--text); }
        .sc-tab.active { color: var(--accent); border-bottom-color: var(--accent); }
        .sc-login-wrap { display: flex; align-items: center; justify-content: center; min-height: calc(100vh - 60px); }
        .sc-login-box { border: 1px solid var(--border2); background: var(--bg2); padding: 40px 48px; width: 380px; }
        .sc-login-title { font-family: 'Syne', sans-serif; font-size: 22px; font-weight: 800; margin-bottom: 28px; color: #fff; }
        .sc-input-label { font-size: 10px; letter-spacing: 1.5px; text-transform: uppercase; color: var(--text-dim); margin-bottom: 6px; }
        .sc-input { width: 100%; background: var(--bg3); border: 1px solid var(--border2); color: var(--text); font-family: 'Space Mono', monospace; font-size: 13px; padding: 9px 12px; outline: none; margin-bottom: 16px; transition: border-color 0.15s; }
        .sc-input:focus { border-color: var(--accent); }
        .sc-btn { background: var(--accent); color: #000; border: none; font-family: 'Space Mono', monospace; font-weight: 700; font-size: 12px; letter-spacing: 1px; padding: 10px 20px; cursor: pointer; transition: opacity 0.15s; }
        .sc-btn:hover { opacity: 0.85; }
        .sc-btn-ghost { background: transparent; color: var(--text-dim); border: 1px solid var(--border2); font-family: 'Space Mono', monospace; font-size: 11px; letter-spacing: 0.5px; padding: 7px 14px; cursor: pointer; transition: all 0.15s; }
        .sc-btn-ghost:hover { color: var(--text); border-color: var(--text-dim); }
        .sc-btn-danger { background: transparent; color: var(--red); border: 1px solid var(--red); font-family: 'Space Mono', monospace; font-size: 11px; padding: 7px 14px; cursor: pointer; transition: all 0.15s; }
        .sc-btn-danger:hover { background: var(--red); color: #fff; }
        .sc-body { display: flex; height: calc(100vh - 99px); overflow: hidden; }
        .sc-sidebar { width: 220px; min-width: 220px; border-right: 1px solid var(--border); background: var(--bg2); padding: 20px 16px; display: flex; flex-direction: column; gap: 16px; overflow-y: auto; }
        .sc-main { flex: 1; overflow-y: auto; padding: 20px 24px; }
        .sc-section-label { font-size: 9px; letter-spacing: 2px; text-transform: uppercase; color: var(--text-dim); margin-bottom: 8px; }
        .sc-chip-area { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 8px; min-height: 28px; }
        .sc-chip { display: inline-flex; align-items: center; gap: 5px; background: var(--bg3); border: 1px solid var(--border2); color: var(--text); font-family: 'Space Mono', monospace; font-size: 11px; padding: 3px 8px; cursor: default; }
        .sc-chip.active { border-color: var(--accent); color: var(--accent); }
        .sc-chip-x { cursor: pointer; color: var(--text-dim); font-size: 12px; line-height: 1; margin-left: 2px; }
        .sc-chip-x:hover { color: var(--red); }
        .sc-chip-add-row { display: flex; gap: 6px; }
        .sc-chip-input { flex: 1; background: var(--bg3); border: 1px solid var(--border2); color: var(--text); font-family: 'Space Mono', monospace; font-size: 11px; padding: 5px 8px; outline: none; text-transform: uppercase; min-width: 0; }
        .sc-chip-input:focus { border-color: var(--accent); }
        .sc-chip-input::placeholder { color: var(--text-dim); text-transform: none; }
        .sc-add-btn { background: transparent; border: 1px solid var(--border2); color: var(--text-dim); font-family: 'Space Mono', monospace; font-size: 13px; padding: 4px 10px; cursor: pointer; transition: all 0.15s; }
        .sc-add-btn:hover { border-color: var(--accent); color: var(--accent); }
        .sc-cap-note { font-size: 9px; color: var(--text-dim); margin-top: 4px; }
        .sc-scorecard { display: grid; grid-template-columns: repeat(4, 1fr); gap: 1px; background: var(--border); border: 1px solid var(--border); margin-bottom: 20px; }
        .sc-score-cell { background: var(--bg2); padding: 14px 16px; }
        .sc-score-label { font-size: 9px; letter-spacing: 1.5px; text-transform: uppercase; color: var(--text-dim); margin-bottom: 6px; }
        .sc-score-value { font-family: 'Syne', sans-serif; font-size: 22px; font-weight: 800; color: #fff; line-height: 1; }
        .sc-score-sub { font-size: 10px; color: var(--text-dim); margin-top: 4px; }
        .sc-chart-block { background: var(--bg2); border: 1px solid var(--border); margin-bottom: 16px; padding: 16px; }
        .sc-chart-title { font-size: 10px; letter-spacing: 1.5px; text-transform: uppercase; color: var(--text-dim); margin-bottom: 12px; display: flex; align-items: center; gap: 10px; }
        .sc-chart-title-line { flex: 1; height: 1px; background: var(--border); }
        .sc-news-feed { background: var(--bg2); border: 1px solid var(--border); padding: 0; margin-bottom: 16px; }
        .sc-news-header { display: flex; align-items: center; justify-content: space-between; padding: 12px 16px; border-bottom: 1px solid var(--border); }
        .sc-news-item { padding: 12px 16px; border-bottom: 1px solid var(--border); transition: background 0.1s; }
        .sc-news-item:last-child { border-bottom: none; }
        .sc-news-item:hover { background: var(--bg3); }
        .sc-news-headline { font-size: 12px; color: var(--text); line-height: 1.5; margin-bottom: 6px; }
        .sc-news-headline a { color: var(--text); text-decoration: none; }
        .sc-news-headline a:hover { color: var(--accent); }
        .sc-news-meta { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
        .sc-news-source { font-size: 10px; color: var(--text-dim); }
        .sc-score-tag { font-size: 10px; padding: 1px 6px; border: 1px solid; }
        .sc-score-pos { border-color: var(--green); color: var(--green); }
        .sc-score-neg { border-color: var(--red);   color: var(--red);   }
        .sc-score-neu { border-color: var(--text-dim); color: var(--text-dim); }
        .sc-live-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--green); display: inline-block; margin-right: 4px; }
        .sc-disagree-badge { display: inline-block; background: rgba(188,140,255,0.15); border: 1px solid var(--purple); color: var(--purple); font-size: 9px; letter-spacing: 1px; text-transform: uppercase; padding: 2px 7px; margin-left: 8px; }
        /* Admin metrics table */
        .sc-metrics-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 1px; background: var(--border); border: 1px solid var(--border); margin-bottom: 20px; }
        .sc-metric-cell { background: var(--bg3); padding: 14px 16px; }
        .sc-metric-label { font-size: 9px; letter-spacing: 1.5px; text-transform: uppercase; color: var(--text-dim); margin-bottom: 6px; }
        .sc-metric-value { font-family: 'Syne', sans-serif; font-size: 20px; font-weight: 800; color: #fff; line-height: 1; }
        .sc-metric-sub { font-size: 10px; color: var(--text-dim); margin-top: 4px; }
        .sc-admin-section-title { font-size: 9px; letter-spacing: 2px; text-transform: uppercase; color: var(--text-dim); margin: 16px 0 8px 0; }
        .sc-table { width: 100%; border-collapse: collapse; font-size: 11px; }
        .sc-table th { text-align: left; font-size: 9px; letter-spacing: 1.5px; text-transform: uppercase; color: var(--text-dim); padding: 8px 12px; border-bottom: 1px solid var(--border); font-weight: 400; }
        .sc-table td { padding: 9px 12px; border-bottom: 1px solid var(--border); color: var(--text); vertical-align: middle; }
        .sc-table tr:last-child td { border-bottom: none; }
        .sc-table tr:hover td { background: var(--bg3); }
        .sc-status-ok  { color: var(--green); font-size: 10px; }
        .sc-status-err { color: var(--red);   font-size: 10px; }
        .sc-corr-pos { color: var(--green); }
        .sc-corr-neg { color: var(--red); }
        .sc-corr-na  { color: var(--text-dim); }
        .sc-alert-banner { padding: 8px 12px; font-size: 11px; margin-bottom: 12px; border: 1px solid; }
        .sc-alert-success { border-color: var(--green); color: var(--green); background: rgba(63,185,80,0.07); }
        .sc-alert-danger  { border-color: var(--red);   color: var(--red);   background: rgba(248,81,73,0.07); }
        ::-webkit-scrollbar { width: 4px; }
        ::-webkit-scrollbar-track { background: var(--bg); }
        ::-webkit-scrollbar-thumb { background: var(--border2); }
    </style>
</head>
<body>
    {%app_entry%}
    <footer>
        {%config%}
        {%scripts%}
        {%renderer%}
    </footer>
</body>
</html>
'''

# ---------------------------------------------------------
# HELPERS
# ---------------------------------------------------------
def clean_trading_data(df):
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df.dropna(subset=["finbert_sentiment", "av_sentiment"], how="all")
    return df.sort_values("date").reset_index(drop=True)

def compute_corr(df, col, lag_col):
    valid = df[[col, lag_col]].dropna()
    if len(valid) >= 5:
        return valid[col].corr(valid[lag_col])
    return None

def fmt_corr(v):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "N/A", "sc-corr-na"
    s = f"{v:+.3f}"
    cls = "sc-corr-pos" if v > 0.05 else ("sc-corr-neg" if v < -0.05 else "sc-corr-na")
    return s, cls

def sentiment_tag(score, label_prefix):
    if score is None:
        return html.Span(f"{label_prefix} —", className="sc-score-tag sc-score-neu")
    cls = "sc-score-pos" if score >= 0.05 else ("sc-score-neg" if score <= -0.05 else "sc-score-neu")
    sign = "+" if score > 0 else ""
    return html.Span(f"{label_prefix} {sign}{score:.2f}", className=f"sc-score-tag {cls}")

def dim(text):
    return html.Span(text, style={"color": "var(--text-dim)"})

PLOTLY_DARK = dict(
    template="plotly_dark",
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    font=dict(family="Space Mono, monospace", size=11, color="#586069"),
    margin=dict(l=10, r=10, t=10, b=10),
)

# Endpoints to show in admin metrics (others are filtered out)
ADMIN_METRIC_ENDPOINTS = {"/api/login", "/api/fetch"}

# ---------------------------------------------------------
# LAYOUT
# ---------------------------------------------------------
app.layout = html.Div([
    dcc.Store(id="auth-token"),
    dcc.Store(id="active-tab", data="analysis"),
    dcc.Store(id="symbol-list", data=[]),
    dcc.Store(id="active-symbol", data=None),
    dcc.Interval(id="news-interval", interval=30_000, n_intervals=0, disabled=True),

    # Header
    html.Div([
        html.Div([
            html.Span("Sentiment", className="sc-header-logo"),
            html.Span("Compare", className="sc-header-logo", style={"color": "var(--accent)"}),
        ], style={"display": "flex"}),
        html.Div(id="header-meta", className="sc-header-meta"),
    ], className="sc-header"),

    # Login View
    html.Div(
        id="login-view",
        className="sc-login-wrap",
        children=[
            html.Div([
                html.Div("Sign In", className="sc-login-title"),
                dbc.Alert(id="login-message", color="danger", is_open=False, className="mb-3",
                          style={"fontSize": "12px", "fontFamily": "Space Mono, monospace"}),
                html.Div("Username", className="sc-input-label"),
                dcc.Input(id="login-username", type="text", value="", className="sc-input"),
                html.Div("Password", className="sc-input-label"),
                dcc.Input(id="login-password", type="password", value="", className="sc-input"),
                html.Button("AUTHENTICATE", id="login-button", className="sc-btn", style={"width": "100%"}),
            ], className="sc-login-box")
        ]
    ),

    # Main View
    html.Div(
        id="main-view",
        style={"display": "none"},
        children=[
            html.Div([
                html.Div("Analysis", id="tab-analysis", className="sc-tab active", n_clicks=0),
                html.Div("Admin",    id="tab-admin",    className="sc-tab",        n_clicks=0),
            ], className="sc-tabs"),

            html.Div(className="sc-body", children=[

                # ── Sidebar ──────────────────────────────────────────────
                html.Div(className="sc-sidebar", children=[
                    html.Div([
                        html.Div("Symbols", className="sc-section-label"),
                        html.Div(id="chip-area", className="sc-chip-area"),
                        html.Div([
                            dcc.Input(id="symbol-add-input", type="text", placeholder="e.g. AAPL",
                                      maxLength=6, className="sc-chip-input", debounce=False, n_submit=0),
                            html.Button("+", id="symbol-add-btn", className="sc-add-btn", n_clicks=0),
                        ], className="sc-chip-add-row"),
                        html.Div(f"Max {MAX_SYMBOLS} symbols", className="sc-cap-note"),
                    ]),

                    html.Div([
                        html.Div("History Days", className="sc-section-label"),
                        dcc.Input(id="days-input", type="number", value=7, min=1, max=365,
                                  className="sc-input", style={"marginBottom": "0"}),
                    ]),

                    html.Button("FETCH DATA",  id="fetch-button", className="sc-btn",       style={"width": "100%"}),
                    html.Button("LOAD CHART",  id="load-btn",     className="sc-btn-ghost",  style={"width": "100%"}),
                    html.Div(id="fetch-message"),
                    html.Div(style={"flex": "1"}),
                    html.Button("LOGOUT", id="logout-button", className="sc-btn-danger", style={"width": "100%"}),
                ]),

                # ── Main Content ─────────────────────────────────────────
                html.Div(className="sc-main", children=[

                    # ── Analysis Tab ──────────────────────────────────────
                    html.Div(id="panel-analysis", children=[

                        html.Div(id="scorecard-strip", className="sc-scorecard"),

                        # Price & Sentiment Chart
                        html.Div(className="sc-chart-block", children=[
                            html.Div([
                                "Price & Sentiment Comparison",
                                html.Div(className="sc-chart-title-line"),
                                html.Div(id="disagree-badge"),
                            ], className="sc-chart-title"),
                            dcc.Loading(dcc.Graph(id="split-chart", config={"displayModeBar": False})),
                        ]),

                        # Scatter Chart
                        html.Div(className="sc-chart-block", children=[
                            html.Div([
                                "Sentiment vs. Price Change — Model × Lag Comparison",
                                html.Div(className="sc-chart-title-line"),
                            ], className="sc-chart-title"),
                            dcc.Loading(dcc.Graph(id="scatter-chart", config={"displayModeBar": False},
                                                  style={"height": "340px"})),
                        ]),

                        # News Feed
                        html.Div(className="sc-news-feed", children=[
                            html.Div([
                                html.Span([html.Span(className="sc-live-dot"), "Latest Finnhub Headlines"],
                                          style={"fontSize": "10px", "letterSpacing": "1.5px",
                                                 "textTransform": "uppercase", "color": "var(--text-dim)"}),
                                html.Span(" • refreshes every 30s",
                                          style={"fontSize": "10px", "color": "var(--text-dim)"}),
                            ], className="sc-news-header"),
                            dcc.Loading(
                                html.Div(id="news-feed-container", children=[
                                    html.Div("Load a chart to see headlines.",
                                             style={"padding": "16px", "color": "var(--text-dim)", "fontSize": "12px"})
                                ])
                            ),
                        ]),
                    ]),

                    # ── Admin Tab ─────────────────────────────────────────
                    html.Div(id="panel-admin", style={"display": "none"}, children=[

                        # Gateway health / metrics
                        html.Div(className="sc-chart-block", children=[
                            html.Div([
                                "Gateway Metrics — Login & Fetch",
                                html.Div(className="sc-chart-title-line"),
                                html.Button("↻ REFRESH", id="admin-refresh-btn", className="sc-btn-ghost",
                                            style={"fontSize": "10px", "padding": "4px 10px"}),
                            ], className="sc-chart-title"),
                            html.Div(id="admin-error"),
                            dcc.Loading(html.Div(id="admin-metrics-table")),
                        ]),

                        # Correlation matrix across all loaded symbols
                        html.Div(className="sc-chart-block", children=[
                            html.Div([
                                "Correlation Matrix — all loaded symbols",
                                html.Div(className="sc-chart-title-line"),
                            ], className="sc-chart-title"),
                            dcc.Loading(html.Div(id="corr-table-container")),
                        ]),

                        # Data inventory
                        html.Div(className="sc-chart-block", children=[
                            html.Div([
                                "Data Inventory",
                                html.Div(className="sc-chart-title-line"),
                            ], className="sc-chart-title"),
                            dcc.Loading(html.Div(id="admin-inventory-table")),
                        ]),
                    ]),
                ]),
            ]),
        ]
    ),
])

# ---------------------------------------------------------
# CALLBACKS — Auth
# ---------------------------------------------------------
@app.callback(
    Output("login-view",  "style"),
    Output("main-view",   "style"),
    Input("auth-token",   "data"),
)
def toggle_views(token):
    if token:
        return {"display": "none"}, {"display": "block"}
    return (
        {"display": "flex", "alignItems": "center", "justifyContent": "center", "minHeight": "calc(100vh - 60px)"},
        {"display": "none"},
    )

@app.callback(
    Output("auth-token",     "data"),
    Output("login-message",  "children"),
    Output("login-message",  "is_open"),
    Input("login-button",    "n_clicks"),
    State("login-username",  "value"),
    State("login-password",  "value"),
    prevent_initial_call=True,
)
def handle_login(_, username, password):
    if not username or not password:
        return None, "Enter username and password.", True
    try:
        resp = requests.post(f"{GATEWAY_API}/login",
                             json={"username": username, "password": password}, timeout=10)
        if resp.status_code != 200:
            return None, "Invalid credentials.", True
        token = resp.json().get("access_token")
        return token, "", False
    except Exception as e:
        return None, f"Connection error: {e}", True

@app.callback(
    Output("auth-token", "clear_data"),
    Input("logout-button", "n_clicks"),
    prevent_initial_call=True,
)
def handle_logout(_):
    return True

# ---------------------------------------------------------
# CALLBACKS — Symbol chips
# ---------------------------------------------------------
@app.callback(
    Output("symbol-list",       "data"),
    Output("active-symbol",     "data"),
    Output("symbol-add-input",  "value"),
    Input("symbol-add-btn",     "n_clicks"),
    Input("symbol-add-input",   "n_submit"),
    Input({"type": "chip-remove", "index": ALL}, "n_clicks"),
    Input({"type": "chip-select", "index": ALL}, "n_clicks"),
    State("symbol-add-input",   "value"),
    State("symbol-list",        "data"),
    State("active-symbol",      "data"),
    prevent_initial_call=True,
)
def manage_chips(add_clicks, add_submit, remove_clicks, select_clicks,
                 input_val, symbol_list, active_symbol):
    triggered = ctx.triggered_id
    if isinstance(triggered, dict):
        if triggered.get("type") == "chip-remove":
            idx = triggered["index"]
            new_list = [s for s in symbol_list if s != idx]
            new_active = active_symbol if active_symbol in new_list else (new_list[0] if new_list else None)
            return new_list, new_active, ""
        if triggered.get("type") == "chip-select":
            return symbol_list, triggered["index"], ""
    if triggered in ("symbol-add-btn", "symbol-add-input"):
        raw = (input_val or "").strip().upper()
        if not raw or raw in symbol_list:
            return symbol_list, active_symbol, ""
        if len(symbol_list) >= MAX_SYMBOLS:
            return symbol_list, active_symbol, ""
        new_list = symbol_list + [raw]
        return new_list, raw, ""
    return symbol_list, active_symbol, ""

@app.callback(
    Output("chip-area", "children"),
    Input("symbol-list",    "data"),
    Input("active-symbol",  "data"),
)
def render_chips(symbol_list, active_symbol):
    if not symbol_list:
        return [html.Span("No symbols added",
                          style={"fontSize": "10px", "color": "var(--text-dim)"})]
    chips = []
    for sym in symbol_list:
        is_active = (sym == active_symbol)
        chips.append(
            html.Span([
                html.Span(sym, id={"type": "chip-select", "index": sym}, style={"cursor": "pointer"}),
                html.Span("×", id={"type": "chip-remove", "index": sym}, className="sc-chip-x"),
            ], className=f"sc-chip{' active' if is_active else ''}")
        )
    return chips

# ---------------------------------------------------------
# CALLBACKS — Tabs
# ---------------------------------------------------------
@app.callback(
    Output("panel-analysis", "style"),
    Output("panel-admin",    "style"),
    Output("tab-analysis",   "className"),
    Output("tab-admin",      "className"),
    Input("tab-analysis",    "n_clicks"),
    Input("tab-admin",       "n_clicks"),
    prevent_initial_call=False,
)
def switch_tabs(_, __):
    triggered = ctx.triggered_id if ctx.triggered_id else "tab-analysis"
    if triggered == "tab-admin":
        return {"display": "none"}, {"display": "block"}, "sc-tab", "sc-tab active"
    return {"display": "block"}, {"display": "none"}, "sc-tab active", "sc-tab"

# ---------------------------------------------------------
# CALLBACKS — Fetch data
# ---------------------------------------------------------
@app.callback(
    Output("fetch-message",     "children"),
    Output("symbol-list",       "data",  allow_duplicate=True),
    Output("active-symbol",     "data",  allow_duplicate=True),
    Output("symbol-add-input",  "value", allow_duplicate=True),
    Input("fetch-button",       "n_clicks"),
    State("auth-token",         "data"),
    State("symbol-list",        "data"),
    State("active-symbol",      "data"),
    State("symbol-add-input",   "value"),
    State("days-input",         "value"),
    prevent_initial_call=True,
)
def fetch_data(_, token, symbol_list, active_symbol, input_val, days):
    ts = datetime.now().strftime("%H:%M:%S")
    pending = (input_val or "").strip().upper()

    if pending and pending not in symbol_list and len(symbol_list) < MAX_SYMBOLS:
        symbol_list = symbol_list + [pending]
        active = pending
        clear_input = ""
    else:
        active = active_symbol if (active_symbol and active_symbol in symbol_list) \
                 else (symbol_list[0] if symbol_list else None)
        clear_input = input_val

    if not token:
        return (html.Div(f"[{ts}] Not authenticated.", className="sc-alert-banner sc-alert-danger"),
                symbol_list, active, clear_input)
    if not symbol_list:
        return (html.Div(f"[{ts}] Add at least one symbol.", className="sc-alert-banner sc-alert-danger"),
                symbol_list, active, clear_input)

    try:
        resp = requests.post(
            f"{GATEWAY_API}/fetch",
            json={"symbols": symbol_list, "days": int(days or 30)},
            headers={"Authorization": f"Bearer {token}"},
            timeout=max(120, len(symbol_list) * 60),
        )
        if resp.status_code == 401:
            return (html.Div(f"[{ts}] Session expired.", className="sc-alert-banner sc-alert-danger"),
                    symbol_list, active, clear_input)
        if resp.status_code != 200:
            return (html.Div(f"[{ts}] Fetch failed: {resp.text}", className="sc-alert-banner sc-alert-danger"),
                    symbol_list, active, clear_input)
        n = resp.json().get("messages_sent", "?")
        return (html.Div(f"[{ts}] OK — {n} messages queued. Click LOAD CHART.",
                         className="sc-alert-banner sc-alert-success"),
                symbol_list, active, "")
    except Exception as e:
        return (html.Div(f"[{ts}] Error: {e}", className="sc-alert-banner sc-alert-danger"),
                symbol_list, active, clear_input)

# ---------------------------------------------------------
# CALLBACKS — News interval toggle
# ---------------------------------------------------------
@app.callback(
    Output("news-interval", "disabled"),
    Input("active-symbol",  "data"),
)
def toggle_news_interval(active_symbol):
    return active_symbol is None

# ---------------------------------------------------------
# CALLBACKS — Main chart + scorecard
# ---------------------------------------------------------
@app.callback(
    Output("split-chart",        "figure"),
    Output("scorecard-strip",    "children"),
    Output("corr-table-container", "children"),
    Output("disagree-badge",     "children"),
    Output("header-meta",        "children"),
    Input("load-btn",            "n_clicks"),
    State("active-symbol",       "data"),
    State("symbol-list",         "data"),
    prevent_initial_call=True,
)
def update_charts(_, symbol, symbol_list):
    empty_fig = go.Figure().update_layout(**PLOTLY_DARK)
    empty = (empty_fig, [], html.Div("No data loaded."), [], "")

    if not symbol:
        return empty

    symbol = symbol.upper().strip()

    try:
        resp = requests.get(f"{DATA_API_BASE}/timeseries/{symbol}", timeout=15)
        resp.raise_for_status()
        data = resp.json()
        if not data:
            return empty

        df = pd.DataFrame(data)
        df = clean_trading_data(df)
        if df.empty:
            return empty

        df["intraday_pct"] = ((df["close_price"] - df["open_price"]) / df["open_price"] * 100).where(
            df[["open_price", "close_price"]].notna().all(axis=1)
        )
        df["next_day_pct"] = df["intraday_pct"].shift(-1)
        df["lag2_pct"]     = df["intraday_pct"].shift(-2)

        has_local  = df["finbert_sentiment"].notna().any()
        has_remote = df["av_sentiment"].notna().any()

        n_diverge = 0
        avg_delta = None
        if has_local and has_remote:
            df["divergence"] = (df["finbert_sentiment"] - df["av_sentiment"]).abs()
            n_diverge  = int((df["divergence"] > 0.35).sum())
            avg_delta  = df["divergence"].mean()

        n_days         = len(df)
        total_articles = int(df.get("article_count", pd.Series(0)).sum())

        # ── Scorecard ──────────────────────────────────────────────────
        scorecard = [
            html.Div([html.Div("Trading Days",     className="sc-score-label"),
                      html.Div(str(n_days),         className="sc-score-value")], className="sc-score-cell"),
            html.Div([html.Div("Finnhub Articles",  className="sc-score-label"),
                      html.Div(f"{total_articles:,}", className="sc-score-value")], className="sc-score-cell"),
            html.Div([html.Div("Avg Divergence",    className="sc-score-label"),
                      html.Div(f"{avg_delta:.3f}" if avg_delta else "—", className="sc-score-value")], className="sc-score-cell"),
            html.Div([html.Div("High Divergence",   className="sc-score-label"),
                      html.Div(str(n_diverge),       className="sc-score-value")], className="sc-score-cell"),
        ]

        disagree_badge = (
            [html.Span(f"{n_diverge} HIGH DIVERGENCE DAYS", className="sc-disagree-badge")]
            if n_diverge > 0 else []
        )

        # ── Split chart ────────────────────────────────────────────────
        fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                            row_heights=[0.6, 0.4], vertical_spacing=0.03)

        price_df   = df.dropna(subset=["open_price", "close_price"])
        bar_colors = ["#3fb950" if c >= o else "#f85149"
                      for o, c in zip(price_df["open_price"], price_df["close_price"])]
        fig.add_trace(go.Bar(
            x=price_df["date"],
            y=price_df["close_price"] - price_df["open_price"],
            base=price_df["open_price"],
            marker_color=bar_colors,
            name="Price",
            width=43200000,
        ), row=1, col=1)

        if has_local:
            fig.add_trace(go.Scatter(
                x=df["date"], y=df["finbert_sentiment"], name=LABEL_LOCAL,
                mode="lines+markers", line=dict(color="#e6a817", width=2.5),
            ), row=2, col=1)
        if has_remote:
            fig.add_trace(go.Scatter(
                x=df["date"], y=df["av_sentiment"], name=LABEL_REMOTE,
                mode="lines+markers", line=dict(color="#22d3ee", width=1.8, dash="dot"),
            ), row=2, col=1)

        fig.add_hline(y=0, line_color="#1e2d3d", row=2, col=1)
        fig.update_layout(**PLOTLY_DARK, height=480, hovermode="x unified",
                          legend=dict(orientation="h", y=-0.12))

        # ── Correlation matrix (all loaded symbols) ────────────────────
        corr_rows = []
        symbols_to_show = symbol_list if symbol_list else [symbol]
        for sym in symbols_to_show:
            try:
                r2 = requests.get(f"{DATA_API_BASE}/timeseries/{sym}", timeout=10)
                r2.raise_for_status()
                d2 = r2.json()
                if not d2:
                    continue
                df2 = pd.DataFrame(d2)
                df2 = clean_trading_data(df2)
                if df2.empty:
                    continue
                df2["intraday_pct"] = (
                    (df2["close_price"] - df2["open_price"]) / df2["open_price"] * 100
                ).where(df2[["open_price", "close_price"]].notna().all(axis=1))
                df2["next_day_pct"] = df2["intraday_pct"].shift(-1)
                df2["lag2_pct"]     = df2["intraday_pct"].shift(-2)

                # Local sentiment correlations
                c_local_same, cls_local_same = fmt_corr(compute_corr(df2, "finbert_sentiment", "intraday_pct"))
                c_local_next, cls_local_next = fmt_corr(compute_corr(df2, "finbert_sentiment", "next_day_pct"))
                c_local_lag2, cls_local_lag2 = fmt_corr(compute_corr(df2, "finbert_sentiment", "lag2_pct"))
                # Remote sentiment correlations
                c_remote_same, cls_remote_same = fmt_corr(compute_corr(df2, "av_sentiment", "intraday_pct"))
                c_remote_next, cls_remote_next = fmt_corr(compute_corr(df2, "av_sentiment", "next_day_pct"))
                c_remote_lag2, cls_remote_lag2 = fmt_corr(compute_corr(df2, "av_sentiment", "lag2_pct"))
                n_pts = len(df2)

                corr_rows.append(html.Tr([
                    html.Td(sym, style={"color": "#fff", "fontWeight": "700"}),
                    html.Td(n_pts),
                    html.Td(html.Span(c_local_same,  className=cls_local_same)),
                    html.Td(html.Span(c_local_next,  className=cls_local_next)),
                    html.Td(html.Span(c_local_lag2,  className=cls_local_lag2)),
                    html.Td(html.Span(c_remote_same, className=cls_remote_same)),
                    html.Td(html.Span(c_remote_next, className=cls_remote_next)),
                    html.Td(html.Span(c_remote_lag2, className=cls_remote_lag2)),
                ]))
            except Exception:
                corr_rows.append(html.Tr([
                    html.Td(sym, style={"color": "#fff"}),
                    html.Td("—", colSpan=7, style={"color": "var(--text-dim)"}),
                ]))

        corr_table = html.Table([
            html.Thead(html.Tr([
                html.Th("Symbol"),
                html.Th("Days"),
                html.Th("Local × Same-day"),
                html.Th("Local × Next-day"),
                html.Th("Local × Lag-2"),
                html.Th("Remote × Same-day"),
                html.Th("Remote × Next-day"),
                html.Th("Remote × Lag-2"),
            ])),
            html.Tbody(corr_rows),
        ], className="sc-table") if corr_rows else html.Div(
            "No correlation data — fetch and load symbols first.",
            style={"color": "var(--text-dim)", "fontSize": "11px", "padding": "8px 0"},
        )

        header_meta = html.Span([
            html.Span(symbol, style={"color": "#fff", "fontWeight": "700"}),
            f" • {n_days} days • loaded {datetime.now().strftime('%H:%M:%S')}",
        ])

        return fig, scorecard, corr_table, disagree_badge, header_meta

    except Exception as e:
        print(f"Chart error for {symbol}: {e}")
        return empty

# ---------------------------------------------------------
# CALLBACKS — News feed
# ---------------------------------------------------------
@app.callback(
    Output("news-feed-container", "children"),
    Input("news-interval",        "n_intervals"),
    Input("load-btn",             "n_clicks"),
    State("active-symbol",        "data"),
    prevent_initial_call=True,
)
def update_news(_, __, symbol):
    if not symbol:
        return [html.Div("Load a chart to see headlines.",
                         style={"padding": "16px", "color": "var(--text-dim)", "fontSize": "12px"})]

    symbol = symbol.upper().strip()
    try:
        resp = requests.get(f"{DATA_API_BASE}/news/{symbol}", params={"limit": 20}, timeout=10)
        resp.raise_for_status()
        articles = resp.json()

        if not articles:
            return [html.Div("No Finnhub headlines found for this symbol yet.",
                             style={"padding": "16px", "color": "var(--text-dim)", "fontSize": "12px"})]

        items = []
        for a in articles:
            title   = a.get("title", "Untitled")
            source  = a.get("source") or "Unknown"
            url     = a.get("url")
            pub_raw = a.get("published_at", "")
            model_s = a.get("model_sentiment")

            try:
                pub_dt   = datetime.strptime(pub_raw, "%Y-%m-%dT%H:%M:%SZ")
                pub_disp = pub_dt.strftime("%b %d, %Y")
            except Exception:
                pub_disp = pub_raw[:10] if pub_raw else "—"

            headline_el = html.A(title, href=url, target="_blank") if url else html.Span(title)

            items.append(html.Div([
                html.Div(headline_el, className="sc-news-headline"),
                html.Div([
                    html.Span(f"{source} · {pub_disp}", className="sc-news-source"),
                    sentiment_tag(model_s, LABEL_LOCAL),
                ], className="sc-news-meta"),
            ], className="sc-news-item"))

        return items

    except Exception as e:
        return [html.Div(f"Error loading headlines: {e}",
                         style={"padding": "16px", "color": "var(--red)", "fontSize": "12px"})]

# ---------------------------------------------------------
# CALLBACKS — Scatter chart
# ---------------------------------------------------------
@app.callback(
    Output("scatter-chart", "figure"),
    Input("load-btn",       "n_clicks"),
    State("active-symbol",  "data"),
    prevent_initial_call=True,
)
def update_scatter(_, symbol):
    empty_fig = go.Figure().update_layout(**PLOTLY_DARK)
    if not symbol:
        return empty_fig

    symbol = symbol.upper().strip()
    try:
        resp = requests.get(f"{DATA_API_BASE}/timeseries/{symbol}", timeout=15)
        resp.raise_for_status()
        data = resp.json()
        if not data:
            return empty_fig

        df = pd.DataFrame(data)
        df = clean_trading_data(df)
        if df.empty:
            return empty_fig

        df["intraday_pct"] = ((df["close_price"] - df["open_price"]) / df["open_price"] * 100).where(
            df[["open_price", "close_price"]].notna().all(axis=1)
        )

        fig = go.Figure()
        if "finbert_sentiment" in df.columns:
            fig.add_trace(go.Scatter(
                x=df["finbert_sentiment"], y=df["intraday_pct"],
                mode="markers", name=LABEL_LOCAL,
                marker=dict(color="#e6a817", size=8, opacity=0.7),
            ))
        if "av_sentiment" in df.columns:
            fig.add_trace(go.Scatter(
                x=df["av_sentiment"], y=df["intraday_pct"],
                mode="markers", name=LABEL_REMOTE,
                marker=dict(color="#22d3ee", size=7, opacity=0.6),
            ))
        fig.update_layout(
            **PLOTLY_DARK, height=340,
            xaxis_title="Sentiment Score",
            yaxis_title="Intraday Price Change (%)",
            legend=dict(orientation="h", y=-0.2),
        )
        return fig

    except Exception as e:
        print(f"Scatter chart error: {e}")
        return empty_fig

# ---------------------------------------------------------
# CALLBACKS — Admin: gateway metrics + inventory
# ---------------------------------------------------------
@app.callback(
    Output("admin-metrics-table",  "children"),
    Output("admin-inventory-table","children"),
    Output("admin-error",          "children"),
    Input("admin-refresh-btn",     "n_clicks"),
    Input("tab-admin",             "n_clicks"),
    State("auth-token",            "data"),
    State("symbol-list",           "data"),
    prevent_initial_call=True,
)
def update_admin(_, __, token, symbol_list):
    error_msg = None

    # ── 1. Gateway metrics — filtered to login & fetch only ──────────
    metrics_block = None
    if not token:
        error_msg = "Not authenticated — cannot fetch gateway metrics."
    else:
        headers = {"Authorization": f"Bearer {token}"}
        try:
            r = requests.get(
                f"{GATEWAY_API}/admin/metrics",
                headers=headers,
                timeout=8,
            )
            if r.status_code == 401:
                error_msg = "Token rejected by gateway — try logging out and back in."
            elif r.status_code != 200:
                error_msg = f"Gateway returned HTTP {r.status_code}."
            else:
                payload    = r.json()
                generated  = payload.get("generated_at", "")
                ep_metrics = payload.get("metrics", {})

                # Filter to only login and fetch endpoints
                filtered_metrics = {
                    path: stats for path, stats in ep_metrics.items()
                    if any(key in path for key in ("/login", "/fetch"))
                }

                if not filtered_metrics:
                    metrics_block = html.Div(
                        "No login or fetch requests recorded yet.",
                        style={"color": "var(--text-dim)", "fontSize": "11px"},
                    )
                else:
                    total_calls  = sum(v.get("calls", 0)  for v in filtered_metrics.values())
                    total_errors = sum(v.get("errors", 0) for v in filtered_metrics.values())
                    all_avgs     = [v["avg_latency"] for v in filtered_metrics.values()
                                    if v.get("avg_latency") is not None and v.get("calls", 0) > 0]
                    overall_avg  = (sum(all_avgs) / len(all_avgs)) if all_avgs else None
                    error_rate   = (total_errors / total_calls * 100) if total_calls else 0.0

                    summary_cells = [
                        html.Div([html.Div("Total Calls",    className="sc-metric-label"),
                                  html.Div(f"{total_calls:,}", className="sc-metric-value")],
                                 className="sc-metric-cell"),
                        html.Div([html.Div("Total Errors",   className="sc-metric-label"),
                                  html.Div(str(total_errors), className="sc-metric-value",
                                           style={"color": "var(--red)" if total_errors else "#fff"})],
                                 className="sc-metric-cell"),
                        html.Div([html.Div("Error Rate",     className="sc-metric-label"),
                                  html.Div(f"{error_rate:.1f}%", className="sc-metric-value",
                                           style={"color": "var(--red)" if error_rate > 1 else "var(--green)"})],
                                 className="sc-metric-cell"),
                        html.Div([html.Div("Avg Latency",    className="sc-metric-label"),
                                  html.Div(f"{overall_avg*1000:.0f} ms" if overall_avg else "—",
                                           className="sc-metric-value")],
                                 className="sc-metric-cell"),
                        html.Div([html.Div("Generated At",   className="sc-metric-label"),
                                  html.Div(generated[11:19] if len(generated) >= 19 else generated,
                                           className="sc-metric-value",
                                           style={"fontSize": "14px"})],
                                 className="sc-metric-cell"),
                    ]

                    ep_rows = []
                    for path, stats in sorted(filtered_metrics.items()):
                        calls      = stats.get("calls", 0)
                        avg_ms     = stats.get("avg_latency", 0) * 1000
                        min_lat    = stats.get("min_latency")
                        min_ms     = f"{min_lat*1000:.0f}" if min_lat is not None else "—"
                        max_ms     = f"{stats.get('max_latency', 0)*1000:.0f}"
                        errs       = stats.get("errors", 0)
                        err_style  = {"color": "var(--red)"} if errs else {"color": "var(--text-dim)"}
                        ep_rows.append(html.Tr([
                            html.Td(path, style={"color": "var(--accent2)", "fontFamily": "monospace"}),
                            html.Td(f"{calls:,}"),
                            html.Td(f"{avg_ms:.0f} ms"),
                            html.Td(f"{min_ms} ms"),
                            html.Td(f"{max_ms} ms"),
                            html.Td(str(errs), style=err_style),
                        ]))

                    ep_table = html.Table([
                        html.Thead(html.Tr([
                            html.Th("Endpoint"),
                            html.Th("Calls"),
                            html.Th("Avg Latency"),
                            html.Th("Min Latency"),
                            html.Th("Max Latency"),
                            html.Th("Errors"),
                        ])),
                        html.Tbody(ep_rows),
                    ], className="sc-table", style={"marginTop": "12px"})

                    metrics_block = html.Div([
                        html.Div(summary_cells, className="sc-metrics-grid",
                                 style={"gridTemplateColumns": "repeat(5, 1fr)"}),
                        html.Div("Per-Endpoint Breakdown", className="sc-admin-section-title"),
                        ep_table,
                    ])

        except Exception as e:
            error_msg = f"Could not reach gateway metrics: {e}"

    if metrics_block is None:
        metrics_block = html.Div(
            error_msg or "Gateway metrics unavailable.",
            style={"color": "var(--text-dim)", "fontSize": "11px", "padding": "4px 0"},
        )
        error_msg = None

    # ── 2. Per-symbol data inventory ──────────────────────────────────
    inv_rows = []
    symbols_to_check = symbol_list if symbol_list else []

    for sym in symbols_to_check:
        try:
            r = requests.get(f"{DATA_API_BASE}/timeseries/{sym}", timeout=10)
            r.raise_for_status()
            raw = r.json()
            if not raw:
                inv_rows.append(html.Tr([
                    html.Td(sym, style={"color": "#fff", "fontWeight": "700"}),
                    html.Td("0"), html.Td("—"), html.Td("—"),
                    html.Td("—"), html.Td("—"),
                    html.Td(html.Span("no data", className="sc-status-err")),
                ]))
                continue
            df = pd.DataFrame(raw)
            df["date"] = pd.to_datetime(df["date"])
            n_rows     = len(df)
            date_min   = df["date"].min().strftime("%Y-%m-%d") if n_rows else "—"
            date_max   = df["date"].max().strftime("%Y-%m-%d") if n_rows else "—"
            has_local  = "✓" if "finbert_sentiment" in df.columns and df["finbert_sentiment"].notna().any() else "✗"
            has_remote = "✓" if "av_sentiment"      in df.columns and df["av_sentiment"].notna().any()      else "✗"
            n_arts     = int(df["article_count"].sum()) if "article_count" in df.columns else "—"

            try:
                rn = requests.get(f"{DATA_API_BASE}/news/{sym}", params={"limit": 1}, timeout=5)
                news_ok = html.Span("ok", className="sc-status-ok") if rn.status_code == 200 \
                          else html.Span(str(rn.status_code), className="sc-status-err")
            except Exception:
                news_ok = html.Span("err", className="sc-status-err")

            inv_rows.append(html.Tr([
                html.Td(sym, style={"color": "#fff", "fontWeight": "700"}),
                html.Td(str(n_rows)),
                html.Td(f"{date_min} → {date_max}"),
                html.Td(html.Span(has_local,  style={"color": "var(--green)" if has_local  == "✓" else "var(--red)"})),
                html.Td(html.Span(has_remote, style={"color": "var(--green)" if has_remote == "✓" else "var(--red)"})),
                html.Td(str(n_arts)),
                html.Td(news_ok),
            ]))
        except Exception as ex:
            inv_rows.append(html.Tr([
                html.Td(sym, style={"color": "#fff", "fontWeight": "700"}),
                html.Td("—", colSpan=5, style={"color": "var(--text-dim)"}),
                html.Td(html.Span(f"err: {ex}", className="sc-status-err")),
            ]))

    if inv_rows:
        inventory_block = html.Table([
            html.Thead(html.Tr([
                html.Th("Symbol"),
                html.Th("Days"),
                html.Th("Date Range"),
                html.Th("Local"),
                html.Th("Remote"),
                html.Th("Articles"),
                html.Th("News API"),
            ])),
            html.Tbody(inv_rows),
        ], className="sc-table")
    else:
        inventory_block = html.Div(
            "Add symbols and fetch data to see inventory.",
            style={"color": "var(--text-dim)", "fontSize": "11px", "padding": "4px 0"},
        )

    error_el = (
        html.Div(error_msg, className="sc-alert-banner sc-alert-danger", style={"marginBottom": "12px"})
        if error_msg else html.Div()
    )

    return metrics_block, inventory_block, error_el


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8050, debug=True)
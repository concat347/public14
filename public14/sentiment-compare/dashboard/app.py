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

DATA_API    = "http://data:8003/timeseries"
NEWS_API    = "http://gateway:8000/api/news"
GATEWAY_API = "http://gateway:8000/api"

# ─────────────────────────────────────────────
# Display labels
# DB column names (finbert_*) are never shown to the user.
# ─────────────────────────────────────────────
LABEL_LOCAL = "Local Model"
LABEL_AV    = "Alpha Vantage"

MAX_SYMBOLS = 12   # maximum chips the selector will hold

app = Dash(__name__, external_stylesheets=[dbc.themes.CYBORG])
server = app.server

# ─────────────────────────────────────────────
# Global CSS
# ─────────────────────────────────────────────
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

        /* ── Header ── */
        .sc-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 14px 28px;
            border-bottom: 1px solid var(--border);
            background: var(--bg2);
        }
        .sc-header-logo {
            font-family: 'Syne', sans-serif;
            font-weight: 800;
            font-size: 20px;
            letter-spacing: -0.5px;
            color: #fff;
        }
        .sc-header-logo span { color: var(--accent); }
        .sc-header-meta {
            font-size: 11px;
            color: var(--text-dim);
            text-align: right;
        }

        /* ── Tabs ── */
        .sc-tabs {
            display: flex;
            gap: 0;
            border-bottom: 1px solid var(--border);
            background: var(--bg2);
            padding: 0 28px;
        }
        .sc-tab {
            padding: 10px 20px;
            font-size: 11px;
            font-weight: 700;
            letter-spacing: 1.5px;
            text-transform: uppercase;
            cursor: pointer;
            color: var(--text-dim);
            border-bottom: 2px solid transparent;
            transition: all 0.15s;
        }
        .sc-tab:hover { color: var(--text); }
        .sc-tab.active { color: var(--accent); border-bottom-color: var(--accent); }

        /* ── Login panel ── */
        .sc-login-wrap {
            display: flex;
            align-items: center;
            justify-content: center;
            min-height: calc(100vh - 60px);
        }
        .sc-login-box {
            border: 1px solid var(--border2);
            background: var(--bg2);
            padding: 40px 48px;
            width: 380px;
        }
        .sc-login-title {
            font-family: 'Syne', sans-serif;
            font-size: 22px;
            font-weight: 800;
            margin-bottom: 28px;
            color: #fff;
        }
        .sc-input-label {
            font-size: 10px;
            letter-spacing: 1.5px;
            text-transform: uppercase;
            color: var(--text-dim);
            margin-bottom: 6px;
        }
        .sc-input {
            width: 100%;
            background: var(--bg3);
            border: 1px solid var(--border2);
            color: var(--text);
            font-family: 'Space Mono', monospace;
            font-size: 13px;
            padding: 9px 12px;
            outline: none;
            margin-bottom: 16px;
            transition: border-color 0.15s;
        }
        .sc-input:focus { border-color: var(--accent); }
        .sc-btn {
            background: var(--accent);
            color: #000;
            border: none;
            font-family: 'Space Mono', monospace;
            font-weight: 700;
            font-size: 12px;
            letter-spacing: 1px;
            padding: 10px 20px;
            cursor: pointer;
            transition: opacity 0.15s;
        }
        .sc-btn:hover { opacity: 0.85; }
        .sc-btn-ghost {
            background: transparent;
            color: var(--text-dim);
            border: 1px solid var(--border2);
            font-family: 'Space Mono', monospace;
            font-size: 11px;
            letter-spacing: 0.5px;
            padding: 7px 14px;
            cursor: pointer;
            transition: all 0.15s;
        }
        .sc-btn-ghost:hover { color: var(--text); border-color: var(--text-dim); }
        .sc-btn-danger {
            background: transparent;
            color: var(--red);
            border: 1px solid var(--red);
            font-family: 'Space Mono', monospace;
            font-size: 11px;
            padding: 7px 14px;
            cursor: pointer;
            transition: all 0.15s;
        }
        .sc-btn-danger:hover { background: var(--red); color: #fff; }

        /* ── Main layout ── */
        .sc-body {
            display: flex;
            height: calc(100vh - 99px);
            overflow: hidden;
        }
        .sc-sidebar {
            width: 220px;
            min-width: 220px;
            border-right: 1px solid var(--border);
            background: var(--bg2);
            padding: 20px 16px;
            display: flex;
            flex-direction: column;
            gap: 16px;
            overflow-y: auto;
        }
        .sc-main {
            flex: 1;
            overflow-y: auto;
            padding: 20px 24px;
        }

        /* ── Sidebar sections ── */
        .sc-section-label {
            font-size: 9px;
            letter-spacing: 2px;
            text-transform: uppercase;
            color: var(--text-dim);
            margin-bottom: 8px;
        }

        /* ── Symbol chip selector ── */
        .sc-chip-area {
            display: flex;
            flex-wrap: wrap;
            gap: 6px;
            margin-bottom: 8px;
            min-height: 28px;
        }
        .sc-chip {
            display: inline-flex;
            align-items: center;
            gap: 5px;
            background: var(--bg3);
            border: 1px solid var(--border2);
            color: var(--text);
            font-family: 'Space Mono', monospace;
            font-size: 11px;
            padding: 3px 8px;
            cursor: default;
        }
        .sc-chip.active {
            border-color: var(--accent);
            color: var(--accent);
        }
        .sc-chip-x {
            cursor: pointer;
            color: var(--text-dim);
            font-size: 12px;
            line-height: 1;
            margin-left: 2px;
        }
        .sc-chip-x:hover { color: var(--red); }
        .sc-chip-add-row {
            display: flex;
            gap: 6px;
        }
        .sc-chip-input {
            flex: 1;
            background: var(--bg3);
            border: 1px solid var(--border2);
            color: var(--text);
            font-family: 'Space Mono', monospace;
            font-size: 11px;
            padding: 5px 8px;
            outline: none;
            text-transform: uppercase;
            min-width: 0;
        }
        .sc-chip-input:focus { border-color: var(--accent); }
        .sc-chip-input::placeholder { color: var(--text-dim); text-transform: none; }
        .sc-add-btn {
            background: transparent;
            border: 1px solid var(--border2);
            color: var(--text-dim);
            font-family: 'Space Mono', monospace;
            font-size: 13px;
            padding: 4px 10px;
            cursor: pointer;
            transition: all 0.15s;
        }
        .sc-add-btn:hover { border-color: var(--accent); color: var(--accent); }
        .sc-cap-note {
            font-size: 9px;
            color: var(--text-dim);
            margin-top: 4px;
        }

        /* ── Scorecard strip ── */
        .sc-scorecard {
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 1px;
            background: var(--border);
            border: 1px solid var(--border);
            margin-bottom: 20px;
        }
        .sc-score-cell {
            background: var(--bg2);
            padding: 14px 16px;
        }
        .sc-score-label {
            font-size: 9px;
            letter-spacing: 1.5px;
            text-transform: uppercase;
            color: var(--text-dim);
            margin-bottom: 6px;
        }
        .sc-score-value {
            font-family: 'Syne', sans-serif;
            font-size: 22px;
            font-weight: 800;
            color: #fff;
            line-height: 1;
        }
        .sc-score-sub {
            font-size: 10px;
            color: var(--text-dim);
            margin-top: 4px;
        }

        /* ── Chart containers ── */
        .sc-chart-block {
            background: var(--bg2);
            border: 1px solid var(--border);
            margin-bottom: 16px;
            padding: 16px;
        }
        .sc-chart-title {
            font-size: 10px;
            letter-spacing: 1.5px;
            text-transform: uppercase;
            color: var(--text-dim);
            margin-bottom: 12px;
            display: flex;
            align-items: center;
            gap: 10px;
        }
        .sc-chart-title-line {
            flex: 1;
            height: 1px;
            background: var(--border);
        }

        /* ── News feed ── */
        .sc-news-feed {
            background: var(--bg2);
            border: 1px solid var(--border);
            padding: 0;
            margin-bottom: 16px;
        }
        .sc-news-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 12px 16px;
            border-bottom: 1px solid var(--border);
        }
        .sc-news-item {
            padding: 12px 16px;
            border-bottom: 1px solid var(--border);
            transition: background 0.1s;
        }
        .sc-news-item:last-child { border-bottom: none; }
        .sc-news-item:hover { background: var(--bg3); }
        .sc-news-headline {
            font-size: 12px;
            color: var(--text);
            line-height: 1.5;
            margin-bottom: 6px;
        }
        .sc-news-headline a {
            color: var(--text);
            text-decoration: none;
        }
        .sc-news-headline a:hover { color: var(--accent); }
        .sc-news-meta {
            display: flex;
            align-items: center;
            gap: 8px;
            flex-wrap: wrap;
        }
        .sc-news-source {
            font-size: 10px;
            color: var(--text-dim);
        }
        .sc-score-tag {
            font-size: 10px;
            padding: 1px 6px;
            border: 1px solid;
        }
        .sc-score-pos { border-color: var(--green); color: var(--green); }
        .sc-score-neg { border-color: var(--red);   color: var(--red);   }
        .sc-score-neu { border-color: var(--text-dim); color: var(--text-dim); }
        .sc-live-dot {
            width: 6px;
            height: 6px;
            border-radius: 50%;
            background: var(--green);
            display: inline-block;
            margin-right: 4px;
        }

        /* ── Scatter + correlation grid ── */
        .sc-scatter-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 16px;
            margin-bottom: 16px;
        }

        /* ── Correlation table ── */
        .sc-corr-table {
            width: 100%;
            border-collapse: collapse;
        }
        .sc-corr-table th {
            font-size: 9px;
            letter-spacing: 1.5px;
            text-transform: uppercase;
            color: var(--text-dim);
            padding: 6px 10px;
            border-bottom: 1px solid var(--border);
            text-align: left;
        }
        .sc-corr-table td {
            padding: 8px 10px;
            border-bottom: 1px solid var(--border);
            font-size: 13px;
        }
        .sc-corr-table tr:last-child td { border-bottom: none; }
        .corr-pos { color: var(--green); }
        .corr-neg { color: var(--red); }
        .corr-na  { color: var(--text-dim); }

        /* ── Alert ── */
        .sc-alert {
            padding: 10px 14px;
            font-size: 12px;
            border-left: 3px solid var(--accent);
            background: rgba(230,168,23,0.08);
            color: var(--text);
            margin-top: 8px;
        }
        .sc-alert-danger  { border-left-color: var(--red);   background: rgba(248,81,73,0.08); }
        .sc-alert-success { border-left-color: var(--green); background: rgba(63,185,80,0.08); }

        /* ── Admin table ── */
        .sc-admin-table {
            width: 100%;
            border-collapse: collapse;
        }
        .sc-admin-table th {
            font-size: 9px;
            letter-spacing: 1.5px;
            text-transform: uppercase;
            color: var(--text-dim);
            padding: 8px 12px;
            border-bottom: 1px solid var(--border);
            text-align: left;
        }
        .sc-admin-table td {
            padding: 9px 12px;
            border-bottom: 1px solid var(--border);
            font-size: 12px;
        }
        .sc-admin-table tr:hover td { background: var(--bg3); }
        .sc-admin-table tr:last-child td { border-bottom: none; }

        /* ── Legend pills ── */
        .sc-legend {
            display: flex;
            gap: 16px;
            font-size: 10px;
            color: var(--text-dim);
            margin-bottom: 10px;
            flex-wrap: wrap;
        }
        .sc-legend-item { display: flex; align-items: center; gap: 5px; }
        .sc-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }

        /* ── Disagreement badge ── */
        .sc-disagree-badge {
            display: inline-block;
            background: rgba(188,140,255,0.15);
            border: 1px solid var(--purple);
            color: var(--purple);
            font-size: 9px;
            letter-spacing: 1px;
            text-transform: uppercase;
            padding: 2px 7px;
            margin-left: 8px;
        }

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

# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def clean_trading_data(df, open_col, close_col, vol_col):
    trading_days = sorted(df.loc[df[close_col].notna(), "date"].tolist())
    if not trading_days:
        return df.dropna(subset=["finbert_sentiment"]).sort_values("date").reset_index(drop=True)

    def next_trading_day(d):
        future = [t for t in trading_days if t >= d]
        return future[0] if future else None

    df["trading_date"] = df["date"].apply(next_trading_day)
    df["trading_date"] = df.apply(
        lambda row: row["trading_date"] if pd.notna(row["trading_date"]) else row["date"], axis=1
    )

    agg_dict = {}
    for col in [open_col, close_col, vol_col]:
        if col in df.columns:
            agg_dict[col] = (col, "first")
    for col in ["finbert_sentiment", "av_sentiment"]:
        if col in df.columns:
            agg_dict[col] = (col, "mean")
    for col in ["finbert_confidence", "finbert_explanation"]:
        if col in df.columns:
            agg_dict[col] = (col, "last")
    if "article_count" in df.columns:
        agg_dict["article_count"] = ("article_count", "sum")

    df = (
        df.groupby("trading_date").agg(**agg_dict)
        .reset_index().rename(columns={"trading_date": "date"})
    )
    df = df.dropna(subset=["finbert_sentiment"])
    return df.sort_values("date").reset_index(drop=True)


def fmt_corr(v):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "N/A", "corr-na"
    s   = f"{v:+.3f}"
    cls = "corr-pos" if v > 0.05 else ("corr-neg" if v < -0.05 else "corr-na")
    return s, cls


def compute_corr(df, col, lag_col):
    valid = df[[col, lag_col]].dropna()
    if len(valid) >= 5:
        return valid[col].corr(valid[lag_col])
    return None


def sentiment_tag(score, label_prefix):
    """Return a styled span for a sentiment score."""
    if score is None:
        return html.Span(f"{label_prefix} —", className="sc-score-tag sc-score-neu")
    cls = "sc-score-pos" if score >= 0.05 else ("sc-score-neg" if score <= -0.05 else "sc-score-neu")
    sign = "+" if score > 0 else ""
    return html.Span(f"{label_prefix} {sign}{score:.2f}", className=f"sc-score-tag {cls}")


PLOTLY_DARK = dict(
    template="plotly_dark",
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    font=dict(family="Space Mono, monospace", size=11, color="#586069"),
    margin=dict(l=10, r=10, t=10, b=10),
)

AXIS_STYLE = dict(gridcolor="#1e2d3d", linecolor="#1e2d3d", zerolinecolor="#1e2d3d")


# ─────────────────────────────────────────────
# Layout
# ─────────────────────────────────────────────

app.layout = html.Div([
    dcc.Store(id="auth-token"),
    dcc.Store(id="active-tab",   data="analysis"),
    # Stores the list of symbols currently in the chip selector.
    dcc.Store(id="symbol-list",  data=[]),
    # Stores which chip is the active/selected one for chart loading.
    dcc.Store(id="active-symbol", data=None),
    # Interval for news feed polling (30 seconds).
    dcc.Interval(id="news-interval", interval=30_000, n_intervals=0, disabled=True),

    # ── Header ──
    html.Div([
        html.Div([
            html.Span("Sentiment",   className="sc-header-logo"),
            html.Span("Compare",     className="sc-header-logo", style={"color": "var(--accent)"}),
        ], style={"display": "flex"}),
        html.Div(id="header-meta", className="sc-header-meta"),
    ], className="sc-header"),

    # ── LOGIN VIEW ──
    html.Div(
        id="login-view",
        className="sc-login-wrap",
        children=[
            html.Div([
                html.Div("Sign In", className="sc-login-title"),
                dbc.Alert(id="login-message", color="danger", is_open=False, className="mb-3",
                          style={"fontSize": "12px", "fontFamily": "Space Mono, monospace"}),
                html.Div("Username", className="sc-input-label"),
                dcc.Input(id="login-username", type="text",     value="", className="sc-input"),
                html.Div("Password", className="sc-input-label"),
                dcc.Input(id="login-password", type="password", value="", className="sc-input"),
                html.Button("AUTHENTICATE", id="login-button", className="sc-btn",
                            style={"width": "100%"}),
            ], className="sc-login-box")
        ]
    ),

    # ── MAIN VIEW ──
    html.Div(
        id="main-view",
        style={"display": "none"},
        children=[
            # Tabs
            html.Div([
                html.Div("Analysis", id="tab-analysis", className="sc-tab active", n_clicks=0),
                html.Div("Admin",    id="tab-admin",    className="sc-tab",        n_clicks=0),
            ], className="sc-tabs"),

            html.Div(className="sc-body", children=[

                # ── Sidebar ──
                html.Div(className="sc-sidebar", children=[

                    # Symbol chip selector
                    html.Div([
                        html.Div("Symbols", className="sc-section-label"),
                        html.Div(id="chip-area", className="sc-chip-area"),
                        html.Div([
                            dcc.Input(
                                id="symbol-add-input",
                                type="text",
                                placeholder="e.g. AAPL",
                                maxLength=6,
                                className="sc-chip-input",
                                debounce=False,
                                n_submit=0,
                            ),
                            html.Button("+", id="symbol-add-btn", className="sc-add-btn",
                                        n_clicks=0),
                        ], className="sc-chip-add-row"),
                        html.Div(f"Max {MAX_SYMBOLS} symbols", className="sc-cap-note"),
                    ]),

                    html.Div([
                        html.Div("History Days", className="sc-section-label"),
                        dcc.Input(id="days-input", type="number", value=7, min=1, max=365,
                                  className="sc-input", style={"marginBottom": "0"}),
                    ]),

                    html.Button("FETCH DATA",  id="fetch-button", className="sc-btn",
                                style={"width": "100%"}),
                    html.Button("LOAD CHART",  id="load-btn",     className="sc-btn-ghost",
                                style={"width": "100%"}),
                    html.Div(id="fetch-message"),
                    html.Div(style={"flex": "1"}),
                    html.Button("LOGOUT", id="logout-button", className="sc-btn-danger",
                                style={"width": "100%"}),
                ]),

                # ── Main content ──
                html.Div(className="sc-main", children=[

                    # ── ANALYSIS TAB ──
                    html.Div(id="panel-analysis", children=[

                        # Scorecard row
                        html.Div(id="scorecard-strip", className="sc-scorecard"),

                        # Split chart: price + sentiment
                        html.Div(className="sc-chart-block", children=[
                            html.Div([
                                "Price & Sentiment",
                                html.Div(className="sc-chart-title-line"),
                                html.Div(id="disagree-badge"),
                            ], className="sc-chart-title"),
                            html.Div(className="sc-legend", children=[
                                html.Div([html.Div(style={"width":"12px","height":"6px","background":"#3fb950"}, className="sc-dot"), "Up day"],        className="sc-legend-item"),
                                html.Div([html.Div(style={"width":"12px","height":"6px","background":"#f85149"}, className="sc-dot"), "Down day"],      className="sc-legend-item"),
                                html.Div([html.Div(style={"background":"#e6a817"}, className="sc-dot"), LABEL_LOCAL],                                   className="sc-legend-item"),
                                html.Div([html.Div(style={"background":"#22d3ee"}, className="sc-dot"), LABEL_AV],                                      className="sc-legend-item"),
                                html.Div([html.Div(style={"background":"#bc8cff"}, className="sc-dot"), "High divergence"],                             className="sc-legend-item"),
                            ]),
                            dcc.Loading(dcc.Graph(id="split-chart", config={"displayModeBar": False})),
                        ]),

                        # Scatter matrix: both models × 3 lags
                        html.Div(className="sc-chart-block", children=[
                            html.Div([
                                "Sentiment vs. Price Change — Model × Lag Comparison",
                                html.Div(className="sc-chart-title-line"),
                            ], className="sc-chart-title"),
                            dcc.Loading(dcc.Graph(id="scatter-chart",
                                                  config={"displayModeBar": False},
                                                  style={"height": "340px"})),
                        ]),

                        # Live news feed
                        html.Div(className="sc-news-feed", children=[
                            html.Div([
                                html.Span([
                                    html.Span(className="sc-live-dot"),
                                    "Latest headlines",
                                ], style={"fontSize": "10px", "letterSpacing": "1.5px",
                                          "textTransform": "uppercase", "color": "var(--text-dim)"}),
                                html.Span("refreshes every 30s",
                                          style={"fontSize": "10px", "color": "var(--text-dim)"}),
                            ], className="sc-news-header"),
                            dcc.Loading(
                                html.Div(id="news-feed-container",
                                         children=[
                                             html.Div("Load a chart to see headlines.",
                                                      style={"padding": "16px",
                                                             "color": "var(--text-dim)",
                                                             "fontSize": "12px"})
                                         ]),
                            ),
                        ]),
                    ]),

                    # ── ADMIN TAB ──
                    html.Div(id="panel-admin", style={"display": "none"}, children=[

                        # Correlation table
                        html.Div(className="sc-chart-block", children=[
                            html.Div(["Correlation Matrix",
                                      html.Div(className="sc-chart-title-line")],
                                     className="sc-chart-title"),
                            html.Div(id="corr-table-container"),
                        ]),

                        # Gateway metrics
                        html.Div(className="sc-chart-block", style={"marginTop": "16px"}, children=[
                            html.Div([
                                "Gateway Metrics",
                                html.Div(className="sc-chart-title-line"),
                                html.Button("↻ REFRESH", id="admin-refresh-btn",
                                            className="sc-btn-ghost",
                                            style={"fontSize": "10px", "padding": "4px 10px"}),
                            ], className="sc-chart-title"),
                            html.Div(id="admin-error"),
                            html.Div(id="admin-metrics-table"),
                        ]),
                    ]),
                ]),
            ]),
        ]
    ),
])


# ─────────────────────────────────────────────
# Callbacks
# ─────────────────────────────────────────────

# Auth visibility
@app.callback(
    Output("login-view", "style"),
    Output("main-view",  "style"),
    Input("auth-token",  "data"),
)
def toggle_views(token):
    if token:
        return {"display": "none"}, {"display": "block"}
    return (
        {"display": "flex", "alignItems": "center", "justifyContent": "center",
         "minHeight": "calc(100vh - 60px)"},
        {"display": "none"},
    )


# Login
@app.callback(
    Output("auth-token",      "data"),
    Output("login-message",   "children"),
    Output("login-message",   "is_open"),
    Input("login-button",     "n_clicks"),
    State("login-username",   "value"),
    State("login-password",   "value"),
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
        if not token:
            return None, "Login failed: no token returned.", True
        return token, "", False
    except Exception as e:
        return None, f"Connection error: {e}", True


# Logout
@app.callback(
    Output("auth-token", "clear_data"),
    Input("logout-button", "n_clicks"),
    prevent_initial_call=True,
)
def handle_logout(_):
    return True


# ── Symbol chip management ──
# Handles: add via button click, add via Enter key in input,
# remove via × click (passed as chip index in a hidden pattern).
@app.callback(
    Output("symbol-list",      "data"),
    Output("active-symbol",    "data"),
    Output("symbol-add-input", "value"),
    Input("symbol-add-btn",    "n_clicks"),
    Input("symbol-add-input",  "n_submit"),
    Input({"type": "chip-remove", "index": ALL}, "n_clicks"),
    Input({"type": "chip-select", "index": ALL}, "n_clicks"),
    State("symbol-add-input",  "value"),
    State("symbol-list",       "data"),
    State("active-symbol",     "data"),
    prevent_initial_call=True,
)
def manage_chips(add_clicks, add_submit, remove_clicks, select_clicks,
                 input_val, symbol_list, active_symbol):
    triggered = ctx.triggered_id

    # Remove chip
    if isinstance(triggered, dict) and triggered.get("type") == "chip-remove":
        idx = triggered["index"]
        new_list = [s for s in symbol_list if s != idx]
        new_active = active_symbol if active_symbol in new_list else (new_list[0] if new_list else None)
        return new_list, new_active, ""

    # Select chip (make active for chart loading)
    if isinstance(triggered, dict) and triggered.get("type") == "chip-select":
        return symbol_list, triggered["index"], ""

    # Add chip
    if triggered in ("symbol-add-btn", "symbol-add-input"):
        raw = (input_val or "").strip().upper()
        if not raw:
            return symbol_list, active_symbol, ""
        if raw in symbol_list:
            return symbol_list, raw, ""          # just activate it
        if len(symbol_list) >= MAX_SYMBOLS:
            return symbol_list, active_symbol, ""
        new_list = symbol_list + [raw]
        return new_list, raw, ""

    return symbol_list, active_symbol, ""


# Render chip area from symbol-list store
@app.callback(
    Output("chip-area", "children"),
    Input("symbol-list",   "data"),
    Input("active-symbol", "data"),
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
                html.Span(
                    sym,
                    id={"type": "chip-select", "index": sym},
                    style={"cursor": "pointer"},
                ),
                html.Span(
                    "×",
                    id={"type": "chip-remove", "index": sym},
                    className="sc-chip-x",
                ),
            ], className=f"sc-chip{'  active' if is_active else ''}")
        )
    return chips


# Tab switching
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


# Fetch data
@app.callback(
    Output("fetch-message",    "children"),
    Output("symbol-list",      "data", allow_duplicate=True),
    Output("active-symbol",    "data", allow_duplicate=True),
    Output("symbol-add-input", "value", allow_duplicate=True),
    Input("fetch-button",      "n_clicks"),
    State("auth-token",        "data"),
    State("symbol-list",       "data"),
    State("symbol-add-input",  "value"),
    State("days-input",        "value"),
    prevent_initial_call=True,
)
def fetch_data(_, token, symbol_list, input_val, days):
    ts = datetime.now().strftime("%H:%M:%S")

    # Auto-add whatever is typed in the input box (common UX shortcut)
    pending = (input_val or "").strip().upper()
    if pending and pending not in symbol_list and len(symbol_list) < MAX_SYMBOLS:
        symbol_list = symbol_list + [pending]
        active = pending
        clear_input = ""
    else:
        active = symbol_list[0] if symbol_list else None
        clear_input = input_val

    if not token:
        return html.Div(f"[{ts}] Not authenticated.", className="sc-alert sc-alert-danger"), symbol_list, active, clear_input
    if not symbol_list:
        return html.Div(f"[{ts}] Add at least one symbol.", className="sc-alert sc-alert-danger"), symbol_list, active, clear_input
    try:
        resp = requests.post(
            f"{GATEWAY_API}/fetch",
            json={"symbols": symbol_list, "days": int(days or 30)},
            headers={"Authorization": f"Bearer {token}"},
            timeout=max(120, len(symbol_list) * 60),
        )
        if resp.status_code == 401:
            return html.Div(f"[{ts}] Session expired.", className="sc-alert sc-alert-danger"), symbol_list, active, clear_input
        if resp.status_code != 200:
            return html.Div(f"[{ts}] Fetch failed: {resp.text}", className="sc-alert sc-alert-danger"), symbol_list, active, clear_input
        n = resp.json().get("messages_sent", "?")
        return (
            html.Div(f"[{ts}] OK — {n} messages queued. Click LOAD CHART.",
                     className="sc-alert sc-alert-success"),
            symbol_list, active, "",
        )
    except Exception as e:
        return html.Div(f"[{ts}] Error: {e}", className="sc-alert sc-alert-danger"), symbol_list, active, clear_input



# Enable/disable news interval based on whether a symbol is active
@app.callback(
    Output("news-interval", "disabled"),
    Input("active-symbol",  "data"),
)
def toggle_news_interval(active_symbol):
    return active_symbol is None


# ── Main chart callback ──
# Fires when LOAD CHART is clicked.  Produces the split price/sentiment
# chart, scorecard, correlation table, and divergence badge.
# The scatter chart is rendered separately by load_admin_scatter().
@app.callback(
    Output("split-chart",          "figure"),
    Output("scorecard-strip",      "children"),
    Output("corr-table-container", "children"),
    Output("disagree-badge",       "children"),
    Output("header-meta",          "children"),
    Input("load-btn",              "n_clicks"),
    State("active-symbol",         "data"),
    prevent_initial_call=True,
)
def update_charts(_, symbol):
    empty_fig = go.Figure()
    empty_fig.update_layout(**PLOTLY_DARK)
    empty = (empty_fig, [], html.Div(), [], "")

    if not symbol:
        return empty

    symbol = symbol.strip().upper()

    try:
        resp = requests.get(f"{DATA_API}/{symbol}", timeout=10)
        if resp.status_code != 200:
            return empty

        data    = resp.json()
        results = data["results"] if isinstance(data, dict) and "results" in data else data
        if not results:
            return empty

        df = pd.DataFrame(results)
        if "date" not in df.columns:
            return empty

        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)

        open_col  = "open_price"
        close_col = "close_price" if "close_price" in df.columns else "close"
        vol_col   = "volume"

        df = clean_trading_data(df, open_col, close_col, vol_col)
        if df.empty:
            return empty

        df["intraday_pct"] = (
            (df[close_col] - df[open_col]) / df[open_col] * 100
        ).where(df[open_col].notna() & df[close_col].notna())
        df["next_day_pct"] = df["intraday_pct"].shift(-1)
        df["lag2_pct"]     = df["intraday_pct"].shift(-2)

        has_local = "finbert_sentiment" in df.columns and df["finbert_sentiment"].notna().any()
        has_av    = "av_sentiment"       in df.columns and df["av_sentiment"].notna().any()

        if has_local and has_av:
            df["divergence"]   = (df["finbert_sentiment"] - df["av_sentiment"]).abs()
            df["high_diverge"] = df["divergence"] > 0.35
        else:
            df["divergence"]   = np.nan
            df["high_diverge"] = False

        n_diverge = int(df["high_diverge"].sum())

        # Scorecard
        total_articles = int(df["article_count"].sum()) if "article_count" in df.columns else 0
        n_days = len(df)

        best_lag, best_val = "—", 0.0
        if has_local:
            for lag, col in [("Same-day", "intraday_pct"), ("+1 Day", "next_day_pct"), ("+2 Days", "lag2_pct")]:
                v = compute_corr(df, "finbert_sentiment", col)
                if v is not None and abs(v) > abs(best_val):
                    best_lag, best_val = lag, v

        agree_rate = "—"
        if has_local and has_av:
            valid = df[["finbert_sentiment", "av_sentiment"]].dropna()
            if len(valid) > 0:
                same_sign  = ((valid["finbert_sentiment"] > 0) == (valid["av_sentiment"] > 0)).mean()
                agree_rate = f"{same_sign:.0%}"

        def score_cell(label, value, sub=""):
            return html.Div([
                html.Div(label, className="sc-score-label"),
                html.Div(value, className="sc-score-value"),
                html.Div(sub,   className="sc-score-sub"),
            ], className="sc-score-cell")

        scorecard = [
            score_cell("Trading Days",    str(n_days),                        "in dataset"),
            score_cell("Articles Scored", f"{total_articles:,}" if total_articles else "—", "total received"),
            score_cell("Best Lag",        best_lag,                           f"r = {best_val:+.3f}" if best_val != 0.0 else "—"),
            score_cell("Model Agreement", agree_rate,                         "same direction"),
        ]

        disagree_badge = []
        if n_diverge > 0:
            disagree_badge = [
                html.Span(
                    f"{n_diverge} HIGH DIVERGENCE DAY{'S' if n_diverge != 1 else ''}",
                    className="sc-disagree-badge",
                )
            ]

        # Split chart
        fig = make_subplots(
            rows=2, cols=1,
            shared_xaxes=True,
            row_heights=[0.6, 0.4],
            vertical_spacing=0.03,
        )

        price_df    = df.dropna(subset=[open_col, close_col])
        bar_colors  = [
            "rgba(63,185,80,0.9)" if c >= o else "rgba(248,81,73,0.9)"
            for o, c in zip(price_df[open_col], price_df[close_col])
        ]
        hover_price = [
            f"<b>{r['date'].strftime('%Y-%m-%d')}</b><br>"
            f"Open: ${r[open_col]:.2f}  Close: ${r[close_col]:.2f}<br>"
            f"Intraday: {r['intraday_pct']:+.2f}%<br>"
            f"Articles: {int(r['article_count']) if pd.notna(r.get('article_count')) else 'N/A'}"
            for _, r in price_df.iterrows()
        ]
        fig.add_trace(go.Bar(
            x=price_df["date"],
            y=price_df[close_col] - price_df[open_col],
            base=price_df[open_col],
            marker_color=bar_colors,
            marker_line_width=0,
            width=43200000,
            name="Price",
            hovertext=hover_price,
            hoverinfo="text",
            showlegend=False,
        ), row=1, col=1)

        div_df = df[df["high_diverge"] == True]
        if not div_df.empty and close_col in div_df.columns:
            fig.add_trace(go.Scatter(
                x=div_df["date"],
                y=div_df[close_col] * 1.005,
                mode="markers",
                marker=dict(symbol="triangle-down", size=8, color="#bc8cff"),
                name="High Divergence",
                hovertemplate="<b>%{x|%Y-%m-%d}</b><br>Divergence > 0.35<extra></extra>",
            ), row=1, col=1)

        if has_local:
            hover_sent = [
                f"<b>{r['date'].strftime('%Y-%m-%d')}</b><br>"
                f"{LABEL_LOCAL}: {r['finbert_sentiment']:+.4f}<br>"
                f"Confidence: {r['finbert_confidence']:.2%}<br>"
                f"Signal: {r.get('finbert_explanation', '—')}"
                for _, r in df.iterrows()
            ]
            fig.add_trace(go.Scatter(
                x=df["date"], y=df["finbert_sentiment"],
                name=LABEL_LOCAL,
                mode="lines+markers",
                line=dict(color="#e6a817", width=2),
                marker=dict(size=4),
                hovertext=hover_sent, hoverinfo="text",
            ), row=2, col=1)

        if has_av:
            fig.add_trace(go.Scatter(
                x=df["date"], y=df["av_sentiment"],
                name=LABEL_AV,
                mode="lines+markers",
                line=dict(color="#22d3ee", width=1.5, dash="dot"),
                marker=dict(size=3),
                hoverinfo="skip",
            ), row=2, col=1)

        fig.add_hline(y=0, line_color="#1e2d3d", line_width=1, row=2, col=1)
        fig.update_layout(
            **PLOTLY_DARK,
            height=480,
            hovermode="x unified",
            legend=dict(orientation="h", y=-0.08, font=dict(size=10)),
            bargap=0,
        )
        fig.update_yaxes(title_text="Price (USD)", row=1, col=1, **AXIS_STYLE, tickfont=dict(size=10))
        fig.update_yaxes(title_text="Sentiment",   row=2, col=1, range=[-1, 1], **AXIS_STYLE, tickfont=dict(size=10))
        fig.update_xaxes(**AXIS_STYLE, tickfont=dict(size=10))

        # Correlation table
        sentiment_cols = []
        if has_local:
            sentiment_cols.append(("finbert_sentiment", LABEL_LOCAL, "#e6a817"))
        if has_av:
            sentiment_cols.append(("av_sentiment",      LABEL_AV,    "#22d3ee"))

        rows_corr = []
        for col, label, color in sentiment_cols:
            for lag_label, lag_col in [
                ("Same-day", "intraday_pct"),
                ("+1 Day",   "next_day_pct"),
                ("+2 Days",  "lag2_pct"),
            ]:
                v = compute_corr(df, col, lag_col)
                val_str, cls = fmt_corr(v)
                rows_corr.append(html.Tr([
                    html.Td(label, style={"color": color}),
                    html.Td(lag_label),
                    html.Td(val_str, className=cls,
                            style={"textAlign": "right", "fontWeight": "700"}),
                ]))

        corr_table = html.Div([
            html.Table([
                html.Thead(html.Tr([
                    html.Th("Model"),
                    html.Th("Lag"),
                    html.Th("Pearson r", style={"textAlign": "right"}),
                ])),
                html.Tbody(rows_corr),
            ], className="sc-corr-table"),
            html.P(
                "Correlation between sentiment and intraday open→close % change. Requires ≥5 days.",
                style={"fontSize": "10px", "color": "var(--text-dim)", "marginTop": "10px"},
            ),
        ]) if rows_corr else html.P(
            "Insufficient data.",
            style={"color": "var(--text-dim)", "fontSize": "12px"},
        )

        header_meta = html.Span([
            html.Span(symbol, style={"color": "#fff", "fontWeight": "700"}),
            f"  ·  {n_days} days  ·  loaded {datetime.now().strftime('%H:%M:%S')}",
        ])

        return fig, scorecard, corr_table, disagree_badge, header_meta

    except Exception:
        import traceback; traceback.print_exc()
        return empty


# ── Scatter chart — lives in Analysis tab ──
# 3-panel layout built with explicit domain-based axes (no make_subplots)
# to avoid trace-routing ambiguity. Each panel shares the same X scale
# (-1..1 sentiment) but has its own Y axis (price Δ% for each lag).
@app.callback(
    Output("scatter-chart", "figure"),
    Input("load-btn",       "n_clicks"),
    State("active-symbol",  "data"),
    prevent_initial_call=True,
)
def load_scatter(_, symbol):
    empty_fig = go.Figure()
    empty_fig.update_layout(paper_bgcolor="rgba(0,0,0,0)",
                             plot_bgcolor="rgba(0,0,0,0)")

    if not symbol:
        return empty_fig

    symbol = symbol.strip().upper()

    try:
        resp = requests.get(f"{DATA_API}/{symbol}", timeout=10)
        if resp.status_code != 200:
            return empty_fig

        data    = resp.json()
        results = data["results"] if isinstance(data, dict) and "results" in data else data
        if not results:
            return empty_fig

        df = pd.DataFrame(results)
        if "date" not in df.columns:
            return empty_fig

        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)

        open_col  = "open_price"
        close_col = "close_price" if "close_price" in df.columns else "close"
        vol_col   = "volume"

        df = clean_trading_data(df, open_col, close_col, vol_col)
        if df.empty:
            return empty_fig

        df["intraday_pct"] = (
            (df[close_col] - df[open_col]) / df[open_col] * 100
        ).where(df[open_col].notna() & df[close_col].notna())
        df["next_day_pct"] = df["intraday_pct"].shift(-1)
        df["lag2_pct"]     = df["intraday_pct"].shift(-2)

        has_local = "finbert_sentiment" in df.columns and df["finbert_sentiment"].notna().any()
        has_av    = "av_sentiment"       in df.columns and df["av_sentiment"].notna().any()

        lag_configs = [
            ("Same-Day", "intraday_pct"),
            ("+1 Day",   "next_day_pct"),
            ("+2 Days",  "lag2_pct"),
        ]

        models = []
        if has_local:
            models.append(("finbert_sentiment", LABEL_LOCAL, "#e6a817"))
        if has_av:
            models.append(("av_sentiment", LABEL_AV, "#22d3ee"))

        def hex_to_rgba(h, alpha):
            h = h.lstrip("#")
            rv, gv, bv = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
            return f"rgba({rv},{gv},{bv},{alpha})"

        # Domain boundaries for 3 side-by-side panels with gaps
        # [x_start, x_end] for each panel in normalised figure coordinates
        panel_x = [(0.00, 0.30), (0.35, 0.65), (0.70, 1.00)]

        # Axis suffix: panel 0 → "xaxis"/"yaxis", panel 1 → "xaxis2"/"yaxis2", etc.
        def ax(n, prefix):
            return prefix if n == 0 else f"{prefix}{n + 1}"

        axis_style = dict(
            gridcolor="#1e2d3d",
            linecolor="#1e2d3d",
            zerolinecolor="#243447",
            zerolinewidth=1,
            tickfont=dict(size=9, color="#586069"),
            title_font=dict(size=9, color="#586069"),
            range=[-1, 1],
        )

        fig = go.Figure()
        legend_added = set()

        for panel_idx, (lag_label, lag_col) in enumerate(lag_configs):
            x0, x1 = panel_x[panel_idx]
            xaxis_key = ax(panel_idx, "xaxis")
            yaxis_key = ax(panel_idx, "yaxis")
            xref = ax(panel_idx, "x")
            yref = ax(panel_idx, "y")

            for sent_col, model_label, color in models:
                sub = df[[sent_col, lag_col, "date"]].dropna(subset=[sent_col, lag_col])
                if sub.empty:
                    continue

                show_in_legend = model_label not in legend_added
                legend_added.add(model_label)

                fig.add_trace(go.Scatter(
                    x=sub[sent_col],
                    y=sub[lag_col],
                    mode="markers",
                    name=model_label,
                    xaxis=xref,
                    yaxis=yref,
                    marker=dict(
                        color=color,
                        size=7,
                        opacity=0.75,
                        line=dict(color="rgba(0,0,0,0.25)", width=1),
                    ),
                    hovertemplate=(
                        f"<b>%{{customdata}}</b><br>"
                        f"{model_label}: %{{x:+.3f}}<br>"
                        f"{lag_label}: %{{y:+.2f}}%<extra></extra>"
                    ),
                    customdata=sub["date"].dt.strftime("%Y-%m-%d"),
                    showlegend=show_in_legend,
                    legendgroup=model_label,
                ))

                if len(sub) >= 3:
                    xs = sub[sent_col].values
                    ys = sub[lag_col].values
                    slope, intercept = np.polyfit(xs, ys, 1)
                    xr = np.linspace(-1, 1, 50)
                    fig.add_trace(go.Scatter(
                        x=xr,
                        y=slope * xr + intercept,
                        mode="lines",
                        xaxis=xref,
                        yaxis=yref,
                        line=dict(color=hex_to_rgba(color, 0.35), width=1.5, dash="dash"),
                        showlegend=False,
                        hoverinfo="skip",
                        legendgroup=model_label,
                    ))

            # Per-panel axis config
            yaxis_cfg = dict(
                **{k: v for k, v in axis_style.items() if k != "range"},
                title_text="Price Δ%",
                domain=[0.0, 1.0],
                anchor=xref,
            )
            xaxis_cfg = dict(
                **axis_style,
                title_text="Sentiment",
                domain=[x0, x1],
                anchor=yref,
            )

            # Subplot title as annotation
            fig.add_annotation(
                text=lag_label,
                xref="paper", yref="paper",
                x=(x0 + x1) / 2, y=1.04,
                showarrow=False,
                font=dict(size=10, color="#586069", family="Space Mono, monospace"),
                xanchor="center", yanchor="bottom",
            )

            fig.layout[xaxis_key] = xaxis_cfg
            fig.layout[yaxis_key] = yaxis_cfg

        fig.update_layout(
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font=dict(family="Space Mono, monospace", size=11, color="#586069"),
            height=340,
            margin=dict(l=40, r=10, t=36, b=48),
            legend=dict(
                orientation="h",
                y=-0.18,
                font=dict(size=10),
                itemsizing="constant",
            ),
            hovermode="closest",
        )
        return fig

    except Exception:
        import traceback; traceback.print_exc()
        return empty_fig


# ── Live news feed ──
# Fires on interval tick or when LOAD CHART is clicked.
@app.callback(
    Output("news-feed-container", "children"),
    Input("news-interval",        "n_intervals"),
    Input("load-btn",             "n_clicks"),
    State("active-symbol",        "data"),
    State("auth-token",           "data"),
    prevent_initial_call=True,
)
def update_news(_, __, symbol, token):
    if not symbol or not token:
        return [html.Div("Load a chart to see headlines.",
                         style={"padding": "16px", "color": "var(--text-dim)", "fontSize": "12px"})]

    symbol = symbol.strip().upper()

    try:
        resp = requests.get(
            f"{NEWS_API}/{symbol}",
            params={"limit": 20},
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        if resp.status_code != 200:
            return [html.Div(f"Could not load headlines (HTTP {resp.status_code}).",
                             style={"padding": "16px", "color": "var(--red)", "fontSize": "12px"})]

        articles = resp.json()
        if not articles:
            return [html.Div("No headlines found for this symbol yet.",
                             style={"padding": "16px", "color": "var(--text-dim)", "fontSize": "12px"})]

        items = []
        for a in articles:
            title    = a.get("title", "Untitled")
            source   = a.get("source") or "Unknown"
            url      = a.get("url")
            pub_raw  = a.get("published_at", "")
            model_s  = a.get("model_sentiment")
            av_s     = a.get("av_sentiment")

            # Format timestamp
            try:
                pub_dt   = datetime.strptime(pub_raw, "%Y-%m-%dT%H:%M:%SZ")
                pub_disp = pub_dt.strftime("%b %d, %Y")
            except Exception:
                pub_disp = pub_raw[:10] if pub_raw else "—"

            headline_el = (
                html.A(title, href=url, target="_blank") if url
                else html.Span(title)
            )

            items.append(
                html.Div([
                    html.Div(headline_el, className="sc-news-headline"),
                    html.Div([
                        html.Span(f"{source} · {pub_disp}", className="sc-news-source"),
                        sentiment_tag(model_s, LABEL_LOCAL),
                        sentiment_tag(av_s,    LABEL_AV),
                    ], className="sc-news-meta"),
                ], className="sc-news-item")
            )

        return items

    except Exception as e:
        return [html.Div(f"Error loading headlines: {e}",
                         style={"padding": "16px", "color": "var(--red)", "fontSize": "12px"})]


# ── Admin metrics ──
@app.callback(
    Output("admin-metrics-table", "children"),
    Output("admin-error",         "children"),
    Input("tab-admin",            "n_clicks"),
    Input("admin-refresh-btn",    "n_clicks"),
    State("auth-token",           "data"),
    prevent_initial_call=True,
)
def load_admin_metrics(_, __, token):
    if not token:
        return [], html.Div("Not logged in.", className="sc-alert sc-alert-danger")
    try:
        resp = requests.get(f"{GATEWAY_API}/admin/metrics",
                            headers={"Authorization": f"Bearer {token}"}, timeout=10)
        if resp.status_code == 401:
            return [], html.Div("Session expired.", className="sc-alert sc-alert-danger")
        if resp.status_code != 200:
            return [], html.Div(f"Gateway error {resp.status_code}.", className="sc-alert sc-alert-danger")

        payload      = resp.json()
        generated_at = payload.get("generated_at", "")
        metrics      = payload.get("metrics", {})

        if not metrics:
            return [html.P("No requests recorded yet.",
                           style={"color": "var(--text-dim)", "fontSize": "12px"})], []

        def fmt_ms(v):
            return f"{v * 1000:.0f}" if v is not None else "—"

        rows = []
        for endpoint, stats in sorted(metrics.items()):
            err = stats.get("errors", 0)
            rows.append(html.Tr([
                html.Td(endpoint, style={"wordBreak": "break-all"}),
                html.Td(stats.get("calls", 0)),
                html.Td(fmt_ms(stats.get("avg_latency"))),
                html.Td(fmt_ms(stats.get("min_latency"))),
                html.Td(fmt_ms(stats.get("max_latency"))),
                html.Td(err, style={"color": "var(--red)" if err > 0 else "var(--text-dim)"}),
            ]))

        table = html.Table([
            html.Thead(html.Tr([
                html.Th(h) for h in ["Endpoint", "Calls", "Avg ms", "Min ms", "Max ms", "Errors"]
            ])),
            html.Tbody(rows),
        ], className="sc-admin-table")

        ts_note = html.P(
            f"As of {generated_at[:19].replace('T', ' ')} UTC" if generated_at else "",
            style={"fontSize": "10px", "color": "var(--text-dim)", "marginTop": "10px"},
        )
        return [table, ts_note], []

    except Exception as e:
        return [], html.Div(f"Could not load metrics: {e}", className="sc-alert sc-alert-danger")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8050, debug=True)

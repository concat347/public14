# SentimentCompare

A microservices pipeline that captures financial news and the associated sentiment score from various APIs, scores the same news with a locally-running financial NLP model, and asks a concrete question: **does the tone of the news actually predict price movement?**

News is fetched from Alpha Vantage, scored by both Alpha Vantage's built-in sentiment engine and a locally-running [DistilRoBERTa or RoBERTa-Large](https://huggingface.co) model, and stored alongside daily OHLCV price data from Polygon.io. Before reaching the locally running model, each article passes through an independent quality filter that removes social media posts, thin blurbs, and ticker-mention noise. The dashboard then lets you explore how well — or how poorly — those two sentiment sources forecast the same-day, next-day, and two-day price changes.

---

## Why This Exists

Markets react to headlines before the dust settles on what actually happened. A tanker seizure, a ceasefire rumor, a surprise production cut — the price moves first, the analysis comes later.

This project tries to examine that relationship systematically. By scoring news sentiment from the last 24 hours, the idea is that this calculated sentiment can forecast what will happen to the price in the current day, the next day, or 2 days from now. The sentiment scores are correlated against price changes that follow, we can test whether the tone of financial news has genuine predictive value, or whether it mostly reflects what the market already did.

The pipeline works for any ticker symbol, including:

| Ticker | Description |
|--------|-------------|
| WTI | West Texas Intermediate Crude |
| USO | United States Oil Fund (WTI crude) |
| BNO | Brent North Sea crude oil |
| UNG | United States Natural Gas Fund |
| DBO | DB Oil Fund |
| XLE | Energy sector ETF (broad energy equities) |

---

## Architecture

```
Browser
  │
  ▼
Dashboard (Dash/Flask :8050)
  │
  ▼
Gateway (FastAPI :8000)  ←── JWT authentication
  │   ├── POST /api/login
  │   ├── POST /api/fetch          (JWT required)
  │   ├── GET  /api/data/{symbol}  (JWT required)
  │   ├── GET  /api/admin/metrics  (JWT required)
  │   ├── DELETE /api/admin/metrics (JWT required)
  │   └── GET  /health
  │
  ├──► Producer (FastAPI :8001)
  │         ├── Alpha Vantage API  (news + sentiment scores)
  │         └── Polygon.io API     (daily OHLCV price data)
  │                   │
  │                   ▼
  │           Redpanda/Kafka (:9092)
  │                   │
  │                   ▼
  │           Consumer (Python)
  │                 ├── Article Quality Filter
  │                 ├── DistilRoBERTa / RoBERTa-Large (HuggingFace)
  │                 └── PostgreSQL (:5432)
  │                           │
  └──► Data Service (FastAPI :8003) ◄──────────┘
```

### Services

| Service | Port | Description |
|---------|------|-------------|
| Gateway | 8000 | Authentication and request routing |
| Producer | 8001 | News and price data fetching |
| Consumer | — | Kafka listener, article filtering, model inference, DB writes |
| Data | 8003 | Time-series query service |
| Dashboard | 8050 | Plotly Dash frontend |
| PostgreSQL | 5432 | Persistent storage |
| Redpanda | 9092 | Kafka-compatible message broker |

---

## Quick Start (Docker Compose)

### Prerequisites

- Docker and Docker Compose
- Alpha Vantage API key (free tier available)
- Polygon.io API key (free tier available)

### Setup

1. Clone the repository:
```bash
git clone https://github.com/concat347/sentiment-compare.git
cd sentiment-compare
```

2. Create a `.env` file in the project root:
```env
ALPHAVANTAGE_API_KEY=your_key_here
POLYGON_API_KEY=your_key_here
SECRET_KEY=a-long-random-string
```

3. Start all services:
```bash
docker compose up --build -d
docker compose logs -f consumer     # follow scoring and filter logs
```

4. Open the dashboard at `http://localhost:8050`

5. Log in with `trader` / `password123` or `demo` / `demo123`

### Stopping

```bash
docker compose down       # stop, keep database
docker compose down -v    # stop and wipe database
```

---

## Deploying to Kubernetes (GKE)

### Prerequisites

- Google Cloud SDK installed and authenticated
- A GCP project with billing enabled
- `kubectl` installed

### Create the Cluster

```bash
gcloud container clusters create sentiment-cluster \
  --num-nodes=3 \
  --machine-type=e2-standard-2 \
  --zone=us-central1-a \
  --disk-size=30

gcloud container clusters get-credentials sentiment-cluster --zone=us-central1-a
```

### Deploy

```bash
kubectl apply -f k8s/
kubectl get pods --watch    # wait for all pods to reach Running
```

### Initialize the Database

```bash
kubectl exec -it postgres-0 -- psql -U stockuser -d stockdb -c "
CREATE TABLE IF NOT EXISTS stock_daily (
    id SERIAL PRIMARY KEY, symbol TEXT NOT NULL, date DATE NOT NULL,
    open_price FLOAT, close_price FLOAT, volume BIGINT,
    finbert_sentiment FLOAT, finbert_confidence FLOAT,
    finbert_explanation TEXT, av_sentiment FLOAT, article_count INT,
    created_at TIMESTAMP DEFAULT NOW(), UNIQUE(symbol, date));
CREATE TABLE IF NOT EXISTS gateway_metrics (
    endpoint TEXT PRIMARY KEY, calls BIGINT NOT NULL DEFAULT 0,
    total_latency FLOAT NOT NULL DEFAULT 0.0, min_latency FLOAT,
    max_latency FLOAT NOT NULL DEFAULT 0.0, errors BIGINT NOT NULL DEFAULT 0,
    last_updated TIMESTAMP DEFAULT NOW());"
```

### Get the Dashboard URL

```bash
kubectl get ingress    # use the ADDRESS field
```

Open the ingress IP in your browser and log in with `trader` / `password123`.

### Cleanup

```bash
gcloud container clusters delete sentiment-cluster --zone=us-central1-a --quiet
```

---

## Sentiment Model

The consumer supports two model options, configured in `services/consumer/main.py`:

**Option A — DistilRoBERTa (default)**
`mrm8488/distilroberta-finetuned-financial-news-sentiment-analysis`
~82M parameters. Fast on CPU, financially domain-aware, good for most use cases.

**Option B — RoBERTa-Large**
`soleimanian/financial-roberta-large-sentiment`
~355M parameters. Higher accuracy, noticeably slower on CPU, comfortable on GPU. Recommended if you have GPU passthrough available or find the default model missing nuance after reviewing several weeks of data.

To switch models, comment/uncomment the `SENTIMENT_MODEL_NAME` lines near the top of `main.py` and rebuild the consumer:

```bash
docker compose build consumer
docker compose up -d --no-deps consumer
```

Both models use the same label order (`negative / neutral / positive`) so no other changes are needed.

---

## Article Quality Filter

Before any article reaches the sentiment model, it passes through a multi-signal quality filter. This step removes social media posts, thin wire blurbs, and articles that mention a ticker without providing any substantive financial news — the main source of noise in sentiment pipelines.

### How It Works

Each article is scored on five independent components that sum to a `[0.0, 1.0]` quality score:

| Component | Max | What It Measures |
|-----------|-----|-----------------|
| Length | 0.25 | Character count (clamped to 1000). Short blurbs score near zero. |
| Substance | 0.30 | Density of unique financial terms (revenue, earnings, CEO, merger, etc.) relative to word count. |
| Structure | 0.20 | Sentence count. Real journalism has multiple sentences; social posts usually don't. |
| Source | +0.15 / −0.10 | Bonus for known quality outlets (Reuters, Bloomberg, WSJ, AP); penalty for known noisy sources (Reddit, StockTwits, Twitter). Unknown sources receive a small neutral bonus. |
| Noise penalty | −0.20 | Deducted for social-media signals: cashtags (`$AAPL`), emoji clusters, meme phrases (`to the moon`, `diamond hands`, `YOLO`). |

Articles scoring below `QUALITY_THRESHOLD` are dropped before inference. Each filtered article is logged with its score and the dominant factor, for example:

```
🚫 FILTERED [USO 2026-04-01] score=0.18 (noise=-0.14) — "$USO 🚀🚀 to the moon..."
🔍 Filter [USO 2026-04-01]: 7/12 passed [███████░░░░░] 58% (threshold=0.35)
```

### Tuning the Threshold

The threshold can be set without rebuilding via an environment variable:

```yaml
# docker-compose.yml
environment:
  - QUALITY_THRESHOLD=0.45
```

Then restart the consumer:
```bash
docker compose up -d --no-deps consumer
```

Suggested values:

| Threshold | Effect |
|-----------|--------|
| 0.30 | Permissive. Cuts obvious social noise but lets through thin wire blurbs. Good starting point. |
| 0.35 | Default. Balanced for mixed news feeds. |
| 0.45 | Moderate. Requires meaningful financial substance. Recommended after a week of log review. |
| 0.60 | Strict. Only well-sourced, substantive articles pass. |

### Article Count in the Database

`article_count` in the database always reflects the **total articles received**, not the number that passed the filter. This keeps historical records comparable if you later adjust the threshold. The pass-rate fraction (`7/12 passed`) is logged per symbol/date but never persisted — the schema is unchanged.

---

## Two Independent Sentiment Streams

The consumer computes and stores two fully independent sentiment scores for every trading day:

**Stream 1 — Our model score (`local_model_sentiment`)**
Each article that passes the quality filter is scored by the local model. Articles are weighted by text length (clamped to [50, 1000] chars) as a proxy for information density. Alpha Vantage's `relevance_score` field is intentionally not used here, keeping this stream independent of AV's judgment.

**Stream 2 — Alpha Vantage baseline (`av_sentiment`)**
AV's pre-computed scores are averaged with equal weight. AV applies its own internal relevance weighting before returning scores, so re-weighting here would double-count its judgment. A plain average is the cleanest independent baseline.

The delta between the two streams is logged on every run. A consistently large delta is a signal to investigate model fit or feed quality. Days where the two models diverge by more than 0.35 are highlighted in the dashboard as purple triangles.

---

## Using the Dashboard

### Analysis Tab

**1. Fetch data** — Enter a ticker (e.g. `USO`, `SPY`, `QQQ`) and a number of history days, then click **Fetch Data**. The pipeline runs: the producer pulls news and prices, publishes to Kafka, the consumer filters and scores each article, and writes the results to PostgreSQL. This runs asynchronously — the status bar will confirm when messages are queued.

**2. Load the chart** — Click **Load Chart** to query the data service and render the dashboard.

---

### Scorecard Strip

Four headline numbers appear at the top of the Analysis tab:

| Card | What It Shows |
|------|---------------|
| Trading Days | Number of days in the loaded dataset |
| Articles Scored | Total news articles received (includes filtered articles) |
| Best Lag | Which time horizon (same-day, +1, +2) has the strongest correlation, and its Pearson r |
| Model Agreement | Percentage of days both models agree on direction (both bullish or both bearish) |

---

### Price & Sentiment Chart

A split two-panel chart with a shared time axis:

- **Top panel** — Daily price bars colored green (up day) or red (down day), spanning open to close. Hover for date, open, close, intraday move, and article count.
- **Bottom panel** — Model sentiment (amber line) and Alpha Vantage sentiment (cyan dashed line) on a −1 to +1 scale. Hover on the model line to see the confidence score and the signal explanation for that day.
- **Purple triangles** — Days where the two models diverge by more than 0.35. Worth examining to see which one was right.

---

### Sentiment vs. Next-Day Price Change (Scatter)

Each dot is one trading day. The x-axis is the sentiment score; the y-axis is how much the price moved the *following* day. A dashed trend line shows the direction of the relationship.

Next-day (rather than same-day) is used deliberately — same-day sentiment is partially contaminated by news that broke after the market had already moved. Next-day is a cleaner test of genuine predictive value.

Purple dots mark the high-divergence days. If the non-purple dots show a pattern while the purple dots scatter randomly, that suggests model agreement is itself a useful quality signal.

---

### Correlation Matrix

Pearson r values for both models across three time horizons:

| Lag | What It Measures |
|-----|-----------------|
| Same-day | Sentiment vs. that day's open→close % change |
| +1 Day | Sentiment vs. the following day's open→close % change |
| +2 Days | Sentiment vs. two days later |

Values are color-coded: green for positive correlation, red for negative. Requires at least 5 complete trading days in the dataset.

---

### Admin Tab

Per-endpoint gateway statistics: call counts, average/min/max latency in milliseconds, and error counts. Stats persist across container restarts via PostgreSQL. Click **↻ Refresh** to update.

---

## API Reference

All endpoints are exposed through the Gateway service. Authentication uses JWT Bearer tokens issued by `POST /api/login`. Tokens expire after 60 minutes.

### `POST /api/login`
Issues a JWT token. No authentication required.

```json
// Request
{ "username": "trader", "password": "password123" }

// Response 200
{ "access_token": "eyJ...", "token_type": "bearer" }
```

---

### `POST /api/fetch`
Triggers the producer to fetch news and price data and push it through the pipeline. Filtering and model scoring happen asynchronously in the consumer.

```json
// Request
{ "symbol": "USO", "days": 30 }

// Response 200
{ "status": "fetch initiated", "symbol": "USO" }
```

---

### `GET /api/data/{symbol}`
Returns the full time series for a symbol: price data, model sentiment, Alpha Vantage sentiment, and article counts.

```json
// Response 200
[
  {
    "date": "2024-01-15",
    "symbol": "USO",
    "open_price": 74.21,
    "close_price": 75.03,
    "volume": 4821000,
    "finbert_sentiment": 0.42,
    "finbert_confidence": 0.87,
    "finbert_explanation": "Bullish: OPEC output cut signals tighter supply ahead...",
    "av_sentiment": 0.31,
    "article_count": 12
  }
]
```

Note: `article_count` reflects total articles received. The number of articles that passed the quality filter is logged by the consumer but not stored.

---

### `GET /api/admin/metrics`
Returns per-endpoint usage statistics.

### `DELETE /api/admin/metrics`
Resets all accumulated metrics to zero.

### `GET /health`
Health check. No authentication required. Returns `{ "status": "ok" }`.

---

## Database Schema

```sql
CREATE TABLE stock_daily (
    id                  SERIAL PRIMARY KEY,
    symbol              TEXT NOT NULL,
    date                DATE NOT NULL,
    open_price          FLOAT,
    close_price         FLOAT,
    volume              BIGINT,
    finbert_sentiment   FLOAT,    -- weighted model score, range [-1.0, +1.0]
    finbert_confidence  FLOAT,    -- mean softmax confidence across scored articles
    finbert_explanation TEXT,     -- highest-impact article headline and direction
    av_sentiment        FLOAT,    -- Alpha Vantage equal-weight average
    article_count       INT,      -- total articles received (pre-filter)
    created_at          TIMESTAMP DEFAULT NOW(),
    UNIQUE(symbol, date)
);

CREATE TABLE gateway_metrics (
    endpoint        TEXT PRIMARY KEY,
    calls           BIGINT  NOT NULL DEFAULT 0,
    total_latency   FLOAT   NOT NULL DEFAULT 0.0,
    min_latency     FLOAT,
    max_latency     FLOAT   NOT NULL DEFAULT 0.0,
    errors          BIGINT  NOT NULL DEFAULT 0,
    last_updated    TIMESTAMP DEFAULT NOW()
);
```

---

## Environment Variables

| Variable | Used By | Description |
|----------|---------|-------------|
| `ALPHAVANTAGE_API_KEY` | producer | Alpha Vantage API key |
| `POLYGON_API_KEY` | producer | Polygon.io API key |
| `KAFKA_BOOTSTRAP_SERVERS` | producer, consumer | Kafka address (default: `redpanda:9092`) |
| `POSTGRES_HOST` | consumer, data, gateway | Postgres host (default: `postgres`) |
| `POSTGRES_DB` | consumer, data, gateway | Database name (default: `stockdb`) |
| `POSTGRES_USER` | consumer, data, gateway | Database user (default: `stockuser`) |
| `POSTGRES_PASSWORD` | consumer, data, gateway | Database password (default: `stockpass`) |
| `SECRET_KEY` | gateway | Secret key for signing JWT tokens |
| `PRODUCER_URL` | gateway | Producer service URL (default: `http://producer:8001`) |
| `DATA_URL` | gateway | Data service URL (default: `http://data:8003`) |
| `QUALITY_THRESHOLD` | consumer | Article quality filter threshold, `[0.0, 1.0]` (default: `0.35`) |

---

## Known Limitations

- **Polygon.io free tier** finalizes daily bars around 4:15–4:30 pm ET and lags approximately 2 days on the aggregates endpoint.
- **Alpha Vantage free tier** caps news responses at 50 articles per request and is rate-limited to 5 API calls per minute. Sentiment is therefore aggregated daily rather than intraday.
- **Correlation cards** show N/A until at least 5 complete trading days are in the database for a symbol.
- **Model runs on CPU** — GPU passthrough is not configured. RoBERTa-Large in particular is noticeably slower on CPU; the default DistilRoBERTa model is recommended unless GPU passthrough is available.
- **US market holidays** are hardcoded for the current year.
- **User credentials** are hardcoded in the gateway. Replace with a proper user store before any production deployment.
- **Quality filter thresholds** are tuned for mixed financial news feeds. If your feed is exclusively from wire services, consider lowering `QUALITY_THRESHOLD` to `0.25` to avoid over-filtering legitimate short dispatches.
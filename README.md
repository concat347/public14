# SentimentCompare

A microservices pipeline that captures financial news, and scores it with a locally-running NLP model. 

The pipeline runs two independent sentiment streams against the same price data. Alpha Vantage supplies news and its own pre-computed sentiment scores. Finnhub supplies a separate news feed that passes through an independent quality filter before being scored by a locally-running [DistilRoBERTa or RoBERTa-Large](https://huggingface.co) model. Both streams are stored alongside daily OHLCV price data from Polygon.io. The dashboard then lets you explore how well — or how poorly — each source forecasts same-day, next-day, and two-day price changes.

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
  │
  ├──► Producer (FastAPI :8001)
  │         ├── Alpha Vantage API  (news + pre-computed sentiment)
  │         ├── Finnhub API        (news → quality filter → local model)
  │         └── Polygon.io API     (daily OHLCV)
  │                   │
  │                   ▼
  │           Redpanda/Kafka (:9092)
  │                   │
  │                   ▼
  │           Consumer (Python)
  │                 ├── Article Quality Filter
  │                 ├── DistilRoBERTa / RoBERTa-Large
  │                 └── PostgreSQL (:5432)
  │                           │
  └──► Data Service (FastAPI :8003) ◄──────────┘
```

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

**Prerequisites:** Docker, an Alpha Vantage API key, and a Polygon.io API key (both have free tiers).

```bash
git clone https://github.com/concat347/sentiment-compare.git
cd sentiment-compare
```

Create a `.env` file in the project root:

```env
ALPHAVANTAGE_API_KEY=your_key_here
POLYGON_API_KEY=your_key_here
SECRET_KEY=a-long-random-string
```

```bash
docker compose up --build -d
docker compose logs -f consumer   # follow scoring and filter logs
```

Open `http://localhost:8050` and log in with `trader` / `password123`.

```bash
docker compose down      # stop, keep database
docker compose down -v   # stop and wipe database
```

---

## Deploying to Kubernetes (GKE)

**Prerequisites:** Google Cloud SDK, a GCP project with billing enabled, `kubectl`.

```bash
# Create the cluster
gcloud container clusters create sentiment-cluster \
  --num-nodes=3 \
  --machine-type=e2-standard-2 \
  --zone=us-central1-a \
  --disk-size=30

gcloud container clusters get-credentials sentiment-cluster --zone=us-central1-a

# Deploy
kubectl apply -f k8s/
kubectl get pods --watch

# Get the dashboard URL
kubectl get ingress
```

Open the ingress IP and log in with `trader` / `password123`.

```bash
# Teardown
gcloud container clusters delete sentiment-cluster --zone=us-central1-a --quiet
```

---

## Sentiment Models

The consumer supports two models, configured in `services/consumer/main.py`:

| Model | Parameters | Notes |
|-------|-----------|-------|
| **DistilRoBERTa** (default) | ~82M | Fast on CPU, financially domain-aware |
| **RoBERTa-Large** | ~355M | Higher accuracy, slower on CPU; recommended with GPU |

To switch models, comment/uncomment the `SENTIMENT_MODEL_NAME` lines near the top of `main.py`, then rebuild:

```bash
docker compose build consumer
docker compose up -d --no-deps consumer
```

---

## Article Quality Filter

Each article is scored across five components before reaching the sentiment model:

| Component | Weight | What It Measures |
|-----------|--------|-----------------|
| Length | 0.25 | Character count — short blurbs score near zero |
| Substance | 0.30 | Density of financial terms relative to word count |
| Structure | 0.20 | Sentence count — social posts score near zero |
| Source | ±0.15 | Bonus for Reuters/Bloomberg/WSJ; penalty for Reddit/StockTwits |
| Noise penalty | −0.20 | Cashtags, emoji clusters, meme phrases |

The threshold is configurable without rebuilding:

```yaml
# docker-compose.yml
environment:
  - QUALITY_THRESHOLD=0.45
```

| Threshold | Effect |
|-----------|--------|
| 0.30 | Permissive — cuts obvious noise, allows thin wire blurbs |
| 0.35 | Default — balanced for mixed news feeds |
| 0.45 | Moderate — requires meaningful financial substance |
| 0.60 | Strict — only well-sourced, substantive articles pass |

---

## Dashboard

**Fetch data** — Enter a ticker (e.g. `USO`, `XLE`, `SPY`) and a history window, then click **Fetch Data**. The pipeline runs asynchronously.

**Load Chart** — Renders three views:
- **Price & Sentiment** — daily OHLCV bars with local model sentiment from Finnhub (amber) and Alpha Vantage sentiment (cyan dashed) overlaid. Purple triangles mark days where the two streams diverge by more than 0.35.
- **Scatter plot** — sentiment score vs. next-day price change, with a trend line.
- **Correlation matrix** — Pearson r for both models across same-day, +1, and +2 day horizons.

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
| `POSTGRES_PASSWORD` | consumer, data, gateway | Database password |
| `SECRET_KEY` | gateway | Secret key for signing JWT tokens |
| `QUALITY_THRESHOLD` | consumer | Article filter threshold, `[0.0, 1.0]` (default: `0.35`) |

---

## Notes

- Polygon.io free tier finalizes daily bars around 4:15–4:30 pm ET with an approximately 2-day lag on the aggregates endpoint.
- Alpha Vantage free tier caps news at 50 articles per request, rate-limited to 5 calls per minute.
- The correlation matrix requires at least 5 complete trading days in the dataset.
- User credentials are hardcoded in the gateway — replace with a proper user store before any production deployment.

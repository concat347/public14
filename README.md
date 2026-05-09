# SentimentCompare

A microservices pipeline that captures financial news, and scores it with a locally-running NLP model. 

The pipeline runs two independent sentiment streams against the same price data. Company A supplies news and its own pre-computed sentiment scores. Company B supplies a separate news feed that passes through an independent quality filter before being scored by a locally-running [FinBERT](https://huggingface.co) model. Both streams are stored alongside daily OHLCV price data from Company C.

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
  │         ├── Company A API  (news + pre-computed sentiment)
  │         ├── Company B API        (news → quality filter → local model)
  │         └── Company C API     (daily OHLCV)
  │                   │
  │                   ▼
  │           Redpanda/Kafka (:9092)
  │                   │
  │                   ▼
  │           Consumer (Python)
  │                 ├── Article Quality Filter
  │                 ├── FinBERT
  │                 └── PostgreSQL (:5432)
  │                           │
  └──► Data Service (FastAPI :8003) ◄──────────┘
```

| Service | Port | Description |
|---------|------|-------------|
| Gateway | 8000 | Authentication and request routing |
| Producer | 8001 | Fetching |
| Consumer | — | Kafka listener, article filtering, model inference, DB writes |
| Data | 8003 | Time-series query service |
| Dashboard | 8050 | Plotly Dash frontend |
| PostgreSQL | 5432 | Persistent storage |
| Redpanda | 9092 | Kafka-compatible message broker |

Sentiment Models

The consumer supports multiple models, configured in `services/consumer/main.py`:

| Model | Parameters | Notes |
|-------|-----------|-------|
| **FinBERT** (default) | Fast on CPU, financially domain-aware |
| **RoBERTa-Large** | ~355M | Higher accuracy, slower on CPU; recommended with GPU |

Article Quality Filter

Each article is scored across five components before reaching the sentiment model.
The threshold is configurable without rebuilding:

```yaml
environment:
  - QUALITY_THRESHOLD=0.45
```

| Threshold | Effect |
|-----------|--------|
| 0.30 | Permissive |
| 0.35 | Default    |
| 0.45 | Moderate   |
| 0.60 | Strict     |

## Dashboard

**Fetch data** — Enter a ticker then click **Fetch Data**. The pipeline runs asynchronously.

## Environment Variables

| Variable | Used By | Description |
|----------|---------|-------------|
| `QUALITY_THRESHOLD` | consumer | filter threshold, `[0.0, 1.0]` (default: `0.35`) |

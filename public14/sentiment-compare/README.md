# SentimentCompare

A microservices pipeline that captures financial news, scores it with a locally-running NLP model, and compares it to sentiment scores from other providers.

The pipeline runs two independent sentiment streams against the same price data. Companies supply news and their own pre-computed sentiment scores. A separate news feed passes through an independent quality filter before being scored by a locally-running [FinBERT](https://huggingface.co) model. Both streams are stored alongside daily OHLCV price data.

---

## Architecture
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
| Service | Port | Description |
|---------|------|-------------|
| Gateway | 8000 | Authentication and request routing |
| Producer | 8001 | Fetching |
| Consumer | — | Kafka listener, article filtering, model inference, DB writes |
| Data | 8003 | Time-series query service |
| Dashboard | 8050 | Plotly Dash frontend |
| PostgreSQL | 5432 | Persistent storage |
| Redpanda | 9092 | Kafka-compatible message broker |

---

Sentiment Models

The consumer supports multiple models, configured in `services/consumer/main.py`:

| Model | Parameters | Notes |
|-------|-----------|-------|
| **FinBERT** | Fast on CPU, financially domain-aware |
| **RoBERTa-Large** | ~355M | Higher accuracy, slower on CPU; recommended with GPU |

To switch models, comment/uncomment the `SENTIMENT_MODEL_NAME` lines near the top of `main.py`, then rebuild:

Article Quality Filter

Each article is scored across five components before reaching the sentiment model:

| Component | Weight | What It Measures |
|-----------|--------|-----------------|
| xxxxxx | 0.25 | 
| xxxxxx | 0.30 | 
| xxxxxx | 0.20 | 
| xxxxxx | ±0.15 | 
| xxxxxx | −0.20 | 

The threshold is configurable without rebuilding:

```yaml
# docker-compose.yml
environment:
  - QUALITY_THRESHOLD=0.45
```

| Threshold | Effect |
|-----------|--------|
| 0.30 | Permissive |
| 0.35 | Default    |
| 0.45 | Moderate   |
| 0.60 | Strict     |

---

## Dashboard

**Fetch data** — Enter a ticker, then click **Fetch Data**. The pipeline runs asynchronously.

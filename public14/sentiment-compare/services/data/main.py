# services/data/main.py
from fastapi import FastAPI, HTTPException
import os
import psycopg2
import psycopg2.pool

# ---------------------------------------------------------
# FASTAPI APP
# ---------------------------------------------------------
app = FastAPI(title="Stock Data API")

# ---------------------------------------------------------
# POSTGRES CONFIG
# ---------------------------------------------------------
POSTGRES_HOST     = os.getenv("POSTGRES_HOST",     "postgres")
POSTGRES_DB       = os.getenv("POSTGRES_DB",       "stockdb")
POSTGRES_USER     = os.getenv("POSTGRES_USER",     "stockuser")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "stockpass")

# ---------------------------------------------------------
# CONNECTION POOL
# ---------------------------------------------------------
pool = psycopg2.pool.SimpleConnectionPool(
    minconn=1,
    maxconn=10,
    host=POSTGRES_HOST,
    database=POSTGRES_DB,
    user=POSTGRES_USER,
    password=POSTGRES_PASSWORD,
)

def get_conn():
    return pool.getconn()

def release_conn(conn):
    pool.putconn(conn)


# ---------------------------------------------------------
# FETCH TIMESERIES DATA
# ---------------------------------------------------------
@app.get("/timeseries/{symbol}")
def get_timeseries(symbol: str):
    """
    Returns daily FinBERT and Alpha Vantage sentiment plus
    price data for a symbol. Used by the Dash dashboard.
    """
    symbol = symbol.upper().strip()
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT date, open_price, close_price, volume,
                       finbert_sentiment, finbert_confidence,
                       finbert_explanation, article_count,
                       av_sentiment
                FROM stock_daily
                WHERE symbol = %s
                ORDER BY date ASC;
                """,
                (symbol,)
            )
            rows = cur.fetchall()

        if not rows:
            return []

        results = []
        for (date, open_price, close_price, volume, finbert_sentiment,
             finbert_confidence, finbert_explanation,
             article_count, av_sentiment) in rows:
            results.append({
                "date":                date.strftime("%Y-%m-%d"),
                "open_price":          float(open_price)         if open_price         is not None else None,
                "close_price":         float(close_price)        if close_price        is not None else None,
                "volume":              volume,
                "finbert_sentiment":   float(finbert_sentiment)  if finbert_sentiment  is not None else None,
                "finbert_confidence":  float(finbert_confidence) if finbert_confidence is not None else None,
                "finbert_explanation": finbert_explanation,
                "article_count":       article_count,
                "av_sentiment":        float(av_sentiment)       if av_sentiment       is not None else None,
            })
        return results

    except Exception as e:
        print(f"❌ Error fetching timeseries for {symbol}: {e}")
        raise HTTPException(status_code=500, detail="Database query failed")
    finally:
        release_conn(conn)


# ---------------------------------------------------------
# FETCH LATEST NEWS ARTICLES FOR A SYMBOL
# ---------------------------------------------------------
@app.get("/news/{symbol}")
def get_news(symbol: str, limit: int = 20):
    """
    Returns the most recent quality-filtered, model-scored articles
    for a symbol, ordered newest first.

    Used by the dashboard's live news feed (polled every 30 seconds
    via dcc.Interval).  Only articles that passed the consumer's
    quality filter and were scored by the local model are present —
    raw blurbs and social noise are never written to this table.

    Query parameters:
        limit  int  Maximum number of articles to return (default 20,
                    capped at 100 to prevent runaway queries).
    """
    symbol = symbol.upper().strip()
    limit  = max(1, min(limit, 100))   # clamp: 1 ≤ limit ≤ 100

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    title,
                    summary,
                    source,
                    url,
                    published_at,
                    av_sentiment,
                    model_sentiment,
                    model_confidence
                FROM articles
                WHERE symbol = %s
                ORDER BY published_at DESC
                LIMIT %s;
                """,
                (symbol, limit),
            )
            rows = cur.fetchall()

        results = []
        for (title, summary, source, url, published_at,
             av_sentiment, model_sentiment, model_confidence) in rows:
            results.append({
                "title":            title,
                "summary":          summary,
                "source":           source,
                "url":              url,
                "published_at":     published_at.strftime("%Y-%m-%dT%H:%M:%SZ")
                                    if published_at else None,
                "av_sentiment":     round(float(av_sentiment),    4) if av_sentiment    is not None else None,
                "model_sentiment":  round(float(model_sentiment), 4) if model_sentiment is not None else None,
                "model_confidence": round(float(model_confidence),4) if model_confidence is not None else None,
            })
        return results

    except Exception as e:
        print(f"❌ Error fetching news for {symbol}: {e}")
        raise HTTPException(status_code=500, detail="Database query failed")
    finally:
        release_conn(conn)


# ---------------------------------------------------------
# HEALTH CHECK
# ---------------------------------------------------------
@app.get("/health")
def health():
    return {
        "status":   "healthy",
        "service":  "data",
        "postgres": POSTGRES_HOST,
    }

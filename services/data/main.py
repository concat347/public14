# services/data/main.py
from fastapi import FastAPI, HTTPException, Query
import os
import psycopg2
import psycopg2.pool
from typing import List, Optional

app = FastAPI(title="Stock Data API")

# ---------------------------------------------------------
# POSTGRES CONFIG
# ---------------------------------------------------------
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "postgres")
POSTGRES_DB = os.getenv("POSTGRES_DB", "stockdb")
POSTGRES_USER = os.getenv("POSTGRES_USER", "stockuser")
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
# ENDPOINTS
# ---------------------------------------------------------
@app.get("/symbols")
def get_symbols():
    """List all symbols with data"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT symbol FROM stock_daily ORDER BY symbol;")
            symbols = [row[0] for row in cur.fetchall()]
        return {"symbols": symbols}
    finally:
        release_conn(conn)

@app.get("/timeseries/{symbol}")
def get_timeseries(symbol: str):
    symbol = symbol.upper().strip()
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT date, open_price, close_price, volume,
                       finbert_sentiment, finbert_confidence, finbert_explanation,
                       article_count, av_sentiment,
                       ROUND((finbert_sentiment - av_sentiment)::numeric, 4) AS sentiment_delta
                FROM stock_daily
                WHERE symbol = %s
                ORDER BY date ASC;
                """,
                (symbol,)
            )
            rows = cur.fetchall()

        results = []
        for row in rows:
            (date, open_p, close_p, vol, f_sent, f_conf, f_exp, art_cnt, av_sent, delta) = row
            results.append({
                "date": date.strftime("%Y-%m-%d"),
                "open_price": float(open_p) if open_p is not None else None,
                "close_price": float(close_p) if close_p is not None else None,
                "volume": vol,
                "finbert_sentiment": float(f_sent) if f_sent is not None else None,
                "finbert_confidence": float(f_conf) if f_conf is not None else None,
                "finbert_explanation": f_exp,
                "article_count": art_cnt,
                "av_sentiment": float(av_sent) if av_sent is not None else None,
                "sentiment_delta": float(delta) if delta is not None else None,
            })
        return results
    finally:
        release_conn(conn)

@app.get("/news/{symbol}")
def get_news(symbol: str, limit: int = Query(20, ge=1, le=100)):
    symbol = symbol.upper().strip()
    limit = max(1, min(limit, 100))
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT title, summary, source, url, published_at,
                       av_sentiment, model_sentiment, model_confidence
                FROM articles
                WHERE symbol = %s
                ORDER BY published_at DESC
                LIMIT %s;
                """,
                (symbol, limit)
            )
            rows = cur.fetchall()

        results = []
        for (title, summary, source, url, published_at, av_s, model_s, model_c) in rows:
            results.append({
                "title": title,
                "summary": summary,
                "source": source,
                "url": url,
                "published_at": published_at.strftime("%Y-%m-%dT%H:%M:%SZ") if published_at else None,
                "av_sentiment": round(float(av_s), 4) if av_s is not None else None,
                "model_sentiment": round(float(model_s), 4) if model_s is not None else None,
                "model_confidence": round(float(model_c), 4) if model_c is not None else None,
            })
        return results
    finally:
        release_conn(conn)

@app.get("/health")
def health():
    return {"status": "healthy", "service": "data"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8003)   # Keep your current port 8003

# services/consumer/db/postgres.py
import psycopg2
import psycopg2.pool
import os
import time
import logging

logger = logging.getLogger(__name__)

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
_pool = None

def _get_pool():
    global _pool
    if _pool is not None:
        return _pool
    retries = 10
    delay   = 3
    for attempt in range(1, retries + 1):
        try:
            _pool = psycopg2.pool.SimpleConnectionPool(
                minconn=1,
                maxconn=10,
                host=POSTGRES_HOST,
                database=POSTGRES_DB,
                user=POSTGRES_USER,
                password=POSTGRES_PASSWORD,
            )
            logger.info(f"✅ Connected to PostgreSQL on attempt {attempt}")
            return _pool
        except psycopg2.OperationalError as e:
            logger.warning(f"⏳ PostgreSQL not ready (attempt {attempt}/{retries}): {e}")
            if attempt < retries:
                time.sleep(delay)
    raise RuntimeError("Could not connect to PostgreSQL after retries.")

def get_conn():
    return _get_pool().getconn()

def release_conn(conn):
    _get_pool().putconn(conn)

# ---------------------------------------------------------
# WRITE DAILY RECORD
# ---------------------------------------------------------
def write_daily_record(
    symbol,
    date,
    open_price,
    close_price,
    volume,
    finbert_sentiment,
    finbert_confidence,
    finbert_explanation,
    article_count,
    av_sentiment=None,
):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO stock_daily (
                    symbol, date, open_price, close_price, volume,
                    finbert_sentiment, finbert_confidence, finbert_explanation,
                    article_count, av_sentiment
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (symbol, date) DO UPDATE SET
                    open_price          = EXCLUDED.open_price,
                    close_price         = EXCLUDED.close_price,
                    volume              = EXCLUDED.volume,
                    finbert_sentiment   = COALESCE(EXCLUDED.finbert_sentiment,   stock_daily.finbert_sentiment),
                    finbert_confidence  = COALESCE(EXCLUDED.finbert_confidence,  stock_daily.finbert_confidence),
                    finbert_explanation = COALESCE(EXCLUDED.finbert_explanation, stock_daily.finbert_explanation),
                    article_count       = COALESCE(EXCLUDED.article_count,       stock_daily.article_count),
                    av_sentiment        = COALESCE(EXCLUDED.av_sentiment,        stock_daily.av_sentiment);
                """,
                (symbol, date, open_price, close_price, volume,
                 finbert_sentiment, finbert_confidence, finbert_explanation,
                 article_count, av_sentiment)
            )
        conn.commit()
    except Exception as e:
        logger.error(f"❌ write_daily_record error: {e}")
        conn.rollback()
    finally:
        release_conn(conn)

# ---------------------------------------------------------
# WRITE ARTICLE - FIXED to accept news_source
# ---------------------------------------------------------
def write_article(
    symbol,
    published_at,
    title,
    summary,
    source,
    url,
    av_sentiment=None,
    model_sentiment=None,
    model_confidence=None,
    news_source="finnhub",      # <-- This was the missing parameter
    quality_score=None
):
    """
    Persist a quality-filtered Finnhub article.
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO articles (
                    symbol, published_at, title, summary, source, url,
                    news_source, av_sentiment, model_sentiment, model_confidence
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT DO NOTHING;
                """,
                (symbol, published_at, title, summary, source, url,
                 news_source, av_sentiment, model_sentiment, model_confidence)
            )
        conn.commit()
    except Exception as e:
        logger.error(f"❌ write_article error: {e}")
        conn.rollback()
    finally:
        release_conn(conn)

# ---------------------------------------------------------
# BACKFILL PRICE
# ---------------------------------------------------------
def backfill_price(symbol, date, open_price, close_price, volume):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE stock_daily
                SET open_price  = %s,
                    close_price = %s,
                    volume      = %s
                WHERE symbol    = %s
                  AND date      = %s
                  AND close_price IS NULL;
                """,
                (open_price, close_price, volume, symbol, date)
            )
        conn.commit()
    except Exception as e:
        logger.error(f"❌ backfill_price error: {e}")
        conn.rollback()
    finally:
        release_conn(conn)

# ---------------------------------------------------------
# HELPER QUERIES
# ---------------------------------------------------------
def get_existing_dates(symbol):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT date FROM stock_daily
                WHERE symbol = %s
                  AND open_price  IS NOT NULL
                  AND close_price IS NOT NULL
                  AND volume      IS NOT NULL;
                """,
                (symbol,)
            )
            rows = cur.fetchall()
            return {row[0].strftime("%Y-%m-%d") for row in rows}
    except Exception as e:
        logger.error(f"❌ get_existing_dates error: {e}")
        return set()
    finally:
        release_conn(conn)

def get_incomplete_dates(symbol):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT date FROM stock_daily
                WHERE symbol = %s
                  AND finbert_sentiment IS NOT NULL
                  AND close_price IS NULL;
                """,
                (symbol,)
            )
            rows = cur.fetchall()
            return {row[0].strftime("%Y-%m-%d") for row in rows}
    except Exception as e:
        logger.error(f"❌ get_incomplete_dates error: {e}")
        return set()
    finally:
        release_conn(conn)
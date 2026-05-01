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
# LAZY CONNECTION POOL
# Pool is created on first use, not at import time.
# This prevents the consumer from crashing during startup
# before PostgreSQL is ready to accept connections.
# ---------------------------------------------------------
_pool = None

def _get_pool():
    global _pool
    if _pool is not None:
        return _pool

    retries = 10
    delay   = 3  # seconds between attempts

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
            logger.warning(
                f"⏳ PostgreSQL not ready (attempt {attempt}/{retries}): {e}"
            )
            if attempt < retries:
                time.sleep(delay)

    raise RuntimeError(
        f"❌ Could not connect to PostgreSQL after {retries} attempts. "
        "Check that the postgres container is healthy and POSTGRES_* env vars are correct."
    )


def get_conn():
    return _get_pool().getconn()

def release_conn(conn):
    _get_pool().putconn(conn)


# ---------------------------------------------------------
# WRITE DAILY RECORD (UPSERT) — FINBERT + ALPHA VANTAGE
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
    """
    Insert or update a daily record with sentiment and price data.

    open_price, close_price and volume may be None when called during market
    hours. NULL is written intentionally so get_existing_dates() keeps the row
    flagged for backfill on the next fetch.

    Sentiment fields are only updated when the incoming values are not None,
    so a price-only backfill cannot accidentally wipe out good sentiment data.
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO stock_daily (
                    symbol,
                    date,
                    open_price,
                    close_price,
                    volume,
                    finbert_sentiment,
                    finbert_confidence,
                    finbert_explanation,
                    article_count,
                    av_sentiment
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (symbol, date)
                DO UPDATE SET
                    open_price          = EXCLUDED.open_price,
                    close_price         = EXCLUDED.close_price,
                    volume              = EXCLUDED.volume,
                    finbert_sentiment   = COALESCE(EXCLUDED.finbert_sentiment,   stock_daily.finbert_sentiment),
                    finbert_confidence  = COALESCE(EXCLUDED.finbert_confidence,  stock_daily.finbert_confidence),
                    finbert_explanation = COALESCE(EXCLUDED.finbert_explanation, stock_daily.finbert_explanation),
                    article_count       = COALESCE(EXCLUDED.article_count,       stock_daily.article_count),
                    av_sentiment        = COALESCE(EXCLUDED.av_sentiment,        stock_daily.av_sentiment);
                """,
                (
                    symbol,
                    date,
                    open_price,
                    close_price,
                    volume,
                    finbert_sentiment,
                    finbert_confidence,
                    finbert_explanation,
                    article_count,
                    av_sentiment,
                )
            )
        conn.commit()
    except Exception as e:
        logger.error(f"❌ Postgres write_daily_record error: {e}")
        conn.rollback()
    finally:
        release_conn(conn)


# ---------------------------------------------------------
# WRITE INDIVIDUAL ARTICLE (INSERT)
# ---------------------------------------------------------
def write_article(
    symbol,
    published_at,
    title,
    summary,
    source,
    url,
    av_sentiment,
    model_sentiment,
    model_confidence,
):
    """
    Persist a single quality-filtered, model-scored article to the
    articles table.

    Called once per article inside process_daily_sentiment(), after
    model_sentiment() has run.  Only articles that pass the quality
    filter reach this function — raw blurbs and social noise are never
    written.

    published_at should be a datetime object or an ISO-8601 string;
    psycopg2 handles both transparently.

    Duplicate articles (same symbol + title + published_at) are silently
    ignored via DO NOTHING so re-running a fetch never creates duplicates.
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO articles (
                    symbol,
                    published_at,
                    title,
                    summary,
                    source,
                    url,
                    av_sentiment,
                    model_sentiment,
                    model_confidence
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT DO NOTHING;
                """,
                (
                    symbol,
                    published_at,
                    title,
                    summary,
                    source,
                    url,
                    av_sentiment,
                    model_sentiment,
                    model_confidence,
                ),
            )
        conn.commit()
    except Exception as e:
        logger.error(f"❌ Postgres write_article error: {e}")
        conn.rollback()
    finally:
        release_conn(conn)


# ---------------------------------------------------------
# BACKFILL PRICE ONLY
# ---------------------------------------------------------
def backfill_price(symbol, date, open_price, close_price, volume):
    """
    Update open_price, close_price and volume for a row that already has
    sentiment data. Used when a date has sentiment but price was NULL at the
    time of the original fetch (market had not yet closed).
    """
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
                AND   date      = %s
                AND   close_price IS NULL;
                """,
                (open_price, close_price, volume, symbol, date)
            )
        conn.commit()
        if cur.rowcount > 0:
            logger.info(
                f"💰 Backfilled price for {symbol} {date}: "
                f"open ${open_price:.2f} / close ${close_price:.2f}"
            )
    except Exception as e:
        logger.error(f"❌ Postgres backfill_price error: {e}")
        conn.rollback()
    finally:
        release_conn(conn)


# ---------------------------------------------------------
# GET EXISTING DATES FOR A SYMBOL
# ---------------------------------------------------------
def get_existing_dates(symbol):
    """
    Returns a set of date strings (YYYY-MM-DD) that already have a fully
    complete record — meaning both sentiment AND price are present.
    Rows with any NULL price field are excluded so they get reprocessed
    on the next fetch and their price gets backfilled.
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT date FROM stock_daily
                WHERE symbol      = %s
                AND   open_price  IS NOT NULL
                AND   close_price IS NOT NULL
                AND   volume      IS NOT NULL;
                """,
                (symbol,)
            )
            rows = cur.fetchall()
            return {row[0].strftime("%Y-%m-%d") for row in rows}
    except Exception as e:
        logger.error(f"❌ Postgres get_existing_dates error: {e}")
        return set()
    finally:
        release_conn(conn)


# ---------------------------------------------------------
# GET INCOMPLETE DATES FOR A SYMBOL
# ---------------------------------------------------------
def get_incomplete_dates(symbol):
    """
    Returns a set of date strings (YYYY-MM-DD) that have sentiment data
    but are missing price data. Candidates for a price-only backfill.
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT date FROM stock_daily
                WHERE symbol           = %s
                AND   finbert_sentiment IS NOT NULL
                AND   close_price      IS NULL;
                """,
                (symbol,)
            )
            rows = cur.fetchall()
            return {row[0].strftime("%Y-%m-%d") for row in rows}
    except Exception as e:
        logger.error(f"❌ Postgres get_incomplete_dates error: {e}")
        return set()
    finally:
        release_conn(conn)

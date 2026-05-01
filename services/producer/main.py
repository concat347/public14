# services/producer/main.py
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from kafka import KafkaProducer
import requests
import json
import os
from datetime import datetime, timedelta, timezone
import time

POLYGON_API_KEY = os.getenv("POLYGON_API_KEY")
if not POLYGON_API_KEY:
    raise ValueError("POLYGON_API_KEY environment variable is required")

# ---------------------------------------------------------
# FASTAPI APP
# ---------------------------------------------------------
app = FastAPI(title="Stock Data Producer")

# ---------------------------------------------------------
# API KEYS
# ---------------------------------------------------------
ALPHAVANTAGE_API_KEY = os.getenv("ALPHAVANTAGE_API_KEY")
if not ALPHAVANTAGE_API_KEY:
    raise ValueError("ALPHAVANTAGE_API_KEY environment variable is required")

FINNHUB_API_KEY = os.getenv("FINNHUB_API_KEY")
if not FINNHUB_API_KEY:
    raise ValueError("FINNHUB_API_KEY environment variable is required")

# ---------------------------------------------------------
# KAFKA CONFIG
# ---------------------------------------------------------
KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:29092")
KAFKA_TOPIC = "stock-data"

# Alpha Vantage rate limiting: 5 calls/minute
ALPHAVANTAGE_CALLS_PER_MINUTE = 5
ALPHAVANTAGE_DELAY = 60 / ALPHAVANTAGE_CALLS_PER_MINUTE  # 12 seconds

# Finnhub free tier: 60 calls/minute — no meaningful delay needed between
# symbols, but we add a small courtesy pause to avoid burst rejections.
FINNHUB_DELAY = 1.0  # seconds between per-symbol Finnhub calls


# ---------------------------------------------------------
# KAFKA CONNECTION
# ---------------------------------------------------------
def get_kafka_producer():
    max_retries = 10
    retry_delay = 5

    for attempt in range(max_retries):
        try:
            producer = KafkaProducer(
                bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
                value_serializer=lambda v: json.dumps(v).encode("utf-8"),
                acks="all",
                retries=5,
                max_block_ms=10000,
            )
            print(f"✓ Connected to Kafka at {KAFKA_BOOTSTRAP_SERVERS}")
            return producer

        except Exception as e:
            print(f"❌ Kafka connection failed ({attempt+1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
            else:
                raise

def send_to_kafka(producer, topic, message):
    future = producer.send(topic, value=message)
    try:
        future.get(timeout=10)
    except Exception as e:
        print(f"❌ Kafka send failed: {e}")
        raise


# ---------------------------------------------------------
# REQUEST MODEL
# ---------------------------------------------------------
class FetchRequest(BaseModel):
    symbols: list[str]
    days: int = 7


# ---------------------------------------------------------
# ALPHA VANTAGE NEWS FETCH
# Unchanged — still the source of the AV sentiment baseline.
# ---------------------------------------------------------
def fetch_alpha_vantage_news(symbol: str, from_str: str, to_str: str):
    time_from = datetime.strptime(from_str, "%Y-%m-%d").strftime("%Y%m%dT0000")
    time_to = (datetime.strptime(to_str, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y%m%dT0000")

    url = "https://www.alphavantage.co/query"
    params = {
        "function": "NEWS_SENTIMENT",
        "tickers": symbol,
        "time_from": time_from,
        "time_to": time_to,
        "limit": 200,
        "sort": "LATEST",
        "apikey": ALPHAVANTAGE_API_KEY,
    }

    try:
        print(f"📰 Fetching Alpha Vantage news for {symbol}...")
        response = requests.get(url, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()

        if "Note" in data:
            print(f"⚠️ Alpha Vantage API limit reached: {data['Note']}")
            return []

        if "Error Message" in data:
            print(f"⚠️ Alpha Vantage error for {symbol}: {data['Error Message']}")
            return []

        if "Information" in data:
            print(f"⚠️ Alpha Vantage premium endpoint message: {data['Information']}")
            return []

        articles = data.get("feed", [])
        print(f"✓ Retrieved {len(articles)} AV news articles for {symbol}")
        return articles

    except Exception as e:
        print(f"❌ Error fetching Alpha Vantage news for {symbol}: {e}")
        return []


# ---------------------------------------------------------
# FINNHUB NEWS FETCH
# New function — provides the article feed for the local model.
# Returns articles published within [from_str, to_str] inclusive.
# Finnhub uses Unix timestamps for its date range parameters.
# ---------------------------------------------------------
def fetch_finnhub_news(symbol: str, from_str: str, to_str: str):
    """
    Fetch company news from Finnhub for a given symbol and date range.

    Finnhub's /company-news endpoint accepts Unix timestamps for from/to.
    We add one day to to_str so the end date is inclusive (Finnhub treats
    the to parameter as exclusive at midnight).

    Each article is normalised into the shape the consumer expects:
      type, symbol, date (YYYY-MM-DD), headline, summary, source, url

    No av_sentiment_score is attached — Finnhub articles are only used
    as the input feed for the local sentiment model.
    """
    try:
        # Convert date strings to Unix timestamps
        from_dt = datetime.strptime(from_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        to_dt   = (datetime.strptime(to_str, "%Y-%m-%d") + timedelta(days=1)).replace(tzinfo=timezone.utc)

        from_ts = int(from_dt.timestamp())
        to_ts   = int(to_dt.timestamp())

        print(f"📡 Fetching Finnhub news for {symbol} ({from_str} → {to_str})...")

        url = "https://finnhub.io/api/v1/company-news"
        params = {
            "symbol": symbol,
            "from":   from_str,
            "to":     to_str,
            "token":  FINNHUB_API_KEY,
        }

        response = requests.get(url, params=params, timeout=15)
        response.raise_for_status()
        articles = response.json()

        if not isinstance(articles, list):
            print(f"⚠️ Finnhub returned unexpected response for {symbol}: {articles}")
            return []

        # Filter to the requested window (Finnhub can return articles slightly
        # outside the window depending on timezone handling) and normalise shape.
        normalised = []
        for article in articles:
            raw_ts = article.get("datetime", 0)

            # Guard: skip articles with no timestamp
            if not raw_ts:
                continue

            # Convert Unix timestamp → YYYY-MM-DD in UTC
            try:
                pub_dt   = datetime.fromtimestamp(raw_ts, tz=timezone.utc)
                pub_date = pub_dt.strftime("%Y-%m-%d")
            except Exception:
                pub_date = from_str

            # Only keep articles within our requested window
            if not (from_str <= pub_date <= to_str):
                continue

            headline = article.get("headline", "").strip()
            summary  = article.get("summary",  "").strip()

            # Skip articles with no usable text
            if not headline and not summary:
                continue

            normalised.append({
                "headline":    headline,
                "summary":     summary,
                "source":      article.get("source", ""),
                "url":         article.get("url",    ""),
                "date":        pub_date,
                "raw_ts":      raw_ts,   # preserved for potential future use
            })

        print(f"✓ Retrieved {len(normalised)} Finnhub articles for {symbol}")
        return normalised

    except Exception as e:
        print(f"❌ Error fetching Finnhub news for {symbol}: {e}")
        return []


# ---------------------------------------------------------
# POLYGON PRICE FETCH
# Unchanged.
# ---------------------------------------------------------
def fetch_polygon_prices(symbol: str, from_str: str, to_str: str):
    try:
        print(f"📈 Fetching Polygon.io price data for {symbol}...")

        url = (
            f"https://api.polygon.io/v2/aggs/ticker/{symbol}"
            f"/range/1/day/{from_str}/{to_str}"
        )
        params = {
            "adjusted": "true",
            "sort": "asc",
            "limit": 120,
            "apiKey": POLYGON_API_KEY,
        }

        response = requests.get(url, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()

        if data.get("status") == "ERROR":
            print(f"⚠️ Polygon.io error for {symbol}: {data.get('error')}")
            return []

        results = data.get("results", [])
        if not results:
            print(f"⚠️ Polygon.io returned no price data for {symbol}")
            return []

        prices = []
        for bar in results:
            date_str = datetime.fromtimestamp(
                bar["t"] / 1000, tz=timezone.utc
            ).strftime("%Y-%m-%d")

            prices.append({
                "date":   date_str,
                "open":   round(float(bar["o"]), 4),
                "high":   round(float(bar["h"]), 4),
                "low":    round(float(bar["l"]), 4),
                "close":  round(float(bar["c"]), 4),
                "volume": int(bar["v"]),
            })

        print(f"✓ Retrieved {len(prices)} days of price data for {symbol}")
        return prices

    except Exception as e:
        print(f"❌ Error fetching Polygon.io price data for {symbol}: {e}")
        return []


# ---------------------------------------------------------
# MAIN FETCH ENDPOINT
# ---------------------------------------------------------
@app.post("/fetch")
async def fetch_stock_data(request: FetchRequest):
    if not request.symbols:
        raise HTTPException(status_code=400, detail="At least one symbol is required")

    if request.days < 1 or request.days > 100:
        raise HTTPException(status_code=400, detail="Days must be between 1 and 100")

    producer = get_kafka_producer()

    messages_sent = 0

    to_date   = datetime.now(tz=timezone.utc)
    from_date = to_date - timedelta(days=request.days)
    to_str    = to_date.strftime("%Y-%m-%d")
    from_str  = from_date.strftime("%Y-%m-%d")

    symbols = [s.upper().strip() for s in request.symbols]

    for symbol in symbols:

        # -------------------------------------------------------------
        # ALPHA VANTAGE NEWS
        # Still fetched — provides the AV sentiment baseline score.
        # These messages are consumed by the consumer and their
        # av_sentiment_score is averaged into the daily AV baseline.
        # -------------------------------------------------------------
        av_articles = fetch_alpha_vantage_news(symbol, from_str, to_str)

        for article in av_articles:
            time_published = article.get("time_published", "")
            try:
                pub_date = datetime.strptime(
                    time_published, "%Y%m%dT%H%M%S"
                ).strftime("%Y-%m-%d")
            except Exception:
                pub_date = to_str

            ticker_sentiment_score = None
            ticker_sentiment_label = None
            relevance_score        = None

            for ts in article.get("ticker_sentiment", []):
                if ts.get("ticker", "").upper() == symbol:
                    ticker_sentiment_score = float(ts.get("ticker_sentiment_score", 0.0))
                    ticker_sentiment_label = ts.get("ticker_sentiment_label", "Neutral")
                    relevance_score        = float(ts.get("relevance_score", 0.0))
                    break

            if ticker_sentiment_score is None:
                continue

            message = {
                "type":               "news",          # AV news — baseline only
                "symbol":             symbol,
                "date":               pub_date,
                "headline":           article.get("title", ""),
                "summary":            article.get("summary", ""),
                "source":             article.get("source", ""),
                "url":                article.get("url", ""),
                "av_sentiment_score": ticker_sentiment_score,
                "av_sentiment_label": ticker_sentiment_label,
                "relevance_score":    relevance_score,
            }
            send_to_kafka(producer, KAFKA_TOPIC, message)
            messages_sent += 1

        # -------------------------------------------------------------
        # FINNHUB NEWS
        # New feed — provides articles for the local sentiment model.
        # Sent as type "finnhub_news" so the consumer routes them
        # separately from AV articles.  No av_sentiment_score attached.
        # -------------------------------------------------------------
        fh_articles = fetch_finnhub_news(symbol, from_str, to_str)

        for article in fh_articles:
            message = {
                "type":     "finnhub_news",   # local model feed
                "symbol":   symbol,
                "date":     article["date"],
                "headline": article["headline"],
                "summary":  article["summary"],
                "source":   article["source"],
                "url":      article["url"],
                # av_sentiment_score intentionally absent — Finnhub
                # articles are only used for local model inference.
            }
            send_to_kafka(producer, KAFKA_TOPIC, message)
            messages_sent += 1

        time.sleep(FINNHUB_DELAY)

        # -------------------------------------------------------------
        # POLYGON.IO PRICE DATA
        # Unchanged.
        # -------------------------------------------------------------
        prices = fetch_polygon_prices(symbol, from_str, to_str)

        for price_row in prices:
            dt = datetime.fromisoformat(price_row["date"]).replace(tzinfo=timezone.utc)
            timestamp = int(dt.timestamp())

            message = {
                "type":      "price",
                "symbol":    symbol,
                "date":      price_row["date"],
                "timestamp": timestamp,
                "open":      price_row["open"],
                "high":      price_row["high"],
                "low":       price_row["low"],
                "close":     price_row["close"],
                "volume":    price_row["volume"],
            }
            send_to_kafka(producer, KAFKA_TOPIC, message)
            messages_sent += 1

        if symbol != symbols[-1]:
            print(f"⏳ Waiting {ALPHAVANTAGE_DELAY}s (Alpha Vantage rate limit)...")
            time.sleep(ALPHAVANTAGE_DELAY)

    # ---------------------------------------------------------
    # SEND END-OF-FETCH SIGNAL
    # ---------------------------------------------------------
    end_message = {"type": "end_of_fetch"}
    send_to_kafka(producer, KAFKA_TOPIC, end_message)
    print("📨 Sent end_of_fetch signal to Kafka")

    producer.flush()

    return {
        "status":        "success",
        "symbols":       symbols,
        "days":          request.days,
        "messages_sent": messages_sent,
        "date_range":    {"from": from_str, "to": to_str},
    }


# ---------------------------------------------------------
# HEALTH CHECK
# ---------------------------------------------------------
@app.get("/health")
async def health():
    return {
        "status":        "healthy",
        "service":       "producer",
        "kafka_servers": KAFKA_BOOTSTRAP_SERVERS,
    }


# ---------------------------------------------------------
# RUN SERVER
# ---------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)

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
 
# ---------------------------------------------------------
# KAFKA CONFIG
# ---------------------------------------------------------
KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:29092")
KAFKA_TOPIC = "stock-data"
 
# Alpha Vantage rate limiting: 5 calls/minute
ALPHAVANTAGE_CALLS_PER_MINUTE = 5
ALPHAVANTAGE_DELAY = 60 / ALPHAVANTAGE_CALLS_PER_MINUTE  # 12 seconds
 
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
# NEWS FETCH
# ---------------------------------------------------------
def fetch_alpha_vantage_news(symbol: str, from_str: str, to_str: str):
    time_from = datetime.strptime(from_str, "%Y-%m-%d").strftime("%Y%m%dT0000")
    time_to = (datetime.strptime(to_str, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y%m%dT0000")
 
    # ── DEBUG ──────────────────────────────────────────────────────────────
    # print(f"🐛 [AV] {symbol} query window: time_from={time_from}  time_to={time_to}")
    # ───────────────────────────────────────────────────────────────────────
 
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
        print(f"✓ Retrieved {len(articles)} news articles for {symbol}")
 
        # ── DEBUG ──────────────────────────────────────────────────────────
        # if articles:
        #     dates_seen = sorted({a.get("time_published", "")[:8] for a in articles})
        #     print(f"🐛 [AV] {symbol} article dates returned: {dates_seen}")
        #     print(f"🐛 [AV] {symbol} newest article: {articles[0].get('time_published')}  |  {articles[0].get('title','')[:60]}")
        #     print(f"🐛 [AV] {symbol} oldest article: {articles[-1].get('time_published')}  |  {articles[-1].get('title','')[:60]}")
        # ───────────────────────────────────────────────────────────────────
 
        return articles
 
    except Exception as e:
        print(f"❌ Error fetching Alpha Vantage news for {symbol}: {e}")
        return []
 
# ---------------------------------------------------------
# PRICE FETCH
# ---------------------------------------------------------
def fetch_polygon_prices(symbol: str, from_str: str, to_str: str):
    try:
        print(f"📈 Fetching Polygon.io price data for {symbol}...")
 
        # ── DEBUG ──────────────────────────────────────────────────────────
        # print(f"🐛 [Polygon] {symbol} query window: {from_str} → {to_str}")
        # ───────────────────────────────────────────────────────────────────
 
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
 
        # ── DEBUG ──────────────────────────────────────────────────────────
        # price_dates = [p["date"] for p in prices]
        # print(f"🐛 [Polygon] {symbol} dates returned: {price_dates}")
        # ───────────────────────────────────────────────────────────────────
 
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
 
    # ── DEBUG ──────────────────────────────────────────────────────────────
    # print(f"🐛 [fetch] UTC now={to_date.isoformat()}  from={from_str}  to={to_str}")
    # ───────────────────────────────────────────────────────────────────────
 
    symbols = [s.upper().strip() for s in request.symbols]
 
    for symbol in symbols:
 
        # -----------------------------
        # ALPHA VANTAGE NEWS
        # -----------------------------
        articles = fetch_alpha_vantage_news(symbol, from_str, to_str)
 
        for article in articles:
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
                "type":               "news",
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
 
        # -----------------------------
        # PRICE DATA
        # -----------------------------
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
        "status":       "success",
        "symbols":      symbols,
        "days":         request.days,
        "messages_sent": messages_sent,
        "date_range":   {"from": from_str, "to": to_str},
    }
 
 
# ---------------------------------------------------------
# HEALTH CHECK
# ---------------------------------------------------------
@app.get("/health")
async def health():
    return {
        "status":       "healthy",
        "service":      "producer",
        "kafka_servers": KAFKA_BOOTSTRAP_SERVERS,
    }
 
 
# ---------------------------------------------------------
# RUN SERVER
# ---------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
 

import sys
import json
import time
import math
import configparser
import yfinance as yf
from confluent_kafka import Producer

if len(sys.argv) < 3 or len(sys.argv) > 4:
    print("Usage: python producer_finance.py <config_file> <ticker> [--realtime]")
    sys.exit(1)

config_file = sys.argv[1]
ticker = sys.argv[2]
realtime = len(sys.argv) == 4 and sys.argv[3] == "--realtime"

conf = configparser.ConfigParser()
conf.read(config_file)

producer = Producer({"bootstrap.servers": conf["default"]["bootstrap.servers"]})

def delivery_report(err, msg):
    if err is not None:
        print(f"Delivery failed: {err}")
    else:
        print(f"Produced to {msg.topic()} [{msg.partition()}] at offset {msg.offset()}")

def safe_float(x):
    return float(x) if x is not None and not math.isnan(x) else None

def row_to_json(row):
    record = {
        "open":   safe_float(row["Open"]),
        "high":   safe_float(row["High"]),
        "low":    safe_float(row["Low"]),
        "close":  safe_float(row["Close"]),
        "volume": safe_float(row["Volume"]),
    }
    return json.dumps(record).encode("utf-8")

# ── REAL-TIME MODE ─────────────────────────────────────────
if realtime:
    print(f"Real-time mode: producing live quotes for {ticker}. Ctrl+C to stop.")
    try:
        while True:
            data = yf.download(ticker, period="1d", interval="1m", progress=False)

            if not data.empty:
                # Fix MultiIndex if present
                if hasattr(data.columns, "levels"):
                    data.columns = data.columns.get_level_values(0)

                latest = data.tail(1)

                for timestamp, row in latest.iterrows():
                    producer.produce(
                        topic=ticker,
                        key=str(timestamp).encode("utf-8"),
                        value=row_to_json(row),
                        callback=delivery_report
                    )
                    producer.poll(0)

            time.sleep(60)

    except KeyboardInterrupt:
        pass

# ── DEVELOPMENT MODE ──────────────────────────────────────
else:
    print(f"Dev mode: producing today's 1-minute history for {ticker}.")

    data = yf.download(ticker, period="1d", interval="1m", progress=False)

    # Fix MultiIndex
    if hasattr(data.columns, "levels"):
        data.columns = data.columns.get_level_values(0)

    for timestamp, row in data.iterrows():
        producer.produce(
            topic=ticker,
            key=str(timestamp).encode("utf-8"),
            value=row_to_json(row),
            callback=delivery_report
        )
        producer.poll(0)

producer.flush()
print("Done.")
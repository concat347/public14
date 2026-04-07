import sys
import configparser
import json
import yfinance as yf
from confluent_kafka import Producer
import math

# Check command line args
if len(sys.argv) != 3:
    print("Usage: python producer_finance.py <config_file> <ticker>")
    sys.exit(1)

config_file, ticker = sys.argv[1], sys.argv[2]

# Load Kafka config
conf = configparser.ConfigParser()
conf.read(config_file)
bootstrap_servers = conf["default"]["bootstrap.servers"]

# Initialize producer
producer_conf = {"bootstrap.servers": bootstrap_servers}
producer = Producer(producer_conf)

# Callback for delivery reports
def delivery_report(err, msg):
    if err is not None:
        print(f"Delivery failed: {err}")
    else:
        print(f"Produced to {msg.topic()} [{msg.partition()}] at offset {msg.offset()}")

print(f"Fetching data for {ticker}...")
data = yf.download(ticker, period="1d", interval="1m")

# Fix multi-index columns
if isinstance(data.columns, tuple) or hasattr(data.columns, "levels"):
    data.columns = data.columns.get_level_values(0)

for timestamp, row in data.iterrows():
    key = str(timestamp)

    # 🔥 NEW: structured JSON value
    value_dict = {
        "open": float(row["Open"]) if not math.isnan(row["Open"]) else None,
        "high": float(row["High"]) if not math.isnan(row["High"]) else None,
        "low": float(row["Low"]) if not math.isnan(row["Low"]) else None,
        "close": float(row["Close"]) if not math.isnan(row["Close"]) else None,
        "volume": float(row["Volume"]) if not math.isnan(row["Volume"]) else None,
    }

    value_json = json.dumps(value_dict)

    print(f"{key} -> {value_json}")  # optional debug

    producer.produce(
        topic=ticker,
        key=key.encode("utf-8"),
        value=value_json.encode("utf-8"),
        callback=delivery_report
    )

    producer.poll(0.1)

producer.flush()
print("All messages sent successfully.")
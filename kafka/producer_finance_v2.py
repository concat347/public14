import sys
import configparser
import json
from datetime import datetime
import yfinance as yf
from confluent_kafka import Producer


# Check command line arguments
if len(sys.argv) != 3:
    print("Usage: python producer_finance.py <config_file> <ticker>")
    sys.exit(1)

config_file, ticker = sys.argv[1], sys.argv[2]

# Load Kafka configuration
conf = configparser.ConfigParser()
conf.read(config_file)

producer_conf = {
    "bootstrap.servers": conf["default"]["bootstrap.servers"]
}

producer = Producer(producer_conf)

# Retrieve live (or recent) financial data using yfinance
data = yf.download(ticker, period="1d", interval="1m")

print(f"Producing financial data for {ticker}...")

for timestamp, row in data.iterrows():
    record_key = str(timestamp)
    record_value = json.dumps({
        "open": float(row["Open"].item() if hasattr(row["Open"], "item") else row["Open"]),
        "high": float(row["High"].item() if hasattr(row["High"], "item") else row["High"]),
        "low": float(row["Low"].item() if hasattr(row["Low"], "item") else row["Low"]),
        "close": float(row["Close"].item() if hasattr(row["Close"], "item") else row["Close"]),
        "volume": int(row["Volume"].item() if hasattr(row["Volume"], "item") else row["Volume"])
    })

    producer.produce(
        topic=ticker,
        key=record_key,
        value=record_value
    )

producer.flush()
print("All messages sent successfully.")

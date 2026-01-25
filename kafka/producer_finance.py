import sys
import configparser
import yfinance as yf
from confluent_kafka import Producer

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

for timestamp, row in data.iterrows():
    key = str(timestamp)
    value = str(row["Close"])
    producer.produce(topic=ticker, key=key, value=value, callback=delivery_report)
    producer.poll(0)

producer.flush()
print("All messages sent successfully.")

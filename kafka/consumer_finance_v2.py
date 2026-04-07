import sys
import json
import time
import configparser
from collections import defaultdict
from confluent_kafka import Consumer, KafkaError, KafkaException
import streamlit as st
import pandas as pd

# Usage:
# streamlit run consumer_finance.py -- <config_file> <ticker1> [ticker2 ...]

if len(sys.argv) < 3:
    st.error("Usage: streamlit run consumer_finance.py -- <config_file> <ticker1> [ticker2 ...]")
    st.stop()

config_file = sys.argv[1]
tickers = sys.argv[2:]

conf = configparser.ConfigParser()
conf.read(config_file)

# ── Kafka Consumer ────────────────────────────────────────
@st.cache_resource
def get_consumer():
    c = Consumer({
        "bootstrap.servers": conf["default"]["bootstrap.servers"],
        "group.id": conf["consumer"]["group.id"],
        "auto.offset.reset": conf["consumer"]["auto.offset.reset"],
    })
    c.subscribe(tickers)
    return c

# ── Data Store ────────────────────────────────────────────
@st.cache_resource
def get_store():
    return defaultdict(list)

consumer = get_consumer()
store = get_store()

# ── Poll messages ─────────────────────────────────────────
for _ in range(100):  # limit per refresh
    msg = consumer.poll(0.1)

    if msg is None:
        break

    if msg.error():
        if msg.error().code() == KafkaError._PARTITION_EOF:
            continue
        raise KafkaException(msg.error())

    topic = msg.topic()
    key = msg.key().decode("utf-8") if msg.key() else None

    try:
        record = json.loads(msg.value().decode("utf-8"))
        record["timestamp"] = key
        store[topic].append(record)

        # Prevent unlimited growth
        if len(store[topic]) > 1000:
            store[topic] = store[topic][-1000:]

    except Exception:
        continue

# ── UI ────────────────────────────────────────────────────
st.title("Kafka Finance Dashboard")
st.caption(f"Watching: {', '.join(tickers)}")

available = [t for t in tickers if t in store]

if not available:
    st.info("Waiting for messages...")
else:
    tabs = st.tabs(available)

    for tab, ticker in zip(tabs, available):
        with tab:
            df = pd.DataFrame(store[ticker])

            if df.empty:
                st.warning("No data yet")
                continue

            df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
            df = df.sort_values("timestamp").set_index("timestamp")

            st.subheader(f"{ticker} — {len(df)} records")

            st.line_chart(df[["open", "high", "low", "close"]], height=300)
            st.bar_chart(df[["volume"]], height=200)

# Auto-refresh
time.sleep(2)
st.rerun()
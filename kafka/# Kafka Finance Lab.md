# Kafka Finance Lab

Stream stock quotes from Yahoo Finance through a Kafka broker and visualize them in a Streamlit dashboard.

## Requirements

```bash
pip install confluent-kafka yfinance streamlit pandas
```

A running Kafka broker is also required. Start one with Docker Compose:

```bash
docker compose up -d
```

## Configuration

Edit `getting_started.ini` to point to your Kafka broker:

```ini
[default]
bootstrap.servers=localhost:9092

[consumer]
group.id=python_example_group_1
auto.offset.reset=earliest
```

## Producer

Fetches OHLCV (open, high, low, close, volume) data from Yahoo Finance and produces it to a Kafka topic named after the ticker.

**Dev mode** — sends today's full 1-minute history:
```bash
python producer_finance.py getting_started.ini SPY
```

**Real-time mode** — sends the latest quote every 60 seconds:
```bash
python producer_finance.py getting_started.ini SPY --realtime
```

## Consumer

Consumes messages from one or more Kafka topics and displays a live-updating dashboard with OHLC line charts and volume bar charts.

```bash
# Single ticker
streamlit run consumer_finance.py -- getting_started.ini SPY

# Multiple tickers
streamlit run consumer_finance.py -- getting_started.ini SPY AAPL MSFT
```

Open `http://localhost:8501` in your browser to view the dashboard.

## Notes

- Real-time mode only returns data during market hours (9:30am–4:00pm ET, weekdays).
- If the dashboard shows "Waiting for messages", check that the producer has run and that the consumer group ID has not already consumed the topic. Change `group.id` in `getting_started.ini` to reset.
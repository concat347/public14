# Consumer V2
import json
import streamlit as st
import pandas as pd
from argparse import ArgumentParser, FileType
from configparser import ConfigParser
from confluent_kafka import Consumer, OFFSET_BEGINNING
 
def parse_args():
    parser = ArgumentParser()
    parser.add_argument('config_file', type=FileType('r'))
    parser.add_argument('tickers', nargs='+', default=['QQQ'])
    parser.add_argument('--reset', action='store_true')
    return parser.parse_args()
 
def make_consumer(tickers, reset):
    config_parser = ConfigParser()
    config_parser.read('getting_started.ini')
    config = dict(config_parser['default'])
    config.update(config_parser['consumer'])
    c = Consumer(config)
    def reset_offset(consumer, partitions):
        if reset:
            for p in partitions:
                p.offset = OFFSET_BEGINNING
            consumer.assign(partitions)
    c.subscribe(tickers, on_assign=reset_offset)
    print('Subscribed to topics:', tickers)
    return c
 
args = parse_args()
 
# --- Streamlit UI ---
st.title('Stock OHLCV Dashboard')
 
# Initialize session state once
if 'consumer' not in st.session_state:
    st.session_state.consumer = make_consumer(args.tickers, args.reset)
    st.session_state.data = {t: pd.DataFrame(columns=['timestamp','open','high','low','close','volume'])
                             for t in args.tickers}
 
consumer = st.session_state.consumer
 
# Poll a batch of messages
for _ in range(10):
    msg = consumer.poll(0.2)
    if msg is None:
        continue
    elif msg.error():
        print("ERROR:", msg.error())
    else:
        try:
            record = json.loads(msg.value().decode('utf-8'))
        except json.JSONDecodeError:
            print("Skipping non-JSON message:", msg.value())
            continue
        topic = msg.topic()
        row = pd.DataFrame([record])
        row['timestamp'] = pd.to_datetime(row['timestamp'])
        df = st.session_state.data[topic]
        df = pd.concat([df, row], ignore_index=True).drop_duplicates('timestamp')
        st.session_state.data[topic] = df
 
selected = st.selectbox('Ticker', args.tickers)
df = st.session_state.data[selected]
 
if df.empty:
    st.write("Waiting for data...")
else:
    df_plot = df.set_index('timestamp')
    st.subheader('Open / High / Low / Close')
    st.line_chart(df_plot[['open', 'high', 'low', 'close']])
    st.subheader('Volume')
    st.bar_chart(df_plot[['volume']])
 
# Auto-rerun every 5 seconds
st.rerun()
# Producer V2
import json
from argparse import ArgumentParser, FileType
from configparser import ConfigParser
from confluent_kafka import Producer
import yfinance as yf
from datetime import date, timedelta
import time
 
def get_today():
    return date.today()
 
if __name__ == '__main__':
    # Parse the command line.
    parser = ArgumentParser()
    parser.add_argument('config_file', type=FileType('r'))
    parser.add_argument('ticker', default='QQQ')
    parser.add_argument('--topic', default=None, help='Kafka topic name (defaults to ticker)')
    parser.add_argument('--mode', choices=['dev', 'realtime'], default='dev')
    args = parser.parse_args()
 
    # Parse the configuration.
    config_parser = ConfigParser()
    config_parser.read_file(args.config_file)
    config = dict(config_parser['default'])
 
    ticker = args.ticker
    topic = args.topic if args.topic else ticker
    print('ticker', ticker, 'topic', topic)
 
    # Create Producer instance
    producer = Producer(config)
 
    def delivery_callback(err, msg):
        if err:
            print('ERROR: Message failed delivery: {}'.format(err))
        else:
            print("Produced event to topic {topic}: key = {key:12} value = {value:12}".format(
                topic=msg.topic(), key=msg.key().decode('utf-8'), value=msg.value().decode('utf-8')))
 
    while True:
        if args.mode == 'dev':
            sd = get_today()
            ed = sd + timedelta(days=1)
            dfvp = yf.download(tickers=ticker, start=sd, end=ed, interval="1m")
            dfvp.columns = [col[0] if isinstance(col, tuple) else col for col in dfvp.columns]
            for index, row in dfvp.iterrows():
                payload = {
                    'timestamp': str(index),
                    'open':   float(row['Open']),
                    'high':   float(row['High']),
                    'low':    float(row['Low']),
                    'close':  float(row['Close']),
                    'volume': float(row['Volume']),
                }
                print(payload)
                producer.produce(topic, key=str(index), value=json.dumps(payload), callback=delivery_callback)
                time.sleep(5)
        else:
            stock = yf.Ticker(ticker)
            data = stock.history(period='1d', interval='1m')
            data.columns = [col[0] if isinstance(col, tuple) else col for col in data.columns]
            if not data.empty:
                row = data.iloc[-1]
                payload = {
                    'timestamp': str(data.index[-1]),
                    'open':   float(row['Open']),
                    'high':   float(row['High']),
                    'low':    float(row['Low']),
                    'close':  float(row['Close']),
                    'volume': float(row['Volume']),
                }
                print(payload)
                producer.produce(topic, key=payload['timestamp'], value=json.dumps(payload), callback=delivery_callback)
 
        producer.poll(10000)
        producer.flush()
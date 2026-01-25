import sys
import json
import configparser
from confluent_kafka import Consumer, KafkaException, KafkaError

if len(sys.argv) != 3:
    print("Usage: python consumer_finance.py <config_file> <ticker>")
    sys.exit(1)

config_file, ticker = sys.argv[1], sys.argv[2]

conf = configparser.ConfigParser()
conf.read(config_file)

consumer_conf = {
    "bootstrap.servers": conf["default"]["bootstrap.servers"],
    "group.id": conf["consumer"]["group.id"],
    "auto.offset.reset": conf["consumer"]["auto.offset.reset"],
}

consumer = Consumer(consumer_conf)
consumer.subscribe([ticker])

print(f"Consuming detailed records from topic: {ticker}")

try:
    while True:
        msg = consumer.poll(1.0)
        if msg is None:
            continue
        if msg.error():
            if msg.error().code() == KafkaError._PARTITION_EOF:
                continue
            else:
                raise KafkaException(msg.error())
        key = msg.key().decode("utf-8") if msg.key() else None
        value = msg.value().decode("utf-8") if msg.value() else None

        try:
            record = json.loads(value)
            print(f"{key}: Open={record['open']:.2f}, High={record['high']:.2f}, "
                  f"Low={record['low']:.2f}, Close={record['close']:.2f}, Volume={record['volume']}")
        except json.JSONDecodeError:
            print(f"{key}: {value}")

except KeyboardInterrupt:
    pass
finally:
    consumer.close()
    print("Consumer closed.")

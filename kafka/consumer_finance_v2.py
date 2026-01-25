import sys
import configparser
from confluent_kafka import Consumer, KafkaException, KafkaError

# Check command line args
if len(sys.argv) != 3:
    print("Usage: python consumer_finance.py <config_file> <ticker>")
    sys.exit(1)

config_file, ticker = sys.argv[1], sys.argv[2]

# Load Kafka configuration
conf = configparser.ConfigParser()
conf.read(config_file)

consumer_conf = {
    "bootstrap.servers": conf["default"]["bootstrap.servers"],
    "group.id": conf["consumer"]["group.id"],
    "auto.offset.reset": conf["consumer"]["auto.offset.reset"],
}

# Initialize the consumer
consumer = Consumer(consumer_conf)
consumer.subscribe([ticker])

print(f"Consuming messages from topic: {ticker}")
try:
    while True:
        msg = consumer.poll(1.0)  # wait up to 1 second for a message
        if msg is None:
            continue
        if msg.error():
            if msg.error().code() == KafkaError._PARTITION_EOF:
                continue
            else:
                raise KafkaException(msg.error())
        key = msg.key().decode("utf-8") if msg.key() else None
        value = msg.value().decode("utf-8") if msg.value() else None
        print(f"Consumed record: key={key}, value={value}")
except KeyboardInterrupt:
    pass
finally:
    consumer.close()
    print("Consumer closed.")

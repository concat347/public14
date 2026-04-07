import configparser
from confluent_kafka import Consumer, KafkaError

conf = configparser.ConfigParser()
conf.read("getting_started.ini")

consumer = Consumer({
    "bootstrap.servers": conf["default"]["bootstrap.servers"],
    "group.id": "test_group_99",
    "auto.offset.reset": "earliest",
})
consumer.subscribe(["SPY"])

print("Polling...")
count = 0
while count < 5:
    msg = consumer.poll(3.0)
    if msg is None:
        print("No message")
        continue
    if msg.error():
        print(f"Error: {msg.error()}")
        continue
    print(f"Got: {msg.key()} = {msg.value()[:50]}")
    count += 1

consumer.close()

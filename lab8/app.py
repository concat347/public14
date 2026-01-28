from flask import Flask, request, jsonify
import redis
import json
import uuid
import os

app = Flask(__name__)

# Connect to Redis. 
# We use os.getenv so it works on WSL2 now AND Kubernetes later!
redis_host = os.getenv("REDIS_HOST", "localhost")
db = redis.Redis(host=redis_host, port=6379, decode_responses=True)

@app.route("/")
def index():
    return "Grocery List API is Online (Local WSL2 Docker version)!"

# 1. ADD ITEM (POST)
@app.route("/todo", methods=["POST"])
def add_item():
    data = request.get_json()
    if not data or 'item' not in data:
        return jsonify({"error": "Please provide an 'item' name"}), 400
    
    item_id = str(uuid.uuid4())
    new_entry = {"id": item_id, "item": data['item']}
    
    # Save into a Redis hash called 'grocery_list'
    db.hset("grocery_list", item_id, json.dumps(new_entry))
    return jsonify(new_entry), 201

# 2. VIEW ALL ITEMS (GET)
@app.route("/todo", methods=["GET"])
def get_all():
    all_data = db.hgetall("grocery_list")
    list_items = [json.loads(val) for val in all_data.values()]
    return jsonify(list_items)

# 3. DELETE ITEM (DELETE)
@app.route("/todo/<item_id>", methods=["DELETE"])
def delete_item(item_id):
    deleted = db.hdel("grocery_list", item_id)
    if deleted:
        return jsonify({"message": f"Item {item_id} removed"}), 200
    return jsonify({"error": "Item not found"}), 404

if __name__ == "__main__":
    # 0.0.0.0 makes the app accessible to your Windows browser too!
    app.run(debug=True, host='0.0.0.0', port=5000)
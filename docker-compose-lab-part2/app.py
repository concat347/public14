import time
import redis.asyncio as redis
from fastapi import FastAPI

app = FastAPI()
cache = redis.Redis(host='redis', port=6379, decode_responses=True)

async def get_hit_count():
    retries = 5
    while True:
        try:
            # Use 'await' because redis-py is asynchronous
            return await cache.incr('hits')
        except redis.exceptions.ConnectionError as exc:
            if retries == 0:
                raise exc
            retries -= 1
            await asyncio.sleep(0.5)

@app.get('/')
async def hello():
    count = await get_hit_count()
    return {"message": f"Hello! I have been seen {count} times."}

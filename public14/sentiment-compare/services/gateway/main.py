# services/gateway/main.py
from fastapi import FastAPI, HTTPException, Depends, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from datetime import datetime, timedelta
from collections import defaultdict
import jwt
import os
import httpx
import time
import psycopg2
import psycopg2.extras
import logging

logger = logging.getLogger(__name__)

# FASTAPI APP
app = FastAPI(title="Stock Sentiment Gateway")

# SECURITY / AUTH
security = HTTPBearer()
SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60

# Simple in-memory user store
USERS_DB = {
    "trader": "password123",
    "demo":   "demo123",
}

def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    try:
        token   = credentials.credentials
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username = payload.get("sub")
        if username is None:
            raise HTTPException(status_code=401, detail="Invalid token")
        return username
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

# SERVICE URLS
PRODUCER_URL = os.getenv("PRODUCER_URL", "http://producer:8001")
DATA_URL     = os.getenv("DATA_URL",     "http://data:8003")

# DATABASE CONFIG
DB_CONFIG = {
    "host":     os.getenv("POSTGRES_HOST",     "postgres"),
    "dbname":   os.getenv("POSTGRES_DB",       "stockdb"),
    "user":     os.getenv("POSTGRES_USER",      "stockuser"),
    "password": os.getenv("POSTGRES_PASSWORD", "stockpass"),
}

# ---------------------------------------------------------------------------
# Persistent metrics helpers
# ---------------------------------------------------------------------------

def get_db_conn():
    return psycopg2.connect(**DB_CONFIG)


def ensure_metrics_table():
    """Create the gateway_metrics table if it doesn't exist yet."""
    ddl = """
    CREATE TABLE IF NOT EXISTS gateway_metrics (
        endpoint        TEXT PRIMARY KEY,
        calls           BIGINT  NOT NULL DEFAULT 0,
        total_latency   FLOAT   NOT NULL DEFAULT 0.0,
        min_latency     FLOAT,
        max_latency     FLOAT   NOT NULL DEFAULT 0.0,
        errors          BIGINT  NOT NULL DEFAULT 0,
        last_updated    TIMESTAMP DEFAULT NOW()
    );
    """
    try:
        with get_db_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(ddl)
            conn.commit()
        logger.info("gateway_metrics table ready")
    except Exception as e:
        logger.error(f"Could not create gateway_metrics table: {e}")


def load_metrics_from_db():
    """
    Read all rows from gateway_metrics into the in-memory dicts so that
    previous sessions' data is immediately available after a restart.
    """
    try:
        with get_db_conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                cur.execute("SELECT * FROM gateway_metrics;")
                rows = cur.fetchall()

        for row in rows:
            ep = row["endpoint"]
            usage_stats[ep]                        = row["calls"]
            latency_stats[ep]["count"]             = row["calls"]
            latency_stats[ep]["total_latency"]     = row["total_latency"]
            latency_stats[ep]["min_latency"]       = row["min_latency"] if row["min_latency"] is not None else float("inf")
            latency_stats[ep]["max_latency"]       = row["max_latency"]
            latency_stats[ep]["errors"]            = row["errors"]

        logger.info(f"Loaded metrics for {len(rows)} endpoint(s) from database")
    except Exception as e:
        logger.warning(f"Could not load metrics from database (starting fresh): {e}")


def flush_metric_to_db(path: str):
    """
    Upsert the current in-memory stats for a single endpoint into Postgres.
    Called after every request so data survives an unexpected shutdown.
    """
    stats   = latency_stats[path]
    min_lat = stats["min_latency"]
    if min_lat == float("inf"):
        min_lat = None

    sql = """
    INSERT INTO gateway_metrics
        (endpoint, calls, total_latency, min_latency, max_latency, errors, last_updated)
    VALUES
        (%s, %s, %s, %s, %s, %s, NOW())
    ON CONFLICT (endpoint) DO UPDATE SET
        calls         = EXCLUDED.calls,
        total_latency = EXCLUDED.total_latency,
        min_latency   = LEAST(gateway_metrics.min_latency, EXCLUDED.min_latency),
        max_latency   = GREATEST(gateway_metrics.max_latency, EXCLUDED.max_latency),
        errors        = EXCLUDED.errors,
        last_updated  = NOW();
    """
    try:
        with get_db_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (
                    path,
                    usage_stats[path],
                    stats["total_latency"],
                    min_lat,
                    stats["max_latency"],
                    stats["errors"],
                ))
            conn.commit()
    except Exception as e:
        logger.warning(f"Could not flush metrics for {path}: {e}")


# METRICS STORAGE (in-memory, seeded from DB on startup)
usage_stats = defaultdict(int)

latency_stats = defaultdict(lambda: {
    "count":         0,
    "total_latency": 0.0,
    "min_latency":   float("inf"),
    "max_latency":   0.0,
    "errors":        0,
})

# STARTUP EVENT
@app.on_event("startup")
async def startup_event():
    ensure_metrics_table()
    load_metrics_from_db()


# METRICS MIDDLEWARE
@app.middleware("http")
async def metrics_middleware(request, call_next):
    path       = request.url.path
    start_time = time.time()

    try:
        response    = await call_next(request)
        status_code = response.status_code
    except Exception:
        latency_stats[path]["errors"] += 1
        raise

    duration = time.time() - start_time

    usage_stats[path] += 1
    stats = latency_stats[path]
    stats["count"]         += 1
    stats["total_latency"] += duration
    stats["min_latency"]    = min(stats["min_latency"], duration)
    stats["max_latency"]    = max(stats["max_latency"], duration)

    if status_code >= 400:
        stats["errors"] += 1

    flush_metric_to_db(path)
    return response


# REQUEST MODELS
class LoginRequest(BaseModel):
    username: str
    password: str

class FetchRequest(BaseModel):
    symbols: list[str]
    days: int = 7


# ---------------------------------------------------------
# ROUTES
# ---------------------------------------------------------

@app.post("/api/login")
async def login(request: LoginRequest):
    if request.username not in USERS_DB or USERS_DB[request.username] != request.password:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
        )
    token = create_access_token({"sub": request.username})
    return {"access_token": token, "token_type": "bearer"}


@app.post("/api/fetch")
async def fetch_data(request: FetchRequest, username: str = Depends(verify_token)):
    timeout_seconds = max(120, len(request.symbols) * 60)
    try:
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            response = await client.post(
                f"{PRODUCER_URL}/fetch",
                json={"symbols": request.symbols, "days": request.days},
            )
            response.raise_for_status()
            return response.json()
    except httpx.HTTPError as e:
        raise HTTPException(status_code=500, detail=f"Error communicating with producer: {e}")


@app.get("/api/data/{symbol}")
async def get_stock_data(symbol: str, username: str = Depends(verify_token)):
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{DATA_URL}/timeseries/{symbol}")
            response.raise_for_status()
            return response.json()
    except httpx.HTTPError as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving data: {e}")


@app.get("/api/news/{symbol}")
async def get_news(symbol: str, limit: int = 20, username: str = Depends(verify_token)):
    """
    Proxy the latest scored articles for a symbol from the data service.
    JWT-protected on the same basis as /api/data/{symbol}.

    Query parameters forwarded to the data service:
        limit  int  Number of articles to return (default 20, capped at 100
                    by the data service).
    """
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{DATA_URL}/news/{symbol}",
                params={"limit": limit},
            )
            response.raise_for_status()
            return response.json()
    except httpx.HTTPError as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving news: {e}")


# ---------------------------------------------------------
# ADMIN ENDPOINTS
# ---------------------------------------------------------

@app.get("/api/admin/metrics")
async def get_metrics(username: str = Depends(verify_token)):
    """Return usage, latency, and error statistics for all endpoints."""
    metrics = {}
    for endpoint, stats in latency_stats.items():
        count       = stats["count"]
        avg_latency = stats["total_latency"] / count if count > 0 else 0.0
        metrics[endpoint] = {
            "calls":       usage_stats[endpoint],
            "avg_latency": round(avg_latency, 4),
            "min_latency": round(stats["min_latency"], 4) if stats["min_latency"] != float("inf") else None,
            "max_latency": round(stats["max_latency"], 4),
            "errors":      stats["errors"],
        }
    return {
        "generated_at": datetime.utcnow().isoformat(),
        "metrics":      metrics,
    }


@app.delete("/api/admin/metrics")
async def reset_metrics(username: str = Depends(verify_token)):
    """
    Wipe all accumulated metrics — both in-memory and in Postgres.
    Useful when you want to start measuring a clean baseline.
    """
    usage_stats.clear()
    latency_stats.clear()
    try:
        with get_db_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM gateway_metrics;")
            conn.commit()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not reset metrics in database: {e}")
    return {"status": "ok", "message": "All metrics have been reset."}


# ---------------------------------------------------------
# HEALTH CHECK
# ---------------------------------------------------------

@app.get("/health")
async def health():
    return {"status": "healthy", "service": "gateway"}


# ---------------------------------------------------------
# RUN SERVER
# ---------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

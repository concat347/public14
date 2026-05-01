"""
Sentiment Compare — Load Test
==============================
Tests the Gateway → Data Service → PostgreSQL path only.
Does NOT trigger the producer or touch any external APIs.

Pre-requisite:
  Run one manual fetch first to populate PostgreSQL with data, e.g.:
    curl -X POST http://<YOUR_GCP_IP>/api/fetch \
         -H "Authorization: Bearer <token>" \
         -H "Content-Type: application/json" \
         -d '{"symbols": ["AAPL", "GOOGL", "MSFT", "AMZN", "TSLA"], "days": 7}'

Install:
  pip install locust

Run:
  locust -f locustfile.py --host=http://<YOUR_GCP_IP>
  Then open http://localhost:8089 in your browser.

Suggested test runs:
  Run 1 (baseline):  1 replica  each for gateway + data — 25 users, ramp 5/sec
  Run 2 (scaled):    3 replicas each for gateway + data — 25 users, ramp 5/sec
  Compare the latency charts and CSV exports for your performance report.
"""

from locust import HttpUser, task, between, events
import logging
import random

# ── symbols that were pre-populated by your manual fetch ──────────────────────
SYMBOLS = ["AAPL", "GOOGL", "MSFT", "AMZN", "TSLA"]

logger = logging.getLogger(__name__)


class SentimentCompareUser(HttpUser):
    """
    Simulates a dashboard user who:
      1. Logs in once and obtains a JWT (on_start)
      2. Repeatedly loads chart data for random symbols  (weight 4)
      3. Occasionally checks the admin metrics panel     (weight 1)

    The producer / fetch endpoint is intentionally excluded so that
    no external API calls (Alpha Vantage, Polygon.io) are made.
    """

    # Each simulated user waits 1–3 seconds between tasks,
    # mimicking a real user clicking around the dashboard.
    wait_time = between(1, 3)

    def on_start(self):
        """Called once per simulated user — log in and store the JWT."""
        self.token = None
        self._login()

    def _login(self):
        """POST /api/login and store the Bearer token."""
        with self.client.post(
            "/api/login",
            json={"username": "trader", "password": "password123"},
            name="/api/login",
            catch_response=True,
        ) as resp:
            if resp.status_code == 200:
                self.token = resp.json().get("access_token")
                resp.success()
            else:
                resp.failure(f"Login failed: {resp.status_code} {resp.text}")
                logger.warning("Login failed — subsequent requests will also fail")

    def _auth_headers(self):
        return {"Authorization": f"Bearer {self.token}"}

    # ── tasks ──────────────────────────────────────────────────────────────────

    @task(4)
    def load_chart_data(self):
        """
        GET /api/data/{symbol}
        Gateway → Data Service → PostgreSQL
        This is the primary scalability target.
        Cycles through the pre-populated symbols in order so every symbol
        gets hit evenly across the user pool.
        """
        if not self.token:
            self._login()
            return

        # Round-robin across symbols using Locust's user index
        symbol = random.choice(SYMBOLS)

        with self.client.get(
            f"/api/data/{symbol}",
            headers=self._auth_headers(),
            name="/api/data/{symbol}",   # group all symbols under one label
            catch_response=True,
        ) as resp:
            if resp.status_code == 200:
                resp.success()
            elif resp.status_code == 401:
                # Token may have expired — re-login and retry once
                resp.failure("401 — refreshing token")
                self._login()
            else:
                resp.failure(f"Unexpected {resp.status_code}: {resp.text}")

    @task(1)
    def load_admin_metrics(self):
        """
        GET /api/admin/metrics
        Gateway → PostgreSQL (metrics table)
        Low-frequency task, mirrors the dashboard's admin panel polling.
        """
        if not self.token:
            self._login()
            return

        with self.client.get(
            "/api/admin/metrics",
            headers=self._auth_headers(),
            name="/api/admin/metrics",
            catch_response=True,
        ) as resp:
            if resp.status_code == 200:
                resp.success()
            elif resp.status_code == 401:
                resp.failure("401 — refreshing token")
                self._login()
            else:
                resp.failure(f"Unexpected {resp.status_code}: {resp.text}")

    @task(1)
    def health_check(self):
        """
        GET /health
        No auth required. Confirms the gateway pod itself is alive.
        Useful as a baseline latency reference in your report.
        """
        with self.client.get(
            "/health",
            name="/health",
            catch_response=True,
        ) as resp:
            if resp.status_code == 200:
                resp.success()
            else:
                resp.failure(f"Health check failed: {resp.status_code}")


# ── event hooks for console logging ───────────────────────────────────────────

@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    logger.info("=" * 60)
    logger.info("Sentiment Compare load test starting")
    logger.info(f"Target host : {environment.host}")
    logger.info(f"Symbols     : {SYMBOLS}")
    logger.info("Excluded    : /api/fetch (no external API calls)")
    logger.info("=" * 60)

@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    logger.info("Load test complete — export CSV from the Locust web UI")
    logger.info("  Stats CSV  : http://localhost:8089/stats/requests/csv")
    logger.info("  Failures   : http://localhost:8089/stats/failures/csv")
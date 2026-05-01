Sentiment Compare — Session Notes
Last updated: April 12, 2026
Purpose: Upload this file at the start of the next conversation so Claude can resume without losing context.

1. What This App Is
A microservices application for a university Microservices final project. It fetches stock news from Alpha Vantage, scores it using FinBERT (a financial NLP model from HuggingFace), and displays sentiment scores alongside price data on an interactive Plotly Dash dashboard. The core research question is whether pre-market news sentiment predicts end-of-day closing price.
The app is fully working locally. The GKE deployment is the only remaining task.

2. Local Setup

Machine: Windows 11, i7-13700, 32GB RAM, RTX 3050 OEM (CUDA capable)
Environment: WSL2 running Ubuntu
Project location: ~/mfp5/sentiment-compare
Local deployment: docker compose up --build -d
Dashboard: http://localhost:8050


3. Architecture
Browser → Dashboard (Dash :8050)
              → Gateway (FastAPI :8000)  ← JWT auth
                  → Producer (FastAPI :8001)
                        → Alpha Vantage API (news + AV sentiment)
                        → Polygon.io API (daily OHLCV price)
                        → Kafka/Redpanda (:29092)
                              → Consumer (Python, no port)
                                    → FinBERT (ProsusAI/finbert)
                                    → PostgreSQL (:5432)
                                          → Data Service (FastAPI :8003)
                                                → Dashboard (chart data)

4. Database
Two PostgreSQL tables in database stockdb:
sql-- Primary data table
CREATE TABLE stock_daily (
    id                  SERIAL PRIMARY KEY,
    symbol              TEXT NOT NULL,
    date                DATE NOT NULL,
    open_price          FLOAT,
    close_price         FLOAT,
    volume              BIGINT,
    finbert_sentiment   FLOAT,
    finbert_confidence  FLOAT,
    finbert_explanation TEXT,
    av_sentiment        FLOAT,
    article_count       INT,
    created_at          TIMESTAMP DEFAULT NOW(),
    UNIQUE(symbol, date)
);

-- Gateway metrics table (created automatically on gateway startup)
CREATE TABLE gateway_metrics (
    endpoint        TEXT PRIMARY KEY,
    calls           BIGINT  NOT NULL DEFAULT 0,
    total_latency   FLOAT   NOT NULL DEFAULT 0.0,
    min_latency     FLOAT,
    max_latency     FLOAT   NOT NULL DEFAULT 0.0,
    errors          BIGINT  NOT NULL DEFAULT 0,
    last_updated    TIMESTAMP DEFAULT NOW()
);

5. Bugs Fixed (Previous Session — March 20)
Bug 1 — Price backfill never worked
Problem: The consumer could only backfill a date that had news articles in the current Kafka buffer. If Alpha Vantage returned no articles for a date on a subsequent fetch, the row stayed with NULL price forever even though Polygon had the closing bar.
Fix: Added get_incomplete_dates() to postgres.py and a separate backfill_price() function. The consumer now runs a dedicated backfill step after the FinBERT loop that checks for price-only updates independently of whether news articles are present.
Bug 2 — Upsert could wipe good sentiment data
Problem: The ON CONFLICT DO UPDATE in write_daily_record() unconditionally overwrote all fields including sentiment. A backfill passing NULL for sentiment would have destroyed existing scores.
Fix: Wrapped all sentiment fields in COALESCE(EXCLUDED.value, stock_daily.value) so existing sentiment is never overwritten by a NULL incoming value.

6. Known Limitation — Alpha Vantage Free Tier
Alpha Vantage free tier caps news responses at 50 articles regardless of the limit parameter (producer sets limit=200). For a heavily covered stock like NVDA, 50 articles only spans 2-3 days. The app is working correctly — this is an API tier constraint. Accepted as a known limitation; the database grows organically with daily fetches.

7. Project Requirements Status
Core requirements (85%)
RequirementStatusMultiple services with REST + event streaming✅ DoneDeployed on cloud platform⏳ GKE deployment in progressJWT access controls on APIs✅ Done (gateway service)Usage statistics + admin endpoint✅ Done (visible in dashboard)
Additional requirements (15% + extra credit)
RequirementStatusKafka event streaming✅ Done (Redpanda)Storage system in containerized form✅ Done (in-cluster PostgreSQL StatefulSet)Machine learning service (FinBERT)✅ DoneNovel design and usefulness✅ DoneContainer orchestration (Kubernetes)⏳ GKE deployment in progress

8. GKE Deployment — Current State
Google Cloud account
ItemValueGoogle accountonetonegg@gmail.comFree trial credit$300 remaining — expires April 28, 2026GCP projectsentiment-compare-gkeBilling account ID01D94A-24F273-DFED2EBilling linked to projectNOT YET — link immediately before Step 8gcloud CLISDK 555.0.0, authenticated, project setkubectlv1.34.1, installed and ready
Infrastructure decisions

PostgreSQL: In-cluster StatefulSet with a 5Gi PersistentVolumeClaim. Simpler than Cloud SQL, self-contained, and demonstrates containerized storage. Data survives pod restarts via the PVC.
Kafka: Ephemeral Redpanda Deployment inside the cluster — no PVC needed. All durable state is in PostgreSQL.
Images: Stored in Google Artifact Registry at us-central1-docker.pkg.dev/sentiment-compare-gke/sentiment-repo/
Image push: Done manually with docker tag and docker push (no push script).

Manifest files
All files are in ~/mfp5/sentiment-compare/k8s/ — all filenames are lowercase:
FileStatusNotessecrets.yaml✅ ReadyContains real API keys — gitignoredpostgres.yaml✅ ReadyStatefulSet + PVC + ClusterIP Serviceredpanda.yaml✅ ReadyEphemeral Deployment + ClusterIP Serviceproducer.yaml✅ ReadyDeployment + ClusterIP Serviceconsumer.yaml✅ ReadyDeployment only, no Servicegateway.yaml✅ ReadyDeployment + ClusterIP Servicedata.yaml✅ ReadyDeployment + ClusterIP Servicedashboard.yaml✅ ReadyDeployment + NodePort Service + Ingress
No Cloud SQL Auth Proxy. Earlier drafts used Cloud SQL with a sidecar proxy container in consumer and data. This was replaced with the in-cluster StatefulSet. The sql-proxy-key secret is no longer needed.
Key fixes made to manifests (April 12)

gateway.yaml: corrected DATA_SERVICE_URL → DATA_URL and JWT_SECRET → SECRET_KEY to match the gateway source code; added the four Postgres env vars for metrics persistence
consumer.yaml: removed Cloud SQL proxy sidecar; POSTGRES_HOST set to postgres
data.yaml: removed Cloud SQL proxy sidecar; POSTGRES_HOST set to postgres
postgres.yaml: new file — StatefulSet, PVC, and ClusterIP Service


9. Deployment Sequence — Next Step is Step 2
No charges are incurred until Step 8 (GKE cluster). Step 6 (Cloud SQL) has been eliminated.
StepWhat happensCharges?Step 2 ← START HEREEnable 4 GCP APIsNoStep 3Create Artifact Registry repo, configure Docker auth~$0.10/moStep 4Tag and push images manually to Artifact Registry~$0.10/moStep 7Verify gcloud project and credentialsNoStep 1Link billing to projectEnables billingStep 8Create GKE cluster (3x e2-small, us-central1)~$1.50-2.00/dayStep 9kubectl apply -f k8s/—
Step 2 — Enable GCP APIs
bashgcloud services enable container.googleapis.com
gcloud services enable artifactregistry.googleapis.com
gcloud services enable sqladmin.googleapis.com
gcloud services enable cloudresourcemanager.googleapis.com
Step 3 — Create Artifact Registry repo and configure Docker auth
bashgcloud artifacts repositories create sentiment-repo \
  --repository-format=docker \
  --location=us-central1

gcloud auth configure-docker us-central1-docker.pkg.dev
Step 4 — Tag and push images manually
Run these from the project root. Your local images are already built.
bashREGISTRY="us-central1-docker.pkg.dev/sentiment-compare-gke/sentiment-repo"

docker tag sentiment-compare-gateway   $REGISTRY/sentiment-compare-gateway:latest
docker tag sentiment-compare-producer  $REGISTRY/sentiment-compare-producer:latest
docker tag sentiment-compare-consumer  $REGISTRY/sentiment-compare-consumer:latest
docker tag sentiment-compare-data      $REGISTRY/sentiment-compare-data:latest
docker tag sentiment-compare-dashboard $REGISTRY/sentiment-compare-dashboard:latest

docker push $REGISTRY/sentiment-compare-gateway:latest
docker push $REGISTRY/sentiment-compare-producer:latest
docker push $REGISTRY/sentiment-compare-consumer:latest   # 2.91GB — will take a while
docker push $REGISTRY/sentiment-compare-data:latest
docker push $REGISTRY/sentiment-compare-dashboard:latest
Step 7 — Verify credentials
bashgcloud config get-value project    # should return: sentiment-compare-gke
gcloud auth list                   # should show onetonegg@gmail.com as active
Step 1 — Link billing (do this just before creating the cluster)
bashgcloud billing projects link sentiment-compare-gke \
  --billing-account=01D94A-24F273-DFED2E
Step 8 — Create GKE cluster
bashgcloud container clusters create sentiment-cluster \
  --num-nodes=3 \
  --machine-type=e2-standard-2 \
  --region=us-central1

gcloud container clusters get-credentials sentiment-cluster --region=us-central1
Step 9 — Deploy
bashkubectl apply -f k8s/
Check that everything comes up:
bashkubectl get pods --watch
The consumer will crash-loop for 1-2 minutes until postgres is ready — this is normal. All pods should reach Running status within a few minutes. The dashboard Ingress will take 3-5 minutes to provision a public IP.
bashkubectl get ingress dashboard-ingress
Once an external IP appears, open it in a browser. That's your screenshot.

10. Cleanup (after screenshots)
bashgcloud container clusters delete sentiment-cluster --region=us-central1
This stops the ~$1.50-2.00/day cluster charge. The Artifact Registry images remain but cost only cents per month.

11. Local Docker Images (confirmed present)
ImageSizesentiment-compare-consumer2.91GB (includes FinBERT)sentiment-compare-producer232MBsentiment-compare-dashboard555MBsentiment-compare-data241MBsentiment-compare-gateway228MB

12. How to Resume

Upload this file (session-notes.md) at the start of the new conversation
Tell Claude: "I am resuming work on my sentiment-compare GKE deployment. Please read the session notes."
Pick up at Step 2 in Section 9 above
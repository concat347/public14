FROM python:3.9-slim

WORKDIR /app

# 1. Install dependencies first (better for build speed)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 2. Copy the code last
COPY . .

EXPOSE 5000

ENV PYTHONUNBUFFERED=1
# Default to 'localhost', but Kubernetes will override this
ENV REDIS_HOST=localhost

CMD ["gunicorn", "-b", "0.0.0.0:5000", "app:app"]

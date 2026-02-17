FROM python:3.9-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 5000

ENV PYTHONUNBUFFERED=1
# Default to 'localhost'
ENV REDIS_HOST=localhost

CMD ["gunicorn", "-b", "0.0.0.0:5000", "app:app"]

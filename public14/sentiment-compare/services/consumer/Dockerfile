FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN python - <<EOF
from transformers import AutoTokenizer, AutoModelForSequenceClassification
model_name = "ProsusAI/finbert"
print(f"Downloading tokenizer for {model_name}...")
AutoTokenizer.from_pretrained(model_name)
print(f"Downloading model for {model_name}...")
AutoModelForSequenceClassification.from_pretrained(model_name)
EOF

COPY . .

CMD ["python", "main.py"]
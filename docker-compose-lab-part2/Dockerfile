FROM python:3.10-alpine
WORKDIR /code
# Install dependencies
COPY requirements.txt requirements.txt
RUN pip install -r requirements.txt
# Copy the rest of the code
COPY . .
# Expose port 8000 (FastAPI default)
EXPOSE 8000
# Run using uvicorn
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]

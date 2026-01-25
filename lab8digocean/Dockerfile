# Use a Python base image
FROM python:3.9-slim

# Set the working directory inside the container
WORKDIR /app

# Copy the current directory contents into the container
COPY . /app

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Expose port 5000 for the Flask app
EXPOSE 5000

# Set environment variable to prevent buffering of logs
ENV PYTHONUNBUFFERED=1

# Run the Flask app using Gunicorn (more efficient for production)
CMD ["gunicorn", "-b", "0.0.0.0:5000", "app:app"]

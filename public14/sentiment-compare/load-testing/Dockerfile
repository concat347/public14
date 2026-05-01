FROM python:3.11-slim
WORKDIR /locust
RUN pip install locust==2.24.0
COPY locustfile.py .
ENTRYPOINT ["locust"]
# Simple Dockerfile to run the Todo Service on port 8000
FROM python:3.11-slim

WORKDIR /app

COPY server.py ./

EXPOSE 8000

CMD ["python", "server.py"]


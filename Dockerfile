# Simple Dockerfile to run the Hello World service
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000

WORKDIR /app

COPY app.py /app/

EXPOSE 8000

CMD ["python", "app.py"]


# Simple runtime image for the Hello World service
FROM python:3.12-slim

# Avoid buffering stdout/stderr
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000

WORKDIR /app
COPY app.py ./

EXPOSE 8000

CMD ["python", "app.py"]


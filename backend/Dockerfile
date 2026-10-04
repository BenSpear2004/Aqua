FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN useradd --create-home appuser
COPY --chown=appuser:appuser main.py .
COPY --chown=appuser:appuser auth ./auth
COPY --chown=appuser:appuser nl2sql ./nl2sql
USER appuser

# 127.0.0.1 only: the public reaches the API through nginx, which adds
# the rate limit. Commands on the server itself still use localhost:8000.
CMD ["uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8000"]

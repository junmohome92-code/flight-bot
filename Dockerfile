FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app

COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir . \
    && python -m playwright install --with-deps chromium \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /data /debug

CMD ["python", "-m", "flight_bot"]

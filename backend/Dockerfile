FROM python:3.12-slim

WORKDIR /app

# System deps occasionally needed by numpy/pandas wheels.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Optional deps are best-effort; never fail the image build on them.
COPY requirements-optional.txt .
RUN pip install --no-cache-dir -r requirements-optional.txt || \
    echo "WARN: optional deps (vectorbt) not installed — engine runs without them."

COPY . .

ENV WINDFALL_DATA_DIR=/app/data
ENV WINDFALL_DB=/app/data/windfall.duckdb
ENV PYTHONUNBUFFERED=1

EXPOSE 8503
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8503"]

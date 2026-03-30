# Trading Bot Skills — Dockerfile
# Usage:
#   docker build -t trading-bot-skills .
#   docker run --env-file .env --name bot trading-bot-skills

FROM python:3.11-slim

# System deps for numpy/pandas build
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies (cached layer)
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY clients/     ./clients/
COPY core/        ./core/
COPY skills/      ./skills/
COPY orchestrator/ ./orchestrator/
COPY config/      ./config/

# Non-root user
RUN useradd -m botuser && chown -R botuser:botuser /app
USER botuser

CMD ["python", "orchestrator/main.py", "--mode", "demo"]

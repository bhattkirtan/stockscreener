# Trading Bot + Backtest + Viewer image
# One image, different CMD per service in docker-compose.yml:
#   bot              → python orchestrator/main.py --mode demo
#   backtest-viewer  → python view_trades.py --host 0.0.0.0 --results-dir /data/results
#   backtest-runner  → python run_skills_backtest.py  (profile=backtest, run on demand)

FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends gcc g++ \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps — base bot + viewer + backtest + API server
RUN pip install --no-cache-dir \
    pandas \
    numpy \
    pytz \
    pyyaml \
    requests \
    cachetools \
    python-dotenv \
    websockets \
    feedparser \
    beautifulsoup4 \
    lxml \
    openpyxl \
    xlsxwriter \
    scipy \
    plotly \
    dash \
    fastapi \
    uvicorn[standard]

# Copy full source (bot + backtest + viewer scripts)
COPY clients/      ./clients/
COPY core/         ./core/
COPY skills/       ./skills/
COPY orchestrator/ ./orchestrator/
COPY config/       ./config/
COPY run_skills_backtest.py fetch_data.py view_trades.py backtest_api.py bot_control_api.py bar_updater.py ./

# Persistent data dirs (overridden by volumes in docker-compose)
RUN useradd -m botuser \
    && mkdir -p /data/results /data/logs /data/price_data \
    && chown -R botuser:botuser /app /data
USER botuser

# Default: run live/demo bot — override via `command:` in docker-compose
CMD ["python", "orchestrator/main.py", "--mode", "demo"]

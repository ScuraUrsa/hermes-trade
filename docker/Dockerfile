FROM python:3.12-slim

LABEL org.opencontainers.image.title="HermesTrade"
LABEL org.opencontainers.image.description="AI/LLM Algorithmic Trading System"
LABEL org.opencontainers.image.authors="Filip Kaźmierczak"

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src/ src/

RUN pip install --no-cache-dir ".[dev,llm,brokers]"

COPY config/ config/

ENV PYTHONPATH=/app/src
ENV HERMES_TRADE_MODE=paper

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import hermes_trade; print(hermes_trade.__version__)" || exit 1

ENTRYPOINT ["python", "-m", "hermes_trade"]
CMD ["--mode", "paper", "--config", "config/default.yaml"]

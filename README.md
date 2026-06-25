# HermesTrade — AI/LLM Algorithmic Trading System

[![CI](https://github.com/ScuraUrsa/hermes-trade/actions/workflows/ci.yml/badge.svg)](https://github.com/ScuraUrsa/hermes-trade/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Event-driven algorithmic trading system powered by AI/LLM. Monitors news, social media, and market data in real-time, analyzes sentiment with FinBERT, and executes trades through multiple broker APIs.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                      HERMES AGENT (Orchestrator)                │
│  - Manages cronjobs / watchers                                  │
│  - Coordinates skills & modules                                 │
│  - Health monitoring                                             │
└─────────────────────────────────────────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        ▼                     ▼                     ▼
┌───────────────┐    ┌───────────────┐    ┌───────────────┐
│  MONITORING   │    │   ANALYSIS    │    │  EXECUTION    │
│  (Watchers)   │    │  (LLM Engine) │    │ (Order Mgr)   │
└───────────────┘    └───────────────┘    └───────────────┘
│                     │                     │
│ • Twitter/X Stream  │ • FinBERT           │ • Alpaca API
│ • RSS/News Feeds    │ • FinGPT/Llama3     │ • IBKR API
│ • YouTube Monitor   │ • Sentiment Score   │ • XTB API
│ • GDELT/EventReg    │ • Impact Assessment │ • Risk Check
└───────────────┘    └───────────────┘    └───────────────┘
        │                     │                     │
        └─────────────────────┼─────────────────────┘
                              ▼
                    ┌───────────────────┐
                    │   EVENT BUS       │
                    │  (Redis Streams)  │
                    └───────────────────┘
                              │
                    ┌───────────────────┐
                    │   DATA STORE      │
                    │  (PostgreSQL +    │
                    │   TimescaleDB)    │
                    └───────────────────┘
```

## Key Features

- **Real-time monitoring**: Twitter/X, RSS feeds, news APIs, YouTube transcripts
- **AI sentiment analysis**: FinBERT + Llama 3 for financial text understanding
- **Dual-model architecture**: Model A (interpretation) + Model B (decision)
- **Multi-broker execution**: Alpaca, Interactive Brokers, XTB
- **Event-driven**: Redis Streams for sub-millisecond message passing
- **Backtesting**: Historical replay with walk-forward analysis
- **Paper trading**: Test strategies risk-free before live deployment
- **Risk management**: Position limits, stop-loss, daily loss caps

## Quick Start

### Prerequisites

- Python 3.11+
- Redis 7+
- [Optional] Ollama for local LLM inference
- [Optional] Docker for containerized deployment

### Installation

```bash
git clone https://github.com/ScuraUrsa/hermes-trade.git
cd hermes-trade
pip install ".[dev]"
```

### Configuration

```bash
cp config/.env.example config/.env
# Edit config/.env with your API keys
```

### Running Tests

```bash
pytest tests/ -v --cov=hermes_trade
```

### Paper Trading Demo

```bash
python -m hermes_trade --mode paper --config config/default.yaml
```

## Project Structure

```
hermes-trade/
├── src/hermes_trade/
│   ├── __init__.py
│   ├── core/           # Event bus, config, logging
│   ├── models/         # Pydantic data models
│   ├── monitoring/     # Twitter, RSS, news watchers
│   ├── analysis/       # FinBERT, sentiment, LLM pipeline
│   ├── execution/      # Broker adapters, order management
│   ├── backtesting/    # Historical replay, metrics
│   └── utils/          # Helpers, rate limiters, etc.
├── tests/
│   ├── unit/
│   └── integration/
├── config/             # YAML configs, .env templates
├── docker/             # Docker Compose, Dockerfiles
├── .github/workflows/  # CI/CD pipelines
└── docs/               # ADRs, architecture decisions
```

## Technology Stack

| Layer | Technology | Rationale |
|-------|-----------|-----------|
| Orchestrator | Hermes Agent (cronjob + skills) | Already available, low cost |
| Message Bus | Redis Streams | Sub-ms latency, simple |
| LLM Inference | vLLM / Ollama / Groq API | Local GPU or free tier |
| Model A (Analysis) | FinBERT + Llama 3 8B | Sentiment + understanding |
| Model B (Decision) | Phi-3-mini / RL agent | Fast, lightweight |
| Backtesting | Backtesting.py + custom | Proven, Python-native |
| Database | PostgreSQL + TimescaleDB | Time-series, audit trail |
| Monitoring | Prometheus + Grafana | Industry standard |
| Deployment | Docker Compose / K8s | Easy scaling |

## Cost Estimates (Monthly)

| Item | Minimal | Medium | Professional |
|------|---------|--------|-------------|
| Server | €30 (Hetzner CCX33) | €70 (Hetzner AX52) | €500+ (colocation) |
| GPU (LLM) | $0 (CPU Ollama) | $50 (RunPod spot) | $320 (RunPod RTX4090) |
| Twitter API | $100 (Basic) | $100 (Basic) | $5,000 (Pro) |
| News API | $0 (Finnhub free) | $50 (NewsAPI) | $200+ (Bloomberg) |
| Market Data | $0 (yfinance) | $30 (Polygon) | $200+ (professional) |
| **Total** | **~€130-200** | **~€250-350** | **~€1,000-6,000** |

## Forks & Dependencies

Key frameworks forked for customization:

- [TradingAgents](https://github.com/ScuraUrsa/TradingAgents) — Multi-Agent LLM Trading Framework
- [FinGPT](https://github.com/ScuraUrsa/FinGPT) — Financial LLM
- [FinRL](https://github.com/ScuraUrsa/FinRL) — Deep RL for Finance
- [backtesting.py](https://github.com/ScuraUrsa/backtesting.py) — Backtesting framework

## License

MIT © 2026 Filip Kaźmierczak

## Research

Full research document: [hermes-algo-trading-research.md](https://github.com/ScuraUrsa/hermes-trade/blob/main/docs/research.md)

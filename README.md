# Trendscope

**Market trend intelligence for niche identification and opportunity detection.**

Part of the [GozerAI](https://gozerai.com) ecosystem.

## Overview

Trendscope is a Python library and API for collecting, analyzing, and scoring market trends across multiple platforms. It identifies niche opportunities, detects trend drift, finds cross-platform correlations, and generates actionable buy/sell signals. Zero external dependencies at the library layer.

## Installation

```bash
pip install trendscope
```

For development (includes test dependencies):

```bash
pip install -e ".[dev]"
```

For the API server (includes FastAPI, httpx, slowapi):

```bash
pip install -e ".[dev,api]"
```

## Quick Start

```python
import asyncio
from trendscope import TrendService

async def main():
    service = TrendService()
    await service.initialize()

    # Collect trends from all configured sources
    result = await service.refresh_trends()

    # Search for specific trends
    matches = await service.search_trends("artificial intelligence")

    # Find niche market opportunities
    opportunities = await service.find_opportunities(min_score=50)

    # Detect significant trend changes
    drifts = await service.detect_drifts(lookback_days=7)

    # Get buy/sell signals
    signals = await service.get_signals()

    # Set up an alert
    await service.create_alert(keyword="AI agents", threshold=0.8)

asyncio.run(main())
```

## Feature Tiers

| Feature | Community | Pro | Enterprise |
|---|:---:|:---:|:---:|
| Trend collection and storage | x | x | x |
| Trend search and listing | x | x | x |
| Alert creation and history | x | x | x |
| Basic stats | x | x | x |
| Top/emerging trend views | x | x | x |
| Opportunity scoring | | x | x |
| Buy/sell signals | | x | x |
| Drift detection | | x | x |
| Cross-platform correlations | | x | x |
| Intelligence reports | | x | x |
| Anomaly detection | | x | x |
| Forecasting | | x | x |
| Credibility scoring | | x | x |
| Real-time feed | | x | x |
| Snapshots and comparison | | x | x |
| Lifecycle tracking | | x | x |
| Coverage analysis | | x | x |
| Time-window comparison | | x | x |
| Scheduler management | | x | x |
| Executive narrative reports | | | x |
| Autonomy dashboard | | | x |

### Gated Features

Pro and Enterprise features require a license key. Set the `VINZY_LICENSE_KEY` environment variable or visit [gozerai.com/pricing](https://gozerai.com/pricing) to upgrade. Without a key, the library operates in Community mode with full access to core trend collection and alerting.

## API Endpoints

Start the API server:

```bash
uvicorn trendscope.app:app --host 0.0.0.0 --port 8001
```

### Community (trendscope:basic)

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Health check |
| GET | `/v1/trends` | List all trends |
| GET | `/v1/trends/top` | Top trends by score |
| GET | `/v1/trends/emerging` | Emerging trends |
| GET | `/v1/trends/search?q=` | Search trends by keyword |
| GET | `/v1/trends/{trend_id}` | Single trend detail |
| GET | `/v1/stats` | Collection statistics |
| POST | `/v1/alerts` | Create an alert |
| GET | `/v1/alerts` | List alerts |
| DELETE | `/v1/alerts/{alert_id}` | Remove an alert |
| GET | `/v1/alerts/history` | Alert trigger history |

### Pro (trendscope:full)

| Method | Path | Description |
|---|---|---|
| GET | `/v1/signals/strong-buy` | Strong buy signals |
| GET | `/v1/signals` | All buy/sell signals |
| GET | `/v1/opportunities` | Scored opportunities |
| GET | `/v1/drifts` | Drift detection |
| GET | `/v1/correlations` | Cross-platform correlations |
| GET | `/v1/intelligence` | Intelligence summary |
| GET | `/v1/executive/{code}` | Executive report |
| POST | `/v1/refresh` | Trigger trend refresh |
| GET | `/v1/trends/{id}/forecast` | Trend forecast |
| GET | `/v1/forecasts` | All forecasts |
| GET | `/v1/credibility` | Credibility scores |
| GET | `/v1/anomalies` | Detected anomalies |
| POST | `/v1/snapshots` | Create snapshot |
| GET | `/v1/snapshots` | List snapshots |
| GET | `/v1/snapshots/compare` | Compare snapshots |
| GET | `/v1/trends/{id}/lifecycle` | Trend lifecycle stage |
| GET | `/v1/coverage` | Source coverage |
| GET | `/v1/compare/this-vs-last` | Period comparison |
| GET | `/v1/compare/movers` | Biggest movers |
| GET | `/v1/feed` | Real-time trend feed |
| GET | `/v1/feed/summary` | Feed summary |

### Enterprise (trendscope:enterprise)

| Method | Path | Description |
|---|---|---|
| GET | `/v1/executive/{code}/narrative` | Executive narrative report |
| GET | `/v1/autonomy/pulse` | Autonomy system pulse |
| GET | `/v1/autonomy/timeline` | Autonomy event timeline |
| GET | `/v1/autonomy/health` | Autonomy health status |

## Configuration

| Variable | Default | Description |
|---|---|---|
| `ZUULTIMATE_BASE_URL` | `http://localhost:8000` | Auth service URL |
| `CORS_ORIGINS` | `http://localhost:3000` | Comma-separated allowed origins |
| `KH_WEBHOOK_SECRET` | (empty) | Knowledge Harvester webhook HMAC secret |
| `KH_BASE_URL` | (empty) | Knowledge Harvester base URL |
| `VINZY_LICENSE_KEY` | (empty) | License key for Pro/Enterprise features |
| `VINZY_SERVER` | `http://localhost:8080` | License validation server |

## Requirements

- Python >= 3.10
- No external dependencies for the library (stdlib only)
- FastAPI + httpx + slowapi for the API server

## License

MIT License. See [LICENSE](LICENSE) for details.

# Trendscope

**AI-powered trend analysis and market intelligence** — Part of the [GozerAI](https://gozerai.com) ecosystem.

## Overview

Trendscope is a Python library for collecting, analyzing, and scoring market trends across multiple platforms. It identifies niche opportunities, detects trend drift, finds cross-platform correlations, and generates actionable buy/sell signals.

## Features (Community Tier)

- **Multi-source collection** — Pluggable collectors for Google Trends, Reddit, Hacker News, and Product Hunt
- **Trend analysis** — Velocity, momentum, and composite scoring with lifecycle classification
- **Niche identification** — Automatic detection of market opportunities
- **Drift detection** — Alerts when trends surge, decline, or exhibit unusual volatility
- **SQLite persistence** — Built-in trend database with history tracking

### Pro Features (requires license)

- Advanced anomaly detection
- Forecasting and predictive models
- Trend intelligence and correlation engine
- Narrative extraction
- Credibility scoring
- Real-time feed

### Enterprise Features (requires license)

- Autonomous analysis pipelines
- Scheduled analysis
- Trend snapshots and time-travel comparison
- Lifecycle tracking and coverage analysis
- External integrations (Knowledge Harvester, graph sync)

Visit [gozerai.com/pricing](https://gozerai.com/pricing) for Pro and Enterprise tier details.

## Installation

```bash
pip install trendscope
```

For development:

```bash
pip install -e ".[dev]"
```

## Quick Start

```python
import asyncio
from trendscope import TrendService

async def main():
    service = TrendService()
    await service.initialize()

    # Collect trends from all sources
    result = await service.refresh_trends()

    # Find niche market opportunities
    opportunities = await service.find_opportunities(min_score=50)

    # Detect significant trend changes
    drifts = await service.detect_drifts(lookback_days=7)

    # Get buy/sell signals
    signals = await service.get_signals()

asyncio.run(main())
```

## Running Tests

```bash
pytest tests/ -v
```

## Requirements

- Python >= 3.10
- No external dependencies (stdlib only)

## License

This project is dual-licensed:

- **AGPL-3.0** — For open-source use (see [LICENSE](LICENSE))
- **Commercial** — For proprietary integration

Contact chris@gozerai.com for commercial licensing.

## Links

- [GozerAI Ecosystem](https://gozerai.com)
- [Pricing](https://gozerai.com/pricing)

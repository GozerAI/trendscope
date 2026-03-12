# Trendscope

Market trend intelligence for niche identification and opportunity detection.

## Overview

Trendscope is a Python library for collecting, analyzing, and scoring market trends across multiple platforms. It identifies niche opportunities, detects trend drift, finds cross-platform correlations, and generates actionable buy/sell signals -- all using the Python standard library with zero external dependencies.

## Features

- **Multi-source collection** -- Pluggable collectors for Google Trends, Reddit, Hacker News, and Product Hunt
- **Trend analysis** -- Velocity, momentum, and composite scoring with lifecycle classification (emerging, growing, peak, declining, stable)
- **Niche identification** -- Automatic detection of market opportunities from keyword clustering and trend convergence
- **Drift detection** -- Alerts when trends surge, decline, or exhibit unusual volatility
- **Cross-platform correlation** -- Discovers relationships between trends across different sources
- **Opportunity scoring** -- Weighted scoring across trend strength, growth velocity, market gap, entry feasibility, and timing
- **Buy/sell signals** -- Trading-style signals (strong buy, buy, hold, sell, strong sell) based on composite metrics
- **SQLite persistence** -- Built-in trend database with history tracking and indexed queries
- **Executive reports** -- Tailored intelligence reports by role (CMO, CPO, CRO, CEO)
- **Autonomous analysis** -- Full refresh-analyze-identify-report cycle in a single call

## Installation

```
pip install trendscope
```

For development:

```
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

    # Generate an executive report
    report = await service.get_executive_report("CMO")

asyncio.run(main())
```

## Architecture

```
src/trendscope/
    core.py          Data models, SQLite database, trend analyzer
    collectors.py    Source collectors and niche identifier
    intelligence.py  Correlation, drift detection, opportunity scoring
    service.py       High-level service API
```

## Running Tests

```
pytest tests/ -v
```

## Requirements

- Python >= 3.10
- No external dependencies (stdlib only)

## License

MIT License. See [LICENSE](LICENSE) for details.

## Author

Chris Arseno

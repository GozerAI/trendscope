#!/usr/bin/env bash
# export_public.sh — Creates a clean public export of Trendscope for GozerAI/trendscope.
# Usage: bash scripts/export_public.sh [target_dir]
#
# Strips proprietary Pro/Enterprise modules and internal infrastructure,
# leaving only community-tier code + the license gate (so users see the upgrade path).

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TARGET="${1:-${REPO_ROOT}/../trendscope-public-export}"

echo "=== Trendscope Public Export ==="
echo "Source: ${REPO_ROOT}"
echo "Target: ${TARGET}"

# Clean target
rm -rf "${TARGET}"
mkdir -p "${TARGET}"

# Use git archive to get a clean copy (respects .gitignore, excludes .git)
cd "${REPO_ROOT}"
git archive HEAD | tar -x -C "${TARGET}"

# ===== STRIP PRO MODULES =====
PRO_MODULES=(anomaly forecasting intelligence narratives credibility feed)
for mod in "${PRO_MODULES[@]}"; do
    rm -f "${TARGET}/src/trendscope/${mod}.py"
done

# ===== STRIP ENTERPRISE MODULES =====
ENT_MODULES=(autonomy scheduler snapshots lifecycle coverage time_compare)
for mod in "${ENT_MODULES[@]}"; do
    rm -f "${TARGET}/src/trendscope/${mod}.py"
done
rm -rf "${TARGET}/src/trendscope/integrations/"

# ===== STRIP INTERNAL DOCS =====
rm -rf "${TARGET}/docs/pricing/"

# ===== STRIP TESTS FOR STRIPPED MODULES =====
PRO_TESTS=(test_anomaly test_forecasting test_intelligence test_narratives test_credibility test_feed)
for t in "${PRO_TESTS[@]}"; do
    rm -f "${TARGET}/tests/unit/${t}.py"
done

ENT_TESTS=(test_autonomy test_scheduler test_snapshots test_lifecycle test_coverage test_time_compare)
for t in "${ENT_TESTS[@]}"; do
    rm -f "${TARGET}/tests/unit/${t}.py"
done

rm -f "${TARGET}/tests/unit/test_graph_sync.py"
rm -f "${TARGET}/tests/unit/test_kh_integration.py"
rm -f "${TARGET}/tests/unit/test_kh_notifier.py"
rm -f "${TARGET}/tests/unit/test_kh_sync.py"
rm -f "${TARGET}/tests/unit/test_research_hooks.py"
rm -f "${TARGET}/tests/unit/test_resilience_integration.py"

# ===== CREATE STUB FILES FOR STRIPPED MODULES =====

write_stub() {
    cat > "$1" << 'PYEOF'
"""This module requires a commercial license.

Visit https://gozerai.com/pricing for Pro and Enterprise tier details.
Set VINZY_LICENSE_KEY to unlock licensed features.
"""

raise ImportError(
    f"{__name__} requires a commercial license. "
    "Visit https://gozerai.com/pricing for details."
)
PYEOF
}

for mod in "${PRO_MODULES[@]}"; do
    write_stub "${TARGET}/src/trendscope/${mod}.py"
done

for mod in "${ENT_MODULES[@]}"; do
    write_stub "${TARGET}/src/trendscope/${mod}.py"
done

mkdir -p "${TARGET}/src/trendscope/integrations"
write_stub "${TARGET}/src/trendscope/integrations/__init__.py"

# ===== FIX PRIVATE REPO REFERENCES =====
sed -i 's|"gozerai-telemetry @ git+https://github.com/GozerAI/gozerai-telemetry.git"|"gozerai-telemetry"|' "${TARGET}/pyproject.toml"
find "${TARGET}" -type f \( -name "*.yml" -o -name "*.yaml" \) -exec sed -i 's|gozerai-telemetry @ git+https://github.com/GozerAI/gozerai-telemetry.git|gozerai-telemetry|g' {} +

# ===== UPDATE README — clean for public =====
cat > "${TARGET}/README.md" << 'MDEOF'
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
MDEOF

# ===== UPDATE LICENSING.md =====
cat > "${TARGET}/LICENSING.md" << 'MDEOF'
# Commercial Licensing — Trendscope

This project is dual-licensed:

- **AGPL-3.0** — Free for open-source use with copyleft obligations
- **Commercial License** — Proprietary use without AGPL requirements

## Tiers

| | Community (Free) | Pro | Enterprise |
|--|:---:|:---:|:---:|
| Base functionality | Yes | Yes | Yes |
| Advanced features | — | Yes | Yes |
| Enterprise features | — | — | Yes |

Part of the **GozerAI ecosystem**. See pricing at **https://gozerai.com/pricing**.

```bash
export VINZY_LICENSE_KEY="your-key-here"
```
MDEOF

echo ""
echo "=== Export complete: ${TARGET} ==="
echo ""
echo "Community-tier modules included:"
echo "  __init__.py, app.py, core.py, licensing.py, service.py,"
echo "  collectors.py, collectors_competitive.py, alerts.py, data/"
echo ""
echo "Stripped (Pro/Enterprise — replaced with stubs):"
echo "  anomaly, forecasting, intelligence, narratives, credibility,"
echo "  feed, autonomy, scheduler, snapshots, lifecycle, coverage,"
echo "  time_compare, integrations/"

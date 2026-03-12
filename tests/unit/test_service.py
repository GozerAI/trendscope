"""Tests for TrendService."""

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch


class TestTrendService:
    """Tests for the TrendService."""

    @pytest.fixture
    def trend_service(self):
        """Create a TrendService instance."""
        from trendscope import TrendService
        return TrendService()

    def test_service_initialization(self, trend_service):
        """Verify service initializes correctly."""
        assert trend_service is not None
        assert hasattr(trend_service, "db")
        assert hasattr(trend_service, "collector_manager")

    @pytest.mark.asyncio
    async def test_get_trending_empty(self, trend_service):
        """Get trending returns empty list when no trends."""
        result = await trend_service.get_trending()
        # Returns list of trend dicts
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_get_executive_report_cmo(self, trend_service):
        """CMO report has marketing focus."""
        report = await trend_service.get_executive_report("CMO")
        assert report["executive"] == "CMO"
        assert report["focus"] == "Marketing & Growth"

    @pytest.mark.asyncio
    async def test_get_executive_report_cpo(self, trend_service):
        """CPO report has product focus."""
        report = await trend_service.get_executive_report("CPO")
        assert report["executive"] == "CPO"
        assert report["focus"] == "Product & Innovation"

    @pytest.mark.asyncio
    async def test_get_executive_report_ceo(self, trend_service):
        """CEO report has strategic focus."""
        report = await trend_service.get_executive_report("CEO")
        assert report["executive"] == "CEO"
        assert report["focus"] == "Strategic Overview"

    @pytest.mark.asyncio
    async def test_get_stats(self, trend_service):
        """Get service stats."""
        stats = await trend_service.get_stats()
        assert "database" in stats
        assert "collectors" in stats

    def test_get_telemetry_returns_dict(self, trend_service):
        """get_telemetry always returns a dict (empty if lib not installed)."""
        result = trend_service.get_telemetry()
        assert isinstance(result, dict)

    def test_get_telemetry_graceful_without_lib(self, trend_service):
        """Without gozerai-telemetry installed, get_telemetry returns {}."""
        import trendscope.service as svc
        original = svc._HAS_TELEMETRY
        try:
            svc._HAS_TELEMETRY = False
            result = trend_service.get_telemetry()
            assert result == {}
        finally:
            svc._HAS_TELEMETRY = original

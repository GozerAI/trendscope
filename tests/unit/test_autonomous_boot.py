"""Tests for autonomous startup and C-Suite priority endpoints."""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from trendscope.core import Trend, TrendCategory
from trendscope.service import TrendService


@pytest.fixture
async def service(tmp_path):
    svc = TrendService(db_path=str(tmp_path / "test.db"))
    await svc.initialize()
    for i in range(3):
        svc.db.save_trend(Trend(
            name=f"Test Trend {i}",
            score=50 + i * 10,
            category=TrendCategory.TECHNOLOGY,
            keywords=["ai", "test"],
            velocity=0.1 * i,
        ))
    return svc


@pytest.fixture
async def client(service):
    """Create test client with injected service."""
    import trendscope.app as app_module
    from trendscope.app import app

    original_service = app_module._service
    app_module._service = service

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app_module._service = original_service


# =============================================================================
# Scheduler starts on boot
# =============================================================================


class TestSchedulerBoot:

    @pytest.mark.asyncio
    async def test_scheduler_starts_on_lifespan(self):
        """Scheduler.start() is called during app lifespan startup."""
        mock_scheduler = MagicMock()
        mock_svc = AsyncMock()
        mock_svc.get_scheduler = MagicMock(return_value=mock_scheduler)

        import trendscope.app as app_module
        from trendscope.app import app, lifespan

        with patch.object(app_module, "TrendService", return_value=mock_svc):
            # Reset global so lifespan creates a fresh service
            original = app_module._service
            app_module._service = None

            async with lifespan(app):
                mock_svc.initialize.assert_awaited_once()
                mock_scheduler.start.assert_called_once()

            mock_scheduler.stop.assert_called_once()
            app_module._service = original

    @pytest.mark.asyncio
    async def test_scheduler_has_real_callbacks(self, service):
        """Scheduler callbacks are wired to real methods, not no-ops."""
        scheduler = service.get_scheduler()
        refresh_entry = scheduler.get_schedule("refresh_trends")
        anomaly_entry = scheduler.get_schedule("detect_anomalies")

        # Verify the callbacks are the sync wrappers, not lambda: None
        assert refresh_entry.callback == service._sync_refresh_trends
        assert anomaly_entry.callback == service._sync_detect_anomalies

    @pytest.mark.asyncio
    async def test_sync_refresh_trends_calls_refresh(self, service):
        """_sync_refresh_trends bridges to the async refresh_trends via run_coroutine_threadsafe."""
        import asyncio

        mock_result = {
            "trends_collected": 0,
            "sources_used": [],
            "refreshed_at": "2026-01-01T00:00:00Z",
        }
        service.refresh_trends = AsyncMock(return_value=mock_result)
        service._loop = asyncio.get_running_loop()

        # Verify the sync wrapper dispatches to run_coroutine_threadsafe
        mock_future = MagicMock()
        mock_future.result.return_value = mock_result
        with patch("asyncio.run_coroutine_threadsafe", return_value=mock_future) as mock_rcts:
            service._sync_refresh_trends()
            mock_rcts.assert_called_once()
            mock_future.result.assert_called_once_with(timeout=120)

    @pytest.mark.asyncio
    async def test_sync_detect_anomalies_calls_detect(self, service):
        """_sync_detect_anomalies calls detect_anomalies(lookback_days=14)."""
        service.detect_anomalies = MagicMock(return_value=[])
        service._sync_detect_anomalies()
        service.detect_anomalies.assert_called_once_with(lookback_days=14)


# =============================================================================
# Priority endpoints — valid token
# =============================================================================


class TestPriorityEndpointsValid:

    @pytest.mark.asyncio
    async def test_priority_refresh_with_valid_token(self, client, service):
        """POST /v1/priority/refresh works with valid service token."""
        service.refresh_trends = AsyncMock(return_value={
            "trends_collected": 5,
            "sources_used": ["mock"],
            "refreshed_at": "2026-01-01T00:00:00Z",
        })
        with patch.dict(os.environ, {"CSUITE_SERVICE_TOKEN": "test-secret-token"}):
            import trendscope.app as app_module
            app_module.CSUITE_SERVICE_TOKEN = "test-secret-token"
            resp = await client.post(
                "/v1/priority/refresh",
                headers={"X-Service-Token": "test-secret-token"},
            )
            app_module.CSUITE_SERVICE_TOKEN = ""

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["result"]["trends_collected"] == 5
        service.refresh_trends.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_priority_analysis_with_valid_token(self, client, service):
        """POST /v1/priority/analysis works with valid service token."""
        service.run_autonomous_analysis = AsyncMock(return_value={
            "cycle_completed_at": "2026-01-01T00:00:00Z",
            "refresh": {},
            "analysis": {},
            "niches_identified": 0,
            "drifts_detected": 0,
            "alerts_triggered": 0,
            "report_generated": True,
            "next_actions": [],
        })
        with patch.dict(os.environ, {"CSUITE_SERVICE_TOKEN": "test-secret-token"}):
            import trendscope.app as app_module
            app_module.CSUITE_SERVICE_TOKEN = "test-secret-token"
            resp = await client.post(
                "/v1/priority/analysis",
                headers={"X-Service-Token": "test-secret-token"},
            )
            app_module.CSUITE_SERVICE_TOKEN = ""

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["result"]["report_generated"] is True
        service.run_autonomous_analysis.assert_awaited_once()


# =============================================================================
# Priority endpoints — rejected tokens
# =============================================================================


class TestPriorityEndpointsRejected:

    @pytest.mark.asyncio
    async def test_priority_refresh_rejects_invalid_token(self, client):
        """POST /v1/priority/refresh rejects wrong service token."""
        import trendscope.app as app_module
        original = app_module.CSUITE_SERVICE_TOKEN
        app_module.CSUITE_SERVICE_TOKEN = "correct-token"
        resp = await client.post(
            "/v1/priority/refresh",
            headers={"X-Service-Token": "wrong-token"},
        )
        app_module.CSUITE_SERVICE_TOKEN = original
        assert resp.status_code == 403
        assert "Invalid service token" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_priority_analysis_rejects_invalid_token(self, client):
        """POST /v1/priority/analysis rejects wrong service token."""
        import trendscope.app as app_module
        original = app_module.CSUITE_SERVICE_TOKEN
        app_module.CSUITE_SERVICE_TOKEN = "correct-token"
        resp = await client.post(
            "/v1/priority/analysis",
            headers={"X-Service-Token": "wrong-token"},
        )
        app_module.CSUITE_SERVICE_TOKEN = original
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_priority_refresh_rejects_missing_token(self, client):
        """POST /v1/priority/refresh rejects when no token header sent."""
        import trendscope.app as app_module
        original = app_module.CSUITE_SERVICE_TOKEN
        app_module.CSUITE_SERVICE_TOKEN = "correct-token"
        resp = await client.post("/v1/priority/refresh")
        app_module.CSUITE_SERVICE_TOKEN = original
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_priority_refresh_503_when_not_configured(self, client):
        """POST /v1/priority/refresh returns 503 if CSUITE_SERVICE_TOKEN is empty."""
        import trendscope.app as app_module
        original = app_module.CSUITE_SERVICE_TOKEN
        app_module.CSUITE_SERVICE_TOKEN = ""
        resp = await client.post(
            "/v1/priority/refresh",
            headers={"X-Service-Token": "anything"},
        )
        app_module.CSUITE_SERVICE_TOKEN = original
        assert resp.status_code == 503
        assert "not configured" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_priority_analysis_503_when_not_configured(self, client):
        """POST /v1/priority/analysis returns 503 if CSUITE_SERVICE_TOKEN is empty."""
        import trendscope.app as app_module
        original = app_module.CSUITE_SERVICE_TOKEN
        app_module.CSUITE_SERVICE_TOKEN = ""
        resp = await client.post(
            "/v1/priority/analysis",
            headers={"X-Service-Token": "anything"},
        )
        app_module.CSUITE_SERVICE_TOKEN = original
        assert resp.status_code == 503

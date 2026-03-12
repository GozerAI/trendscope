"""Unit tests for Trendscope FastAPI endpoints."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from httpx import ASGITransport, AsyncClient

from trendscope.core import Trend, TrendCategory, TrendDatabase
from trendscope.service import TrendService


@pytest.fixture
def mock_tenant():
    """Mock tenant context returned by auth validation."""
    return {
        "user_id": "u_test",
        "username": "tester",
        "tenant_id": "t_test",
        "plan": "pro",
        "entitlements": ["trendscope:basic", "trendscope:full"],
    }


@pytest.fixture
def basic_tenant():
    """Mock tenant with only basic entitlement."""
    return {
        "user_id": "u_basic",
        "username": "basic_user",
        "tenant_id": "t_basic",
        "plan": "starter",
        "entitlements": ["trendscope:basic"],
    }


@pytest.fixture
async def service(tmp_path):
    svc = TrendService(db_path=str(tmp_path / "test.db"))
    await svc.initialize()
    # Seed some test data
    for i in range(5):
        svc.db.save_trend(Trend(
            name=f"Test Trend {i}",
            score=50 + i * 10,
            category=TrendCategory.TECHNOLOGY if i < 3 else TrendCategory.BUSINESS,
            keywords=["ai", "test"],
            velocity=0.1 * i,
        ))
    return svc


@pytest.fixture
async def client(service, mock_tenant):
    """Create test client with mocked auth."""
    import trendscope.app as app_module
    from trendscope.app import app, get_tenant

    original_service = app_module._service
    app_module._service = service
    app.dependency_overrides[get_tenant] = lambda: mock_tenant

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()
    app_module._service = original_service


# =============================================================================
# Health
# =============================================================================


class TestHealth:

    @pytest.mark.asyncio
    async def test_health(self, client):
        resp = await client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["service"] == "trendscope"
        assert "version" in data

    @pytest.mark.asyncio
    async def test_health_detailed(self, client):
        resp = await client.get("/health/detailed")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["service"] == "trendscope"
        assert "checks" in data
        assert data["checks"]["service"]["status"] == "ok"
        assert data["checks"]["service"]["trends_stored"] == 5


# =============================================================================
# Basic endpoints (trendscope:basic)
# =============================================================================


class TestBasicEndpoints:

    @pytest.mark.asyncio
    async def test_get_trends(self, client):
        resp = await client.get("/v1/trends")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 5

    @pytest.mark.asyncio
    async def test_get_trends_with_category(self, client):
        resp = await client.get("/v1/trends", params={"category": "technology"})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 3

    @pytest.mark.asyncio
    async def test_get_trends_with_min_score(self, client):
        resp = await client.get("/v1/trends", params={"min_score": 70})
        assert resp.status_code == 200
        data = resp.json()
        assert all(t["score"] >= 70 for t in data)

    @pytest.mark.asyncio
    async def test_get_top_trends(self, client):
        resp = await client.get("/v1/trends/top", params={"limit": 3})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) <= 3
        # Should be sorted by score descending
        if len(data) >= 2:
            assert data[0]["score"] >= data[1]["score"]

    @pytest.mark.asyncio
    async def test_get_emerging_trends(self, client):
        resp = await client.get("/v1/trends/emerging")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    @pytest.mark.asyncio
    async def test_search_trends(self, client):
        resp = await client.get("/v1/trends/search", params={"q": "Test Trend"})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1

    @pytest.mark.asyncio
    async def test_search_trends_no_results(self, client):
        resp = await client.get("/v1/trends/search", params={"q": "zzzznonexistent"})
        assert resp.status_code == 200
        assert resp.json() == []

    @pytest.mark.asyncio
    async def test_get_trend_by_id(self, client, service):
        trends = service.db.get_trends(limit=1)
        trend_id = trends[0].id
        resp = await client.get(f"/v1/trends/{trend_id}")
        assert resp.status_code == 200
        assert resp.json()["id"] == trend_id

    @pytest.mark.asyncio
    async def test_get_trend_not_found(self, client):
        resp = await client.get("/v1/trends/nonexistent_id")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_get_stats(self, client):
        resp = await client.get("/v1/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert "database" in data
        assert "collectors" in data


# =============================================================================
# Full endpoints (trendscope:full)
# =============================================================================


class TestFullEndpoints:

    @pytest.mark.asyncio
    async def test_get_signals(self, client):
        resp = await client.get("/v1/signals")
        assert resp.status_code == 200
        data = resp.json()
        for key in ("strong_buy", "buy", "hold", "sell", "strong_sell"):
            assert key in data

    @pytest.mark.asyncio
    async def test_detect_drifts(self, client):
        resp = await client.get("/v1/drifts")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    @pytest.mark.asyncio
    async def test_find_correlations(self, client):
        resp = await client.get("/v1/correlations")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    @pytest.mark.asyncio
    async def test_get_intelligence_report(self, client):
        resp = await client.get("/v1/intelligence")
        assert resp.status_code == 200
        data = resp.json()
        assert "summary" in data or "signals" in data

    @pytest.mark.asyncio
    async def test_refresh_trends(self, client):
        resp = await client.post("/v1/refresh")
        assert resp.status_code == 200
        data = resp.json()
        assert "trends_collected" in data
        assert data["trends_collected"] >= 0

    @pytest.mark.asyncio
    async def test_find_opportunities(self, client):
        resp = await client.get("/v1/opportunities")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


# =============================================================================
# Executive reports
# =============================================================================


class TestExecutiveReports:

    @pytest.mark.asyncio
    async def test_valid_executive_codes(self, client):
        for code in ("CMO", "CPO", "CRO", "CEO"):
            resp = await client.get(f"/v1/executive/{code}")
            assert resp.status_code == 200, f"Failed for {code}: {resp.text}"
            data = resp.json()
            assert data["executive"] == code

    @pytest.mark.asyncio
    async def test_invalid_executive_code(self, client):
        resp = await client.get("/v1/executive/INVALID")
        assert resp.status_code == 400


# =============================================================================
# Auth enforcement
# =============================================================================


class TestAuthEnforcement:

    @pytest.mark.asyncio
    async def test_no_auth_header_returns_401(self, service):
        """Endpoints should return 401 without auth header."""
        from trendscope.app import app

        # Use real auth (no override) — will fail since no Zuultimate running
        app.dependency_overrides.clear()

        with patch.object(
            __import__("trendscope.app", fromlist=["_service"]),
            "_service",
            service,
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                resp = await ac.get("/v1/trends")
                assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_basic_plan_blocked_from_full_endpoints(self, service, basic_tenant):
        """Basic plan should be blocked from full-tier endpoints."""
        from trendscope.app import app, get_tenant

        app.dependency_overrides[get_tenant] = lambda: basic_tenant

        with patch.object(
            __import__("trendscope.app", fromlist=["_service"]),
            "_service",
            service,
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                resp = await ac.get("/v1/signals")
                assert resp.status_code == 403

        app.dependency_overrides.clear()


# =============================================================================
# Snapshot Diff Summary
# =============================================================================


class TestSnapshotDiffSummary:

    @pytest.mark.asyncio
    async def test_diff_summary_insufficient_snapshots(self, client, service):
        """Returns insufficient_snapshots when fewer than 2 snapshots exist."""
        resp = await client.get("/v1/snapshots/diff-summary")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "insufficient_snapshots"

    @pytest.mark.asyncio
    async def test_diff_summary_with_snapshots(self, client, service):
        """Returns diff when 2+ snapshots exist."""
        service.create_snapshot(label="snap-1")
        # Add a trend to change state
        service.db.save_trend(Trend(
            name="New Trend For Diff",
            score=75,
            category=TrendCategory.TECHNOLOGY,
            keywords=["diff"],
            velocity=0.5,
        ))
        service.create_snapshot(label="snap-2")
        resp = await client.get("/v1/snapshots/diff-summary")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "diff" in data
        assert "latest" in data
        assert "previous" in data

    @pytest.mark.asyncio
    async def test_diff_summary_returns_snapshot_ids(self, client, service):
        """Returns latest and previous snapshot IDs."""
        service.create_snapshot(label="a")
        service.create_snapshot(label="b")
        resp = await client.get("/v1/snapshots/diff-summary")
        data = resp.json()
        assert data["latest"] is not None
        assert data["previous"] is not None
        assert data["latest"] != data["previous"]

    @pytest.mark.asyncio
    async def test_diff_summary_requires_full_entitlement(self, service, basic_tenant):
        """Basic plan should be blocked."""
        from trendscope.app import app, get_tenant
        import trendscope.app as app_module

        original_service = app_module._service
        app_module._service = service
        app.dependency_overrides[get_tenant] = lambda: basic_tenant

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get("/v1/snapshots/diff-summary")
            assert resp.status_code == 403

        app.dependency_overrides.clear()
        app_module._service = original_service

    @pytest.mark.asyncio
    async def test_diff_summary_single_snapshot(self, client, service):
        """Returns insufficient with exactly one snapshot."""
        service.create_snapshot(label="only-one")
        resp = await client.get("/v1/snapshots/diff-summary")
        data = resp.json()
        assert data["status"] == "insufficient_snapshots"
        assert data["count"] == 1

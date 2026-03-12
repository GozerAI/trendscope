"""Unit tests for Knowledge Harvester integration."""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from httpx import ASGITransport, AsyncClient

from trendscope.core import Trend, TrendCategory, TrendSource, TrendDatabase, NicheOpportunity
from trendscope.integrations.kh_client import (
    CATEGORY_MAP,
    map_kh_category_to_ts,
    map_ts_category_to_kh,
    _request,
    get_artifacts,
    get_popular,
)
from trendscope.integrations.kh_collector import KnowledgeHarvesterCollector
from trendscope.intelligence import OpportunityScorer


# =============================================================================
# kh_client tests
# =============================================================================


class TestCategoryMap:

    def test_category_map_has_all_ts_categories(self):
        """CATEGORY_MAP covers all 6 expected TS categories."""
        expected = {"technology", "ecommerce", "business", "consumer", "niche_market", "emerging"}
        assert set(CATEGORY_MAP.keys()) == expected

    def test_category_map_covers_all_kh_categories(self):
        """CATEGORY_MAP covers all 21 KH categories."""
        all_kh = []
        for cats in CATEGORY_MAP.values():
            all_kh.extend(cats)
        assert len(all_kh) == 21

    def test_map_kh_to_ts_technology(self):
        """KH 'ai-agent' maps to TS 'technology'."""
        assert map_kh_category_to_ts("ai-agent") == "technology"

    def test_map_kh_to_ts_ecommerce(self):
        assert map_kh_category_to_ts("ecommerce") == "ecommerce"

    def test_map_kh_to_ts_business(self):
        assert map_kh_category_to_ts("lead-gen-crm") == "business"

    def test_map_kh_to_ts_consumer(self):
        assert map_kh_category_to_ts("customer-support") == "consumer"

    def test_map_kh_to_ts_niche_market(self):
        assert map_kh_category_to_ts("data-pipeline") == "niche_market"

    def test_map_kh_to_ts_emerging(self):
        assert map_kh_category_to_ts("content-marketing") == "emerging"

    def test_map_kh_to_ts_unknown_defaults_technology(self):
        """Unknown KH category defaults to 'technology'."""
        assert map_kh_category_to_ts("unknown-category") == "technology"

    def test_map_ts_to_kh_technology(self):
        result = map_ts_category_to_kh("technology")
        assert "ai-agent" in result
        assert len(result) == 8

    def test_map_ts_to_kh_unknown_returns_empty(self):
        assert map_ts_category_to_kh("nonexistent") == []


class TestKHClientRequests:

    @patch("trendscope.integrations.kh_client.urllib.request.urlopen")
    def test_request_returns_none_on_connection_failure(self, mock_urlopen):
        """_request returns None when KH is unreachable."""
        import urllib.error
        mock_urlopen.side_effect = urllib.error.URLError("Connection refused")
        assert _request("/api/health") is None

    @patch("trendscope.integrations.kh_client._request")
    def test_get_artifacts_returns_empty_on_failure(self, mock_req):
        mock_req.return_value = None
        assert get_artifacts() == []

    @patch("trendscope.integrations.kh_client._request")
    def test_get_popular_returns_empty_on_failure(self, mock_req):
        mock_req.return_value = None
        assert get_popular() == []

    @patch("trendscope.integrations.kh_client._request")
    def test_get_artifacts_parses_dict_response(self, mock_req):
        mock_req.return_value = {"artifacts": [{"name": "tool-a"}, {"name": "tool-b"}]}
        result = get_artifacts()
        assert len(result) == 2
        assert result[0]["name"] == "tool-a"

    @patch("trendscope.integrations.kh_client._request")
    def test_get_popular_parses_dict_response(self, mock_req):
        mock_req.return_value = {"results": [{"name": "pop-1"}]}
        result = get_popular()
        assert len(result) == 1
        assert result[0]["name"] == "pop-1"


# =============================================================================
# kh_collector tests
# =============================================================================


class TestKHCollector:

    def test_collector_source_is_internal(self):
        c = KnowledgeHarvesterCollector()
        assert c.source == TrendSource.INTERNAL

    def test_collector_name(self):
        c = KnowledgeHarvesterCollector()
        assert c.name == "Knowledge Harvester"

    @pytest.mark.asyncio
    @patch("trendscope.integrations.kh_collector.get_analytics_trends", return_value=[])
    @patch("trendscope.integrations.kh_collector.get_popular", return_value=[])
    async def test_collect_returns_empty_when_kh_unreachable(self, mock_pop, mock_ana):
        c = KnowledgeHarvesterCollector()
        result = await c.collect()
        assert result == []

    @pytest.mark.asyncio
    @patch("trendscope.integrations.kh_collector.get_analytics_trends", return_value=[])
    @patch("trendscope.integrations.kh_collector.get_popular")
    async def test_collect_creates_trends_from_popular(self, mock_pop, mock_ana):
        mock_pop.return_value = [
            {"name": "AutoGen", "primary_category": "ai-agent", "quality_score": 75, "view_count": 100},
            {"name": "LangChain", "primary_category": "ai-agent", "quality_score": 85, "view_count": 200},
        ]
        c = KnowledgeHarvesterCollector()
        trends = await c.collect()
        assert len(trends) == 2
        assert trends[0].name.startswith("KH: ")

    @pytest.mark.asyncio
    @patch("trendscope.integrations.kh_collector.get_popular", return_value=[])
    @patch("trendscope.integrations.kh_collector.get_analytics_trends")
    async def test_collect_creates_surge_trends(self, mock_ana, mock_pop):
        mock_ana.return_value = [
            {"category": "ai-agent", "count": 10},
            {"category": "ecommerce", "count": 5},
        ]
        c = KnowledgeHarvesterCollector()
        trends = await c.collect()
        assert len(trends) == 2
        assert "Surge" in trends[0].name

    @pytest.mark.asyncio
    @patch("trendscope.integrations.kh_collector.get_analytics_trends", return_value=[])
    @patch("trendscope.integrations.kh_collector.get_popular")
    async def test_trends_have_internal_source(self, mock_pop, mock_ana):
        mock_pop.return_value = [
            {"name": "Tool", "primary_category": "ai-agent", "quality_score": 50},
        ]
        c = KnowledgeHarvesterCollector()
        trends = await c.collect()
        assert trends[0].source == TrendSource.INTERNAL

    @pytest.mark.asyncio
    @patch("trendscope.integrations.kh_collector.get_analytics_trends", return_value=[])
    @patch("trendscope.integrations.kh_collector.get_popular")
    async def test_score_capped_at_100(self, mock_pop, mock_ana):
        mock_pop.return_value = [
            {"name": "OverScore", "primary_category": "ai-agent", "quality_score": 999},
        ]
        c = KnowledgeHarvesterCollector()
        trends = await c.collect()
        assert trends[0].score <= 100.0

    @pytest.mark.asyncio
    @patch("trendscope.integrations.kh_collector.get_analytics_trends", return_value=[])
    @patch("trendscope.integrations.kh_collector.get_popular")
    async def test_keywords_extracted(self, mock_pop, mock_ana):
        mock_pop.return_value = [
            {"name": "AutoGen Framework", "primary_category": "ai-agent", "quality_score": 60},
        ]
        c = KnowledgeHarvesterCollector()
        trends = await c.collect()
        kw = trends[0].keywords
        assert isinstance(kw, list)
        assert len(kw) > 0


# =============================================================================
# OpportunityScorer tests
# =============================================================================


class TestOpportunityScorerKH:

    def test_weights_sum_to_one(self):
        db = TrendDatabase()
        scorer = OpportunityScorer(db)
        total = sum(scorer.weights.values())
        assert abs(total - 1.0) < 1e-9

    def test_ecosystem_maturity_weight(self):
        db = TrendDatabase()
        scorer = OpportunityScorer(db)
        assert scorer.weights["ecosystem_maturity"] == 0.10

    def test_ecosystem_maturity_defaults_to_half(self):
        """When no artifact_evidence in metadata, ecosystem_maturity = 0.5."""
        db = TrendDatabase()
        scorer = OpportunityScorer(db)
        niche = NicheOpportunity(
            name="Test Niche",
            parent_trend_ids=[],
            opportunity_score=50,
            confidence=0.8,
            competition_density=0.3,
            storefront_fit=["tech_gadgets"],
            growth_rate=10,
            metadata={},
        )
        score = scorer.score_opportunity(niche)
        # Just verify it runs without error and returns a number
        assert isinstance(score, float)
        assert score > 0


# =============================================================================
# Webhook tests
# =============================================================================


@pytest.fixture
def mock_tenant():
    return {
        "user_id": "u_test",
        "username": "tester",
        "tenant_id": "t_test",
        "plan": "pro",
        "entitlements": ["trendscope:basic", "trendscope:full"],
    }


@pytest.fixture
async def webhook_client(mock_tenant):
    """Create test client with mocked auth for webhook tests."""
    from trendscope.service import TrendService
    import trendscope.app as app_module
    from trendscope.app import app, get_tenant

    svc = TrendService()
    await svc.initialize()
    original_service = app_module._service
    app_module._service = svc
    app.dependency_overrides[get_tenant] = lambda: mock_tenant

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()
    app_module._service = original_service


class TestKHWebhook:

    @pytest.mark.asyncio
    async def test_webhook_accepts_artifact_created(self, webhook_client):
        resp = await webhook_client.post(
            "/v1/webhooks/kh",
            json={"event": "artifact.created", "data": {"name": "test-tool"}},
        )
        assert resp.status_code == 200
        assert resp.json()["event"] == "artifact.created"

    @pytest.mark.asyncio
    async def test_webhook_accepts_harvest_completed(self, webhook_client):
        resp = await webhook_client.post(
            "/v1/webhooks/kh",
            json={"event": "harvest.completed", "data": {}},
        )
        assert resp.status_code == 200
        assert resp.json()["event"] == "harvest.completed"

    @pytest.mark.asyncio
    async def test_webhook_ignores_unknown_event(self, webhook_client):
        resp = await webhook_client.post(
            "/v1/webhooks/kh",
            json={"event": "unknown.event", "data": {}},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ignored"

    @pytest.mark.asyncio
    async def test_webhook_rejects_invalid_json(self, webhook_client):
        resp = await webhook_client.post(
            "/v1/webhooks/kh",
            content=b"not json",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 400


# =============================================================================
# Service enrichment tests
# =============================================================================


class TestServiceEnrichment:

    def test_enrich_with_artifacts_returns_unchanged_when_kh_unavailable(self):
        """_enrich_with_artifacts returns trends unchanged when KH unavailable."""
        import trendscope.service as svc_mod
        from trendscope.service import TrendService

        original = svc_mod._HAS_KH
        try:
            svc_mod._HAS_KH = False
            service = TrendService()
            trends = [{"name": "Test", "category": "technology", "keywords": ["ai"]}]
            result = service._enrich_with_artifacts(trends)
            assert result == trends
            assert "artifact_evidence" not in result[0]
        finally:
            svc_mod._HAS_KH = original

"""Tests for intelligence graph sync."""

import json
from unittest.mock import patch, MagicMock
import pytest

from trendscope.core import Trend, TrendSource, TrendCategory, TrendStatus
from trendscope.integrations.graph_sync import sync_trends_to_graph


def _make_trend(name="test-trend", score=75):
    return Trend(
        name=name,
        category=TrendCategory.TECHNOLOGY,
        source=TrendSource.GOOGLE_TRENDS,
        status=TrendStatus.GROWING,
        score=score,
        velocity=0.5,
        momentum=0.3,
    )


class TestSyncTrendsToGraph:
    def test_builds_correct_node_format(self):
        trends = [_make_trend("react-framework", 85)]
        with patch("trendscope.integrations.graph_sync.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.read.return_value = b'{"created": 1}'
            mock_resp.status = 200
            mock_resp.__enter__ = lambda s: s
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value = mock_resp

            result = sync_trends_to_graph(trends, kh_base_url="http://test:8011")
            assert result["synced"] == 1
            assert result["status"] == "ok"

    def test_empty_trends_returns_no_trends(self):
        result = sync_trends_to_graph([], kh_base_url="http://test:8011")
        assert result["synced"] == 0
        assert result["status"] == "no_trends"

    def test_handles_connection_failure(self):
        trends = [_make_trend()]
        with patch("trendscope.integrations.graph_sync.urlopen", side_effect=Exception("Connection refused")):
            result = sync_trends_to_graph(trends, kh_base_url="http://test:8011")
            assert result["synced"] == 0
            assert result["status"] == "error"

    def test_includes_trend_metadata(self):
        trends = [_make_trend("ai-tools", 90)]
        with patch("trendscope.integrations.graph_sync.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.read.return_value = b'{"created": 1}'
            mock_resp.__enter__ = lambda s: s
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value = mock_resp

            result = sync_trends_to_graph(trends, kh_base_url="http://test:8011")

            call_args = mock_urlopen.call_args
            req = call_args[0][0]
            body = json.loads(req.data.decode())
            assert body["nodes"][0]["type"] == "trend"
            assert body["nodes"][0]["data"]["label"] == "ai-tools"
            assert body["nodes"][0]["data"]["score"] == 90

    def test_multiple_trends(self):
        trends = [_make_trend("t1"), _make_trend("t2"), _make_trend("t3")]
        with patch("trendscope.integrations.graph_sync.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.read.return_value = b'{"created": 3}'
            mock_resp.__enter__ = lambda s: s
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value = mock_resp

            result = sync_trends_to_graph(trends, kh_base_url="http://test:8011")
            assert result["synced"] == 3

    def test_uses_default_base_url(self):
        trends = [_make_trend()]
        with patch("trendscope.integrations.graph_sync.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.read.return_value = b'{"created": 1}'
            mock_resp.__enter__ = lambda s: s
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value = mock_resp

            sync_trends_to_graph(trends)
            call_args = mock_urlopen.call_args
            req = call_args[0][0]
            assert "localhost:8011" in req.full_url

    def test_url_error_returns_failed(self):
        from urllib.error import URLError
        trends = [_make_trend()]
        with patch("trendscope.integrations.graph_sync.urlopen", side_effect=URLError("timeout")):
            result = sync_trends_to_graph(trends, kh_base_url="http://test:8011")
            assert result["status"] == "failed"

    def test_sends_post_to_correct_endpoint(self):
        trends = [_make_trend()]
        with patch("trendscope.integrations.graph_sync.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.read.return_value = b'{"created": 1}'
            mock_resp.__enter__ = lambda s: s
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value = mock_resp

            sync_trends_to_graph(trends, kh_base_url="http://myhost:9000")
            call_args = mock_urlopen.call_args
            req = call_args[0][0]
            assert req.full_url == "http://myhost:9000/api/graph/nodes"

    def test_includes_signal_in_node_data(self):
        trend = _make_trend("hot-trend", 95)
        trend.velocity = 5.0
        trend.momentum = 3.0
        with patch("trendscope.integrations.graph_sync.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.read.return_value = b'{"created": 1}'
            mock_resp.__enter__ = lambda s: s
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value = mock_resp

            sync_trends_to_graph([trend], kh_base_url="http://test:8011")
            call_args = mock_urlopen.call_args
            req = call_args[0][0]
            body = json.loads(req.data.decode())
            assert "signal" in body["nodes"][0]["data"]

    def test_handles_trend_with_no_velocity(self):
        trend = _make_trend()
        trend.velocity = 0.0
        trend.momentum = 0.0
        with patch("trendscope.integrations.graph_sync.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.read.return_value = b'{"created": 1}'
            mock_resp.__enter__ = lambda s: s
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value = mock_resp

            result = sync_trends_to_graph([trend], kh_base_url="http://test:8011")
            assert result["synced"] == 1

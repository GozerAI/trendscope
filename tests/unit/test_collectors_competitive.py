"""Unit tests for competitive landscape collectors."""

import json
import pytest
from unittest.mock import patch, MagicMock

from trendscope.core import Trend, TrendCategory, TrendSource, TrendStatus, TrendDatabase
from trendscope.collectors_competitive import (
    GitHubTrendingCollector,
    GitHubTrendingParser,
    PackageDownloadsCollector,
)


# =============================================================================
# Sample HTML for GitHub Trending
# =============================================================================

SAMPLE_TRENDING_HTML = """
<html>
<body>
<article>
  <h2><a href="/facebook/react">facebook / react</a></h2>
  <p>A declarative, efficient, and flexible JavaScript library for building user interfaces.</p>
</article>
<article>
  <h2><a href="/vuejs/vue">vuejs / vue</a></h2>
  <p>Vue.js is a progressive framework for building user interfaces.</p>
</article>
<article>
  <h2><a href="/torvalds/linux">torvalds / linux</a></h2>
  <p>Linux kernel source tree</p>
</article>
</body>
</html>
"""

EMPTY_HTML = "<html><body></body></html>"

MALFORMED_HTML = "<html><body><h2><a href='/bad'>nope</h2></body></html>"

NO_DESCRIPTION_HTML = """
<html>
<body>
<article>
  <h2><a href="/owner/repo">owner / repo</a></h2>
</article>
</body>
</html>
"""


# =============================================================================
# GitHubTrendingParser
# =============================================================================


class TestGitHubTrendingParser:

    def test_parses_well_formed_trending_html(self):
        parser = GitHubTrendingParser()
        parser.feed(SAMPLE_TRENDING_HTML)
        assert len(parser.repos) == 3

    def test_extracts_owner_and_name_from_href(self):
        parser = GitHubTrendingParser()
        parser.feed(SAMPLE_TRENDING_HTML)
        assert parser.repos[0]["owner"] == "facebook"
        assert parser.repos[0]["name"] == "react"
        assert parser.repos[0]["full_name"] == "facebook/react"
        assert parser.repos[0]["url"] == "https://github.com/facebook/react"

    def test_handles_repos_without_descriptions(self):
        """Repos without <p> tags after <h2> are not appended (no endtag trigger)."""
        parser = GitHubTrendingParser()
        parser.feed(NO_DESCRIPTION_HTML)
        # No <p> tag means _current_repo never gets appended
        assert len(parser.repos) == 0


# =============================================================================
# GitHubTrendingCollector
# =============================================================================


class TestGitHubTrendingCollector:

    @pytest.fixture
    def collector(self):
        return GitHubTrendingCollector()

    def test_init(self, collector):
        assert collector.name == "github-trending"
        assert collector.source == TrendSource.GITHUB
        assert collector.collection_count == 0
        assert collector.error_count == 0

    async def test_parses_html_with_repos_correctly(self, collector):
        with patch.object(collector, "_make_raw_request", return_value=SAMPLE_TRENDING_HTML.encode()):
            trends = await collector.collect()
            assert len(trends) == 3
            assert all(isinstance(t, Trend) for t in trends)

    async def test_extracts_repo_names_and_descriptions(self, collector):
        with patch.object(collector, "_make_raw_request", return_value=SAMPLE_TRENDING_HTML.encode()):
            trends = await collector.collect()
            assert trends[0].name == "facebook/react"
            assert "JavaScript library" in trends[0].description

    async def test_scores_decrease_by_position(self, collector):
        with patch.object(collector, "_make_raw_request", return_value=SAMPLE_TRENDING_HTML.encode()):
            trends = await collector.collect()
            assert trends[0].score > trends[1].score
            assert trends[1].score > trends[2].score

    async def test_limits_to_25_repos_max(self, collector):
        # Generate HTML with 30 repos
        repos_html = ""
        for i in range(30):
            repos_html += f"""
            <h2><a href="/owner{i}/repo{i}">owner{i} / repo{i}</a></h2>
            <p>Description for repo {i}</p>
            """
        html = f"<html><body>{repos_html}</body></html>"

        with patch.object(collector, "_make_raw_request", return_value=html.encode()):
            trends = await collector.collect()
            assert len(trends) <= 25

    async def test_handles_empty_html(self, collector):
        with patch.object(collector, "_make_raw_request", return_value=EMPTY_HTML.encode()):
            trends = await collector.collect()
            assert trends == []

    async def test_handles_malformed_html_gracefully(self, collector):
        with patch.object(collector, "_make_raw_request", return_value=MALFORMED_HTML.encode()):
            trends = await collector.collect()
            # Should not crash, may return 0 or partial results
            assert isinstance(trends, list)

    async def test_sets_correct_source_and_category(self, collector):
        with patch.object(collector, "_make_raw_request", return_value=SAMPLE_TRENDING_HTML.encode()):
            trends = await collector.collect()
            for t in trends:
                assert t.source == TrendSource.GITHUB
                assert t.category == TrendCategory.TECHNOLOGY

    async def test_handles_network_failure_gracefully(self, collector):
        with patch.object(collector, "_make_raw_request", return_value=None):
            trends = await collector.collect()
            assert trends == []

    async def test_increments_collection_count_on_success(self, collector):
        with patch.object(collector, "_make_raw_request", return_value=SAMPLE_TRENDING_HTML.encode()):
            await collector.collect()
            assert collector.collection_count == 1

    async def test_increments_error_count_on_failure(self, collector):
        with patch.object(collector, "_make_raw_request", side_effect=Exception("boom")):
            trends = await collector.collect()
            assert trends == []
            assert collector.error_count == 1


# =============================================================================
# PackageDownloadsCollector
# =============================================================================


class TestPackageDownloadsCollector:

    @pytest.fixture
    def collector(self):
        return PackageDownloadsCollector(
            npm_packages=["react"],
            pypi_packages=["flask"],
        )

    def test_init_defaults(self):
        c = PackageDownloadsCollector()
        assert "react" in c.npm_packages
        assert "flask" in c.pypi_packages

    async def test_collects_npm_package_data(self, collector):
        npm_data = {"downloads": 5_000_000, "package": "react", "start": "2026-03-05", "end": "2026-03-12"}
        with patch.object(collector, "_make_request", return_value=npm_data):
            trend = collector._collect_npm("react")
            assert trend is not None
            assert trend.name == "npm:react"
            assert trend.volume == 5_000_000

    async def test_collects_pypi_package_data(self, collector):
        pypi_data = {"data": {"last_week": 1_000_000}, "package": "flask", "type": "recent_downloads"}
        with patch.object(collector, "_make_request", return_value=pypi_data):
            trend = collector._collect_pypi("flask")
            assert trend is not None
            assert trend.name == "pypi:flask"
            assert trend.volume == 1_000_000

    def test_downloads_to_score_npm_tiers(self, collector):
        assert collector._downloads_to_score(10_000_000, "npm") == 95
        assert collector._downloads_to_score(1_000_000, "npm") == 85
        assert collector._downloads_to_score(100_000, "npm") == 70
        assert collector._downloads_to_score(10_000, "npm") == 50
        assert collector._downloads_to_score(100, "npm") == 30

    def test_downloads_to_score_pypi_tiers(self, collector):
        assert collector._downloads_to_score(5_000_000, "pypi") == 95
        assert collector._downloads_to_score(500_000, "pypi") == 85
        assert collector._downloads_to_score(50_000, "pypi") == 70
        assert collector._downloads_to_score(5_000, "pypi") == 50
        assert collector._downloads_to_score(100, "pypi") == 30

    async def test_handles_npm_api_failure_gracefully(self, collector):
        with patch.object(collector, "_make_request", return_value=None):
            trend = collector._collect_npm("nonexistent")
            assert trend is None

    async def test_handles_pypi_api_failure_gracefully(self, collector):
        with patch.object(collector, "_make_request", return_value=None):
            trend = collector._collect_pypi("nonexistent")
            assert trend is None

    async def test_custom_package_lists_work(self):
        c = PackageDownloadsCollector(npm_packages=["express"], pypi_packages=["django"])
        assert c.npm_packages == ["express"]
        assert c.pypi_packages == ["django"]

    async def test_creates_trends_with_correct_metadata(self, collector):
        npm_data = {"downloads": 2_000_000, "package": "react"}
        with patch.object(collector, "_make_request", return_value=npm_data):
            trend = collector._collect_npm("react")
            assert trend.metadata["downloads_weekly"] == 2_000_000
            assert trend.metadata["registry"] == "npm"

    async def test_sets_volume_to_download_count(self, collector):
        pypi_data = {"data": {"last_week": 750_000}}
        with patch.object(collector, "_make_request", return_value=pypi_data):
            trend = collector._collect_pypi("flask")
            assert trend.volume == 750_000

    async def test_collect_increments_count(self, collector):
        with patch.object(collector, "_make_request", return_value=None):
            await collector.collect()
            assert collector.collection_count == 1

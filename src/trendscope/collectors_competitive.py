"""Competitive landscape collectors: GitHub Trending + npm/PyPI downloads."""

import json
import logging
import time
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional
from urllib.request import Request, urlopen
from urllib.error import URLError

from trendscope.core import Trend, TrendSource, TrendCategory, TrendStatus
from trendscope.collectors import TrendCollector

logger = logging.getLogger(__name__)


class GitHubTrendingParser(HTMLParser):
    """Parse GitHub trending page HTML to extract repos."""

    def __init__(self):
        super().__init__()
        self.repos: List[Dict[str, Any]] = []
        self._current_repo: Optional[Dict[str, Any]] = None
        self._in_repo_name = False
        self._in_description = False
        self._in_stars = False
        self._capture_text = False
        self._current_text = ""
        self._h2_count = 0

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        # Repo link: <h2 class="..."><a href="/owner/repo">
        if tag == "h2":
            self._h2_count += 1
        if tag == "a" and self._h2_count > 0:
            href = attrs_dict.get("href", "")
            parts = href.strip("/").split("/")
            if len(parts) == 2 and parts[0] and parts[1]:
                self._current_repo = {
                    "owner": parts[0],
                    "name": parts[1],
                    "full_name": f"{parts[0]}/{parts[1]}",
                    "description": "",
                    "stars": 0,
                    "language": "",
                    "url": f"https://github.com{href}",
                }
                self._in_repo_name = True
        if tag == "p" and self._current_repo:
            self._in_description = True
            self._current_text = ""
            self._capture_text = True

    def handle_endtag(self, tag):
        if tag == "h2":
            self._h2_count = max(0, self._h2_count - 1)
            self._in_repo_name = False
        if tag == "p" and self._in_description and self._current_repo:
            self._current_repo["description"] = self._current_text.strip()
            self._in_description = False
            self._capture_text = False
            self.repos.append(self._current_repo)
            self._current_repo = None

    def handle_data(self, data):
        if self._capture_text:
            self._current_text += data


class GitHubTrendingCollector(TrendCollector):
    """Collects trending repositories from GitHub."""

    def __init__(self):
        super().__init__("github-trending", TrendSource.GITHUB)

    async def collect(self) -> List[Trend]:
        """Collect trending repos from GitHub."""
        try:
            raw = self._make_raw_request(
                "https://github.com/trending",
                headers={"Accept": "text/html"},
            )
            if not raw:
                return []

            html = raw.decode("utf-8", errors="replace")
            parser = GitHubTrendingParser()
            parser.feed(html)

            trends = []
            for i, repo in enumerate(parser.repos[:25]):
                score = max(90 - i * 3, 10)
                trend = self._create_trend(
                    name=repo["full_name"],
                    description=repo.get("description", "") or f"Trending GitHub repo: {repo['full_name']}",
                    category=TrendCategory.TECHNOLOGY,
                    score=score,
                    status=TrendStatus.GROWING,
                    keywords=[repo["owner"], repo["name"]],
                    tags=["github", "trending", "open-source"],
                    metadata={"github_url": repo["url"], "language": repo.get("language", "")},
                )
                trends.append(trend)

            self.collection_count += 1
            self.last_collection = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            return trends
        except Exception as e:
            logger.warning(f"GitHub trending collection failed: {e}")
            self.error_count += 1
            return []


class PackageDownloadsCollector(TrendCollector):
    """Collects download stats from npm and PyPI for curated packages."""

    # Curated packages to track
    DEFAULT_NPM_PACKAGES = ["react", "vue", "angular", "svelte", "next", "express", "fastify"]
    DEFAULT_PYPI_PACKAGES = ["django", "flask", "fastapi", "pandas", "numpy", "pytorch", "transformers"]

    def __init__(self, npm_packages=None, pypi_packages=None):
        super().__init__("package-downloads", TrendSource.NPM)
        self.npm_packages = npm_packages or self.DEFAULT_NPM_PACKAGES
        self.pypi_packages = pypi_packages or self.DEFAULT_PYPI_PACKAGES

    async def collect(self) -> List[Trend]:
        """Collect download stats from npm and PyPI."""
        trends = []

        # npm packages
        for pkg in self.npm_packages:
            trend = self._collect_npm(pkg)
            if trend:
                trends.append(trend)

        # PyPI packages
        for pkg in self.pypi_packages:
            trend = self._collect_pypi(pkg)
            if trend:
                trends.append(trend)

        self.collection_count += 1
        self.last_collection = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        return trends

    def _collect_npm(self, package_name):
        """Get npm download stats."""
        try:
            url = f"https://api.npmjs.org/downloads/point/last-week/{package_name}"
            data = self._make_request(url)
            if not data:
                return None

            downloads = data.get("downloads", 0)
            score = self._downloads_to_score(downloads, "npm")

            return self._create_trend(
                name=f"npm:{package_name}",
                description=f"npm package {package_name}: {downloads:,} downloads/week",
                category=TrendCategory.TECHNOLOGY,
                score=score,
                status=TrendStatus.STABLE,
                volume=downloads,
                keywords=[package_name, "npm", "javascript", "nodejs"],
                tags=["npm", "package", "downloads"],
                metadata={"downloads_weekly": downloads, "registry": "npm"},
            )
        except Exception as e:
            logger.debug(f"npm collection failed for {package_name}: {e}")
            return None

    def _collect_pypi(self, package_name):
        """Get PyPI download stats."""
        try:
            url = f"https://pypistats.org/api/packages/{package_name}/recent"
            data = self._make_request(url)
            if not data:
                return None

            downloads = data.get("data", {}).get("last_week", 0)
            score = self._downloads_to_score(downloads, "pypi")

            trend = self._create_trend(
                name=f"pypi:{package_name}",
                description=f"PyPI package {package_name}: {downloads:,} downloads/week",
                category=TrendCategory.TECHNOLOGY,
                score=score,
                status=TrendStatus.STABLE,
                volume=downloads,
                keywords=[package_name, "pypi", "python"],
                tags=["pypi", "package", "downloads"],
                metadata={"downloads_weekly": downloads, "registry": "pypi"},
            )
            trend.source = TrendSource.PYPI
            return trend
        except Exception as e:
            logger.debug(f"PyPI collection failed for {package_name}: {e}")
            return None

    def _downloads_to_score(self, downloads, registry):
        """Convert download count to 0-100 score."""
        if registry == "npm":
            if downloads >= 10_000_000:
                return 95
            if downloads >= 1_000_000:
                return 85
            if downloads >= 100_000:
                return 70
            if downloads >= 10_000:
                return 50
            return 30
        else:  # pypi
            if downloads >= 5_000_000:
                return 95
            if downloads >= 500_000:
                return 85
            if downloads >= 50_000:
                return 70
            if downloads >= 5_000:
                return 50
            return 30

"""Tests for category coverage analysis."""

import pytest
from trendscope.core import Trend, TrendCategory, TrendSource, TrendDatabase
from trendscope.coverage import CoverageAnalyzer


class TestCoverageAnalyzer:
    @pytest.fixture
    def db(self, tmp_path):
        return TrendDatabase(db_path=tmp_path / "test.db")

    @pytest.fixture
    def analyzer(self, db):
        return CoverageAnalyzer(db)

    def test_analyze_coverage_empty(self, analyzer):
        matrix = analyzer.analyze_coverage()
        assert matrix == {}

    def test_analyze_coverage_single_trend(self, db, analyzer):
        t = Trend(name="AI", score=80, category=TrendCategory.TECHNOLOGY, source=TrendSource.GOOGLE_TRENDS)
        db.save_trend(t)
        matrix = analyzer.analyze_coverage()
        assert "technology" in matrix or TrendCategory.TECHNOLOGY.value in matrix

    def test_analyze_coverage_multiple_categories(self, db, analyzer):
        t1 = Trend(name="AI", score=80, category=TrendCategory.TECHNOLOGY, source=TrendSource.GOOGLE_TRENDS)
        t2 = Trend(name="Crypto", score=60, category=TrendCategory.FINANCE, source=TrendSource.REDDIT)
        db.save_trend(t1)
        db.save_trend(t2)
        matrix = analyzer.analyze_coverage()
        assert len(matrix) >= 2

    def test_analyze_coverage_multiple_sources(self, db, analyzer):
        t1 = Trend(name="AI 1", score=80, category=TrendCategory.TECHNOLOGY, source=TrendSource.GOOGLE_TRENDS)
        t2 = Trend(name="AI 2", score=70, category=TrendCategory.TECHNOLOGY, source=TrendSource.REDDIT)
        db.save_trend(t1)
        db.save_trend(t2)
        matrix = analyzer.analyze_coverage()
        tech_key = TrendCategory.TECHNOLOGY.value
        assert tech_key in matrix
        assert len(matrix[tech_key]) == 2

    def test_identify_blind_spots_empty(self, analyzer):
        spots = analyzer.identify_blind_spots()
        assert spots == []

    def test_identify_blind_spots_low_diversity(self, db, analyzer):
        t = Trend(name="AI", score=50, category=TrendCategory.TECHNOLOGY, source=TrendSource.GOOGLE_TRENDS)
        db.save_trend(t)
        spots = analyzer.identify_blind_spots(min_sources=2)
        low_diversity = [s for s in spots if s["issue"] == "low_source_diversity"]
        assert len(low_diversity) >= 1

    def test_identify_blind_spots_no_high_scoring(self, db, analyzer):
        t = Trend(name="Niche", score=30, category=TrendCategory.NICHE_MARKET, source=TrendSource.GOOGLE_TRENDS)
        db.save_trend(t)
        spots = analyzer.identify_blind_spots(min_high_score=70)
        no_high = [s for s in spots if s["issue"] == "no_high_scoring_trends"]
        assert len(no_high) >= 1

    def test_identify_blind_spots_no_issues(self, db, analyzer):
        for i in range(3):
            src = [TrendSource.GOOGLE_TRENDS, TrendSource.REDDIT, TrendSource.HACKER_NEWS][i]
            t = Trend(name=f"AI {i}", score=85, category=TrendCategory.TECHNOLOGY, source=src)
            db.save_trend(t)
        spots = analyzer.identify_blind_spots(min_sources=2, min_high_score=70)
        tech_spots = [s for s in spots if s["category"] == TrendCategory.TECHNOLOGY.value]
        assert len(tech_spots) == 0

    def test_get_coverage_report_structure(self, analyzer):
        report = analyzer.get_coverage_report()
        assert "matrix" in report
        assert "blind_spots" in report
        assert "summary" in report
        assert "total_categories" in report["summary"]
        assert "total_sources" in report["summary"]
        assert "blind_spot_count" in report["summary"]

    def test_get_coverage_report_with_data(self, db, analyzer):
        t = Trend(name="AI", score=80, category=TrendCategory.TECHNOLOGY, source=TrendSource.GOOGLE_TRENDS)
        db.save_trend(t)
        report = analyzer.get_coverage_report()
        assert report["summary"]["total_categories"] >= 1

    def test_coverage_matrix_count_accuracy(self, db, analyzer):
        for i in range(5):
            t = Trend(name=f"Tech {i}", score=70 + i, category=TrendCategory.TECHNOLOGY, source=TrendSource.GOOGLE_TRENDS)
            db.save_trend(t)
        matrix = analyzer.analyze_coverage()
        tech_key = TrendCategory.TECHNOLOGY.value
        assert tech_key in matrix
        google_key = TrendSource.GOOGLE_TRENDS.value
        assert matrix[tech_key][google_key]["count"] == 5

    def test_coverage_avg_score(self, db, analyzer):
        t1 = Trend(name="A", score=80, category=TrendCategory.TECHNOLOGY, source=TrendSource.GOOGLE_TRENDS)
        t2 = Trend(name="B", score=60, category=TrendCategory.TECHNOLOGY, source=TrendSource.GOOGLE_TRENDS)
        db.save_trend(t1)
        db.save_trend(t2)
        matrix = analyzer.analyze_coverage()
        tech_key = TrendCategory.TECHNOLOGY.value
        google_key = TrendSource.GOOGLE_TRENDS.value
        assert matrix[tech_key][google_key]["avg_score"] == 70.0

    def test_blind_spots_min_sources_threshold(self, db, analyzer):
        t1 = Trend(name="A", score=90, category=TrendCategory.TECHNOLOGY, source=TrendSource.GOOGLE_TRENDS)
        t2 = Trend(name="B", score=85, category=TrendCategory.TECHNOLOGY, source=TrendSource.REDDIT)
        db.save_trend(t1)
        db.save_trend(t2)
        spots = analyzer.identify_blind_spots(min_sources=3)
        low_div = [s for s in spots if s["issue"] == "low_source_diversity" and s["category"] == TrendCategory.TECHNOLOGY.value]
        assert len(low_div) >= 1

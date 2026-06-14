"""Category coverage analysis and blind spot detection."""

import sqlite3


class CoverageAnalyzer:
    def __init__(self, db):
        self.db = db

    def analyze_coverage(self) -> dict:
        """Build coverage matrix by category x source."""
        with sqlite3.connect(self.db.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT category, source, COUNT(*) as count, AVG(score) as avg_score "
                "FROM trends GROUP BY category, source"
            )
            matrix: dict = {}
            for row in cursor.fetchall():
                cat = row[0] or "uncategorized"
                src = row[1] or "unknown"
                if cat not in matrix:
                    matrix[cat] = {}
                matrix[cat][src] = {
                    "count": row[2],
                    "avg_score": round(row[3] or 0, 2),
                }
            return matrix

    def identify_blind_spots(
        self, min_sources: int = 2, min_high_score: float = 70
    ) -> list[dict]:
        """Find categories with limited source diversity or no high-scoring trends."""
        with sqlite3.connect(self.db.db_path) as conn:
            cursor = conn.cursor()
            blind_spots = []

            # Categories with few sources
            cursor.execute(
                "SELECT category, COUNT(DISTINCT source) as source_count "
                "FROM trends GROUP BY category"
            )
            for row in cursor.fetchall():
                if row[1] < min_sources:
                    blind_spots.append(
                        {
                            "category": row[0] or "uncategorized",
                            "issue": "low_source_diversity",
                            "source_count": row[1],
                            "min_required": min_sources,
                        }
                    )

            # Categories with no high-scoring trends
            cursor.execute(
                "SELECT category, MAX(score) as max_score "
                "FROM trends GROUP BY category"
            )
            for row in cursor.fetchall():
                if (row[1] or 0) < min_high_score:
                    blind_spots.append(
                        {
                            "category": row[0] or "uncategorized",
                            "issue": "no_high_scoring_trends",
                            "max_score": row[1] or 0,
                            "threshold": min_high_score,
                        }
                    )
            return blind_spots

    def get_coverage_report(self) -> dict:
        matrix = self.analyze_coverage()
        blind_spots = self.identify_blind_spots()
        total_categories = len(matrix)
        all_sources: set = set()
        for sources in matrix.values():
            all_sources.update(sources.keys())
        return {
            "matrix": matrix,
            "blind_spots": blind_spots,
            "summary": {
                "total_categories": total_categories,
                "total_sources": len(all_sources),
                "blind_spot_count": len(blind_spots),
            },
        }

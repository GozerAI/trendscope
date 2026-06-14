"""Statistical anomaly detection using z-score, IQR, and moving average."""

import math
from dataclasses import dataclass
from typing import Optional

try:
    from gozerai_telemetry.metrics import get_collector
    _collector = get_collector("trendscope")
    _anomaly_counter = _collector.counter("anomalies_detected_total", "Total anomalies detected")
except ImportError:
    _anomaly_counter = None


@dataclass
class AnomalyResult:
    trend_id: str
    trend_name: str
    anomaly_type: str  # 'zscore', 'iqr', 'moving_average', 'composite'
    severity: str  # 'low', 'medium', 'high', 'critical'
    value: float
    expected_range: tuple
    deviation: float


def mean(series: list[float]) -> float:
    return sum(series) / len(series) if series else 0.0


def std_dev(series: list[float]) -> float:
    if len(series) < 2:
        return 0.0
    m = mean(series)
    variance = sum((x - m) ** 2 for x in series) / (len(series) - 1)
    return math.sqrt(variance)


def zscore_detect(series: list[float], threshold: float = 2.0) -> list[dict]:
    """Detect anomalies using z-score method."""
    if len(series) < 3:
        return []
    m = mean(series)
    s = std_dev(series)
    if s == 0:
        return []
    results = []
    for i, val in enumerate(series):
        z = abs(val - m) / s
        if z >= threshold:
            results.append({
                "index": i,
                "value": val,
                "z_score": z,
                "expected_range": (m - threshold * s, m + threshold * s),
            })
    return results


def iqr_detect(series: list[float], multiplier: float = 1.5) -> list[dict]:
    """Detect anomalies using IQR method."""
    if len(series) < 4:
        return []
    sorted_s = sorted(series)
    n = len(sorted_s)
    q1 = sorted_s[n // 4]
    q3 = sorted_s[(3 * n) // 4]
    iqr = q3 - q1
    lower = q1 - multiplier * iqr
    upper = q3 + multiplier * iqr
    results = []
    for i, val in enumerate(series):
        if val < lower or val > upper:
            results.append({
                "index": i,
                "value": val,
                "expected_range": (lower, upper),
                "deviation": min(abs(val - lower), abs(val - upper)),
            })
    return results


def moving_average_detect(
    series: list[float], window: int = 5, threshold: float = 2.0
) -> list[dict]:
    """Detect anomalies using moving average deviation."""
    if len(series) < window + 1:
        return []
    results = []
    for i in range(window, len(series)):
        window_data = series[i - window : i]
        ma = mean(window_data)
        s = std_dev(window_data)
        if s == 0:
            continue
        deviation = abs(series[i] - ma) / s
        if deviation >= threshold:
            results.append({
                "index": i,
                "value": series[i],
                "moving_avg": ma,
                "deviation": deviation,
                "expected_range": (ma - threshold * s, ma + threshold * s),
            })
    return results


def composite_anomaly_score(
    series: list[float],
    threshold_z: float = 2.0,
    threshold_iqr: float = 1.5,
    threshold_ma: float = 2.0,
    window: int = 5,
) -> dict:
    """Multi-method confirmation scoring. Returns {index: fraction_of_methods}."""
    z_results = zscore_detect(series, threshold_z)
    iqr_results = iqr_detect(series, threshold_iqr)
    ma_results = moving_average_detect(series, window, threshold_ma)

    z_indices = {r["index"] for r in z_results}
    iqr_indices = {r["index"] for r in iqr_results}
    ma_indices = {r["index"] for r in ma_results}

    all_indices = z_indices | iqr_indices | ma_indices
    scored = {}
    for idx in all_indices:
        methods = sum([idx in z_indices, idx in iqr_indices, idx in ma_indices])
        scored[idx] = methods / 3.0
    return scored


def classify_severity(score: float) -> str:
    if score >= 1.0:
        return "critical"
    elif score >= 0.67:
        return "high"
    elif score >= 0.34:
        return "medium"
    return "low"


class AnomalyDetector:
    def __init__(self, db):
        self.db = db

    def detect_all(self, lookback_days: int = 14) -> list[AnomalyResult]:
        """Run anomaly detection on all trends with sufficient history."""
        results = []
        trends = self.db.get_trends(limit=1000)
        for trend in trends:
            trend_results = self.detect_for_trend(
                trend.id, trend.name, lookback_days
            )
            results.extend(trend_results)
        if _anomaly_counter:
            for r in results:
                _anomaly_counter.inc(severity=r.severity)
        return results

    def detect_for_trend(
        self, trend_id: str, trend_name: str = "", lookback_days: int = 14
    ) -> list[AnomalyResult]:
        """Run anomaly detection on a single trend's history."""
        history = self.db.get_trend_history(trend_id, days=lookback_days)
        if len(history) < 3:
            return []
        scores = []
        for h in history:
            if isinstance(h, dict):
                scores.append(h.get("score", h.get("value", 0)) or 0)
            else:
                scores.append(getattr(h, "score", 0) or 0)
        if not scores:
            return []
        composite = composite_anomaly_score(scores)
        results = []
        m = mean(scores)
        s = std_dev(scores)
        for idx, score in composite.items():
            severity = classify_severity(score)
            results.append(
                AnomalyResult(
                    trend_id=trend_id,
                    trend_name=trend_name,
                    anomaly_type="composite",
                    severity=severity,
                    value=scores[idx] if idx < len(scores) else 0,
                    expected_range=(m - 2 * s, m + 2 * s),
                    deviation=score,
                )
            )
        return results

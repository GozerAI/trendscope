"""TrendScope FastAPI application."""

import hashlib
import hmac
import json
import logging
import os
from contextlib import asynccontextmanager
from typing import Optional

import httpx
from fastapi import FastAPI, Depends, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware

from trendscope.service import TrendService

logger = logging.getLogger(__name__)

_service: TrendService | None = None

ZUULTIMATE_BASE_URL = os.environ.get("ZUULTIMATE_BASE_URL", "http://localhost:8000")
CORS_ORIGINS = os.environ.get("CORS_ORIGINS", "http://localhost:3000").split(",")
KH_WEBHOOK_SECRET = os.environ.get("KH_WEBHOOK_SECRET", "")
KH_BASE_URL = os.environ.get("KH_BASE_URL", "")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _service
    _service = TrendService()
    await _service.initialize()
    logger.info("TrendScope started")
    yield
    logger.info("TrendScope shutting down")


app = FastAPI(title="TrendScope", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "Authorization"],
)


# ── Auth dependency ────────────────────────────────────────────────────────────

async def get_tenant(request: Request) -> dict:
    """Validate bearer token against Zuultimate and return tenant context."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")

    token = auth[7:]
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"{ZUULTIMATE_BASE_URL}/v1/identity/auth/validate",
                headers={"Authorization": f"Bearer {token}"},
            )
    except httpx.RequestError as e:
        logger.error("Zuultimate unreachable: %s", e)
        raise HTTPException(status_code=503, detail="Auth service unavailable")

    if resp.status_code == 401:
        raise HTTPException(status_code=401, detail="Invalid or expired credentials")
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail="Auth service error")

    return resp.json()  # { user_id, username, tenant_id, plan, entitlements }


def require_entitlement(entitlement: str):
    """Dependency factory: blocks if tenant lacks the required entitlement."""
    async def _check(tenant: dict = Depends(get_tenant)) -> dict:
        if entitlement not in tenant.get("entitlements", []):
            raise HTTPException(
                status_code=403,
                detail=f"Your plan does not include '{entitlement}'. Upgrade to access this feature.",
            )
        return tenant
    return _check


def _svc() -> TrendService:
    if _service is None:
        raise HTTPException(status_code=503, detail="Service not initialized")
    return _service


# ── Basic endpoints (trendscope:basic) ────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "service": "trendscope", "version": app.version}


@app.get("/health/detailed")
async def health_detailed():
    checks = {}
    status = "ok"

    # Service layer check
    try:
        svc = _svc()
        stats = await svc.get_stats()
        db_stats = stats.get("database", {})
        checks["service"] = {"status": "ok", "trends_stored": db_stats.get("total_trends", 0)}
    except Exception as e:
        checks["service"] = {"status": "error", "error": str(e)}
        status = "degraded"

    # Telemetry check
    try:
        svc = _svc()
        telemetry = svc.get_telemetry()
        checks["telemetry"] = {"status": "ok" if telemetry else "unavailable"}
    except Exception:
        checks["telemetry"] = {"status": "unavailable"}

    return {"status": status, "service": "trendscope", "version": app.version, "checks": checks}


@app.get("/v1/trends")
async def get_trends(
    category: Optional[str] = Query(None),
    min_score: float = Query(0.0),
    limit: int = Query(50, le=200),
    tenant: dict = Depends(require_entitlement("trendscope:basic")),
):
    return await _svc().get_trends(category=category, min_score=min_score, limit=limit)


@app.get("/v1/trends/top")
async def get_top_trends(
    limit: int = Query(10, le=50),
    tenant: dict = Depends(require_entitlement("trendscope:basic")),
):
    return await _svc().get_top_trends(limit=limit)


@app.get("/v1/trends/emerging")
async def get_emerging_trends(
    limit: int = Query(10, le=50),
    tenant: dict = Depends(require_entitlement("trendscope:basic")),
):
    return await _svc().get_emerging_trends(limit=limit)


@app.get("/v1/trends/search")
async def search_trends(
    q: str = Query(..., min_length=2),
    limit: int = Query(20, le=100),
    tenant: dict = Depends(require_entitlement("trendscope:basic")),
):
    return await _svc().search_trends(query=q, limit=limit)


@app.get("/v1/trends/{trend_id}")
async def get_trend(
    trend_id: str,
    tenant: dict = Depends(require_entitlement("trendscope:basic")),
):
    result = await _svc().get_trend(trend_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Trend not found")
    return result


@app.get("/v1/stats")
async def get_stats(tenant: dict = Depends(require_entitlement("trendscope:basic"))):
    return await _svc().get_stats()


# ── Full endpoints (trendscope:full) ──────────────────────────────────────────

@app.get("/v1/signals/strong-buy")
async def get_strong_buy_signals(
    min_score: int = Query(80),
    tenant=Depends(require_entitlement("trendscope:full")),
):
    """Get trends with STRONG_BUY signal for the research agent."""
    trends = _svc().get_strong_buy_trends(min_score)
    return {"trends": trends, "total": len(trends)}


@app.get("/v1/opportunities")
async def find_opportunities(
    min_score: float = Query(50.0),
    limit: int = Query(10, le=50),
    tenant: dict = Depends(require_entitlement("trendscope:full")),
):
    return await _svc().find_opportunities(min_score=min_score, limit=limit)


@app.get("/v1/signals")
async def get_signals(tenant: dict = Depends(require_entitlement("trendscope:full"))):
    return await _svc().get_signals()


@app.get("/v1/drifts")
async def detect_drifts(
    lookback_days: int = Query(7),
    tenant: dict = Depends(require_entitlement("trendscope:full")),
):
    return await _svc().detect_drifts(lookback_days=lookback_days)


@app.get("/v1/correlations")
async def find_correlations(
    min_correlation: float = Query(0.3),
    tenant: dict = Depends(require_entitlement("trendscope:full")),
):
    return await _svc().find_correlations(min_correlation=min_correlation)


@app.get("/v1/intelligence")
async def get_intelligence_report(
    tenant: dict = Depends(require_entitlement("trendscope:full")),
):
    return await _svc().get_intelligence_report()


@app.get("/v1/executive/{executive_code}")
async def get_executive_report(
    executive_code: str,
    tenant: dict = Depends(require_entitlement("trendscope:full")),
):
    if executive_code not in ("CMO", "CPO", "CRO", "CEO"):
        raise HTTPException(status_code=400, detail="Invalid executive code. Use CMO, CPO, CRO, or CEO.")
    return await _svc().get_executive_report(executive_code)


@app.get("/v1/executive/{executive_code}/narrative")
async def get_executive_narrative(
    executive_code: str,
    tenant=Depends(require_entitlement("trendscope:enterprise")),
):
    import time as _time
    svc = _svc()
    report = await svc.get_executive_report(executive_code)
    if "error" in report:
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=400, content=report)
    return {
        "executive": executive_code,
        "narrative": report.get("narrative"),
        "generated_at": _time.strftime("%Y-%m-%dT%H:%M:%SZ", _time.gmtime()),
    }


@app.post("/v1/refresh")
async def refresh_trends(
    tenant: dict = Depends(require_entitlement("trendscope:full")),
):
    return await _svc().refresh_trends()


# ── Forecast endpoints ───────────────────────────────────────────────────────

@app.get("/v1/trends/{trend_id}/forecast")
async def get_trend_forecast(
    trend_id: str,
    tenant=Depends(require_entitlement("trendscope:full")),
):
    forecast = _svc().get_forecast(trend_id)
    if not forecast:
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=404, content={"detail": "Insufficient history for forecast"})
    return forecast


@app.get("/v1/forecasts")
async def get_forecasts(
    limit: int = Query(20, le=100),
    tenant=Depends(require_entitlement("trendscope:full")),
):
    return _svc().get_forecasts(limit)


# ── Credibility endpoint ─────────────────────────────────────────────────────

@app.get("/v1/credibility")
async def get_credibility(tenant=Depends(require_entitlement("trendscope:full"))):
    return _svc().get_credibility_report()


# ── Alert endpoints ──────────────────────────────────────────────────────────

@app.post("/v1/alerts")
async def create_alert(request: Request, tenant=Depends(require_entitlement("trendscope:full"))):
    body = await request.json()
    rule = _svc().register_alert_rule(
        name=body["name"], conditions=body["conditions"],
        webhook_url=body["webhook_url"], secret=body.get("webhook_secret", ""),
    )
    return {"id": rule.id, "name": rule.name, "created_at": rule.created_at}


@app.get("/v1/alerts")
async def list_alerts(tenant=Depends(require_entitlement("trendscope:full"))):
    rules = _svc().get_alert_rules()
    return {"rules": [{"id": r.id, "name": r.name, "conditions": r.conditions, "webhook_url": r.webhook_url, "active": r.active, "created_at": r.created_at, "last_triggered_at": r.last_triggered_at} for r in rules]}


@app.delete("/v1/alerts/{alert_id}")
async def delete_alert(alert_id: str, tenant=Depends(require_entitlement("trendscope:full"))):
    deleted = _svc().delete_alert_rule(alert_id)
    if not deleted:
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=404, content={"detail": "Alert not found"})
    return {"deleted": True}


@app.get("/v1/alerts/history")
async def alert_history(limit: int = 50, tenant=Depends(require_entitlement("trendscope:full"))):
    return {"history": _svc().get_alert_history(limit)}


# -- Knowledge Harvester Integration -------------------------------------------

@app.post("/v1/webhooks/kh")
async def kh_webhook(request: Request):
    """Receive webhook events from Knowledge Harvester."""
    body = await request.body()

    # Verify HMAC signature if secret is configured
    if KH_WEBHOOK_SECRET:
        signature = request.headers.get("X-Webhook-Signature", "")
        expected = "sha256=" + hmac.new(
            KH_WEBHOOK_SECRET.encode(), body, hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise HTTPException(status_code=401, detail="Invalid webhook signature")

    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    event_type = payload.get("event", "")
    logger.info("KH webhook received: %s", event_type)

    # Route through receive_intelligence for known event types
    result = _svc().receive_kh_intelligence(payload)

    # Push accepted events to the intelligence feed
    if result.get("status") == "accepted":
        _svc()._feed.push_event(f"kh.{payload.get('event', 'unknown')}", payload.get("data", {}))

    return result


@app.get("/v1/trends/{trend_id}/artifacts")
async def get_trend_artifacts(
    trend_id: str,
    limit: int = Query(10, le=50),
    tenant: dict = Depends(require_entitlement("trendscope:full")),
):
    """Get KH artifacts related to a specific trend."""
    svc = _svc()
    trend = await svc.get_trend(trend_id)
    if trend is None:
        raise HTTPException(status_code=404, detail="Trend not found")

    if not KH_BASE_URL:
        return {"trend_id": trend_id, "artifacts": [], "note": "KH integration not configured"}

    # Use trend keywords to search KH artifacts
    keywords = trend.get("keywords", [])
    category = trend.get("category", "")

    from trendscope.integrations.kh_client import get_artifacts, map_ts_category_to_kh

    artifacts = []
    kh_categories = map_ts_category_to_kh(category)
    for kh_cat in kh_categories[:2]:
        arts = get_artifacts(category=kh_cat, quality_min=50, limit=limit)
        artifacts.extend(arts)

    return {
        "trend_id": trend_id,
        "trend_name": trend.get("name", ""),
        "artifacts": artifacts[:limit],
        "total": len(artifacts),
    }


# ── Scheduler endpoints ──────────────────────────────────────────────────────

@app.get("/v1/schedules")
async def list_schedules(tenant=Depends(require_entitlement("trendscope:full"))):
    return _svc().get_scheduler().list_schedules()


@app.post("/v1/schedules/{name}/run")
async def run_schedule(name: str, tenant=Depends(require_entitlement("trendscope:full"))):
    return _svc().get_scheduler().run_now(name)


@app.put("/v1/schedules/{name}")
async def update_schedule(name: str, request: Request, tenant=Depends(require_entitlement("trendscope:full"))):
    body = await request.json()
    scheduler = _svc().get_scheduler()
    if body.get("enabled", True):
        scheduler.enable(name)
    else:
        scheduler.disable(name)
    entry = scheduler.get_schedule(name)
    if not entry:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return {"name": entry.name, "enabled": entry.enabled}


# ── Anomaly endpoints ───────────────────────────────────────────────────────

@app.get("/v1/anomalies")
async def get_anomalies(
    lookback_days: int = Query(14),
    tenant=Depends(require_entitlement("trendscope:full")),
):
    results = _svc().detect_anomalies(lookback_days=lookback_days)
    return {
        "anomalies": [
            {
                "trend_id": r.trend_id,
                "trend_name": r.trend_name,
                "anomaly_type": r.anomaly_type,
                "severity": r.severity,
                "value": r.value,
                "expected_range": list(r.expected_range),
                "deviation": r.deviation,
            }
            for r in results
        ],
        "total": len(results),
    }


# ── Snapshot endpoints ──────────────────────────────────────────────────────

@app.post("/v1/snapshots")
async def create_snapshot(request: Request, tenant=Depends(require_entitlement("trendscope:full"))):
    body = await request.json()
    snap = _svc().create_snapshot(label=body.get("label", "snapshot"))
    return {"id": snap.id, "label": snap.label, "created_at": snap.created_at}


@app.get("/v1/snapshots")
async def list_snapshots(tenant=Depends(require_entitlement("trendscope:full"))):
    snaps = _svc().list_snapshots()
    return [{"id": s.id, "label": s.label, "data": s.data, "created_at": s.created_at} for s in snaps]


@app.get("/v1/snapshots/diff-summary")
async def get_snapshot_diff_summary(tenant=Depends(require_entitlement("trendscope:full"))):
    """Return latest snapshot diff summary for cross-system consumption."""
    snapshots = _svc().list_snapshots()
    if len(snapshots) < 2:
        return {"status": "insufficient_snapshots", "count": len(snapshots)}
    latest = snapshots[0]
    previous = snapshots[1]
    diff = _svc().compare_snapshots(latest.id, previous.id)
    return {"status": "ok", "diff": diff, "latest": latest.id, "previous": previous.id}


@app.get("/v1/snapshots/compare")
async def compare_snapshots(
    a: str = Query(...),
    b: str = Query(...),
    tenant=Depends(require_entitlement("trendscope:full")),
):
    return _svc().compare_snapshots(a, b)


# ── Lifecycle endpoints ─────────────────────────────────────────────────────

@app.get("/v1/trends/{trend_id}/lifecycle")
async def get_trend_lifecycle(
    trend_id: str,
    tenant=Depends(require_entitlement("trendscope:full")),
):
    return _svc().get_lifecycle(trend_id)


@app.get("/v1/lifecycle/distribution")
async def get_lifecycle_distribution(tenant=Depends(require_entitlement("trendscope:full"))):
    return _svc().get_lifecycle_distribution()


@app.get("/v1/lifecycle/aging")
async def get_aging_trends(
    min_days: int = Query(7),
    tenant=Depends(require_entitlement("trendscope:full")),
):
    return _svc().get_aging_trends(min_days)


# ── Coverage endpoints ──────────────────────────────────────────────────────

@app.get("/v1/coverage")
async def get_coverage(tenant=Depends(require_entitlement("trendscope:full"))):
    return _svc().get_coverage_report()


@app.get("/v1/coverage/blind-spots")
async def get_blind_spots(tenant=Depends(require_entitlement("trendscope:full"))):
    return _svc().get_blind_spots()


# ── Time comparison endpoints ───────────────────────────────────────────────

@app.get("/v1/compare/this-vs-last")
async def this_vs_last(
    period: str = Query("week"),
    tenant=Depends(require_entitlement("trendscope:full")),
):
    return _svc().compare_time_windows(period)


@app.get("/v1/compare/movers")
async def get_movers(
    period: str = Query("week"),
    tenant=Depends(require_entitlement("trendscope:full")),
):
    return _svc().get_movers(period)


# ── Feed endpoints ──────────────────────────────────────────────────────────

@app.get("/v1/feed")
async def get_feed(tenant=Depends(require_entitlement("trendscope:full"))):
    from fastapi.responses import StreamingResponse
    return StreamingResponse(
        _svc()._feed.stream(),
        media_type="text/event-stream",
    )


@app.get("/v1/feed/summary")
async def get_feed_summary(
    minutes: int = Query(5),
    tenant=Depends(require_entitlement("trendscope:full")),
):
    return _svc().get_feed_summary(minutes)


# ── KH Sync endpoints ──────────────────────────────────────────────────────

@app.post("/v1/webhooks/kh/intelligence")
async def kh_intelligence_webhook(request: Request):
    body = await request.json()
    return _svc().receive_kh_intelligence(body)


@app.get("/v1/sync/status")
async def get_sync_status(tenant=Depends(require_entitlement("trendscope:full"))):
    return _svc().get_sync_status()


# ── Autonomy Dashboard endpoints ────────────────────────────────────────────

@app.get("/v1/autonomy/pulse")
async def get_system_pulse(tenant=Depends(require_entitlement("trendscope:full"))):
    return _svc().get_system_pulse()


@app.get("/v1/autonomy/timeline")
async def get_autonomy_timeline(
    hours: int = Query(24),
    tenant=Depends(require_entitlement("trendscope:full")),
):
    return _svc().get_autonomy_timeline(hours)


@app.get("/v1/autonomy/health")
async def get_autonomy_health(tenant=Depends(require_entitlement("trendscope:full"))):
    return {"health_score": _svc().get_health_score()}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("trendscope.app:app", host="0.0.0.0", port=8002, reload=True)

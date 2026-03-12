"""
Licensing stub for TrendScope.

Access control is handled by Zuultimate via the /v1/identity/auth/validate
endpoint. This module provides a no-op gate so service.py can import cleanly.

In production, the FastAPI layer enforces entitlements before any service
method is called. These gate() calls are therefore redundant but harmless.
"""
import logging

logger = logging.getLogger(__name__)


class _LicenseGate:
    """No-op license gate. Entitlements are checked at the HTTP layer."""

    def gate(self, feature: str) -> None:
        """No-op. Zuultimate enforces entitlements before service methods run."""
        logger.debug("license_gate.gate(%r) — delegated to Zuultimate", feature)


license_gate = _LicenseGate()

"""Dependency-aware, evidence-backed local component health model."""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Iterable


class HealthState(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


_COMPONENTS: tuple[dict[str, Any], ...] = (
    {"id": "python_environment", "name": "Python environment", "check": "python_version", "depends_on": ()},
    {"id": "repository_structure", "name": "Repository structure", "check": "repository_structure", "depends_on": ()},
    {"id": "ci_workflow", "name": "CI workflow", "check": "ci_workflow_readable", "depends_on": ("repository_structure",)},
    {"id": "ci_actions", "name": "CI action integrity", "check": "ci_actions_pinned", "depends_on": ("ci_workflow",)},
    {"id": "ci_permissions", "name": "CI permissions", "check": "ci_permissions", "depends_on": ("ci_workflow",)},
    {"id": "recovery_ci", "name": "Recovery CI coverage", "check": "recovery_ci_coverage", "depends_on": ("ci_workflow",)},
    {
        "id": "developer_baseline",
        "name": "Developer baseline",
        "check": None,
        "depends_on": (
            "python_environment", "repository_structure", "ci_workflow",
            "ci_actions", "ci_permissions", "recovery_ci",
        ),
    },
)
_RANK = {
    HealthState.HEALTHY: 0,
    HealthState.UNKNOWN: 1,
    HealthState.DEGRADED: 2,
    HealthState.UNAVAILABLE: 3,
}


def _state_for_check(check: dict[str, Any] | None) -> HealthState:
    if check is None:
        return HealthState.UNKNOWN
    status = check.get("status")
    if status == "pass":
        return HealthState.HEALTHY
    if status == "fail":
        return HealthState.DEGRADED
    if status == "unavailable":
        return HealthState.UNAVAILABLE
    return HealthState.UNKNOWN


def build_health_report(
    checks: Iterable[dict[str, Any]],
    *,
    observed_at: str | None = None,
) -> dict[str, Any]:
    """Build a dependency graph; missing observations remain unknown."""
    check_map: dict[str, dict[str, Any]] = {}
    for check in checks:
        check_id = check.get("id")
        if not isinstance(check_id, str) or not check_id:
            raise ValueError("each health check must have a non-empty id")
        if check_id in check_map:
            raise ValueError(f"duplicate health check id: {check_id}")
        check_map[check_id] = check

    timestamp = observed_at or datetime.now(timezone.utc).isoformat()
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("observed_at must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("observed_at must include a timezone")

    states: dict[str, HealthState] = {}
    components: list[dict[str, Any]] = []
    for spec in _COMPONENTS:
        own_check = check_map.get(spec["check"]) if spec["check"] else None
        candidates = [_state_for_check(own_check)] if spec["check"] else []
        candidates.extend(states[dependency] for dependency in spec["depends_on"])
        state = (
            max(candidates, key=lambda candidate: _RANK[candidate])
            if candidates
            else HealthState.UNKNOWN
        )
        states[spec["id"]] = state
        components.append({
            "id": spec["id"],
            "name": spec["name"],
            "status": state.value,
            "depends_on": list(spec["depends_on"]),
            "evidence": (
                {
                    "type": "diagnostic_check",
                    "check_id": own_check["id"],
                    "status": own_check["status"],
                }
                if own_check is not None
                else None
            ),
            "observed_at": timestamp,
        })

    counts = {
        state.value: sum(item["status"] == state.value for item in components)
        for state in HealthState
    }
    overall = max(states.values(), key=lambda candidate: _RANK[candidate])
    return {
        "schema_version": 1,
        "scope": "local_static_repository_checks",
        "status": overall.value,
        "summary": {"components": len(components), **counts},
        "components": components,
        "limitations": [
            "Only locally observable repository and CI configuration checks are represented.",
            "No remote service, provider, credential, deployment, or runtime-session health is inferred.",
            "Unknown means no direct observation was available; it is not a passing result.",
        ],
    }

"""Tests for Capri's dependency-aware local health model."""
import unittest

from capri_core.health import build_health_report


def checks():
    return [
        {"id": "python_version", "status": "pass"},
        {"id": "repository_structure", "status": "pass"},
        {"id": "ci_workflow_readable", "status": "pass"},
        {"id": "ci_actions_pinned", "status": "pass"},
        {"id": "ci_permissions", "status": "pass"},
        {"id": "recovery_ci_coverage", "status": "pass"},
    ]


class HealthModelTests(unittest.TestCase):
    def test_all_observed_checks_produce_healthy_graph(self):
        report = build_health_report(checks(), observed_at="2026-11-05T12:00:00Z")
        self.assertEqual(report["status"], "healthy")
        self.assertEqual(report["summary"]["healthy"], 7)
        self.assertEqual(report["summary"]["unknown"], 0)

    def test_failed_workflow_degrades_dependent_components(self):
        observations = [
            {**item, "status": "fail"} if item["id"] == "ci_workflow_readable" else item
            for item in checks()
        ]
        report = build_health_report(observations)
        states = {item["id"]: item["status"] for item in report["components"]}
        for component in ("ci_workflow", "ci_actions", "ci_permissions", "recovery_ci", "developer_baseline"):
            self.assertEqual(states[component], "degraded")

    def test_missing_observation_stays_unknown_and_propagates(self):
        observations = [item for item in checks() if item["id"] != "ci_actions_pinned"]
        report = build_health_report(observations)
        states = {item["id"]: item["status"] for item in report["components"]}
        self.assertEqual(states["ci_actions"], "unknown")
        self.assertEqual(states["developer_baseline"], "unknown")
        self.assertEqual(report["status"], "unknown")

    def test_unavailable_dependency_propagates(self):
        observations = [
            {**item, "status": "unavailable"} if item["id"] == "ci_workflow_readable" else item
            for item in checks()
        ]
        report = build_health_report(observations)
        states = {item["id"]: item["status"] for item in report["components"]}
        self.assertEqual(states["ci_actions"], "unavailable")
        self.assertEqual(states["developer_baseline"], "unavailable")

    def test_duplicate_check_ids_are_rejected(self):
        with self.assertRaises(ValueError):
            build_health_report(checks() + [checks()[0]])

    def test_naive_timestamp_is_rejected(self):
        with self.assertRaises(ValueError):
            build_health_report(checks(), observed_at="2026-11-05T12:00:00")


if __name__ == "__main__":
    unittest.main()

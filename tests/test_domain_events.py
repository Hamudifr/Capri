import unittest

from capri_runtime.domain_events import (
    DomainEvent,
    DomainEventValidationError,
    goal_event,
    memory_event,
    project_domain_events,
    task_event,
)


class DomainEventTests(unittest.TestCase):
    def test_cloud_events_identity_and_read_only_projection_are_deterministic(self):
        goal = goal_event(
            event_id=1, goal_id="goal-1", timestamp="2026-11-25T08:00:00+00:00",
            state="planning", version=2, event_type="transition", principal_id="alice",
        )
        task = task_event(
            event_id=1, task_id="task-1", timestamp="2026-11-25T08:00:01+00:00",
            state="running", step_index=0, attempt=1, error_code=None,
            principal_id="alice",
        )
        memory = memory_event(
            event_id="event-1", memory_id="memory-1", event_type="correction_created",
            timestamp="2026-11-25T08:00:02+00:00", supersedes_id="memory-0",
            status="active",
        )
        projected = project_domain_events((task, memory), (goal,))
        self.assertEqual(tuple(item.id for item in projected), ("1", "1", "event-1"))
        self.assertEqual(tuple(item.specversion for item in projected), ("1.0",) * 3)
        self.assertEqual(dict(projected[0].data)["actor_id"], "alice")
        self.assertEqual(dict(projected[2].data)["supersedes_id"], "memory-0")
        self.assertNotIn("content", projected[2].as_dict()["data"])

    def test_duplicate_source_and_id_is_rejected_across_streams(self):
        event = DomainEvent(
            id="same-id", source="urn:capri:goal:goal-1",
            type="com.capri.goal.created", subject="goal-1",
            time="2026-11-25T08:00:00+00:00",
        )
        with self.assertRaises(DomainEventValidationError):
            project_domain_events((event,), (event,))

    def test_event_contract_rejects_raw_content_and_unbounded_metadata(self):
        with self.assertRaises(DomainEventValidationError):
            DomainEvent(
                id="event-1", source="urn:capri:memory:memory-1",
                type="com.capri.memory.created", subject="memory-1",
                time="2026-11-25T08:00:00+00:00",
                data=(("content", "raw memory text"),),
            )
        with self.assertRaises(DomainEventValidationError):
            DomainEvent(
                id="event-1", source="urn:capri:memory:memory-1",
                type="com.capri.memory.created", subject="memory-1",
                time="2026-11-25T08:00:00+00:00",
                data=(("evidence_reference", "x" * 513),),
            )

    def test_oversized_source_reference_is_represented_by_digest(self):
        event = memory_event(
            event_id="event-2", memory_id="memory-2", event_type="record_created",
            timestamp="2026-11-25T08:00:00+00:00", derived_from="https://example.com/" + "x" * 600,
        )
        data = dict(event.data)
        self.assertIn("evidence_digest", data)
        self.assertNotIn("derived_from", data)

    def test_event_type_rejects_unbounded_or_whitespace_names(self):
        with self.assertRaises(DomainEventValidationError):
            DomainEvent(
                id="event-1", source="urn:capri:memory:memory-1",
                type="com.capri.memory.created injected", subject="memory-1",
                time="2026-11-25T08:00:00+00:00",
            )

    def test_event_contract_rejects_naive_time_and_invalid_namespaces(self):
        with self.assertRaises(DomainEventValidationError):
            DomainEvent(
                id="event-1", source="urn:capri:memory:memory-1",
                type="com.capri.memory.created", subject="memory-1",
                time="2026-11-25T08:00:00",
            )
        with self.assertRaises(DomainEventValidationError):
            DomainEvent(
                id="event-1", source="https://example.com/source",
                type="com.capri.memory.created", subject="memory-1",
                time="2026-11-25T08:00:00+00:00",
            )


if __name__ == "__main__":
    unittest.main()

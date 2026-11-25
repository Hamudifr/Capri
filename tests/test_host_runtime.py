import os
import tempfile
import unittest

from capri_runtime import (
    AssistantTurn,
    HostAuthorityError,
    HostAuthorityResolver,
    InMemoryAuditSink,
    SessionClosedError,
    SessionNotFoundError,
    SQLiteSessionStore,
    SQLiteTaskStore,
    TaskEngine,
    TaskWorker,
    ToolExecutionBridge,
    ToolExecutor,
    ToolOrchestrator,
    ToolRegistry,
    UntrustedMemoryContext,
    UntrustedKnowledgeContext,
)
from capri_runtime.host_runtime import CapriHostRuntime, HostRuntimeError
from capri_runtime.tasks import TaskNotFoundError, TaskValidationError
from capri_runtime.goals import GoalNotFoundError, GoalPlanProposal, SQLiteGoalStore


class RecordingAdapter:
    def __init__(self):
        self.calls = []
        self.memory_contexts = []
        self.knowledge_contexts = []

    def complete_with_tools(self, session_id, history, tools):
        self.calls.append((session_id, history, tools))
        return AssistantTurn(content="answer: " + history[-1].content)

    def complete_with_tools_and_memory(self, session_id, history, tools, memory_context):
        self.calls.append((session_id, history, tools))
        self.memory_contexts.append(memory_context)
        return AssistantTurn(content="memory-aware answer")

    def complete_with_tools_and_knowledge(self, session_id, history, tools, knowledge_context):
        self.calls.append((session_id, history, tools))
        self.knowledge_contexts.append(knowledge_context)
        return AssistantTurn(content="knowledge-aware answer")

    def complete_with_tools_and_memory_and_knowledge(
        self, session_id, history, tools, memory_context, knowledge_context
    ):
        self.calls.append((session_id, history, tools))
        self.memory_contexts.append(memory_context)
        self.knowledge_contexts.append(knowledge_context)
        return AssistantTurn(content="memory-and-knowledge-aware answer")


class CapriHostRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        if os.name == "posix":
            os.chmod(self.temp.name, 0o700)
        self.store = SQLiteSessionStore(
            os.path.join(self.temp.name, "sessions.sqlite3"),
            max_output_chars=131_072,
        )
        self.task_store = SQLiteTaskStore(
            os.path.join(self.temp.name, "tasks.sqlite3")
        )
        self.adapter = RecordingAdapter()
        bridge = ToolExecutionBridge(
            ToolExecutor(ToolRegistry(), InMemoryAuditSink())
        )
        self.orchestrator = ToolOrchestrator(self.adapter, bridge)
        self.authority = HostAuthorityResolver(
            authenticate=lambda credential: {
                "alice-token": "alice",
                "bob-token": "bob",
            }.get(credential),
            permissions_for=lambda principal_id: (),
        )

    def tearDown(self):
        self.temp.cleanup()

    def make_host(self, **kwargs):
        return CapriHostRuntime(
            self.authority,
            self.store,
            self.orchestrator,
            **kwargs,
        )

    def test_create_get_and_run_turn_are_bound_to_authenticated_principal(self):
        host = self.make_host()
        session = host.create_session("alice-token")
        self.assertEqual(host.get_session("alice-token", session.session_id), session)
        with self.assertRaises(SessionNotFoundError):
            host.get_session("bob-token", session.session_id)
        with self.assertRaises(SessionNotFoundError):
            host.run_turn("bob-token", session.session_id, "unauthorized")
        self.assertEqual(self.adapter.calls, [])

        result = host.run_turn("alice-token", session.session_id, "hello")
        self.assertEqual(result.result.final_text, "answer: hello")
        self.assertEqual(result.session.version, 1)
        self.assertEqual(
            host.get_session("alice-token", session.session_id),
            result.session,
        )
        with self.assertRaises(SessionNotFoundError):
            host.get_session("bob-token", session.session_id)

    def test_unauthorized_session_is_rejected_before_memory_retrieval(self):
        memory_calls = []
        host = self.make_host(
            memory_context_resolver=lambda principal, session_id, text: (
                memory_calls.append((principal, session_id, text))
                or UntrustedMemoryContext(())
            )
        )
        session = host.create_session("alice-token")
        with self.assertRaises(SessionNotFoundError):
            host.run_turn("bob-token", session.session_id, "try foreign session")
        self.assertEqual(memory_calls, [])
        self.assertEqual(self.adapter.calls, [])

        host.run_turn("alice-token", session.session_id, "allowed")
        self.assertEqual(memory_calls, [("alice", session.session_id, "allowed")])
        self.assertEqual(len(self.adapter.memory_contexts), 1)

    def test_unauthorized_session_is_rejected_before_graph_retrieval(self):
        graph_calls = []
        host = self.make_host(
            knowledge_context_resolver=lambda principal, session_id, text: (
                graph_calls.append((principal, session_id, text))
                or UntrustedKnowledgeContext((), (), text)
            )
        )
        session = host.create_session("alice-token")
        with self.assertRaises(SessionNotFoundError):
            host.run_turn("bob-token", session.session_id, "foreign graph query")
        self.assertEqual(graph_calls, [])
        self.assertEqual(self.adapter.knowledge_contexts, [])

        result = host.run_turn("alice-token", session.session_id, "allowed graph query")
        self.assertEqual(result.result.final_text, "knowledge-aware answer")
        self.assertEqual(graph_calls, [("alice", session.session_id, "allowed graph query")])
        self.assertEqual(len(self.adapter.knowledge_contexts), 1)

    def test_host_can_pass_memory_and_graph_as_separate_contexts(self):
        memory = UntrustedMemoryContext(())
        knowledge = UntrustedKnowledgeContext((), (), "combined query")
        host = self.make_host(
            memory_context_resolver=lambda *_: memory,
            knowledge_context_resolver=lambda *_: knowledge,
        )
        session = host.create_session("alice-token")
        result = host.run_turn("alice-token", session.session_id, "combined query")
        self.assertEqual(result.result.final_text, "memory-and-knowledge-aware answer")
        self.assertEqual(self.adapter.memory_contexts, [memory])
        self.assertEqual(self.adapter.knowledge_contexts, [knowledge])

    def test_close_is_owner_scoped_and_idempotent(self):
        host = self.make_host()
        session = host.create_session("alice-token")
        with self.assertRaises(SessionNotFoundError):
            host.close_session("bob-token", session.session_id)
        closed = host.close_session("alice-token", session.session_id)
        self.assertTrue(closed.closed)
        self.assertEqual(host.close_session("alice-token", session.session_id), closed)
        with self.assertRaises(SessionClosedError):
            host.run_turn("alice-token", session.session_id, "after close")

    def test_invalid_input_is_rejected_before_memory_callback(self):
        memory_calls = []
        host = self.make_host(
            memory_context_resolver=lambda *args: memory_calls.append(args)
        )
        session = host.create_session("alice-token")
        with self.assertRaises(HostRuntimeError):
            host.run_turn("alice-token", session.session_id, " " * 20)
        with self.assertRaises(HostRuntimeError):
            host.run_turn("alice-token", session.session_id, "x" * 16_001)
        self.assertEqual(memory_calls, [])
        self.assertEqual(self.adapter.calls, [])

    def test_memory_resolver_failure_is_redacted(self):
        def fail(*args):
            raise RuntimeError("private memory provider secret")

        host = self.make_host(memory_context_resolver=fail)
        session = host.create_session("alice-token")
        with self.assertRaises(HostRuntimeError) as caught:
            host.run_turn("alice-token", session.session_id, "hello")
        self.assertNotIn("private memory provider secret", str(caught.exception))
        self.assertEqual(self.adapter.calls, [])

    def test_invalid_credentials_are_rejected_by_trusted_authority(self):
        host = self.make_host()
        with self.assertRaises(HostAuthorityError):
            host.create_session("invalid-token")

    def test_task_worker_requires_explicit_host_configuration(self):
        host = self.make_host()
        with self.assertRaises(HostRuntimeError):
            host.run_task_worker(object())


    def test_task_creation_read_and_cancel_are_bound_to_authenticated_principal(self):
        worker = TaskWorker(TaskEngine(
            self.task_store,
            {},
            "worker",
            principal_handlers={"collect": lambda data, key, principal: {"ok": True}},
        ))
        host = self.make_host(task_worker=worker)
        task = host.create_task(
            "alice-token",
            [{"tool": "collect", "input": {"scope": "private"}}],
            idempotency_key="request-1",
        )
        self.assertEqual(host.get_task("alice-token", task.task_id), task)
        with self.assertRaises(TaskNotFoundError):
            host.get_task("bob-token", task.task_id)
        with self.assertRaises(TaskNotFoundError):
            host.cancel_task("bob-token", task.task_id)
        cancelled = host.cancel_task("alice-token", task.task_id)
        self.assertEqual(cancelled.state, "cancelled")
        self.assertEqual(host.get_task("alice-token", task.task_id), cancelled)
        with self.assertRaises(HostRuntimeError):
            host.create_task(
                "alice-token", [{"tool": "not-registered", "input": {}}]
            )

    def test_task_creation_rejects_hostile_plan_containers_before_inspection(self):
        class HostileList(list):
            def __iter__(self):
                raise AssertionError("host must not iterate a custom list")

        class HostileDict(dict):
            def get(self, *args, **kwargs):
                raise AssertionError("host must not inspect a custom dict")

        worker = TaskWorker(TaskEngine(
            self.task_store,
            {},
            "worker",
            principal_handlers={"collect": lambda data, key, principal: {"ok": True}},
        ))
        host = self.make_host(task_worker=worker)

        with self.assertRaises(TaskValidationError):
            host.create_task(
                "alice-token",
                HostileList([{"tool": "collect", "input": {}}]),
            )
        with self.assertRaises(TaskValidationError):
            host.create_task(
                "alice-token",
                [HostileDict(tool="collect", input={})],
            )
        class HostileString(str):
            def __hash__(self):
                raise AssertionError("host must not hash a custom tool string")

        with self.assertRaises(TaskValidationError):
            host.create_task(
                "alice-token",
                [{"tool": HostileString("collect"), "input": {}}],
            )

    def test_principal_task_creation_requires_a_configured_worker_registry(self):
        host = self.make_host()
        with self.assertRaises(HostRuntimeError):
            host.create_task(
                "alice-token", [{"tool": "collect", "input": {}}]
            )

    def test_goal_operations_are_bound_to_authenticated_principal(self):
        goal_store = SQLiteGoalStore(os.path.join(self.temp.name, "goals.sqlite3"))
        worker = TaskWorker(TaskEngine(
            self.task_store, {}, "worker",
            principal_handlers={
                "collect": lambda data, key, principal: {"ok": True},
            },
        ))
        host = self.make_host(task_worker=worker, goal_store=goal_store)
        goal = host.create_goal(
            "alice-token", "Prepare a verified report",
            acceptance_criteria=["Sources cited", "Claims checked"],
            idempotency_key="goal-1",
        )
        self.assertEqual(host.get_goal("alice-token", goal.goal_id), goal)
        with self.assertRaises(GoalNotFoundError):
            host.get_goal("bob-token", goal.goal_id)
        with self.assertRaises(GoalNotFoundError):
            host.transition_goal(
                "bob-token", goal.goal_id, "planning", expected_version=1,
            )
        planned = host.save_goal_plan(
            "alice-token", goal.goal_id,
            GoalPlanProposal(({"tool": "collect", "input": {}},)),
            expected_version=1,
        )
        self.assertEqual(planned.state, "planned")
        self.assertEqual(planned.plan[0]["tool"], "collect")
        with self.assertRaises(Exception):
            host.save_goal_plan(
                "alice-token", goal.goal_id,
                GoalPlanProposal(({"tool": "admin", "input": {}},)),
                expected_version=2,
            )

    def test_goal_api_requires_configured_store_and_authentication(self):
        host = self.make_host()
        with self.assertRaises(HostRuntimeError):
            host.create_goal(
                "alice-token", "outcome", acceptance_criteria=["done"],
            )
        goal_store = SQLiteGoalStore(os.path.join(self.temp.name, "goals-auth.sqlite3"))
        configured = self.make_host(goal_store=goal_store)
        with self.assertRaises(HostAuthorityError):
            configured.create_goal(
                "invalid-token", "outcome", acceptance_criteria=["done"],
            )


if __name__ == "__main__":
    unittest.main()

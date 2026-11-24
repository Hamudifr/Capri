import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from tools.termux_bridge import (
    BridgeError, TASKS, _retryable_result_push_error, claim_is_live, parse_claim,
    parse_job, parse_queue_paths, publish_result, redact,
)


class TermuxBridgeManifestTests(unittest.TestCase):
    def valid_manifest(self):
        return {
            "schema_version": 1,
            "job_id": "0123456789abcdef0123456789abcdef",
            "target_commit": "d5b07c57011c6ffed878bba05431c2d1c7ebcd84",
            "task": "full_validation",
        }

    def test_valid_fixed_task_manifest_is_accepted(self):
        parsed = parse_job(json.dumps(self.valid_manifest()))
        self.assertEqual(parsed["task"], "full_validation")

    def test_focused_task_names_are_fixed_and_accepted(self):
        expected = {
            "security_store_tests": "security_store",
            "approval_binding_tests": "approval_binding",
            "x7_runtime_tests": "x7_runtime",
        }
        for task, suite_name in expected.items():
            with self.subTest(task=task):
                manifest = self.valid_manifest()
                manifest["task"] = task
                parsed = parse_job(json.dumps(manifest))
                self.assertEqual(parsed["task"], task)
                self.assertEqual(
                    TASKS[task],
                    [[sys.executable, "tools/focused_tests.py", suite_name]],
                )

    def test_focused_test_suites_discover_existing_modules(self):
        from tools.focused_tests import SUITES, load_suite

        self.assertEqual(
            set(SUITES), {"security_store", "approval_binding", "x7_runtime"}
        )
        for suite_name in SUITES:
            with self.subTest(suite=suite_name):
                self.assertGreater(load_suite(suite_name).countTestCases(), 0)

    def test_boolean_schema_version_is_rejected(self):
        manifest = self.valid_manifest()
        manifest["schema_version"] = True
        with self.assertRaises(BridgeError):
            parse_job(json.dumps(manifest))

    def test_unknown_fields_are_rejected(self):
        manifest = self.valid_manifest()
        manifest["command"] = "rm -rf ~"
        with self.assertRaises(BridgeError):
            parse_job(json.dumps(manifest))

    def test_arbitrary_task_names_are_rejected(self):
        manifest = self.valid_manifest()
        manifest["task"] = "shell"
        with self.assertRaises(BridgeError):
            parse_job(json.dumps(manifest))

    def test_short_or_invalid_commit_ids_are_rejected(self):
        manifest = self.valid_manifest()
        manifest["target_commit"] = "HEAD"
        with self.assertRaises(BridgeError):
            parse_job(json.dumps(manifest))

    def test_invalid_job_ids_are_rejected(self):
        manifest = self.valid_manifest()
        manifest["job_id"] = "../job"
        with self.assertRaises(BridgeError):
            parse_job(json.dumps(manifest))

    def test_queue_paths_are_sorted_and_deduplicated(self):
        first = "jobs/0123456789abcdef0123456789abcdef.json"
        second = "jobs/abcdef0123456789abcdef0123456789.json"
        raw = f"{second}\n{first}\n{second}\n"
        self.assertEqual(parse_queue_paths(raw), [first, second])

    def test_queue_paths_reject_traversal_and_noncanonical_names(self):
        raw = (
            "jobs/../job.json\n"
            "jobs/ABCDEF0123456789ABCDEF0123456789.json\n"
            "jobs/0123456789abcdef0123456789abcdef.txt\n"
            "bridge/job.json\n"
        )
        self.assertEqual(parse_queue_paths(raw), [])

    def valid_claim(self):
        return {
            "schema_version": 1,
            "job_id": "0123456789abcdef0123456789abcdef",
            "owner_id": "abcdef0123456789abcdef0123456789",
            "attempt": 1,
            "claimed_at": 100,
            "lease_expires_at": 200,
            "status": "active",
        }

    def test_valid_distributed_claim_is_accepted(self):
        claim = parse_claim(json.dumps(self.valid_claim()), self.valid_manifest()["job_id"])
        self.assertEqual(claim["attempt"], 1)

    def test_claim_rejects_invalid_owner_attempt_and_status(self):
        for key, value in (("owner_id", "../bad"), ("attempt", 0), ("status", [])):
            claim = self.valid_claim()
            claim[key] = value
            with self.subTest(key=key), self.assertRaises(BridgeError):
                parse_claim(json.dumps(claim), self.valid_manifest()["job_id"])

    def test_claim_rejects_job_id_mismatch_and_expiry_before_claim(self):
        claim = self.valid_claim()
        claim["job_id"] = "abcdef0123456789abcdef0123456789"
        with self.assertRaises(BridgeError):
            parse_claim(json.dumps(claim), self.valid_manifest()["job_id"])
        claim = self.valid_claim()
        claim["lease_expires_at"] = claim["claimed_at"]
        with self.assertRaises(BridgeError):
            parse_claim(json.dumps(claim), self.valid_manifest()["job_id"])

    def test_claim_branch_is_scoped_to_job_id(self):
        from tools.termux_bridge import claim_branch
        self.assertEqual(
            claim_branch(self.valid_manifest()["job_id"]),
            "capri-termux-claim-0123456789abcdef0123456789abcdef",
        )

    def test_claim_attempt_limit_is_enforced(self):
        claim = self.valid_claim()
        claim["attempt"] = 4
        with self.assertRaises(BridgeError):
            parse_claim(json.dumps(claim), self.valid_manifest()["job_id"])

    def test_claim_lease_expiry_is_deterministic(self):
        claim = self.valid_claim()
        self.assertTrue(claim_is_live(claim, 199))
        self.assertFalse(claim_is_live(claim, 200))
        claim["status"] = "abandoned"
        self.assertFalse(claim_is_live(claim, 199))


    def test_first_claim_is_created_from_the_inbox_tip(self):
        from tools.termux_bridge import claim_job
        inbox_ref = "refs/remotes/origin/capri-termux-bridge-inbox"
        with patch("tools.termux_bridge.read_claim", return_value=(None, None)), \
             patch("tools.termux_bridge.write_claim") as write, \
             patch("tools.termux_bridge.time.time", return_value=1_000):
            acquired, claim = claim_job(self.valid_manifest()["job_id"])
        self.assertTrue(acquired)
        self.assertEqual(claim["attempt"], 1)
        self.assertEqual(claim["status"], "active")
        self.assertEqual(claim["lease_expires_at"], 1_000 + 3600)
        write.assert_called_once_with(self.valid_manifest()["job_id"], claim, inbox_ref)

    def test_live_claim_is_not_stolen(self):
        from tools.termux_bridge import claim_job
        current = self.valid_claim()
        current["lease_expires_at"] = 201
        with patch("tools.termux_bridge.read_claim", return_value=("claim-ref", current)), \
             patch("tools.termux_bridge.write_claim") as write, \
             patch("tools.termux_bridge.time.time", return_value=200):
            acquired, claim = claim_job(self.valid_manifest()["job_id"])
        self.assertFalse(acquired)
        self.assertEqual(claim, current)
        write.assert_not_called()

    def test_expired_claim_advances_attempt_on_existing_claim_branch(self):
        from tools.termux_bridge import claim_job
        job_id = self.valid_manifest()["job_id"]
        current_ref = "refs/remotes/origin/capri-termux-claim-" + job_id
        current = self.valid_claim()
        current["lease_expires_at"] = 200
        with patch("tools.termux_bridge.read_claim", return_value=(current_ref, current)), \
             patch("tools.termux_bridge.write_claim") as write, \
             patch("tools.termux_bridge.time.time", return_value=200):
            acquired, claim = claim_job(job_id)
        self.assertTrue(acquired)
        self.assertEqual(claim["attempt"], 2)
        self.assertEqual(claim["status"], "active")
        write.assert_called_once_with(job_id, claim, current_ref)

    def test_expired_final_attempt_becomes_abandoned(self):
        from tools.termux_bridge import claim_job, MAX_CLAIM_ATTEMPTS
        job_id = self.valid_manifest()["job_id"]
        current_ref = "refs/remotes/origin/capri-termux-claim-" + job_id
        current = self.valid_claim()
        current["attempt"] = MAX_CLAIM_ATTEMPTS
        current["lease_expires_at"] = 200
        with patch("tools.termux_bridge.read_claim", return_value=(current_ref, current)), \
             patch("tools.termux_bridge.write_claim") as write, \
             patch("tools.termux_bridge.time.time", return_value=200):
            acquired, claim = claim_job(job_id)
        self.assertFalse(acquired)
        self.assertEqual(claim["attempt"], MAX_CLAIM_ATTEMPTS)
        self.assertEqual(claim["status"], "abandoned")
        self.assertEqual(claim["lease_expires_at"], 201)
        write.assert_called_once_with(job_id, claim, current_ref)

    def test_competing_claim_push_failure_is_never_reported_as_acquired(self):
        from tools.termux_bridge import claim_job
        job_id = self.valid_manifest()["job_id"]
        with patch("tools.termux_bridge.read_claim", return_value=(None, None)), \
             patch("tools.termux_bridge.write_claim", side_effect=BridgeError("non-fast-forward")):
            with self.assertRaisesRegex(BridgeError, "non-fast-forward"):
                claim_job(job_id)

    def test_result_push_retry_classifies_concurrency_and_transient_errors(self):
        self.assertTrue(_retryable_result_push_error("rejected non-fast-forward"))
        self.assertTrue(_retryable_result_push_error("Could not resolve host: github.com"))
        self.assertFalse(_retryable_result_push_error("protected branch hook declined"))

    def test_result_publish_rebuilds_commit_after_non_fast_forward_race(self):
        pushes = []

        def fake_git(*args, **kwargs):
            if args and args[0] == "push":
                pushes.append(args)
                if len(pushes) == 1:
                    return subprocess.CompletedProcess(args, 1, "", "rejected non-fast-forward")
            return subprocess.CompletedProcess(args, 0, "", "")

        with (
            patch("tools.termux_bridge.git", side_effect=fake_git),
            patch("tools.termux_bridge.fetch_branches"),
            patch("tools.termux_bridge.result_exists", side_effect=[False, False, False, True]),
            patch("tools.termux_bridge.time.sleep"),
        ):
            publish_result(
                "0123456789abcdef0123456789abcdef",
                {"schema_version": 1, "status": "passed"},
            )

        self.assertEqual(len(pushes), 2)

    def test_result_publish_accepts_result_written_by_racing_worker(self):
        pushes = []

        def fake_git(*args, **kwargs):
            if args and args[0] == "push":
                pushes.append(args)
                return subprocess.CompletedProcess(args, 1, "", "rejected non-fast-forward")
            return subprocess.CompletedProcess(args, 0, "", "")

        with (
            patch("tools.termux_bridge.git", side_effect=fake_git),
            patch("tools.termux_bridge.fetch_branches"),
            patch("tools.termux_bridge.result_exists", side_effect=[False, True]),
            patch("tools.termux_bridge.time.sleep"),
        ):
            publish_result(
                "0123456789abcdef0123456789abcdef",
                {"schema_version": 1, "status": "passed"},
            )

        self.assertEqual(len(pushes), 1)

    def test_result_publish_fails_fast_for_non_retryable_push_error(self):
        def fake_git(*args, **kwargs):
            if args and args[0] == "push":
                return subprocess.CompletedProcess(args, 1, "", "protected branch hook declined")
            return subprocess.CompletedProcess(args, 0, "", "")

        with (
            patch("tools.termux_bridge.git", side_effect=fake_git),
            patch("tools.termux_bridge.fetch_branches"),
            patch("tools.termux_bridge.result_exists", side_effect=[False, False]),
        ):
            with self.assertRaises(BridgeError):
                publish_result(
                    "0123456789abcdef0123456789abcdef",
                    {"schema_version": 1, "status": "passed"},
                )

    def test_secret_like_values_are_redacted(self):
        token = "ghp_" + ("A" * 32)
        self.assertNotIn(token, redact("failed with " + token))
        self.assertIn("[REDACTED]", redact("failed with " + token))


class TermuxBridgeGitConcurrencyIntegrationTests(unittest.TestCase):
    def test_two_independent_checkouts_cannot_create_the_same_claim_branch(self):
        """Exercise the real Git ref race with two separate worker checkouts."""
        branch = "capri-termux-claim-0123456789abcdef0123456789abcdef"
        inbox = "capri-termux-bridge-inbox"
        job_id = "0123456789abcdef0123456789abcdef"
        project_root = Path(__file__).resolve().parents[1]

        with tempfile.TemporaryDirectory(prefix="capri-claim-race-") as temporary:
            root = Path(temporary)
            bare = root / "origin.git"
            seed = root / "seed"
            subprocess.run(["git", "init", "--bare", str(bare)], check=True, capture_output=True, text=True)
            subprocess.run(["git", "init", str(seed)], check=True, capture_output=True, text=True)
            subprocess.run(["git", "checkout", "-b", inbox], cwd=seed, check=True, capture_output=True, text=True)
            subprocess.run(["git", "config", "user.name", "Capri Test"], cwd=seed, check=True)
            subprocess.run(["git", "config", "user.email", "capri-test@example.invalid"], cwd=seed, check=True)
            (seed / "README.md").write_text("claim race fixture\n", encoding="utf-8")
            subprocess.run(["git", "add", "README.md"], cwd=seed, check=True, capture_output=True, text=True)
            subprocess.run(["git", "commit", "-m", "seed inbox"], cwd=seed, check=True, capture_output=True, text=True)
            subprocess.run(["git", "remote", "add", "origin", str(bare)], cwd=seed, check=True)
            subprocess.run(["git", "push", "origin", inbox], cwd=seed, check=True, capture_output=True, text=True)
            subprocess.run(
                ["git", "--git-dir", str(bare), "symbolic-ref", "HEAD", f"refs/heads/{inbox}"],
                check=True, capture_output=True, text=True,
            )

            checkouts = [root / "worker-a", root / "worker-b"]
            for checkout in checkouts:
                subprocess.run(["git", "clone", str(bare), str(checkout)], check=True, capture_output=True, text=True)
                subprocess.run(
                    ["git", "fetch", "origin", f"+refs/heads/{inbox}:refs/remotes/origin/{inbox}"],
                    cwd=checkout, check=True, capture_output=True, text=True,
                )

            worker_script = (
                "import json, sys; from pathlib import Path; "
                "import tools.termux_bridge as bridge; "
                "bridge.ROOT = Path(sys.argv[1]); "
                "bridge.write_claim(sys.argv[2], json.loads(sys.argv[3]), sys.argv[4])"
            )
            claims = []
            for owner in (
                "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
            ):
                claims.append({
                    "schema_version": 1,
                    "job_id": job_id,
                    "owner_id": owner,
                    "attempt": 1,
                    "claimed_at": 100,
                    "lease_expires_at": 3700,
                    "status": "active",
                })

            environment = os.environ.copy()
            existing_pythonpath = environment.get("PYTHONPATH", "")
            environment["PYTHONPATH"] = str(project_root) + (
                os.pathsep + existing_pythonpath if existing_pythonpath else ""
            )
            workers = [
                subprocess.Popen(
                    [
                        sys.executable, "-c", worker_script, str(checkout),
                        job_id, json.dumps(claim), f"refs/remotes/origin/{inbox}",
                    ],
                    cwd=project_root,
                    env=environment,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                for checkout, claim in zip(checkouts, claims)
            ]
            outcomes = [worker.communicate(timeout=30) for worker in workers]
            return_codes = [worker.returncode for worker in workers]

            self.assertEqual(
                return_codes.count(0), 1,
                msg=f"Expected exactly one claim winner; codes={return_codes}, output={outcomes}",
            )
            stored = subprocess.run(
                ["git", "--git-dir", str(bare), "show", f"refs/heads/{branch}:bridge_claim.json"],
                check=True, capture_output=True, text=True,
            )
            winning_claim = json.loads(stored.stdout)
            self.assertIn(winning_claim["owner_id"], {claim["owner_id"] for claim in claims})
            self.assertEqual(winning_claim["job_id"], job_id)


    def test_two_independent_checkouts_cannot_race_to_take_over_expired_claim(self):
        """Exercise competing lease takeovers against an existing claim ref."""
        branch = "capri-termux-claim-0123456789abcdef0123456789abcdef"
        inbox = "capri-termux-bridge-inbox"
        job_id = "0123456789abcdef0123456789abcdef"
        project_root = Path(__file__).resolve().parents[1]

        with tempfile.TemporaryDirectory(prefix="capri-claim-takeover-race-") as temporary:
            root = Path(temporary)
            bare = root / "origin.git"
            seed = root / "seed"
            subprocess.run(["git", "init", "--bare", str(bare)], check=True, capture_output=True, text=True)
            subprocess.run(["git", "init", str(seed)], check=True, capture_output=True, text=True)
            subprocess.run(["git", "checkout", "-b", inbox], cwd=seed, check=True, capture_output=True, text=True)
            subprocess.run(["git", "config", "user.name", "Capri Test"], cwd=seed, check=True)
            subprocess.run(["git", "config", "user.email", "capri-test@example.invalid"], cwd=seed, check=True)
            (seed / "README.md").write_text("claim takeover race fixture\n", encoding="utf-8")
            subprocess.run(["git", "add", "README.md"], cwd=seed, check=True, capture_output=True, text=True)
            subprocess.run(["git", "commit", "-m", "seed inbox"], cwd=seed, check=True, capture_output=True, text=True)
            subprocess.run(["git", "remote", "add", "origin", str(bare)], cwd=seed, check=True)
            subprocess.run(["git", "push", "origin", inbox], cwd=seed, check=True, capture_output=True, text=True)

            initial_claim = {
                "schema_version": 1,
                "job_id": job_id,
                "owner_id": "cccccccccccccccccccccccccccccccc",
                "attempt": 1,
                "claimed_at": 100,
                "lease_expires_at": 200,
                "status": "active",
            }
            (seed / "bridge_claim.json").write_text(
                json.dumps(initial_claim, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            subprocess.run(["git", "add", "bridge_claim.json"], cwd=seed, check=True, capture_output=True, text=True)
            subprocess.run(["git", "commit", "-m", "seed expired claim"], cwd=seed, check=True, capture_output=True, text=True)
            subprocess.run(["git", "push", "origin", f"HEAD:refs/heads/{branch}"], cwd=seed, check=True, capture_output=True, text=True)

            checkouts = [root / "worker-a", root / "worker-b"]
            for checkout in checkouts:
                subprocess.run(["git", "clone", str(bare), str(checkout)], check=True, capture_output=True, text=True)
                subprocess.run(
                    [
                        "git", "fetch", "origin",
                        f"+refs/heads/{inbox}:refs/remotes/origin/{inbox}",
                        f"+refs/heads/{branch}:refs/remotes/origin/{branch}",
                    ],
                    cwd=checkout, check=True, capture_output=True, text=True,
                )

            worker_script = (
                "import json, sys; from pathlib import Path; "
                "import tools.termux_bridge as bridge; "
                "bridge.ROOT = Path(sys.argv[1]); "
                "bridge.write_claim(sys.argv[2], json.loads(sys.argv[3]), sys.argv[4])"
            )
            claims = []
            for owner in (
                "dddddddddddddddddddddddddddddddd",
                "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
            ):
                claims.append({
                    "schema_version": 1,
                    "job_id": job_id,
                    "owner_id": owner,
                    "attempt": 2,
                    "claimed_at": 200,
                    "lease_expires_at": 3800,
                    "status": "active",
                })

            environment = os.environ.copy()
            existing_pythonpath = environment.get("PYTHONPATH", "")
            environment["PYTHONPATH"] = str(project_root) + (
                os.pathsep + existing_pythonpath if existing_pythonpath else ""
            )
            workers = [
                subprocess.Popen(
                    [
                        sys.executable, "-c", worker_script, str(checkout),
                        job_id, json.dumps(claim), f"refs/remotes/origin/{branch}",
                    ],
                    cwd=project_root,
                    env=environment,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                for checkout, claim in zip(checkouts, claims)
            ]
            outcomes = [worker.communicate(timeout=30) for worker in workers]
            return_codes = [worker.returncode for worker in workers]

            self.assertEqual(
                return_codes.count(0), 1,
                msg=f"Expected exactly one takeover winner; codes={return_codes}, output={outcomes}",
            )
            stored = subprocess.run(
                ["git", "--git-dir", str(bare), "show", f"refs/heads/{branch}:bridge_claim.json"],
                check=True, capture_output=True, text=True,
            )
            winning_claim = json.loads(stored.stdout)
            self.assertIn(winning_claim["owner_id"], {claim["owner_id"] for claim in claims})
            self.assertEqual(winning_claim["attempt"], 2)
            self.assertEqual(winning_claim["job_id"], job_id)



class TermuxBridgeTargetWorktreeTests(unittest.TestCase):
    def test_validation_runs_in_exact_remote_commit_without_moving_worker_checkout(self):
        import tools.termux_bridge as bridge

        with tempfile.TemporaryDirectory(prefix="capri-target-worktree-") as temporary:
            root = Path(temporary)
            bare = root / "origin.git"
            seed = root / "seed"
            worker = root / "worker"

            subprocess.run(
                ["git", "init", "--bare", str(bare)],
                check=True, capture_output=True, text=True,
            )
            subprocess.run(
                ["git", "init", str(seed)],
                check=True, capture_output=True, text=True,
            )
            subprocess.run(
                ["git", "checkout", "-b", "worker"],
                cwd=seed, check=True, capture_output=True, text=True,
            )
            subprocess.run(["git", "config", "user.name", "Capri Test"], cwd=seed, check=True)
            subprocess.run(
                ["git", "config", "user.email", "capri-test@example.invalid"],
                cwd=seed, check=True,
            )
            (seed / "worker.txt").write_text("worker checkout\n", encoding="utf-8")
            subprocess.run(["git", "add", "worker.txt"], cwd=seed, check=True, capture_output=True, text=True)
            subprocess.run(["git", "commit", "-m", "worker base"], cwd=seed, check=True, capture_output=True, text=True)
            subprocess.run(["git", "remote", "add", "origin", str(bare)], cwd=seed, check=True)
            subprocess.run(["git", "push", "origin", "worker"], cwd=seed, check=True, capture_output=True, text=True)

            subprocess.run(
                ["git", "checkout", "--orphan", "candidate"],
                cwd=seed, check=True, capture_output=True, text=True,
            )
            subprocess.run(
                ["git", "rm", "-rf", "."],
                cwd=seed, check=False, capture_output=True, text=True,
            )
            (seed / "candidate.txt").write_text("exact candidate commit\n", encoding="utf-8")
            subprocess.run(["git", "add", "candidate.txt"], cwd=seed, check=True, capture_output=True, text=True)
            subprocess.run(["git", "commit", "-m", "candidate commit"], cwd=seed, check=True, capture_output=True, text=True)
            subprocess.run(["git", "push", "origin", "candidate"], cwd=seed, check=True, capture_output=True, text=True)
            target_commit = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=seed,
                check=True, capture_output=True, text=True,
            ).stdout.strip()

            subprocess.run(
                ["git", "--git-dir", str(bare), "symbolic-ref", "HEAD", "refs/heads/worker"],
                check=True, capture_output=True, text=True,
            )
            subprocess.run(
                ["git", "init", str(worker)],
                check=True, capture_output=True, text=True,
            )
            subprocess.run(
                ["git", "remote", "add", "origin", str(bare)],
                cwd=worker, check=True, capture_output=True, text=True,
            )
            subprocess.run(
                [
                    "git", "fetch", "--quiet", "origin",
                    "refs/heads/worker:refs/remotes/origin/worker",
                ],
                cwd=worker, check=True, capture_output=True, text=True,
            )
            subprocess.run(
                ["git", "checkout", "-b", "worker", "--track", "origin/worker"],
                cwd=worker, check=True, capture_output=True, text=True,
            )
            absent = subprocess.run(
                ["git", "cat-file", "-e", f"{target_commit}^{{commit}}"],
                cwd=worker, check=False, capture_output=True, text=True,
            )
            self.assertNotEqual(absent.returncode, 0)
            worker_head = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=worker,
                check=True, capture_output=True, text=True,
            ).stdout.strip()
            self.assertNotEqual(worker_head, target_commit)

            probe = [
                sys.executable, "-c",
                "from pathlib import Path; print(Path('candidate.txt').read_text(), end='')",
            ]
            with patch.object(bridge, "ROOT", worker), patch.dict(
                bridge.TASKS, {"target_probe": [probe]}
            ):
                result = bridge.execute_target_task("target_probe", target_commit)

            self.assertEqual(result["status"], "passed")
            self.assertEqual(result["target_commit"], target_commit)
            self.assertIn("exact candidate commit", result["steps"][0]["output_tail"])
            after_head = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=worker,
                check=True, capture_output=True, text=True,
            ).stdout.strip()
            self.assertEqual(after_head, worker_head)
            self.assertFalse((worker / "candidate.txt").exists())


if __name__ == "__main__":
    unittest.main()

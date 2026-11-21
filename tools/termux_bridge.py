#!/usr/bin/env python3
"""Narrow, GitHub-relayed Termux runner for Capri validation tasks.

This is deliberately NOT a remote shell. Jobs select one fixed task from TASKS;
the manifest cannot supply commands, arguments, paths, or environment variables.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
INBOX_BRANCH = "capri-termux-bridge-inbox"
RESULTS_BRANCH = "capri-termux-bridge-results"
JOB_PATH = "bridge/job.json"  # Legacy single-job compatibility
QUEUE_PREFIX = "jobs/"
CLAIM_PREFIX = "capri-termux-claim-"
CLAIM_LEASE_SECONDS = 3600
MAX_CLAIM_ATTEMPTS = 3
MAX_OUTPUT = 48_000
STEP_TIMEOUT = 900
TASKS = {
    "full_validation": [
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
        [sys.executable, "-m", "compileall", "-q", "capri_core", "capri_runtime", "tests"],
        [sys.executable, "-m", "capri_core", "doctor"],
    ],
    "memory_tests": [
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_memory.py", "-v"],
    ],
    "doctor": [
        [sys.executable, "-m", "capri_core", "doctor"],
    ],
    "bridge_tests": [
        [
            sys.executable, "-m", "unittest", "discover",
            "-s", "tests", "-p", "test_termux_bridge.py", "-v",
        ],
    ],
}
SECRET_PATTERNS = [
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bsb_secret_[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"(?i)(Bearer\s+)[A-Za-z0-9._~-]{20,}"),
]


class BridgeError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def redact(text: str) -> str:
    for pattern in SECRET_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    return text


def parse_job(raw: str) -> dict[str, Any]:
    try:
        job = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        raise BridgeError("Job manifest is not valid JSON") from exc
    if not isinstance(job, dict):
        raise BridgeError("Job manifest must be an object")
    if set(job) != {"schema_version", "job_id", "target_commit", "task"}:
        raise BridgeError("Job manifest has missing or unexpected fields")
    if type(job["schema_version"]) is not int or job["schema_version"] != 1:
        raise BridgeError("Unsupported job schema version")
    if not isinstance(job["job_id"], str) or not re.fullmatch(r"[0-9a-f]{32}", job["job_id"]):
        raise BridgeError("job_id must be 32 lowercase hexadecimal characters")
    try:
        uuid.UUID(hex=job["job_id"])
    except ValueError as exc:
        raise BridgeError("job_id is not a valid UUID") from exc
    if not isinstance(job["target_commit"], str) or not re.fullmatch(r"[0-9a-f]{40}", job["target_commit"]):
        raise BridgeError("target_commit must be a full 40-character Git SHA")
    if not isinstance(job["task"], str) or job["task"] not in TASKS:
        raise BridgeError("Task is not in the fixed allowlist")
    return job



def parse_queue_paths(raw: str) -> list[str]:
    """Return only canonical immutable queue entries, in deterministic order."""
    paths = {
        line.strip()
        for line in raw.splitlines()
        if re.fullmatch(r"jobs/[0-9a-f]{32}\.json", line.strip())
    }
    return sorted(paths)



def parse_claim(raw: str, expected_job_id: str) -> dict[str, Any]:
    try:
        claim = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        raise BridgeError("Claim record is not valid JSON") from exc
    required = {
        "schema_version", "job_id", "owner_id", "attempt",
        "claimed_at", "lease_expires_at", "status",
    }
    if not isinstance(claim, dict) or set(claim) != required:
        raise BridgeError("Claim record has missing or unexpected fields")
    if type(claim["schema_version"]) is not int or claim["schema_version"] != 1:
        raise BridgeError("Unsupported claim schema version")
    if claim["job_id"] != expected_job_id:
        raise BridgeError("Claim job_id does not match queue entry")
    if not isinstance(claim["owner_id"], str) or not re.fullmatch(r"[0-9a-f]{32}", claim["owner_id"]):
        raise BridgeError("Claim owner_id is invalid")
    if type(claim["attempt"]) is not int or not 1 <= claim["attempt"] <= MAX_CLAIM_ATTEMPTS:
        raise BridgeError("Claim attempt is outside the allowed range")
    if type(claim["claimed_at"]) is not int or type(claim["lease_expires_at"]) is not int:
        raise BridgeError("Claim timestamps must be integer Unix timestamps")
    if claim["lease_expires_at"] <= claim["claimed_at"]:
        raise BridgeError("Claim lease must expire after it is created")
    if not isinstance(claim["status"], str) or claim["status"] not in {"active", "abandoned"}:
        raise BridgeError("Claim status is invalid")
    return claim


def claim_is_live(claim: dict[str, Any], now: int) -> bool:
    return claim["status"] == "active" and claim["lease_expires_at"] > now


def claim_branch(job_id: str) -> str:
    return f"{CLAIM_PREFIX}{job_id}"


def read_claim(job_id: str) -> tuple[str | None, dict[str, Any] | None]:
    branch = claim_branch(job_id)
    remote = git("ls-remote", "--heads", "origin", f"refs/heads/{branch}")
    if not remote.stdout.strip():
        return None, None
    git(
        "fetch", "--quiet", "origin",
        f"+refs/heads/{branch}:refs/remotes/origin/{branch}",
    )
    ref = f"refs/remotes/origin/{branch}"
    raw = remote_file(ref, "bridge_claim.json")
    if raw is None:
        raise BridgeError(f"Claim branch {branch} has no bridge_claim.json")
    return ref, parse_claim(raw, job_id)


def write_claim(
    job_id: str,
    claim: dict[str, Any],
    base_ref: str,
) -> None:
    branch = claim_branch(job_id)
    with tempfile.TemporaryDirectory(prefix="capri-bridge-claim-") as temporary:
        worktree = Path(temporary) / "claim"
        git("worktree", "add", "--detach", str(worktree), base_ref)
        try:
            destination = worktree / "bridge_claim.json"
            destination.write_text(
                json.dumps(claim, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            git("add", "bridge_claim.json", cwd=worktree)
            git(
                "-c", "user.name=Capri Bridge Claim",
                "-c", "user.email=capri-bridge-claim@users.noreply.github.com",
                "commit", "-m", f"bridge: claim {job_id}", cwd=worktree,
            )
            pushed = git(
                "push", "origin", f"HEAD:refs/heads/{branch}",
                cwd=worktree, check=False,
            )
            if pushed.returncode:
                detail = redact((pushed.stderr or pushed.stdout)[-2000:])
                raise BridgeError(
                    f"Could not acquire/update distributed claim for {job_id}; "
                    f"another worker may have won the race: {detail}"
                )
        finally:
            git("worktree", "remove", "--force", str(worktree), check=False)


def claim_job(job_id: str) -> tuple[bool, dict[str, Any] | None]:
    now = int(time.time())
    current_ref, current = read_claim(job_id)
    if current and current["status"] == "abandoned":
        return False, current
    if current and claim_is_live(current, now):
        return False, current

    if current is None:
        attempt = 1
        base_ref = f"refs/remotes/origin/{INBOX_BRANCH}"
    else:
        base_ref = current_ref
        if current["attempt"] >= MAX_CLAIM_ATTEMPTS:
            terminal = {
                "schema_version": 1,
                "job_id": job_id,
                "owner_id": uuid.uuid4().hex,
                "attempt": current["attempt"],
                "claimed_at": now,
                "lease_expires_at": now + 1,
                "status": "abandoned",
            }
            write_claim(job_id, terminal, base_ref)
            return False, terminal
        attempt = current["attempt"] + 1

    claim = {
        "schema_version": 1,
        "job_id": job_id,
        "owner_id": uuid.uuid4().hex,
        "attempt": attempt,
        "claimed_at": now,
        "lease_expires_at": now + CLAIM_LEASE_SECONDS,
        "status": "active",
    }
    write_claim(job_id, claim, base_ref)
    return True, claim


def owns_live_claim(job_id: str, owner_id: str) -> bool:
    _, current = read_claim(job_id)
    return bool(
        current
        and current["owner_id"] == owner_id
        and claim_is_live(current, int(time.time()))
    )


def acquire_worker_lock() -> int:
    """Ensure only one watcher in this local checkout can execute jobs."""
    git_path = git("rev-parse", "--git-path", "capri-termux-bridge.lock").stdout.strip()
    lock_path = Path(git_path)
    if not lock_path.is_absolute():
        lock_path = ROOT / lock_path
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        os.close(descriptor)
        raise BridgeError("Another Termux bridge worker is already active in this checkout") from exc
    return descriptor



def git(*args: str, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    # Resolve ROOT at call time so tests and isolated worker checkouts can override it.
    working_directory = ROOT if cwd is None else cwd
    proc = subprocess.run(
        ["git", *args], cwd=str(working_directory), text=True, encoding="utf-8",
        errors="replace", capture_output=True, check=False,
    )
    if check and proc.returncode:
        detail = redact((proc.stderr or proc.stdout)[-3000:])
        raise BridgeError(f"git {' '.join(args[:3])} failed ({proc.returncode}): {detail}")
    return proc


def fetch_branches() -> None:
    git(
        "fetch", "--quiet", "origin",
        f"+refs/heads/{INBOX_BRANCH}:refs/remotes/origin/{INBOX_BRANCH}",
        f"+refs/heads/{RESULTS_BRANCH}:refs/remotes/origin/{RESULTS_BRANCH}",
    )


def remote_file(ref: str, path: str) -> str | None:
    proc = git("show", f"{ref}:{path}", check=False)
    return proc.stdout if proc.returncode == 0 else None


def result_exists(job_id: str) -> bool:
    proc = git("cat-file", "-e", f"refs/remotes/origin/{RESULTS_BRANCH}:results/{job_id}.json", check=False)
    return proc.returncode == 0


def safe_environment() -> dict[str, str]:
    env = os.environ.copy()
    for name in (
        "NOTION_API_TOKEN", "CAPRI_NOTION_LIVE_TESTS", "OPENAI_API_KEY",
        "GITHUB_TOKEN", "GH_TOKEN", "SUPABASE_ACCESS_TOKEN",
    ):
        env.pop(name, None)
    return env


def execute_task(task_name: str, target_commit: str) -> dict[str, Any]:
    steps: list[dict[str, Any]] = []
    overall_ok = True
    started = utc_now()
    for index, command in enumerate(TASKS[task_name], start=1):
        step_started = time.monotonic()
        try:
            proc = subprocess.run(
                command, cwd=str(ROOT), env=safe_environment(),
                text=True, encoding="utf-8", errors="replace",
                capture_output=True, timeout=STEP_TIMEOUT, check=False,
            )
            output = redact((proc.stdout or "") + (proc.stderr or ""))
            code = proc.returncode
            timed_out = False
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout or ""
            stderr = exc.stderr or ""
            if isinstance(stdout, bytes):
                stdout = stdout.decode("utf-8", "replace")
            if isinstance(stderr, bytes):
                stderr = stderr.decode("utf-8", "replace")
            output = redact(stdout + stderr + "\n[step timed out]")
            code = 124
            timed_out = True
        except OSError as exc:
            output = f"Could not start allowlisted task: {type(exc).__name__}: {exc}"
            code = 127
            timed_out = False
        steps.append({
            "step": index,
            "command_id": task_name,
            "exit_code": code,
            "timed_out": timed_out,
            "duration_seconds": round(time.monotonic() - step_started, 3),
            "output_tail": output[-MAX_OUTPUT:],
        })
        if code != 0:
            overall_ok = False
            break
    return {
        "schema_version": 1,
        "target_commit": target_commit,
        "task": task_name,
        "status": "passed" if overall_ok else "failed",
        "started_at": started,
        "finished_at": utc_now(),
        "steps": steps,
    }


def _retryable_result_push_error(detail: str) -> bool:
    """Identify push failures that can be repaired by refreshing the result branch."""
    lowered = detail.lower()
    return any(marker in lowered for marker in (
        "non-fast-forward", "fetch first", "failed to push some refs",
        "remote rejected", "connection reset", "connection timed out",
        "could not resolve host", "failed to connect", "remote end hung up",
    ))


def publish_result(job_id: str, result: dict[str, Any]) -> None:
    # Different workers can finish different jobs concurrently. A push based on
    # the same results-branch tip will make one worker lose the race; rebuild its
    # result commit on the latest tip instead of losing the completed job.
    max_push_attempts = 5
    for attempt in range(max_push_attempts):
        fetch_branches()
        if result_exists(job_id):
            return
        with tempfile.TemporaryDirectory(prefix="capri-termux-bridge-") as temporary:
            worktree = Path(temporary) / "results"
            git("worktree", "add", "--detach", str(worktree), f"refs/remotes/origin/{RESULTS_BRANCH}")
            try:
                destination = worktree / "results" / f"{job_id}.json"
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_text(
                    json.dumps(result, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                git("add", f"results/{job_id}.json", cwd=worktree)
                git(
                    "-c", "user.name=Capri Termux Bridge",
                    "-c", "user.email=capri-termux-bridge@users.noreply.github.com",
                    "commit", "-m", f"bridge: report {job_id}", cwd=worktree,
                )
                pushed = git(
                    "push", "origin", f"HEAD:refs/heads/{RESULTS_BRANCH}",
                    cwd=worktree, check=False,
                )
            finally:
                git("worktree", "remove", "--force", str(worktree), check=False)

        if pushed.returncode == 0:
            fetch_branches()
            if result_exists(job_id):
                return
            raise BridgeError(
                f"Result push for {job_id} reported success but read-back did not find the result."
            )

        detail = redact((pushed.stderr or pushed.stdout)[-2000:])
        # Another worker may have published this exact job while our push raced.
        fetch_branches()
        if result_exists(job_id):
            return
        if not _retryable_result_push_error(detail):
            raise BridgeError(f"Could not publish result for {job_id}: {detail}")
        if attempt + 1 == max_push_attempts:
            raise BridgeError(
                f"Could not publish result for {job_id} after {max_push_attempts} "
                f"concurrent/transient push attempts: {detail}"
            )
        time.sleep(min(0.25 * (2 ** attempt), 2.0))


def process_once() -> bool:
    fetch_branches()
    inbox_ref = f"refs/remotes/origin/{INBOX_BRANCH}"
    tree = git("ls-tree", "-r", "--name-only", inbox_ref, QUEUE_PREFIX).stdout
    paths = parse_queue_paths(tree)

    # Keep the original path readable during migration, but new jobs use
    # immutable jobs/<job_id>.json entries and are never overwritten.
    if remote_file(inbox_ref, JOB_PATH) is not None:
        paths.append(JOB_PATH)

    did_work = False
    for path in paths:
        raw = remote_file(inbox_ref, path)
        if raw is None:
            continue
        try:
            job = parse_job(raw)
        except BridgeError as exc:
            print(f"Rejected inbox entry {path}: {exc}")
            if path.startswith(QUEUE_PREFIX):
                queued_id = path[len(QUEUE_PREFIX):-5]
                rejection = {
                    "schema_version": 1,
                    "task": "invalid",
                    "status": "rejected",
                    "reason": str(exc),
                    "finished_at": utc_now(),
                    "steps": [],
                }
                publish_result(queued_id, rejection)
                did_work = True
            continue
        if path.startswith(QUEUE_PREFIX) and path != f"jobs/{job['job_id']}.json":
            print(f"Rejected inbox entry {path}: filename does not match job_id")
            rejection = {
                "schema_version": 1,
                "target_commit": job["target_commit"],
                "task": job["task"],
                "status": "rejected",
                "reason": "Queue filename does not match manifest job_id.",
                "finished_at": utc_now(),
                "steps": [],
            }
            publish_result(path[len(QUEUE_PREFIX):-5], rejection)
            did_work = True
            continue
        if result_exists(job["job_id"]):
            continue

        try:
            acquired, claim = claim_job(job["job_id"])
        except BridgeError as exc:
            print(f"Could not claim job {job['job_id']}: {exc}")
            continue
        if not acquired:
            if claim and claim["status"] == "abandoned":
                abandoned = {
                    "schema_version": 1,
                    "target_commit": job["target_commit"],
                    "task": job["task"],
                    "status": "abandoned",
                    "reason": f"Distributed claim expired after {MAX_CLAIM_ATTEMPTS} attempts.",
                    "finished_at": utc_now(),
                    "steps": [],
                }
                publish_result(job["job_id"], abandoned)
                did_work = True
            continue

        local_commit = git("rev-parse", "HEAD").stdout.strip()
        if local_commit != job["target_commit"]:
            result = {
                "schema_version": 1,
                "target_commit": job["target_commit"],
                "local_commit": local_commit,
                "task": job["task"],
                "status": "rejected",
                "reason": "Local checkout does not match target_commit; no task was executed.",
                "finished_at": utc_now(),
                "steps": [],
            }
        else:
            print(f"Executing allowlisted task '{job['task']}' at {local_commit}...")
            result = execute_task(job["task"], local_commit)
        if not owns_live_claim(job["job_id"], claim["owner_id"]):
            print(f"Job {job['job_id']}: claim expired or ownership changed; result not published.")
            continue
        publish_result(job["job_id"], result)
        print(f"Job {job['job_id']}: {result['status']}; result published to {RESULTS_BRANCH}.")
        did_work = True
    return did_work


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Capri's fixed, allowlisted Termux validation jobs.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true", help="check the inbox once and exit (default)")
    mode.add_argument("--watch", action="store_true", help="poll the private GitHub inbox continuously")
    parser.add_argument("--interval", type=int, default=5, help="poll interval in seconds (3-300; default: 5)")
    args = parser.parse_args()
    if not 3 <= args.interval <= 300:
        parser.error("--interval must be between 3 and 300 seconds")
    remote = git("remote", "get-url", "origin").stdout.strip().lower()
    if "github.com/hamudifr/capri" not in remote and "github.com:hamudifr/capri" not in remote:
        raise BridgeError("origin must point to the private Hamudifr/Capri repository")
    lock_fd = acquire_worker_lock()
    try:
        print(f"Capri Termux Bridge ready. Repository: {remote}")
        if not args.watch:
            process_once()
            return 0
        while True:
            try:
                process_once()
            except BridgeError as exc:
                print(f"Bridge cycle failed safely: {exc}")
            time.sleep(args.interval)
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BridgeError as exc:
        print(f"Bridge stopped safely: {exc}", file=sys.stderr)
        raise SystemExit(2)

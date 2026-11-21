#!/usr/bin/env python3
"""Narrow, GitHub-relayed Termux runner for Capri validation tasks.

This is deliberately NOT a remote shell. Jobs select one fixed task from TASKS;
the manifest cannot supply commands, arguments, paths, or environment variables.
"""
from __future__ import annotations

import argparse
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
JOB_PATH = "bridge/job.json"
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
    if job["schema_version"] != 1:
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


def git(*args: str, cwd: Path = ROOT, check: bool = True) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        ["git", *args], cwd=str(cwd), text=True, encoding="utf-8",
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
            output = redact((exc.stdout or "") + (exc.stderr or "") + "\n[step timed out]")
            if isinstance(output, bytes):
                output = output.decode("utf-8", "replace")
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


def publish_result(job_id: str, result: dict[str, Any]) -> None:
    fetch_branches()
    if result_exists(job_id):
        return
    with tempfile.TemporaryDirectory(prefix="capri-termux-bridge-") as temporary:
        worktree = Path(temporary) / "results"
        git("worktree", "add", "--detach", str(worktree), f"refs/remotes/origin/{RESULTS_BRANCH}")
        try:
            destination = worktree / "results" / f"{job_id}.json"
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            git("add", f"results/{job_id}.json", cwd=worktree)
            git(
                "-c", "user.name=Capri Termux Bridge",
                "-c", "user.email=capri-termux-bridge@users.noreply.github.com",
                "commit", "-m", f"bridge: report {job_id}", cwd=worktree,
            )
            git("push", "origin", f"HEAD:refs/heads/{RESULTS_BRANCH}", cwd=worktree)
        finally:
            git("worktree", "remove", "--force", str(worktree), check=False)


def process_once() -> bool:
    fetch_branches()
    raw = remote_file(f"refs/remotes/origin/{INBOX_BRANCH}", JOB_PATH)
    if raw is None:
        print("Bridge inbox is empty.")
        return False
    try:
        job = parse_job(raw)
    except BridgeError as exc:
        print(f"Rejected inbox job: {exc}")
        return False
    if result_exists(job["job_id"]):
        print(f"Job {job['job_id']} already has a result.")
        return False

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
    publish_result(job["job_id"], result)
    print(f"Job {job['job_id']}: {result['status']}; result published to {RESULTS_BRANCH}.")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Capri's fixed, allowlisted Termux validation jobs.")
    parser.add_argument("--watch", action="store_true", help="poll the private GitHub inbox continuously")
    parser.add_argument("--interval", type=int, default=20, help="poll interval in seconds (10-300)")
    args = parser.parse_args()
    if not 10 <= args.interval <= 300:
        parser.error("--interval must be between 10 and 300 seconds")
    remote = git("remote", "get-url", "origin").stdout.strip().lower()
    if "github.com/hamudifr/capri" not in remote and "github.com:hamudifr/capri" not in remote:
        raise BridgeError("origin must point to the private Hamudifr/Capri repository")
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


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BridgeError as exc:
        print(f"Bridge stopped safely: {exc}", file=sys.stderr)
        raise SystemExit(2)

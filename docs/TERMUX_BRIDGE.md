# Capri Termux Bridge

The Termux bridge is a narrow GitHub-relayed worker for running fixed Capri validation tasks on the user's Android checkout. It is not a remote shell.

## Queue protocol

New jobs are immutable files on the `capri-termux-bridge-inbox` branch. Enqueuing requires repository write access:

`jobs/<32-character-lowercase-hex-job-id>.json`

Each manifest contains exactly:

```json
{
  "schema_version": 1,
  "job_id": "0123456789abcdef0123456789abcdef",
  "target_commit": "full-40-character-git-commit-sha",
  "task": "full_validation"
}
```

Create a new file for every job. Do not replace an existing job file. Supported task identifiers are:

- `full_validation`: full unittest discovery, compileall, and Capri Doctor.
- `memory_tests`: memory test module.
- `doctor`: Capri Doctor only.
- `bridge_tests`: focused tests for queue manifests, claim validation, and lease logic.
- `security_store_tests`: the fixed CAP-167 security-store and backup regression suite.
- `approval_binding_tests`: the fixed approval-signature, lifecycle, resolver, gateway, executor, bridge and resource-authorization suites.
- `x7_runtime_tests`: the fixed task-runtime, host-runtime and runtime-core suites.

The worker scans canonical queue paths in sorted order and processes all pending jobs sequentially. Results are immutable per-job files at `results/<job-id>.json` on `capri-termux-bridge-results`. Completed results remain as history; jobs are not deleted. The old `bridge/job.json` location is still read for migration compatibility, but new producers must use the queue path.

## Worker concurrency and trust boundary

- A Git-directory file lock prevents two bridge processes using the same local checkout from running concurrently.
- Each job has a dedicated claim branch, `capri-termux-claim-<job-id>`. Workers acquire or take over a claim by pushing a commit to that branch. Git rejects a competing non-fast-forward push, providing cross-checkout/device mutual exclusion without a separate service.
- Claims last 60 minutes. Each claim can be acquired at most three times; an expired third attempt becomes terminally abandoned. The task allowlist currently has a maximum theoretical runtime of 45 minutes (three 15-minute steps), leaving a 15-minute lease margin.
- A worker checks that it still owns a live claim before publishing. Keep device clocks synchronized. Claims are retained as audit history; no automated branch cleanup is currently implemented.
- Crash recovery is at-least-once: if a worker finishes a task but crashes before publishing its result, a later lease takeover may repeat that task. Current allowlisted tasks are diagnostics/tests, not external side effects. Exactly-once execution is not claimed. Failed task results are final; automatic retries are for expired/crashed workers only.
- The worker resolves each exact 40-character target commit from its local Git objects or fetches that commit from `origin`, then creates a temporary detached worktree and verifies its HEAD before running the fixed task. The worker's own checkout and branch are never switched. If the exact commit cannot be fetched or verified, the job is rejected without executing a task.
- Validation code and tests from the target commit execute as the Termux operating-system user inside that temporary worktree. The fixed task allowlist prevents manifest-supplied commands, but this is not an OS sandbox; only queue commits from trusted repository writers.
- The manifest cannot provide a command, arguments, filesystem path, or environment variables. The task allowlist is fixed in code.
- Subprocesses run without a shell, with a timeout and bounded/redacted output.
- Inbox authorization derives from repository write access. Public repository visibility does not grant write access, but queue manifests and results are publicly readable when the repository is public. Manifests are not cryptographically signed.

## Running on Termux

From the Capri repository:

```sh
python tools/termux_bridge.py --once
python tools/termux_bridge.py --watch --interval 5
```

Use Ctrl+C to stop the watcher. Keep the Termux session alive while watching. The bridge does not install boot persistence or a wake lock.

When updating the worker, stop the existing watcher first, pull the branch, then restart it:

```sh
git pull --ff-only
python tools/termux_bridge.py --watch --interval 5
```

The bridge uses the existing GitHub repository and does not require a new cloud service or GitHub Actions workflow. Focused task names map to fixed test-file patterns in `FOCUSED_TEST_SUITES` inside `tools/termux_bridge.py`; the worker executes the fixed runner code from the target worktree. The manifest cannot choose test files or module names.

## Relationship to the durable task runtime

The Termux bridge currently transports only its fixed validation-task allowlist. It does not deserialize GitHub inbox manifests into `SQLiteTaskStore` plans or execute arbitrary `TaskWorker` handlers. The durable task runtime is a separate host-managed capability: principal-owned work requires authenticated ownership and explicitly injected `principal_handlers` with resource-level authorization. Do not treat repository write access as a task principal or use the bridge to bypass that boundary.

The `bridge_tests` job runs the focused `tests.test_termux_bridge` suite, including manifest validation, claim lifecycle, lease recovery, real two-independent-checkout Git ref races for both initial claim creation and expired-claim takeover against a temporary bare remote, concurrent result-publish retry behavior, and exact-target detached-worktree execution without moving the worker checkout.


## Current validation window

Until 2026-12-01, use only the focused regression tasks when the owner has requested focused validation. Defer `full_validation` until the free CI window is rechecked. The three focused task names are fixed in `TASKS`, each maps to one bounded Python invocation, and `tools/focused_tests.py` maps the suite names to fixed test-file patterns. Do not add manifest-supplied commands, paths or patterns.

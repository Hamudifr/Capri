# Capri Termux Bridge

The Termux bridge is a narrow GitHub-relayed worker for running fixed Capri validation tasks on the user's Android checkout. It is not a remote shell.

## Queue protocol

New jobs are immutable files on the private `capri-termux-bridge-inbox` branch:

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

The worker scans canonical queue paths in sorted order and processes all pending jobs sequentially. Results are immutable per-job files at `results/<job-id>.json` on `capri-termux-bridge-results`. Completed results remain as history; jobs are not deleted. The old `bridge/job.json` location is still read for migration compatibility, but new producers must use the queue path.

## Worker concurrency and trust boundary

- A Git-directory file lock prevents two bridge processes using the same local checkout from running concurrently.
- Each job has a dedicated claim branch, `capri-termux-claim-<job-id>`. Workers acquire or take over a claim by pushing a commit to that branch. Git rejects a competing non-fast-forward push, providing cross-checkout/device mutual exclusion without a separate service.
- Claims last 60 minutes. Each claim can be acquired at most three times; an expired third attempt becomes terminally abandoned. The task allowlist currently has a maximum theoretical runtime of 45 minutes (three 15-minute steps), leaving a 15-minute lease margin.
- A worker checks that it still owns a live claim before publishing. Keep device clocks synchronized. Claims are retained as audit history; no automated branch cleanup is currently implemented.
- Crash recovery is at-least-once: if a worker finishes a task but crashes before publishing its result, a later lease takeover may repeat that task. Current allowlisted tasks are diagnostics/tests, not external side effects. Exactly-once execution is not claimed. Failed task results are final; automatic retries are for expired/crashed workers only.
- The worker requires exact local HEAD equality with each job's target commit. A mismatch is rejected without running the task.
- The manifest cannot provide a command, arguments, filesystem path, or environment variables. The task allowlist is fixed in code.
- Subprocesses run without a shell, with a timeout and bounded/redacted output.
- Inbox authorization derives from write access to the private repository. Manifests are not cryptographically signed.

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

The bridge uses the existing private GitHub repository and does not require a new cloud service or GitHub Actions workflow.

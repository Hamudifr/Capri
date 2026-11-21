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

The worker scans canonical queue paths in sorted order and processes all pending jobs sequentially. Results are immutable per-job files at `results/<job-id>.json` on `capri-termux-bridge-results`. Completed results remain as history; jobs are not deleted. The old `bridge/job.json` location is still read for migration compatibility, but new producers must use the queue path.

## Worker concurrency and trust boundary

- A Git-directory file lock prevents two bridge processes using the same local checkout from running concurrently.
- Run one active worker checkout/device. The local lock does not coordinate separate clones or devices; multi-device distributed claiming is not implemented.
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

# Host service lifecycle and health

`CapriHostRuntime` remains a dependency-injected composition object. Constructing it, or constructing `CapriHostService`, starts no threads and performs no background work.

## Explicit lifecycle

Use `CapriHostService` when the host process needs to supervise its optional `TaskWorker` in-process:

```python
from capri_runtime import CapriHostService

service = CapriHostService(host_runtime)
health = service.start()
try:
    # Serve authenticated host requests while the optional worker runs.
    ...
finally:
    health = service.stop(timeout_seconds=10)
```

- `start()` is explicit and idempotent while already running.
- If a `TaskWorker` is configured, the service starts one daemon worker thread. If no worker is configured, the service manages the host lifecycle without creating a thread.
- `stop(timeout_seconds)` signals cooperative shutdown and joins the worker for up to the requested timeout (0–300 seconds).
- A running handler is not forcibly interrupted. If it outlives the timeout, the service remains `stopping`; release/cancel the handler through its normal contract and call `stop()` again.
- Unexpected worker exit moves the service to `failed` with a generic failure code. A failed service cannot be restarted in place; let the external supervisor replace the service/process.
- The service does not create an HTTP server, restart the process, or impose OS-level CPU/memory limits.

## Health reporting

`service.health()` returns a frozen `HostServiceHealth` snapshot and `as_dict()` provides a JSON-safe representation. It includes:

- lifecycle state and observation/start/stop timestamps;
- worker configured/alive status and a generic failure code;
- redacted integrity status for session, task, goal and budget stores.

Storage statuses are `healthy`, `degraded`, `unavailable`, or `not_configured`. Overall status is `healthy` only while the service is running and every configured store is healthy; storage faults or worker failures produce `degraded`; new, stopping and stopped services are `unavailable`.

Health checks call each configured store's `integrity_check()`. This is a local operator diagnostic, not a cheap per-request liveness probe. Schedule it at an appropriate interval and do not expose it to untrusted principals. Raw database errors and exception messages are deliberately not returned.

## Operational boundary

Run the host under an external process supervisor (for example, systemd or an equivalent deployment platform) for process restart, startup ordering, termination grace periods and OS-level resource limits. Configure persistent task and budget stores before starting the service. The in-process service only owns the optional worker thread and its cooperative shutdown.

No automatic provider/network checks are performed by health reporting, and no live provider calls are required for service lifecycle tests.

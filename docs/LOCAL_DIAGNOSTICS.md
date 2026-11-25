# Local repository diagnostics

Run the read-only Capri Doctor from the repository root:

```bash
python -m capri_core doctor
```

Use `python -m capri_core doctor --root /path/to/Capri` to inspect another checkout. Add `--json` to emit a versioned JSON report (`schema_version: 1`) containing stable check IDs, per-check status and details, overall status, and passed/failed/total counts.

## Checks

- Python 3.15.x only.
- Required source, test, documentation entry-point, and workflow files.
- External GitHub Actions references pinned to full 40-character commit SHAs.
- Explicit least-privilege `contents: read` workflow permissions.
- The `push` trigger includes `main`; the `pull_request` trigger includes `main`.

The command is read-only and uses only the known paths above. It does not enumerate arbitrary files, inspect transcripts or credentials, contact external services, execute tests, or modify the working tree.

A successful diagnostic is a structural sanity check, not a security certification, test result, CI result, or release approval. Run compilation and unit tests separately:

```bash
python -m compileall -q capri_core capri_runtime tests
python -m unittest discover -s tests -v
```

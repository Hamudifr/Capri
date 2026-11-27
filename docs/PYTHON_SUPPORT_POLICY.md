# Python support policy

Capri currently supports **CPython 3.15.x only**.

## Enforcement

- Package metadata requires `>=3.15,<3.16`, so pip rejects older and newer minor releases.
- Repository quality CI runs the complete test suite once, on Python 3.15. There is no multi-version matrix.
- Runtime, SQLite, Rust-reference, and four-language benchmark workflows use Python 3.15.
- Capri Doctor checks that the interpreter is Python 3.15.x.
- Capri Doctor probes the interpreter's SQLite build and fails closed unless JSON CHECK constraints are enforceable under `trusted_schema=OFF` (SQLite 3.41+).

## Upgrade rule

When a newer stable Python minor release becomes the chosen project baseline:

1. Update the package version range and Python classifier in `pyproject.toml`.
2. Update the single interpreter pin in every workflow.
3. Update Capri Doctor and the support statements in the README and contributor documentation.
4. Run the full quality workflow and all benchmark workflows on that new interpreter.
5. Keep historical benchmark and CI records unchanged. They describe the environment that actually ran at the time.

This policy deliberately trades broad backward compatibility for a smaller, faster, easier-to-maintain validation surface. It does not imply that older historical test results were invalid.

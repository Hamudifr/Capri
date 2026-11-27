"""Local runtime capability probes shared by Capri Doctor and runtime stores."""
from __future__ import annotations


def sqlite_json_capability() -> tuple[bool, str]:
    """Probe whether this interpreter's SQLite enforces json CHECK constraints.

    The durable session store creates ``CHECK(json_valid(...))`` constraints on
    a connection that sets ``PRAGMA trusted_schema=OFF``. SQLite builds older
    than 3.41.0 reject that combination with ``unsafe use of json_valid()``,
    so the probe replays the exact pattern in an in-memory database (main
    schema; TEMP tables are exempt and would mask the incompatibility).

    Returns ``(capable, detail)``; ``detail`` always names the linked SQLite
    version so failures are actionable instead of a raw driver error.
    """
    try:
        import sqlite3
    except ImportError:
        return False, "python sqlite3 module is unavailable"

    version = sqlite3.sqlite_version
    connection = None
    try:
        connection = sqlite3.connect(":memory:", isolation_level=None)
        connection.execute("PRAGMA trusted_schema=OFF")
        connection.execute(
            "CREATE TABLE capri_capability_probe ("
            "value TEXT CHECK(json_valid(value) AND json_type(value) = 'array'))"
        )
        connection.execute("INSERT INTO capri_capability_probe VALUES ('[]')")
    except sqlite3.Error as exc:
        return False, (
            f"SQLite {version} cannot enforce json CHECK constraints under "
            f"trusted_schema=OFF ({exc}); Capri requires SQLite 3.41 or newer"
        )
    finally:
        if connection is not None:
            connection.close()
    return True, (
        f"SQLite {version} enforces json CHECK constraints under trusted_schema=OFF"
    )

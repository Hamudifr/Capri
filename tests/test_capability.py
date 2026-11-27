"""Tests for local runtime capability probes."""
import sqlite3
import unittest
from unittest.mock import MagicMock, patch

from capri_core.capability import sqlite_json_capability


class SQLiteCapabilityProbeTests(unittest.TestCase):
    def test_probe_passes_on_capable_sqlite(self):
        capable, detail = sqlite_json_capability()
        self.assertTrue(capable, detail)
        self.assertIn(sqlite3.sqlite_version, detail)
        self.assertIn("trusted_schema=OFF", detail)

    def test_probe_fails_closed_when_connect_rejected(self):
        with patch(
            "sqlite3.connect",
            side_effect=sqlite3.OperationalError("unable to open database file"),
        ):
            capable, detail = sqlite_json_capability()
        self.assertFalse(capable)
        self.assertIn("unable to open database file", detail)
        self.assertIn(sqlite3.sqlite_version, detail)
        self.assertIn("3.41", detail)

    def test_probe_fails_closed_when_schema_ddl_rejected(self):
        # Mirrors SQLite < 3.41.0: connect and PRAGMA succeed, but CREATE TABLE
        # with a json CHECK under trusted_schema=OFF raises "unsafe use of ...".
        connection = MagicMock()
        connection.execute.side_effect = [
            None,
            sqlite3.OperationalError("unsafe use of json_valid()"),
        ]
        with patch("sqlite3.connect", return_value=connection):
            capable, detail = sqlite_json_capability()
        self.assertFalse(capable)
        self.assertIn("unsafe use of json_valid()", detail)
        self.assertIn("3.41", detail)
        connection.close.assert_called_once()

    def test_probe_fails_closed_when_existing_schema_write_rejected(self):
        # Mirrors opening an existing session database on SQLite < 3.41.0:
        # CREATE is skipped, the INSERT evaluates the persisted CHECK and fails.
        connection = MagicMock()
        connection.execute.side_effect = [
            None,
            None,
            sqlite3.OperationalError("unsafe use of json_type()"),
        ]
        with patch("sqlite3.connect", return_value=connection):
            capable, detail = sqlite_json_capability()
        self.assertFalse(capable)
        self.assertIn("unsafe use of json_type()", detail)
        connection.close.assert_called_once()

    def test_probe_fails_closed_without_sqlite_module(self):
        with patch.dict("sys.modules", {"sqlite3": None}):
            capable, detail = sqlite_json_capability()
        self.assertFalse(capable)
        self.assertIn("sqlite3 module is unavailable", detail)

    def test_probe_closes_connection_on_success(self):
        connection = MagicMock()
        with patch("sqlite3.connect", return_value=connection):
            capable, _ = sqlite_json_capability()
        self.assertTrue(capable)
        connection.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()

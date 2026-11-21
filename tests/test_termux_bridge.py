import json
import unittest

from tools.termux_bridge import BridgeError, parse_job, parse_queue_paths, redact


class TermuxBridgeManifestTests(unittest.TestCase):
    def valid_manifest(self):
        return {
            "schema_version": 1,
            "job_id": "0123456789abcdef0123456789abcdef",
            "target_commit": "d5b07c57011c6ffed878bba05431c2d1c7ebcd84",
            "task": "full_validation",
        }

    def test_valid_fixed_task_manifest_is_accepted(self):
        parsed = parse_job(json.dumps(self.valid_manifest()))
        self.assertEqual(parsed["task"], "full_validation")

    def test_boolean_schema_version_is_rejected(self):
        manifest = self.valid_manifest()
        manifest["schema_version"] = True
        with self.assertRaises(BridgeError):
            parse_job(json.dumps(manifest))

    def test_unknown_fields_are_rejected(self):
        manifest = self.valid_manifest()
        manifest["command"] = "rm -rf ~"
        with self.assertRaises(BridgeError):
            parse_job(json.dumps(manifest))

    def test_arbitrary_task_names_are_rejected(self):
        manifest = self.valid_manifest()
        manifest["task"] = "shell"
        with self.assertRaises(BridgeError):
            parse_job(json.dumps(manifest))

    def test_short_or_invalid_commit_ids_are_rejected(self):
        manifest = self.valid_manifest()
        manifest["target_commit"] = "HEAD"
        with self.assertRaises(BridgeError):
            parse_job(json.dumps(manifest))

    def test_invalid_job_ids_are_rejected(self):
        manifest = self.valid_manifest()
        manifest["job_id"] = "../job"
        with self.assertRaises(BridgeError):
            parse_job(json.dumps(manifest))

    def test_queue_paths_are_sorted_and_deduplicated(self):
        first = "jobs/0123456789abcdef0123456789abcdef.json"
        second = "jobs/abcdef0123456789abcdef0123456789.json"
        raw = f"{second}\n{first}\n{second}\n"
        self.assertEqual(parse_queue_paths(raw), [first, second])

    def test_queue_paths_reject_traversal_and_noncanonical_names(self):
        raw = (
            "jobs/../job.json\n"
            "jobs/ABCDEF0123456789ABCDEF0123456789.json\n"
            "jobs/0123456789abcdef0123456789abcdef.txt\n"
            "bridge/job.json\n"
        )
        self.assertEqual(parse_queue_paths(raw), [])

    def test_secret_like_values_are_redacted(self):
        token = "ghp_" + ("A" * 32)
        self.assertNotIn(token, redact("failed with " + token))
        self.assertIn("[REDACTED]", redact("failed with " + token))


if __name__ == "__main__":
    unittest.main()

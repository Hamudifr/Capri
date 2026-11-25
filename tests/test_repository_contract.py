from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class RepositoryContractTests(unittest.TestCase):
    def test_required_recovery_documents_exist(self):
        for relative in (
            "README.md",
            "docs/OPERATING_MODEL.md",
            "docs/RECOVERY_PLAN.md",
            "docs/EVALUATION_DATA_CONTRACT.md",
            "docs/RUNTIME_CORE.md",
            "docs/RUNTIME_FOUNDATION.md",
            "capri_core/ledger.py",
            "capri_runtime/runtime.py",
        ):
            with self.subTest(path=relative):
                self.assertTrue((ROOT / relative).is_file())

    def test_continuity_evaluation_is_ordinary_project_work(self):
        text = (ROOT / "docs/OPERATING_MODEL.md").read_text(encoding="utf-8")
        self.assertIn("Continuity and capability evaluation", text)
        self.assertIn("ordinary project materials", text)
        self.assertIn("optional and never a general prerequisite", text)
        self.assertNotIn("X5", text)
        self.assertNotIn("protected blind evaluation", text.lower())

    def test_independence_is_not_self_scoring(self):
        text = (ROOT / "docs/EVALUATION_DATA_CONTRACT.md").read_text(encoding="utf-8")
        self.assertIn("Independent requires a genuinely separate reviewer", text)
        self.assertIn("Self-Scored does not equal Independently Reviewed", text)

    def test_recovery_plan_does_not_claim_completion(self):
        text = (ROOT / "docs/RECOVERY_PLAN.md").read_text(encoding="utf-8")
        self.assertIn("release gate not met", text.lower())
        self.assertIn("not a claim of AGI or public/multi-tenant production readiness", text)

    def test_runtime_tool_boundary_is_documented_without_provider_claims(self):
        text = (ROOT / "docs/RUNTIME_FOUNDATION.md").read_text(encoding="utf-8")
        self.assertIn("concrete model provider", text)
        self.assertIn("not connected to a model provider", text)
        self.assertIn("not a sandbox", text)
        self.assertIn("process-local", text)

    def test_local_secrets_and_runtime_data_are_ignored(self):
        text = (ROOT / ".gitignore").read_text(encoding="utf-8")
        for pattern in (".env", ".venv/", "data/", "*.jsonl", "*.sqlite3", "__pycache__/"):
            with self.subTest(pattern=pattern):
                self.assertIn(pattern, text)

    def test_legacy_runtime_document_names_are_retired(self):
        self.assertFalse((ROOT / "docs/NON_X5_RUNTIME_DESIGN.md").exists())
        self.assertFalse((ROOT / "docs/NON_X5_RUNTIME_SPEC_TEMPLATE.md").exists())
        self.assertTrue((ROOT / "docs/RUNTIME_FOUNDATION.md").is_file())
        self.assertTrue((ROOT / "docs/RUNTIME_SPEC_TEMPLATE.md").is_file())


if __name__ == "__main__":
    unittest.main()

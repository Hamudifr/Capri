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
            "docs/NON_X5_RUNTIME_DESIGN.md",
            "capri_core/ledger.py",
            "capri_runtime/runtime.py",
        ):
            with self.subTest(path=relative):
                self.assertTrue((ROOT / relative).is_file())

    def test_x5_boundary_is_explicit(self):
        text = (ROOT / "docs/OPERATING_MODEL.md").read_text(encoding="utf-8")
        self.assertIn("Do not execute X5", text)
        self.assertIn("Do not search for, fetch, reconstruct", text)
        self.assertIn("stop reading that source immediately", text)

    def test_independence_is_not_self_scoring(self):
        text = (ROOT / "docs/EVALUATION_DATA_CONTRACT.md").read_text(encoding="utf-8")
        self.assertIn("Independent requires a genuinely separate reviewer", text)
        self.assertIn("Self-Scored does not equal Independently Reviewed", text)

    def test_recovery_plan_does_not_claim_completion(self):
        text = (ROOT / "docs/RECOVERY_PLAN.md").read_text(encoding="utf-8")
        self.assertIn("release gate not met", text.lower())
        self.assertIn("not a claim of AGI or public/multi-tenant production readiness", text)

    def test_runtime_tool_boundary_is_documented_without_provider_claims(self):
        text = (ROOT / "docs/NON_X5_RUNTIME_DESIGN.md").read_text(encoding="utf-8")
        self.assertIn("concrete model provider", text)
        self.assertIn("not connected to a model provider", text)
        self.assertIn("not a sandbox", text)
        self.assertIn("process-local", text)

    def test_local_secrets_and_runtime_data_are_ignored(self):
        text = (ROOT / ".gitignore").read_text(encoding="utf-8")
        for pattern in (".env", ".venv/", "data/", "*.jsonl", "*.sqlite3", "__pycache__/"):
            with self.subTest(pattern=pattern):
                self.assertIn(pattern, text)

    def test_no_protected_x5_artifact_paths(self):
        forbidden = {"x5_rubric", "x5_answers", "x5_expected", "x5_scoring"}
        paths = {p.as_posix().lower() for p in ROOT.rglob("*") if p.is_file()}
        for path in paths:
            for token in forbidden:
                self.assertNotIn(token, path)


if __name__ == "__main__":
    unittest.main()

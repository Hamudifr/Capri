import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from capri_core.__main__ import main
from capri_core.skill_validation import validate_skill_tree


ROOT = Path(__file__).resolve().parents[1]


def write_skill(root: Path, directory: str, frontmatter: str, body: str = "# Example Skill\n\nUse this workflow.\n") -> Path:
    skill_dir = root / "skills" / directory
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\n{frontmatter}---\n\n{body}",
        encoding="utf-8",
    )
    return skill_dir


class SkillValidationTests(unittest.TestCase):
    def test_repository_skill_packages_pass_validation(self):
        report = validate_skill_tree(ROOT)
        self.assertEqual(report["status"], "pass", report)
        self.assertEqual(report["summary"]["skills"], 2)
        self.assertEqual(report["summary"]["valid"], 2)

    def test_accepts_spec_optional_metadata_and_valid_relative_references(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            skill = write_skill(
                root,
                "sample-skill",
                "name: sample-skill\n"
                "description: Use when validating a sample skill package.\n"
                "license: MIT\n"
                "compatibility: Python 3.11+\n"
                "allowed-tools: Read\n"
                "metadata:\n"
                "  author: Capri\n"
                "  version: \"1.0\"\n",
                "# Sample Skill\n\nRead [the guide](references/guide.md).\n",
            )
            references = skill / "references"
            references.mkdir()
            (references / "guide.md").write_text("Reference.\n", encoding="utf-8")
            report = validate_skill_tree(root)
            self.assertEqual(report["status"], "pass", report)

    def test_accepts_block_scalar_description(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_skill(
                root,
                "block-skill",
                "name: block-skill\n"
                "description: |-\n"
                "  Use when a multi-line skill description is needed.\n"
                "  It explains both capability and trigger.\n",
            )
            report = validate_skill_tree(root)
            self.assertEqual(report["status"], "pass", report)

    def test_rejects_missing_frontmatter(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            skill = root / "skills" / "missing-frontmatter"
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text("# Missing frontmatter\n", encoding="utf-8")
            report = validate_skill_tree(root)
            self.assertEqual(report["status"], "fail")
            self.assertIn("YAML frontmatter", " ".join(report["skills"][0]["errors"]))

    def test_rejects_duplicate_frontmatter_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_skill(
                root,
                "duplicate-key",
                "name: duplicate-key\n"
                "name: duplicate-key\n"
                "description: Use when checking duplicate metadata.\n",
            )
            report = validate_skill_tree(root)
            self.assertEqual(report["status"], "fail")
            self.assertTrue(any("duplicate frontmatter key" in item for item in report["skills"][0]["errors"]))

    def test_rejects_unknown_frontmatter_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_skill(
                root,
                "unknown-field",
                "name: unknown-field\n"
                "description: Use when validating supported metadata.\n"
                "argument-hint: ignored by the Agent Skills format.\n",
            )
            report = validate_skill_tree(root)
            self.assertEqual(report["status"], "fail")
            self.assertTrue(any("unsupported frontmatter key" in item for item in report["skills"][0]["errors"]))

    def test_rejects_implicit_non_string_required_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_skill(
                root,
                "numeric-name",
                "name: 123\n"
                "description: Use when validating scalar types.\n",
            )
            report = validate_skill_tree(root)
            self.assertTrue(any("not a string" in item for item in report["skills"][0]["errors"]))

    def test_rejects_unsupported_yaml_aliases_instead_of_misparsing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_skill(
                root,
                "yaml-alias",
                "name: yaml-alias\n"
                "description: &shared Use when testing unsupported YAML aliases.\n",
            )
            report = validate_skill_tree(root)
            self.assertEqual(report["status"], "fail")
            self.assertTrue(any("unsupported YAML" in item for item in report["skills"][0]["errors"]))

    def test_rejects_name_that_does_not_match_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_skill(
                root,
                "directory-name",
                "name: other-name\n"
                "description: Use when testing name and directory alignment.\n",
            )
            report = validate_skill_tree(root)
            self.assertTrue(any("must match directory" in item for item in report["skills"][0]["errors"]))

    def test_rejects_invalid_kebab_case_name(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_skill(
                root,
                "bad--name",
                "name: bad--name\n"
                "description: Use when validating skill identifiers.\n",
            )
            report = validate_skill_tree(root)
            self.assertTrue(any("single hyphen separators" in item for item in report["skills"][0]["errors"]))

    def test_rejects_compatibility_over_500_characters(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_skill(
                root,
                "long-compatibility",
                "name: long-compatibility\n"
                "description: Use when testing compatibility field limits.\n"
                f"compatibility: {'x' * 501}\n",
            )
            report = validate_skill_tree(root)
            self.assertTrue(any("compatibility exceeds 500" in item for item in report["skills"][0]["errors"]))

    def test_rejects_missing_relative_resource(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_skill(
                root,
                "missing-resource",
                "name: missing-resource\n"
                "description: Use when validating referenced skill files.\n",
                "# Missing Resource\n\nRead [the missing guide](references/missing.md).\n",
            )
            report = validate_skill_tree(root)
            self.assertTrue(any("does not exist" in item for item in report["skills"][0]["errors"]))

    def test_rejects_unsafe_link_schemes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_skill(
                root,
                "unsafe-link",
                "name: unsafe-link\\n"
                "description: Use when validating skill resource links.\\n",
                "# Unsafe Link\\n\\nOpen [this](javascript:alert(1)).\\n",
            )
            report = validate_skill_tree(root)
            self.assertTrue(any("unsupported linked resource scheme" in item for item in report["skills"][0]["errors"]))

    def test_rejects_relative_resource_that_escapes_skill_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_skill(
                root,
                "escaping-resource",
                "name: escaping-resource\n"
                "description: Use when validating safe skill references.\n",
                "# Escaping Resource\n\nRead [outside](../outside.md).\n",
            )
            (root / "outside.md").write_text("outside\n", encoding="utf-8")
            report = validate_skill_tree(root)
            self.assertTrue(any("escapes the skill directory" in item for item in report["skills"][0]["errors"]))

    def test_duplicate_descriptions_are_reported_as_warnings(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            description = "Use when checking duplicate skill descriptions."
            write_skill(root, "skill-one", f"name: skill-one\ndescription: {description}\n")
            write_skill(root, "skill-two", f"name: skill-two\ndescription: {description}\n")
            report = validate_skill_tree(root)
            self.assertEqual(report["status"], "pass")
            self.assertEqual(report["summary"]["warnings"], 2)

    def test_supports_single_quoted_values_and_inline_comments(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_skill(
                root,
                "quoted-skill",
                "name: quoted-skill # package id\n"
                "description: 'Use when checking a skill''s description # safely.'\n"
                "license: 'MIT' # license label\n",
            )
            report = validate_skill_tree(root)
            self.assertEqual(report["status"], "pass", report)

    def test_rejects_duplicate_metadata_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_skill(
                root,
                "metadata-duplicate",
                "name: metadata-duplicate\n"
                "description: Use when testing metadata integrity.\n"
                "metadata:\n"
                "  author: Capri\n"
                "  author: another-value\n",
            )
            report = validate_skill_tree(root)
            self.assertTrue(any("duplicate metadata key" in item for item in report["skills"][0]["errors"]))

    def test_rejects_symbolic_link_skill_directories(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_skill(
                root,
                "real-skill",
                "name: real-skill\n"
                "description: Use when testing symbolic link rejection.\n",
            )
            try:
                (root / "skills" / "linked-skill").symlink_to(
                    root / "skills" / "real-skill",
                    target_is_directory=True,
                )
            except (OSError, NotImplementedError):
                self.skipTest("symbolic links are unavailable on this platform")
            report = validate_skill_tree(root)
            linked = next(item for item in report["skills"] if item["directory"] == "linked-skill")
            self.assertTrue(any("symbolic link" in item for item in linked["errors"]))

    def test_missing_skills_root_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            report = validate_skill_tree(Path(directory))
            self.assertEqual(report["status"], "fail")
            self.assertEqual(report["summary"]["errors"], 1)

    def test_authoring_document_exists(self):
        self.assertTrue((ROOT / "docs" / "SKILL_AUTHORING.md").is_file())

    def test_cli_emits_machine_readable_validation_report(self):
        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = main(["skills", "validate", "--root", str(ROOT), "--json"])
        report = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(report["tool"], "capri-skill-validator")
        self.assertEqual(report["summary"]["valid"], 2)

    def test_cli_returns_nonzero_for_invalid_skill_tree(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_skill(root, "invalid-skill", "name: invalid-skill\n")
            with redirect_stdout(io.StringIO()):
                exit_code = main(["skills", "validate", "--root", str(root), "--json"])
            self.assertEqual(exit_code, 1)


if __name__ == "__main__":
    unittest.main()

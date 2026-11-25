"""Dependency-free validation for repository-local Agent Skills packages.

This validates the strict, intentionally small YAML frontmatter subset used by
Capri's repository skills. Unsupported YAML constructs fail closed with a
clear diagnostic rather than being silently misparsed.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

_ALLOWED_FIELDS = {
    "name", "description", "license", "compatibility", "metadata", "allowed-tools",
}
_NAME_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
_KEY_PATTERN = re.compile(r"[a-z][a-z0-9-]*\Z")
_METADATA_KEY_PATTERN = re.compile(r"[A-Za-z0-9_-]+\Z")
_LINK_PATTERN = re.compile(r"!?(?:\[[^\]]*\])\(([^)\s]+)(?:\s+[^)]*)?\)")


def _strip_comment(value: str) -> str:
    quote: str | None = None
    index = 0
    while index < len(value):
        char = value[index]
        if quote == "'" and char == "'":
            if index + 1 < len(value) and value[index + 1] == "'":
                index += 2
                continue
            quote = None
        elif quote == '"' and char == "\\":
            index += 2
            continue
        elif quote is not None and char == quote:
            quote = None
        elif quote is None and char in {"'", '"'}:
            quote = char
        elif quote is None and char == "#" and (index == 0 or value[index - 1].isspace()):
            return value[:index].rstrip()
        index += 1
    return value.rstrip()

def _parse_scalar(raw: str) -> str:
    value = _strip_comment(raw).strip()
    if not value:
        raise ValueError("empty scalar")
    if value.startswith('"'):
        parsed = json.loads(value)
        if not isinstance(parsed, str):
            raise ValueError("expected a quoted string")
        return parsed
    if value.startswith("'"):
        if len(value) < 2 or not value.endswith("'"):
            raise ValueError("unterminated single-quoted string")
        return value[1:-1].replace("''", "'")
    if value[0] in "&*!{}[]":
        raise ValueError("unsupported YAML anchor, tag, alias, or flow collection")
    if value in {"|", "|-", "|+", ">", ">-", ">+"}:
        raise ValueError("block scalar must be parsed with its following lines")
    return value


def _parse_frontmatter(text: str) -> tuple[dict[str, Any], str, list[str]]:
    errors: list[str] = []
    source = text.lstrip("\ufeff")
    lines = source.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, "", ["SKILL.md must begin with YAML frontmatter opened by ---"]
    closing = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if closing is None:
        return {}, "", ["YAML frontmatter is missing its closing --- delimiter"]

    fields: dict[str, Any] = {}
    seen: set[str] = set()
    index = 1
    while index < closing:
        line = lines[index]
        line_number = index + 1
        if not line.strip() or line.lstrip().startswith("#"):
            index += 1
            continue
        if line.startswith((" ", "\t")):
            errors.append(f"line {line_number}: unexpected indentation at frontmatter root")
            index += 1
            continue
        if "\t" in line:
            errors.append(f"line {line_number}: tabs are not supported in YAML frontmatter")
            index += 1
            continue
        match = re.fullmatch(r"([A-Za-z][A-Za-z0-9-]*):(?:[ \t]*(.*))?", line)
        if not match:
            errors.append(f"line {line_number}: unsupported YAML frontmatter syntax")
            index += 1
            continue
        key, raw_value = match.group(1), _strip_comment((match.group(2) or "").strip()).strip()
        if key in seen:
            errors.append(f"line {line_number}: duplicate frontmatter key {key!r}")
            index += 1
            continue
        seen.add(key)
        if key not in _ALLOWED_FIELDS:
            errors.append(f"line {line_number}: unsupported frontmatter key {key!r}")
            index += 1
            continue

        if key == "metadata" and not raw_value:
            metadata: dict[str, str] = {}
            index += 1
            while index < closing:
                nested = lines[index]
                if not nested.strip():
                    index += 1
                    continue
                indent = len(nested) - len(nested.lstrip(" "))
                if indent == 0:
                    break
                if indent != 2 or "\t" in nested:
                    errors.append(f"line {index + 1}: metadata entries must use exactly two spaces")
                    index += 1
                    continue
                nested_match = re.fullmatch(r"  ([A-Za-z0-9_-]+):[ \t]*(.*)", nested)
                if not nested_match:
                    errors.append(f"line {index + 1}: invalid metadata entry")
                    index += 1
                    continue
                nested_key, nested_raw = nested_match.groups()
                if nested_key in metadata:
                    errors.append(f"line {index + 1}: duplicate metadata key {nested_key!r}")
                else:
                    try:
                        metadata[nested_key] = _parse_scalar(nested_raw)
                    except (ValueError, json.JSONDecodeError) as exc:
                        errors.append(f"line {index + 1}: invalid metadata value: {exc}")
                index += 1
            fields[key] = metadata
            continue

        if key == "metadata" and raw_value == "{}":
            fields[key] = {}
            index += 1
            continue

        if raw_value in {"|", "|-", "|+", ">", ">-", ">+"}:
            style = raw_value[0]
            index += 1
            block_lines: list[str] = []
            block_indent: int | None = None
            while index < closing:
                candidate = lines[index]
                if not candidate.strip():
                    block_lines.append("")
                    index += 1
                    continue
                indent = len(candidate) - len(candidate.lstrip(" "))
                if indent == 0:
                    break
                if block_indent is None:
                    block_indent = indent
                if indent < block_indent:
                    break
                block_lines.append(candidate[block_indent:])
                index += 1
            if style == ">":
                value = " ".join(part.strip() for part in block_lines if part.strip())
            else:
                value = "\n".join(block_lines)
            if raw_value.endswith("-"):
                value = value.rstrip("\n")
            elif value:
                value = value.rstrip("\n") + "\n"
            fields[key] = value
            continue

        try:
            fields[key] = _parse_scalar(raw_value)
        except (ValueError, json.JSONDecodeError) as exc:
            errors.append(f"line {line_number}: invalid {key!r} value: {exc}")
        index += 1

    body = "\n".join(lines[closing + 1:]).lstrip("\n")
    return fields, body, errors


def _validate_skill_directory(skill_dir: Path) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    manifest = skill_dir / "SKILL.md"
    result: dict[str, Any] = {
        "directory": skill_dir.name,
        "path": manifest.as_posix(),
        "status": "fail",
        "name": None,
        "description": None,
        "errors": errors,
        "warnings": warnings,
    }
    if skill_dir.is_symlink():
        errors.append("skill package directory must not be a symbolic link")
        return result
    if not manifest.is_file():
        errors.append("missing required file SKILL.md")
        return result
    if manifest.is_symlink():
        errors.append("SKILL.md must not be a symbolic link")
        return result
    try:
        text = manifest.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        errors.append(f"cannot read SKILL.md: {type(exc).__name__}")
        return result

    fields, body, parse_errors = _parse_frontmatter(text)
    errors.extend(parse_errors)
    name = fields.get("name")
    description = fields.get("description")
    result["name"] = name if isinstance(name, str) else None
    result["description"] = description if isinstance(description, str) else None

    if not isinstance(name, str) or not name.strip():
        errors.append("frontmatter requires a non-empty string name")
    else:
        if len(name) > 64:
            errors.append(f"name exceeds 64 characters ({len(name)})")
        if not _NAME_PATTERN.fullmatch(name):
            errors.append("name must be lowercase ASCII letters/digits with single hyphen separators")
        if name != skill_dir.name:
            errors.append(f"name {name!r} must match directory {skill_dir.name!r}")

    if not isinstance(description, str) or not description.strip():
        errors.append("frontmatter requires a non-empty string description")
    else:
        if len(description) > 1024:
            errors.append(f"description exceeds 1024 characters ({len(description)})")
        if not re.search(r"\bwhen\b", description, flags=re.IGNORECASE):
            warnings.append("description should state when the skill should be used")

    for key in ("license", "compatibility", "allowed-tools"):
        if key in fields and not isinstance(fields[key], str):
            errors.append(f"optional field {key!r} must be a string")
    compatibility = fields.get("compatibility")
    if isinstance(compatibility, str) and len(compatibility) > 500:
        errors.append(f"compatibility exceeds 500 characters ({len(compatibility)})")
    metadata = fields.get("metadata")
    if "metadata" in fields and (
        not isinstance(metadata, dict)
        or any(not isinstance(k, str) or not isinstance(v, str) for k, v in metadata.items())
    ):
        errors.append("metadata must be a flat string-to-string mapping")

    if not body.strip():
        errors.append("skill instruction body must not be empty")
    else:
        first_heading = next((line.strip() for line in body.splitlines() if line.strip()), "")
        if not first_heading.startswith("# "):
            warnings.append("body should begin with an H1 skill title")
        if len(body.splitlines()) > 500:
            warnings.append("SKILL.md exceeds the recommended 500-line limit; move details to references/")

    for target in _LINK_PATTERN.findall(body):
        parsed = urlsplit(target)
        if parsed.scheme or target.startswith(("#", "//")):
            continue
        relative = unquote(parsed.path)
        if not relative:
            continue
        if Path(relative).is_absolute():
            errors.append(f"linked resource must be relative to the skill directory: {target}")
            continue
        resolved = (skill_dir / relative).resolve()
        try:
            resolved.relative_to(skill_dir.resolve())
        except ValueError:
            errors.append(f"linked resource escapes the skill directory: {target}")
            continue
        if not resolved.exists():
            errors.append(f"linked resource does not exist: {target}")

    for item in skill_dir.rglob("*"):
        if item.is_symlink():
            errors.append(f"symbolic links are not allowed in skill packages: {item.relative_to(skill_dir).as_posix()}")

    result["status"] = "pass" if not errors else "fail"
    return result


def validate_skill_tree(repository_root: Path) -> dict[str, Any]:
    """Validate all direct child skill packages under repository_root/skills."""
    root = Path(repository_root)
    skills_root = root / "skills"
    if not skills_root.exists() or not skills_root.is_dir() or skills_root.is_symlink():
        return {
            "schema_version": 1,
            "tool": "capri-skill-validator",
            "status": "fail",
            "summary": {"skills": 0, "valid": 0, "invalid": 0, "errors": 1, "warnings": 0},
            "skills": [],
            "errors": [f"skills directory is missing or invalid: {skills_root}"],
        }

    directories = sorted(path for path in skills_root.iterdir() if path.is_dir() and not path.name.startswith("."))
    if not directories:
        return {
            "schema_version": 1,
            "tool": "capri-skill-validator",
            "status": "fail",
            "summary": {"skills": 0, "valid": 0, "invalid": 0, "errors": 1, "warnings": 0},
            "skills": [],
            "errors": ["no skill package directories found"],
        }

    results = [_validate_skill_directory(path) for path in directories]
    names: dict[str, list[dict[str, Any]]] = {}
    descriptions: dict[str, list[dict[str, Any]]] = {}
    for result in results:
        if result["name"]:
            names.setdefault(result["name"], []).append(result)
        if result["description"]:
            normalized = " ".join(result["description"].casefold().split())
            descriptions.setdefault(normalized, []).append(result)
    for duplicate_name, entries in names.items():
        if len(entries) > 1:
            for entry in entries:
                entry["errors"].append(f"duplicate skill name {duplicate_name!r}")
                entry["status"] = "fail"
    for entries in descriptions.values():
        if len(entries) > 1:
            for entry in entries:
                entry["warnings"].append("description duplicates another skill; review discovery clarity")

    error_count = sum(len(item["errors"]) for item in results)
    warning_count = sum(len(item["warnings"]) for item in results)
    valid_count = sum(item["status"] == "pass" for item in results)
    return {
        "schema_version": 1,
        "tool": "capri-skill-validator",
        "status": "pass" if error_count == 0 else "fail",
        "summary": {
            "skills": len(results),
            "valid": valid_count,
            "invalid": len(results) - valid_count,
            "errors": error_count,
            "warnings": warning_count,
        },
        "skills": results,
        "errors": [],
    }

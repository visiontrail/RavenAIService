"""Source-controlled response Skills loaded by the server on every Agent run."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any


_REQUIRED_SKILLS = {
    "log_analysis": ("humanizer-zh",),
    "project_expert": ("humanizer-zh",),
}
_SKILLS_ROOT = Path(__file__).resolve().parent / "required_skills"


def required_skill_names(agent_key: str) -> tuple[str, ...]:
    return _REQUIRED_SKILLS.get(agent_key, ())


def required_skill_sources(agent_key: str) -> list[tuple[dict[str, Any], Path]]:
    from app.services.skills_service import _parse_skill_frontmatter

    sources = []
    for name in required_skill_names(agent_key):
        directory = _SKILLS_ROOT / name
        metadata = _parse_skill_frontmatter(directory / "SKILL.md")
        if metadata["name"] != name:
            raise ValueError(f"Required Skill name mismatch: {name}")
        sources.append(({
            "id": name,
            "name": name,
            "description": metadata.get("description", ""),
            "enabled": True,
            "source": "required",
            "source_filename": "built-in (required)",
            "size_bytes": sum(path.stat().st_size for path in directory.iterdir() if path.is_file()),
            "dir_name": name,
        }, directory))
    return sources


def load_required_skill_prompt(
    agent_key: str, workspace: str | Path,
) -> tuple[str, list[dict[str, str]]]:
    """Read full rules each run; fail before querying if any required file fails.

    This is server-side activation, not a synthetic SDK tool call. Return
    content digests so the run trace can attest exactly which rules were loaded.
    """
    from app.services.skills_service import materialize_required_skills

    names = required_skill_names(agent_key)
    if not names:
        return "", []
    materialized = materialize_required_skills(agent_key, workspace)
    if set(materialized) != set(names):
        raise RuntimeError(f"Required Skills could not be materialized: {agent_key}")
    sections = []
    evidence = []
    for entry, source in required_skill_sources(agent_key):
        name = entry["name"]
        directory = Path(workspace) / ".claude" / "skills" / name
        raw = (directory / "SKILL.md").read_bytes()
        policy_raw = (directory / "response_policy.md").read_bytes()
        if (
            raw != (source / "SKILL.md").read_bytes()
            or policy_raw != (source / "response_policy.md").read_bytes()
        ):
            raise RuntimeError(f"Required Skill materialization mismatch: {name}")
        rules = raw.decode("utf-8")
        policy = policy_raw.decode("utf-8")
        if not rules.strip() or not policy.strip():
            raise RuntimeError(f"Empty required Skill: {name}")
        sections.append(
            f"\n\n<required-skill name=\"{name}\">\n"
            f"{rules}\n</required-skill>\n\n{policy}"
        )
        evidence.append({
            "name": name,
            "load_method": "server_prompt",
            "sha256": hashlib.sha256(raw).hexdigest(),
            "policy_sha256": hashlib.sha256(policy_raw).hexdigest(),
        })
    return "".join(sections), evidence

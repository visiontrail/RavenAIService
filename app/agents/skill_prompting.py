"""Prompt helpers for Claude Agent SDK Skill activation."""

from __future__ import annotations

import json
from typing import Any, Dict, Iterable, List, Optional


def build_skill_availability_prompt(
    skills: Iterable[Any],
    *,
    final_output_contract: str,
) -> str:
    """Build a user-prompt addendum advertising the materialized skills.

    Materializing a Skill only makes it discoverable to the SDK. Relevance
    judgement is left to the model at inference time: it reads the name +
    description menu below and loads each Skill on demand via the ``Skill``
    tool — at any point in the run, not just at the start.

    *skills* accepts ``{"name", "description"}`` dicts or bare name strings.
    """
    entries: List[tuple[str, str]] = []
    seen = set()
    for raw in skills:
        if isinstance(raw, dict):
            name = str(raw.get("name") or "").strip()
            description = str(raw.get("description") or "").strip()
        else:
            name = str(raw or "").strip()
            description = ""
        if not name or name in seen:
            continue
        seen.add(name)
        entries.append((name, description))
    if not entries:
        return ""

    bullets = "\n".join(
        f"- `{name}`：{description}" if description else f"- `{name}`"
        for name, description in entries
    )
    example = json.dumps({"skill": entries[0][0]}, ensure_ascii=False)
    paths = "\n".join(
        f"- `{name}` 文件：`.claude/skills/{name}/`" for name, _ in entries
    )
    return (
        "\n\n## 可用的 Skill（按需加载）\n"
        "下列 Skill 已物化到当前工作区。请根据名称与描述自行判断哪些与"
        "当前问题或子任务相关：\n"
        f"{bullets}\n\n"
        "使用规则：\n"
        "- 决定使用某个 Skill 之前，必须先调用 `Skill` 工具读取它的完整"
        f"指令（输入形如 `{example}`），再按指令执行；\n"
        "- 推理中途发现需要某个 Skill 时，可以随时补充加载，不限于开场；\n"
        "- 与当前请求无关的 Skill 不要加载，避免浪费上下文；\n"
        "- 一旦加载了某个 Skill，该主题的回答必须以其内容为准。\n\n"
        "如果 Skill 指令引用了相对路径脚本、模板或资源文件，必须相对下面"
        "的物化目录解析路径；例如 `<skill-dir>/scripts/...`，不要假设这些"
        "文件位于当前工作目录根部：\n"
        f"{paths}\n\n"
        f"最终输出仍必须遵守{final_output_contract}。如果某个 Skill 要求"
        "输出一个特定字符串、或要求“不要解释/不要添加额外文字”，请把该"
        "字符串原样放入最终 JSON 的 `answer` 和 `summary` 字段；不要输出"
        "裸文本，也不要省略 JSON 围栏。"
    )


def build_plain_text_skill_answer_fields(
    final_text: str,
    skill_names: Iterable[str],
) -> Optional[Dict[str, Any]]:
    """Wrap a non-JSON skill answer into the agent's structured schema fields."""
    answer = (final_text or "").strip()
    if not answer:
        return None

    names: List[str] = []
    seen = set()
    for raw in skill_names:
        name = str(raw or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        names.append(name)
    if not names:
        return None

    return {
        "status": "ok",
        "error_kind": None,
        "question_type": "qa",
        "answer": answer,
        "summary": answer,
        "severity": "info",
        "root_cause_hypotheses": [],
        "recommended_actions": [],
        "related_keywords": names,
        "parse_warning": "plain_text_skill_answer_wrapped",
    }

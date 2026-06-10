"""Prompt helpers for Claude Agent SDK Skill activation."""

from __future__ import annotations

import json
from typing import Any, Dict, Iterable, List, Optional


def build_skill_activation_prompt(
    skill_names: Iterable[str],
    *,
    final_output_contract: str,
) -> str:
    """Build a high-priority user-prompt addendum for selected skills.

    Materializing a Skill only makes it discoverable to the SDK. The model must
    still call the ``Skill`` tool to read the selected Skill's instructions, so
    agents append this addendum whenever relevance selection has picked skills.
    """
    names: List[str] = []
    seen = set()
    for raw in skill_names:
        name = str(raw or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        names.append(name)
    if not names:
        return ""

    bullets = "\n".join(f"- `{name}`" for name in names)
    calls = "\n".join(
        f"- `Skill` with input `{json.dumps({'skill': name}, ensure_ascii=False)}`"
        for name in names
    )
    paths = "\n".join(f"- `{name}` files: `.claude/skills/{name}/`" for name in names)
    return (
        "\n\n## 本轮命中的 Skill（必须先加载）\n"
        "下列 Skill 已经由后端相关性选择命中，并已物化到当前工作区：\n"
        f"{bullets}\n\n"
        "在执行问题分类、读取 `task.json`、克隆仓库或作答之前，你的下一步"
        "必须先逐个调用 `Skill` 工具加载并阅读这些 Skill：\n"
        f"{calls}\n\n"
        "不要因为问题看起来像常识题、源码题或日志题就跳过 Skill；一旦本节"
        "列出了 Skill，本轮回答必须以这些 Skill 的内容为准。\n\n"
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

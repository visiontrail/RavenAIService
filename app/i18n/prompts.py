"""Locale selection for per-language prompt bodies.

Prompt bodies in ``prompts_config.yaml`` are moving from a single string to a
per-language map, e.g.::

    system_prompt:
      zh: |
        ...
      en: |
        ...

This module centralizes the "pick the body for a locale, fall back to the
default language" rule so every agent loader (and the admin service) shares one
implementation. It is intentionally tolerant: a plain string body (the legacy
shape) is returned as-is, so loaders keep working before/while the YAML is
restructured.
"""

from __future__ import annotations

from typing import Any

from app.i18n import DEFAULT, normalize

# Short, imperative response-language directives keyed by locale. These are
# appended near the *end* of an agent's system prompt so the answer language is
# decoupled from the (possibly mixed-language) input data such as logs or source
# code. Kept deliberately blunt — an explicit final instruction is the most
# reliable lever on output language even when the prompt body drifts.
_RESPONSE_LANGUAGE_DIRECTIVES: dict[str, str] = {
    "zh": (
        "请全程使用简体中文回答。最终围栏 JSON 中所有面向用户的自然语言字段"
        "（尤其 answer、summary、root_cause_hypotheses[].hypothesis、"
        "recommended_actions、proposed_fixes 的 title/description/rationale）"
        "必须使用简体中文；日志关键字、代码标识符、协议字段名、文件路径和"
        "原始错误可保留原文。"
    ),
    "en": (
        "Respond entirely in English. In the final fenced JSON, every user-facing "
        "natural-language field, especially answer, summary, "
        "root_cause_hypotheses[].hypothesis, recommended_actions, and proposed_fixes "
        "title/description/rationale, must be English; log keywords, code "
        "identifiers, protocol field names, file paths, and raw errors may stay "
        "verbatim."
    ),
}


def response_language_directive(locale: str | None = None) -> str:
    """Return a short directive instructing the model to answer in ``locale``.

    ``locale`` is normalized (loose inputs like ``"en-US"`` are accepted) and
    falls back to :data:`app.i18n.DEFAULT` (``zh``) when unknown. The returned
    string carries no leading/trailing whitespace; callers decide how to join it
    onto the system prompt (typically ``"\\n\\n" + directive``). Never raises.
    """
    code = normalize(locale)
    return _RESPONSE_LANGUAGE_DIRECTIVES.get(
        code, _RESPONSE_LANGUAGE_DIRECTIVES[DEFAULT]
    )


def select_localized_body(body: Any, locale: str | None = None) -> str:
    """Return the prompt body for ``locale`` with a default-language fallback.

    Resolution order:

    1. If ``body`` is a plain string, return it stripped (legacy single-language
       shape — locale is irrelevant).
    2. If ``body`` is a per-language map, return the requested locale's body;
       if that locale is missing, fall back to :data:`app.i18n.DEFAULT` (``zh``);
       if that is also missing, return any non-empty variant present.
    3. Otherwise (``None`` / unexpected type / empty map) return ``""``.

    Never raises. ``locale`` is normalized, so loose inputs like ``"en-US"`` are
    accepted.
    """
    if isinstance(body, str):
        return body.strip()
    if not isinstance(body, dict) or not body:
        return ""

    code = normalize(locale)
    candidate = body.get(code)
    if not isinstance(candidate, str) or not candidate.strip():
        candidate = body.get(DEFAULT)
    if not isinstance(candidate, str) or not candidate.strip():
        # Last resort: first non-empty string variant, so a prompt authored in
        # only one (non-default) language still renders rather than vanishing.
        candidate = next(
            (v for v in body.values() if isinstance(v, str) and v.strip()),
            "",
        )
    return candidate.strip() if isinstance(candidate, str) else ""

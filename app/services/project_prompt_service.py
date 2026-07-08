"""
Project 级系统提示词管理服务。

让系统提示词也能像 Skill 一样分级处理：

- **Agent 级（基础层）**：来自 ``prompts_config.yaml``，按 agent + locale 选择。
  日志分析与重构包配置管理员的基础提示词**自带**代码仓库工作流（这两个 Agent
  必须能克隆仓库）；只有项目专家的基础提示词是**通用、与代码无关**的。
- **Project 级（追加层）**：针对单个 ``project_code`` 追加的系统提示词，用于限定
  该项目的专属约束（可以为空）。本服务负责存取这一层，它又分为两类：

  * **项目共享层**：对该项目下所有 Agent 生效（即历史上的单一文件，保持兼容）。
  * **Agent 专属层**：仅对某个 Agent 生效。**项目创建时会为「项目专家」播种默认
    提示词**：关联了代码仓库的项目播种 ``code_workflow_prompt``（克隆/分析源码
    的工作流），未关联仓库的项目播种 ``no_repo_workflow_prompt``（无代码约束）。
    日志分析与重构包配置管理员的这一层默认为空，仅由管理员按需填写。

存储布局（按 project_code 隔离，与 Project Skills 平行）：

    data/project_prompts/
    └── <project_code>/
        ├── system_prompt.md            # 项目共享层（对所有 Agent 生效）
        ├── project_expert/
        │   └── system_prompt.md        # Agent 专属层（仅项目专家）
        ├── log_analysis/
        │   └── system_prompt.md        # Agent 专属层（仅日志分析）
        └── package_search/
            └── system_prompt.md        # Agent 专属层（仅重构包配置管理员）

读取走文件系统、无缓存，Admin 编辑后立即对后续 Agent 运行生效。Agent 运行前
调用 :func:`build_project_prompt_addendum` （传入 ``agent_key``）拿到要拼接到基础
系统提示词之后的项目级附加段：它会合并「Agent 专属层 + 项目共享层」（无内容时
返回空串）。
"""

from __future__ import annotations

import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# 单个项目系统提示词的字符上限，防止异常大文件拖垮上下文 / 存储。
MAX_PROJECT_PROMPT_CHARS = 20000

_PROMPT_FILENAME = "system_prompt.md"

# 拥有「Agent 专属层」项目提示词的 Agent。键既是磁盘上的子目录名，也是各 Agent
# 在 ``build_project_prompt_addendum`` 中传入的 ``agent_key``。
PROJECT_AGENT_KEYS = ("project_expert", "log_analysis", "package_search")

# 兼容旧名（历史脚本/调用方可能仍引用）。
CODE_WORKFLOW_AGENT_KEYS = PROJECT_AGENT_KEYS

# 项目创建时会播种默认项目级提示词的 Agent：目前仅项目专家。日志分析与重构包
# 配置管理员的代码工作流内置在基础提示词中，其项目级提示词默认为空。
SEEDED_AGENT_KEYS = ("project_expert",)

# agent_key -> prompts_config.yaml 中对应的功能键，用于读取默认提示词模板。
_AGENT_CONFIG_KEY: Dict[str, str] = {
    "project_expert": "claude_agent_project_expert",
    "log_analysis": "claude_agent_log_analysis",
    "package_search": "claude_agent_package_search",
}

# 默认项目级提示词模板在 prompts_config.yaml 中的字段名，按「是否关联代码仓库」区分。
_DEFAULT_TEMPLATE_FIELD: Dict[bool, str] = {
    True: "code_workflow_prompt",
    False: "no_repo_workflow_prompt",
}


class ProjectPromptError(Exception):
    """项目提示词管理基础异常。"""


class ProjectPromptValidationError(ProjectPromptError):
    """project_code / agent_key 非法或内容超限。"""


# ─────────────────────── Path helpers ──────────────────────────────

def _project_prompts_root() -> Path:
    from app.config import settings

    return Path(settings.project_prompts_data_dir)


def validate_project_code(project_code: str) -> str:
    """规范化 project_code（去空白 + 小写），与 skills_service 保持一致。"""
    if not project_code or not project_code.strip():
        raise ProjectPromptValidationError("project_code 不能为空")
    return project_code.strip().lower()


def validate_agent_key(agent_key: Optional[str]) -> Optional[str]:
    """校验 agent_key：``None`` 表示项目共享层；否则必须是已知的 Agent。

    限定取值可同时充当路径白名单，避免 ``../`` 之类的目录穿越。
    """
    if agent_key is None:
        return None
    normalized = agent_key.strip().lower()
    if normalized not in PROJECT_AGENT_KEYS:
        raise ProjectPromptValidationError(f"未知的 agent_key: {agent_key}")
    return normalized


def _prompt_path(project_code: str, agent_key: Optional[str] = None) -> Path:
    code = validate_project_code(project_code)
    agent = validate_agent_key(agent_key)
    base = _project_prompts_root() / code
    if agent is not None:
        base = base / agent
    return base / _PROMPT_FILENAME


# ─────────────────────── Public API ────────────────────────────────

def get_project_prompt(project_code: str, agent_key: Optional[str] = None) -> Dict[str, Any]:
    """返回项目系统提示词的可读视图。

    ``agent_key`` 为 ``None`` 时读取项目共享层；否则读取该 Agent 的专属层。
    Always returns a dict; ``content`` 为空串且 ``exists=False`` 表示该层尚未
    配置项目级提示词。
    """
    code = validate_project_code(project_code)
    agent = validate_agent_key(agent_key)
    path = _prompt_path(code, agent)
    if not path.is_file():
        return {
            "project_code": code,
            "agent_key": agent,
            "content": "",
            "exists": False,
            "updated_at": None,
            "size_bytes": 0,
        }
    content = path.read_text(encoding="utf-8", errors="replace")
    stat = path.stat()
    return {
        "project_code": code,
        "agent_key": agent,
        "content": content,
        "exists": True,
        "updated_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
        "size_bytes": stat.st_size,
    }


def get_project_prompt_text(
    project_code: Optional[str], agent_key: Optional[str] = None
) -> str:
    """便捷读取：仅返回某一层的提示词正文，无内容时返回空串、绝不抛错。"""
    if not project_code:
        return ""
    try:
        path = _prompt_path(project_code, agent_key)
    except ProjectPromptValidationError:
        return ""
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError as exc:  # noqa: BLE001
        logger.warning("get_project_prompt_text failed for %s: %s", project_code, exc)
        return ""


def set_project_prompt(
    project_code: str, content: str, agent_key: Optional[str] = None
) -> Dict[str, Any]:
    """写入（或清空）某一层的项目系统提示词。

    空内容会删除底层文件，等价于“未配置”。返回写入后的可读视图。
    """
    if content is None:
        content = ""
    if len(content) > MAX_PROJECT_PROMPT_CHARS:
        raise ProjectPromptValidationError(
            f"系统提示词长度 {len(content)} 超过上限 {MAX_PROJECT_PROMPT_CHARS}"
        )

    code = validate_project_code(project_code)
    agent = validate_agent_key(agent_key)
    path = _prompt_path(code, agent)

    if not content.strip():
        # 空内容视为清除：删除文件（若存在），并回收已空的 Agent 子目录。
        if path.exists():
            path.unlink()
            logger.info("project prompt cleared: project=%s agent=%s", code, agent)
        if agent is not None:
            _cleanup_empty_dir(path.parent)
        return get_project_prompt(code, agent)

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".md.tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)
    logger.info("project prompt saved: project=%s agent=%s size=%d", code, agent, len(content))
    return get_project_prompt(code, agent)


def delete_project_prompt(project_code: str, agent_key: Optional[str] = None) -> None:
    """删除某一层的项目系统提示词（含其目录，若已为空）。"""
    code = validate_project_code(project_code)
    agent = validate_agent_key(agent_key)
    path = _prompt_path(code, agent)
    if path.exists():
        path.unlink()
    _cleanup_empty_dir(path.parent)
    logger.info("project prompt deleted: project=%s agent=%s", code, agent)


def _cleanup_empty_dir(directory: Path) -> None:
    try:
        if directory.is_dir() and not any(directory.iterdir()):
            shutil.rmtree(directory, ignore_errors=True)
    except OSError:
        pass


def build_project_prompt_addendum(
    project_code: Optional[str],
    agent_key: Optional[str] = None,
    *,
    project_name: Optional[str] = None,
) -> str:
    """构建拼接到基础系统提示词之后的项目级附加段。

    合并顺序为「Agent 专属层（含已播种的代码工作流）→ 项目共享层」，两者皆可为
    空。无任何内容时返回空串。返回的内容包含一个清晰的小标题，并声明该段是针对
    当前项目的专属约束，优先级高于通用约束（但不得违背安全/格式底线）。

    ``agent_key`` 为 ``None`` 时仅取项目共享层（保持历史调用方的行为不变）。
    """
    sections: List[str] = []
    agent_text = get_project_prompt_text(project_code, agent_key) if agent_key else ""
    if agent_text:
        sections.append(agent_text)
    shared_text = get_project_prompt_text(project_code, None)
    if shared_text and shared_text != agent_text:
        sections.append(shared_text)
    if not sections:
        return ""

    label = (project_name or "").strip() or validate_project_code(project_code)
    body = "\n\n---\n\n".join(sections)
    return (
        "\n\n## 项目级附加系统指令（{label}）\n"
        "以下是针对当前项目「{label}」配置的专属系统指令（含代码工作流）。在不违背"
        "安全约束与最终输出格式要求的前提下，这些项目特定的约束优先于通用指令，"
        "你必须严格遵守：\n\n"
        "{body}\n"
    ).format(label=label, body=body)


def load_agent_base_system_prompt(agent_key: str, *, locale: Optional[str] = None) -> str:
    """读取某个项目型 Agent 的基础层系统提示词。

    该基础层来自 ``prompts_config.yaml``，与 Agent 运行时的 loader 使用同一套
    locale fallback 规则。未知 Agent 抛出校验异常，便于 API 返回 422。
    """
    agent = validate_agent_key(agent_key)
    if agent is None:
        raise ProjectPromptValidationError("agent_key 不能为空")
    function_key = _AGENT_CONFIG_KEY.get(agent)
    if not function_key:
        return ""

    try:
        import os

        import yaml

        from app.config import settings
        from app.i18n.prompts import select_localized_body

        raw = getattr(settings, "prompts_config_path", "app/prompts/prompts_config.yaml")
        if os.path.isabs(raw):
            path = Path(raw)
        else:
            project_root = Path(__file__).resolve().parents[2]  # repository root
            path = (project_root / raw).resolve()

        parsed = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        agent_cfg = parsed.get(function_key) or {}
        variant = agent_cfg.get("generic") or {}
        return select_localized_body(variant.get("system_prompt"), locale)
    except FileNotFoundError:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.warning("load_agent_base_system_prompt failed for %s: %s", agent_key, exc)
        return ""


def build_project_system_prompt_preview(
    project_code: str,
    agent_key: str,
    *,
    project_name: Optional[str] = None,
    locale: Optional[str] = None,
) -> Dict[str, Any]:
    """构建后台配置层的系统提示词拼接预览。

    返回 ``基础层 Agent system_prompt + 项目级附加系统指令``。这里刻意不注入
    每次运行才产生的动态上下文（工作区路径、Skill 菜单、回复语言指令等）。
    """
    code = validate_project_code(project_code)
    agent = validate_agent_key(agent_key)
    if agent is None:
        raise ProjectPromptValidationError("agent_key 不能为空")

    base_prompt = load_agent_base_system_prompt(agent, locale=locale)
    project_addendum = build_project_prompt_addendum(
        code,
        agent,
        project_name=project_name,
    )
    composed_prompt = f"{base_prompt}{project_addendum}"
    agent_layer = get_project_prompt(code, agent)
    shared_layer = get_project_prompt(code, None)

    return {
        "project_code": code,
        "project_name": (project_name or "").strip() or code,
        "agent_key": agent,
        "locale": locale or None,
        "base_prompt": base_prompt,
        "project_addendum": project_addendum,
        "content": composed_prompt,
        "base_chars": len(base_prompt),
        "addendum_chars": len(project_addendum),
        "total_chars": len(composed_prompt),
        "layers": [
            {
                "key": "base",
                "label": "Agent 基础层",
                "exists": bool(base_prompt.strip()),
                "size_bytes": len(base_prompt.encode("utf-8")),
                "updated_at": None,
            },
            {
                "key": "agent",
                "label": "Agent 项目层",
                "exists": agent_layer["exists"],
                "size_bytes": agent_layer["size_bytes"],
                "updated_at": agent_layer["updated_at"],
            },
            {
                "key": "shared",
                "label": "项目共享层",
                "exists": shared_layer["exists"],
                "size_bytes": shared_layer["size_bytes"],
                "updated_at": shared_layer["updated_at"],
            },
        ],
    }


# ─────────────────────── Default-prompt seeding ─────────────────────

def load_default_prompt_template(
    agent_key: str, *, has_repo: bool = True, locale: Optional[str] = None
) -> str:
    """读取某 Agent 的默认项目级提示词模板（来自 ``prompts_config.yaml``）。

    ``has_repo=True`` 读取 ``code_workflow_prompt``（关联了代码仓库的项目），
    ``has_repo=False`` 读取 ``no_repo_workflow_prompt``（未关联仓库的项目）。
    ``locale`` 选择多语言变体，缺失时回退默认语言（``zh``）。未知 agent_key、
    模板不存在或读不到时返回空串、绝不抛错。
    """
    try:
        agent = validate_agent_key(agent_key)
    except ProjectPromptValidationError:
        return ""
    if agent is None:
        return ""
    function_key = _AGENT_CONFIG_KEY.get(agent)
    if not function_key:
        return ""

    try:
        import os

        import yaml

        from app.config import settings
        from app.i18n.prompts import select_localized_body

        raw = getattr(settings, "prompts_config_path", "app/prompts/prompts_config.yaml")
        if os.path.isabs(raw):
            path = Path(raw)
        else:
            project_root = Path(__file__).resolve().parents[2]  # repository root
            path = (project_root / raw).resolve()

        parsed = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        agent_cfg = parsed.get(function_key) or {}
        variant = agent_cfg.get("generic") or {}
        field = _DEFAULT_TEMPLATE_FIELD[bool(has_repo)]
        body = select_localized_body(variant.get(field), locale)
        return (body or "").strip()
    except Exception as exc:  # noqa: BLE001
        logger.warning("load_default_prompt_template failed for %s: %s", agent_key, exc)
        return ""


def load_code_workflow_template(agent_key: str, locale: Optional[str] = None) -> str:
    """兼容旧名：读取某 Agent 的「代码工作流」模板正文。"""
    return load_default_prompt_template(agent_key, has_repo=True, locale=locale)


def seed_default_project_prompt(
    project_code: str,
    agent_key: str,
    *,
    has_repo: bool,
    locale: Optional[str] = None,
    overwrite: bool = False,
) -> bool:
    """把某 Agent 的默认项目级提示词模板播种到该项目的 Agent 专属层。

    幂等且不覆盖管理员的改动：目标文件已存在时，仅当其内容仍是**另一变体**的
    未改动默认值（项目在「有仓库 ↔ 无仓库」之间切换）才替换为新变体；其余情况
    一律跳过。``overwrite=True`` 强制用最新模板刷新。返回是否实际写入。
    """
    code = validate_project_code(project_code)
    agent = validate_agent_key(agent_key)
    if agent is None:
        return False
    template = load_default_prompt_template(agent, has_repo=has_repo, locale=locale)
    if not template:
        return False
    path = _prompt_path(code, agent)
    if path.is_file() and not overwrite:
        current = path.read_text(encoding="utf-8", errors="replace").strip()
        if current == template:
            return False
        other = load_default_prompt_template(agent, has_repo=not has_repo, locale=locale)
        if current != other:
            # 管理员已自定义该层：保留改动，不播种。
            return False
    set_project_prompt(code, template, agent_key=agent)
    logger.info(
        "seeded default project prompt: project=%s agent=%s has_repo=%s",
        code,
        agent,
        has_repo,
    )
    return True


def seed_project_default_prompts(
    project_code: str,
    *,
    has_repo: bool,
    locale: Optional[str] = None,
    overwrite: bool = False,
) -> List[str]:
    """为项目播种各 Agent 的默认项目级提示词（目前仅项目专家）。

    ``has_repo`` 决定播种「代码工作流」还是「无仓库」变体。返回实际写入的
    agent_key 列表。项目创建以及仓库关联状态变化时都应调用。
    """
    seeded: List[str] = []
    for agent in SEEDED_AGENT_KEYS:
        try:
            if seed_default_project_prompt(
                project_code, agent, has_repo=has_repo, locale=locale, overwrite=overwrite
            ):
                seeded.append(agent)
        except ProjectPromptValidationError as exc:
            logger.warning(
                "seed_project_default_prompts skipped project=%s agent=%s: %s",
                project_code,
                agent,
                exc,
            )
    return seeded

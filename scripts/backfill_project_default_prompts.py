#!/usr/bin/env python3
"""回填「项目专家」的默认项目级提示词，并清理旧版播种残留。

背景：提示词分级策略调整后——

- **日志分析** 与 **重构包配置管理员** 的代码仓库工作流回到了**基础提示词**里
  （这两个 Agent 必须能克隆仓库），它们的项目级提示词默认为空；
- 只有 **项目专家** 在项目创建时播种默认的项目级提示词：关联了代码仓库的项目
  播种 ``code_workflow_prompt``，未关联仓库的项目播种 ``no_repo_workflow_prompt``。

新建/更新项目时会自动播种（见 ``app/api/admin.py``）。本脚本用于一次性回填
存量项目，并做两件事：

1. 为每个已启用项目（无论有无仓库）播种项目专家的对应默认提示词；
   已有内容且被管理员改过的不会被覆盖。
2. 清理旧版为日志分析 / 重构包配置管理员播种的项目级代码工作流：仅当文件内容
   与旧版内置模板逐字一致（哈希比对）才删除，管理员改过的内容一律保留。

幂等，可重复执行。用法：
    python scripts/backfill_project_default_prompts.py [--dry-run]
                                                       [--locale zh] [--code <project_code>]
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import sys
from pathlib import Path

# 允许以 ``python scripts/xxx.py`` 直接运行：把仓库根加入 sys.path。
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models.database import db_manager  # noqa: E402
from app.services import project_prompt_service, project_repo_service  # noqa: E402

# 旧版播种到 log_analysis / package_search 项目层的代码工作流模板（zh/en）的
# SHA-256（对 strip 后正文计算）。内容与其一致说明管理员从未改动，可安全删除。
_LEGACY_SEED_HASHES = {
    "log_analysis": {
        "924b77befe251336f52dc3e53ebcdd64dac48b9b3ef7a3d15aae658e7741d270",  # zh
        "1ea9c9a488bc596f9d9db572bf3f6d39a067f405ecad47edc206917a51d09b09",  # en
    },
    "package_search": {
        "98a6c3444cc6d3fba89bad37f1e75da599a0a922494d8f859e5f302479d4cb3d",  # zh
        "598123e022607b43d409f6e2df09adb95bb266e691b06e62a9177fcaa043194a",  # en
    },
}


async def _list_enabled_projects():
    """返回所有已启用项目（含未关联代码仓库的项目）。"""
    db_manager.initialize()
    async for session in db_manager.get_session():
        return await project_repo_service.list_repos(
            session,
            include_disabled=False,
            offset=0,
            limit=100000,
        )
    return []


def _load_repos():
    try:
        return asyncio.run(_list_enabled_projects())
    except Exception as exc:  # noqa: BLE001
        from app.config import settings

        print(
            "无法读取项目列表（数据库未初始化或表不存在）。请先在已初始化的数据库上运行。\n"
            f"  database_url = {settings.get_database_url()}\n"
            f"  错误：{exc}",
            file=sys.stderr,
        )
        return None


def _prune_legacy_seed(code: str, agent: str, dry_run: bool) -> bool:
    """删除旧版播种且未被改动的 Agent 专属层，返回是否（将）删除。"""
    text = project_prompt_service.get_project_prompt_text(code, agent)
    if not text:
        return False
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if digest not in _LEGACY_SEED_HASHES[agent]:
        return False
    if not dry_run:
        project_prompt_service.delete_project_prompt(code, agent)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="只打印将要执行的动作，不写文件")
    parser.add_argument("--locale", default=None, help="播种使用的语言变体（默认 zh 兜底）")
    parser.add_argument("--code", default=None, help="仅处理指定 project_code（默认全部）")
    args = parser.parse_args()

    repos = _load_repos()
    if repos is None:
        return 1
    if args.code:
        target = project_prompt_service.validate_project_code(args.code)
        repos = [r for r in repos if r.project_code == target]

    if not repos:
        print("没有匹配的已启用项目，无需回填。")
        return 0

    total_seeded = 0
    total_pruned = 0
    for repo in repos:
        code = repo.project_code
        has_repo = project_repo_service.has_repo(repo)
        actions = []

        if args.dry_run:
            existing = project_prompt_service.get_project_prompt_text(code, "project_expert")
            template = project_prompt_service.load_default_prompt_template(
                "project_expert", has_repo=has_repo, locale=args.locale
            )
            other = project_prompt_service.load_default_prompt_template(
                "project_expert", has_repo=not has_repo, locale=args.locale
            )
            if template and (not existing or existing == other):
                actions.append(f"播种 project_expert（has_repo={has_repo}）")
        else:
            seeded = project_prompt_service.seed_project_default_prompts(
                code, has_repo=has_repo, locale=args.locale
            )
            total_seeded += len(seeded)
            if seeded:
                actions.append(f"已播种 {', '.join(seeded)}（has_repo={has_repo}）")

        for agent in ("log_analysis", "package_search"):
            if _prune_legacy_seed(code, agent, args.dry_run):
                total_pruned += 1
                actions.append(f"清理旧播种 {agent}")

        prefix = "[dry-run] " if args.dry_run else ""
        if actions:
            print(f"{prefix}{code}: {'；'.join(actions)}")
        else:
            print(f"{prefix}{code}: 无需处理")

    if not args.dry_run:
        print(f"\n完成：处理 {len(repos)} 个项目，播种 {total_seeded} 个，清理 {total_pruned} 个旧播种层。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

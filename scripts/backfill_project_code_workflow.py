#!/usr/bin/env python3
"""回填「项目级代码工作流提示词」到已关联代码仓库的存量项目。

背景：系统提示词改为分级处理后，三个 Agent（项目专家 / 日志分析 / 重构包配置
管理员）的**基础提示词不再包含代码相关内容**；与代码相关的工作流提示词改为在
「项目关联了代码仓库」时，由 ``project_prompt_service`` 播种到该项目的 Agent
专属层（``data/project_prompts/<code>/<agent>/system_prompt.md``）。

新建/更新项目时会自动播种（见 ``app/api/admin.py``）。本脚本用于一次性回填升级
前就已存在、且已关联代码仓库的项目。

幂等：默认只为尚未配置该层的 Agent 写入；已存在的文件不会被覆盖（保留管理员的
改动）。需要用最新模板强制刷新时加 ``--overwrite``。

用法：
    python scripts/backfill_project_code_workflow.py [--dry-run] [--overwrite]
                                                     [--locale zh] [--code <project_code>]
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# 允许以 ``python scripts/xxx.py`` 直接运行：把仓库根加入 sys.path。
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models.database import db_manager  # noqa: E402
from app.services import project_prompt_service, project_repo_service  # noqa: E402


async def _list_repo_enabled_projects():
    """返回所有「已启用且关联了代码仓库」的项目（去掉已关联判断里的分页上限）。"""
    db_manager.initialize()
    async for session in db_manager.get_session():
        return await project_repo_service.list_repos(
            session,
            include_disabled=False,
            offset=0,
            limit=100000,
            with_repo=True,
        )
    return []


def _load_repos():
    try:
        return asyncio.run(_list_repo_enabled_projects())
    except Exception as exc:  # noqa: BLE001
        from app.config import settings

        print(
            "无法读取项目列表（数据库未初始化或表不存在）。请先在已初始化的数据库上运行。\n"
            f"  database_url = {settings.get_database_url()}\n"
            f"  错误：{exc}",
            file=sys.stderr,
        )
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="只打印将要播种的内容，不写文件")
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="用最新模板覆盖已存在的 Agent 专属层（会丢弃管理员对该层的改动）",
    )
    parser.add_argument("--locale", default=None, help="播种使用的语言变体（默认 zh 兜底）")
    parser.add_argument("--code", default=None, help="仅回填指定 project_code（默认全部）")
    args = parser.parse_args()

    repos = _load_repos()
    if repos is None:
        return 1
    if args.code:
        target = project_prompt_service.validate_project_code(args.code)
        repos = [r for r in repos if r.project_code == target]

    if not repos:
        print("没有匹配的「已关联代码仓库」项目，无需回填。")
        return 0

    total_seeded = 0
    for repo in repos:
        code = repo.project_code
        if args.dry_run:
            pending = [
                agent
                for agent in project_prompt_service.CODE_WORKFLOW_AGENT_KEYS
                if args.overwrite
                or not project_prompt_service.get_project_prompt(code, agent)["exists"]
            ]
            if pending:
                print(f"[dry-run] {code}: 将播种 -> {', '.join(pending)}")
            else:
                print(f"[dry-run] {code}: 已齐全，跳过")
            continue

        seeded = project_prompt_service.seed_project_code_workflows(
            code, locale=args.locale, overwrite=args.overwrite
        )
        total_seeded += len(seeded)
        if seeded:
            print(f"{code}: 已播种 -> {', '.join(seeded)}")
        else:
            print(f"{code}: 已齐全，跳过")

    if not args.dry_run:
        print(f"\n完成：共为 {len(repos)} 个项目处理，写入 {total_seeded} 个 Agent 专属层。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

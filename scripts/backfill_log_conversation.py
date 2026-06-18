#!/usr/bin/env python3
"""回填日志的 AI 分析多轮对话历史（``ai_analysis_conversation``）。

背景：多轮历史是后加的特性。旧版本只在 ``ai_analysis_result`` 保存最近一次结果，
不维护历史；因此在升级前已完成的轮次不会进入 ``ai_analysis_conversation``，
导致日志详情页只显示最近一轮。但这些轮次的完整问答仍保存在 ``chat_agent_runs``
（ai_chat 触发的分析），可据此重建。

本脚本针对给定 ``log_id``：
- 取出所有引用该日志、且成功的 ``chat_agent_runs``（按 ``started_at`` 升序）；
- 与现有 ``ai_analysis_conversation`` 富结构轮次按提问去重合并（已有的富结构优先保留，
  缺失的轮次从 run 的 Markdown 回答重建）；
- 按时间顺序写回，使详情页展示完整的多轮问答。

幂等：重复运行结果一致（已在历史中的提问不会重复插入）。

用法：
    python scripts/backfill_log_conversation.py <log_id> [--db data/logs.db] [--dry-run]
    python scripts/backfill_log_conversation.py --all [--db data/logs.db] [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from typing import Any, Dict, List, Optional, Tuple

# chat 回答 Markdown 中，回答正文之后可能出现的顶层小节标题（按构造顺序）。
# 见 app/services/log_analysis_chat_service.py 的 _build_chat_answer。
_SECTION_HEADERS = ["## 摘要", "## 根因假设", "## 建议", "## 关键词"]
_ANSWER_HEADER = "## 回答"


def _section_body(text: str, header: str, following: List[str]) -> str:
    """提取 ``header`` 小节正文：从该标题之后到下一个顶层小节标题之前。"""
    i = text.find(header)
    if i < 0:
        return ""
    start = i + len(header)
    end = len(text)
    for h in following:
        j = text.find(h, start)
        if j >= 0:
            end = min(end, j)
    return text[start:end].strip()


def parse_chat_answer(answer_md: str) -> Tuple[str, str, List[str]]:
    """从 chat 渲染的回答 Markdown 中还原 (answer 正文, summary, keywords)。

    若无法定位「## 回答」标题（格式异常），则把去掉开头横幅后的整段作为回答正文。
    """
    answer_md = answer_md or ""
    answer = _section_body(answer_md, _ANSWER_HEADER, _SECTION_HEADERS)
    if not answer:
        # 兜底：丢弃开头的「**日志分析 Agent** ...」横幅，保留其余内容
        answer = re.sub(r"^\*\*.*?Agent\*\*.*?\n", "", answer_md, count=1, flags=re.S).strip()
    summary = _section_body(answer_md, "## 摘要", ["## 根因假设", "## 建议", "## 关键词"])
    keywords_block = _section_body(answer_md, "## 关键词", [])
    keywords = re.findall(r"`([^`]+)`", keywords_block)
    return answer, summary, keywords


def _iso(ts: Optional[str]) -> Optional[str]:
    """把 sqlite 存储的 'YYYY-MM-DD HH:MM:SS.ffffff' 规整为 ISO 'T' 形式。"""
    if not ts:
        return None
    return ts.replace(" ", "T")


def _norm_query(q: Optional[str]) -> str:
    return (q or "").strip()


def reconstruct_turn(run: Dict[str, Any], user: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """从一条 chat_agent_run 重建一轮分析结果（结构对齐前端 normalizeAIAnalysisResult）。"""
    answer, summary, keywords = parse_chat_answer(run.get("answer") or "")
    return {
        "engine": "claude-agent-sdk",
        "model": run.get("model") or "unknown",
        "schema_version": 3,
        "status": "ok",
        "question_type": "qa",
        "answer": answer,
        "summary": summary,
        "related_keywords": keywords,
        "query": run.get("user_message") or "",
        "created_at": _iso(run.get("finished_at") or run.get("started_at")),
        # 审计标记：表示该轮是从历史 run 回填重建，而非实时分析直接持久化。
        "recovered_from_run": run.get("id"),
        "triggered_by": {
            "source": "ai_chat",
            "run_id": run.get("id"),
            "session_id": run.get("session_id"),
            "user": {k: v for k, v in (user or {}).items() if v is not None},
            "started_at": _iso(run.get("started_at")),
            "finished_at": _iso(run.get("finished_at")),
        },
    }


def _fetch_user(cur: sqlite3.Cursor, user_id: Optional[str]) -> Optional[Dict[str, Any]]:
    if not user_id:
        return None
    cols = [r[1] for r in cur.execute("PRAGMA table_info(users)").fetchall()]
    row = cur.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    if not row:
        return {"id": user_id}
    d = dict(zip(cols, row))
    return {
        "id": d.get("id"),
        "username": d.get("username"),
        "display_name": d.get("display_name"),
        "email": d.get("email"),
    }


def _fetch_runs_for_log(cur: sqlite3.Cursor, log_id: str) -> List[Dict[str, Any]]:
    cols = [r[1] for r in cur.execute("PRAGMA table_info(chat_agent_runs)").fetchall()]
    rows = cur.execute(
        "SELECT * FROM chat_agent_runs WHERE agent_kind='log_analysis' "
        "AND status='succeeded' AND request_json LIKE ? ORDER BY started_at ASC",
        (f"%{log_id}%",),
    ).fetchall()
    runs: List[Dict[str, Any]] = []
    for row in rows:
        d = dict(zip(cols, row))
        # 精确校验 request_json.log_id（LIKE 仅做粗筛，避免子串误匹配）
        try:
            payload = json.loads(d.get("request_json") or "{}")
        except Exception:
            payload = {}
        if str(payload.get("log_id") or "") == str(log_id):
            runs.append(d)
    return runs


def backfill_log(cur: sqlite3.Cursor, log_id: str, *, dry_run: bool) -> bool:
    """回填单条日志。返回是否发生变更。"""
    row = cur.execute(
        "SELECT id, metadata_json FROM log_records WHERE id=?", (log_id,)
    ).fetchone()
    if not row:
        print(f"[skip] log not found: {log_id}")
        return False

    full_id, metadata_json = row
    try:
        metadata = json.loads(metadata_json) if metadata_json else {}
    except Exception as exc:
        print(f"[skip] metadata_json 解析失败 {full_id}: {exc}")
        return False
    extra = metadata.get("extra_fields")
    if not isinstance(extra, dict):
        extra = {}

    existing = extra.get("ai_analysis_conversation")
    existing = existing if isinstance(existing, list) else []
    existing_by_query: Dict[str, Dict[str, Any]] = {
        _norm_query(t.get("query")): t for t in existing if isinstance(t, dict)
    }

    runs = _fetch_runs_for_log(cur, full_id)
    if not runs:
        print(f"[skip] 无可用 chat_agent_runs：{full_id}")
        return False

    # 按 run 的时间顺序重建历史：已有富结构轮次优先保留，缺失轮次从 run 重建。
    new_history: List[Dict[str, Any]] = []
    used_queries = set()
    for run in runs:
        q = _norm_query(run.get("user_message"))
        if q in existing_by_query:
            new_history.append(existing_by_query[q])
        else:
            user = _fetch_user(cur, run.get("user_id"))
            new_history.append(reconstruct_turn(run, user))
        used_queries.add(q)

    # 安全兜底：保留任何未能与 run 对应的已有富结构轮次（如非 ai_chat 来源）。
    for t in existing:
        if isinstance(t, dict) and _norm_query(t.get("query")) not in used_queries:
            new_history.append(t)

    before = [(_norm_query(t.get("query")), bool(t.get("recovered_from_run"))) for t in existing]
    after = [(_norm_query(t.get("query")), bool(t.get("recovered_from_run"))) for t in new_history]
    if before == after:
        print(f"[ok] 已是完整历史，无需回填：{full_id}（{len(existing)} 轮）")
        return False

    print(f"[backfill] {full_id}: {len(existing)} 轮 -> {len(new_history)} 轮")
    for idx, t in enumerate(new_history):
        tag = "重建" if t.get("recovered_from_run") else "原有"
        print(f"    turn[{idx}] ({tag}) query={_norm_query(t.get('query'))[:40]!r}")

    if dry_run:
        print("    --dry-run：未写入数据库")
        return True

    extra["ai_analysis_conversation"] = new_history
    metadata["extra_fields"] = extra
    cur.execute(
        "UPDATE log_records SET metadata_json=? WHERE id=?",
        (json.dumps(metadata, ensure_ascii=False, default=str), full_id),
    )
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log_id", nargs="?", help="要回填的日志 ID")
    parser.add_argument("--all", action="store_true", help="回填所有日志")
    parser.add_argument("--db", default="data/logs.db", help="sqlite 数据库路径")
    parser.add_argument("--dry-run", action="store_true", help="仅预览，不写入")
    args = parser.parse_args()

    if not args.log_id and not args.all:
        parser.error("需要提供 log_id 或 --all")

    con = sqlite3.connect(args.db)
    cur = con.cursor()
    try:
        if args.all:
            ids = [r[0] for r in cur.execute("SELECT id FROM log_records").fetchall()]
        else:
            ids = [args.log_id]

        changed = 0
        for lid in ids:
            if backfill_log(cur, lid, dry_run=args.dry_run):
                changed += 1
        if not args.dry_run:
            con.commit()
        print(f"\n完成：{changed} 条日志{'（预览）' if args.dry_run else '已更新'}。")
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

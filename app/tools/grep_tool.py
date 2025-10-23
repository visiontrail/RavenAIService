"""
Streaming grep tool for large logs with context and safety limits.
"""
import os
import re
from collections import deque
from typing import Deque, Dict, List, Optional

from app.config import settings
from app.agents.xml_utils import wrap_search_results, wrap_excerpt


def _is_in_allowed_root(path: str) -> bool:
    try:
        abs_path = os.path.abspath(path)
        abs_root = os.path.abspath(settings.agent_root_dir)
        return os.path.commonpath([abs_path, abs_root]) == abs_root
    except Exception:
        return False


def _compile_query(query: str, flags: int = re.MULTILINE) -> re.Pattern:
    try:
        return re.compile(query, flags)
    except re.error:
        # Fallback to literal search by escaping
        return re.compile(re.escape(query), flags)


def grep_file(
    path: str,
    query: str,
    context: int = 2,
    max_matches: Optional[int] = None,
    max_bytes: Optional[int] = None,
) -> Dict[str, List[Dict[str, str]]]:
    """Search file for pattern, returning excerpts and summary.
    Limits matches and bytes to avoid memory blowups.
    """
    if not settings.agent_enabled:
        raise RuntimeError("Agent disabled by configuration")
    if not _is_in_allowed_root(path):
        raise PermissionError("Path outside allowed root: %s" % path)
    if not os.path.isfile(path):
        raise FileNotFoundError(path)

    limit_matches = max_matches or settings.agent_max_matches
    limit_bytes = max_bytes or settings.agent_max_snippet_bytes

    pattern = _compile_query(query)
    pre: Deque[str] = deque(maxlen=context)
    results: List[Dict[str, str]] = []

    consumed = 0
    with open(path, "r", errors="ignore") as f:
        for lineno, line in enumerate(f, start=1):
            if pattern.search(line):
                # Build excerpt
                before = list(pre)
                after_lines = []
                for _ in range(context):
                    nxt = f.readline()
                    if not nxt:
                        break
                    after_lines.append(nxt)
                start_line = max(1, lineno - len(before))
                end_line = lineno + len(after_lines)
                snippet = "".join(before + [line] + after_lines)
                # enforce byte limit on snippet
                if len(snippet.encode("utf-8", errors="ignore")) > limit_bytes:
                    snippet = snippet[: limit_bytes]
                results.append({
                    "path": path,
                    "start_line": str(start_line),
                    "end_line": str(end_line),
                    "match": query,
                    "text": snippet,
                })
                if len(results) >= limit_matches:
                    break
                pre.clear()
                continue
            pre.append(line)
            consumed += len(line)
            if consumed > limit_bytes * 10:  # soft stop for extremely large files
                break

    return {"query": query, "results": results}


def grep_file_xml(
    path: str,
    query: str,
    context: int = 2,
    max_matches: Optional[int] = None,
    max_bytes: Optional[int] = None,
) -> str:
    res = grep_file(path, query, context=context, max_matches=max_matches, max_bytes=max_bytes)
    # Convert excerpts to XML list
    xml_items: List[Dict[str, str]] = []
    for r in res["results"]:
        xml_items.append({
            "path": r["path"],
            "start_line": r["start_line"],
            "end_line": r["end_line"],
            "excerpt": r["text"],
        })
    results_xml = wrap_search_results(res["query"], xml_items)
    # Also append raw excerpts
    excerpts_xml = "".join([
        wrap_excerpt(r["path"], int(r["start_line"]), int(r["end_line"]), r["text"], match=res["query"]) 
        for r in res["results"]
    ])
    return f"<grep>{results_xml}{excerpts_xml}</grep>"
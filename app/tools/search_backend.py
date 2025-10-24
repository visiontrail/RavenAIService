"""
Pluggable search backend for log files.
Includes a local regex-based search and an optional Elasticsearch/OpenSearch stub.
"""
import os
import re
import logging
from typing import Dict, List, Optional, Tuple

from app.config import settings
from app.tools.grep_tool import grep_file
from app.agents.xml_utils import wrap_search_results

logger = logging.getLogger(__name__)


class SearchBackend:
    def index(self, paths: List[str]) -> None:
        raise NotImplementedError

    def search(self, query: str, k: int = 10) -> List[Dict[str, str]]:
        raise NotImplementedError


class RegexSearchBackend(SearchBackend):
    """Simple local backend that scans indexed file paths with regex.
    Designed for huge logs by sampling via grep_file with tight limits.
    """
    def __init__(self, root: Optional[str] = None):
        self.root = os.path.abspath(root or settings.agent_root_dir)
        self.paths: List[str] = []

    def index(self, paths: List[str]) -> None:
        safe_paths = []
        for p in paths:
            ap = os.path.abspath(p)
            if os.path.commonpath([ap, self.root]) != self.root:
                continue
            if os.path.isfile(ap):
                safe_paths.append(ap)
        self.paths = safe_paths
        logger.info("SearchBackend index: paths_indexed=%d root=%s", len(safe_paths), self.root)

    def search(self, query: str, k: int = 10) -> List[Dict[str, str]]:
        logger.info("ToolCall regex_search: query=%s k=%d indexed_paths=%d", query, k, len(self.paths))
        results: List[Dict[str, str]] = []
        for path in self.paths:
            try:
                res = grep_file(path, query=query, context=1, max_matches=1)
                if res["results"]:
                    r0 = res["results"][0]
                    results.append({
                        "path": r0["path"],
                        "score": 1.0,  # naive score
                        "start_line": r0["start_line"],
                        "end_line": r0["end_line"],
                    })
                    if len(results) >= k:
                        break
            except Exception:
                continue
        logger.info("ToolResult regex_search: hits=%d query=%s", len(results), query)
        return results


class ElasticSearchBackend(SearchBackend):
    """Optional OpenSearch/Elasticsearch backend.
    NOTE: This is a lightweight stub; wire to your ES client as needed.
    """
    def __init__(self, url: Optional[str] = None, index_name: str = "logs"):
        self.url = url or settings.elasticsearch_url
        self.index_name = index_name
        self.client = None
        try:
            from opensearchpy import OpenSearch  # type: ignore
            if self.url:
                self.client = OpenSearch(self.url)
        except Exception:
            try:
                from elasticsearch import Elasticsearch  # type: ignore
                if self.url:
                    self.client = Elasticsearch(self.url)
            except Exception:
                self.client = None

    def index(self, paths: List[str]) -> None:
        # Stub: implement ingestion pipeline externally for large logs
        pass

    def search(self, query: str, k: int = 10) -> List[Dict[str, str]]:
        if not self.client:
            return []
        logger.info("ToolCall elastic_search: query=%s k=%d url=%s index=%s", query, k, self.url, self.index_name)
        try:
            resp = self.client.search(index=self.index_name, body={
                "size": k,
                "query": {"match": {"content": query}}
            })
            hits = resp.get("hits", {}).get("hits", [])
            results: List[Dict[str, str]] = []
            for h in hits:
                src = h.get("_source", {})
                results.append({
                    "path": src.get("path", "unknown"),
                    "score": h.get("_score", 0.0),
                })
            logger.info("ToolResult elastic_search: hits=%d query=%s", len(results), query)
            return results
        except Exception:
            return []


def search_to_xml(backend: SearchBackend, query: str, k: int = 10) -> str:
    results = backend.search(query=query, k=k)
    logger.info("ToolResult search_to_xml: results_count=%d query=%s", len(results), query)
    return wrap_search_results(query, results)
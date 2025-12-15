"""
LangChain/LangGraph-based Log Analysis Agent with ReAct-style loop.

Key changes in this refactor:
- LangGraph StateGraph orchestrates plan -> act -> loop until done
- Planning still produces XML <plan><step>...</step></plan> for compatibility
- Tools execution routes to existing grep/metadata/fs/search helpers and emits XML
- Short-term memory kept (compatible), plus outputs compression to summary
- Backward-compatible API: LogAnalysisAgent.plan(), LogAnalysisAgent.run(), demo_agent_run()
"""
from typing import Any, Dict, List, Optional, TypedDict
import os
import re
import json
import logging
import shutil
from enum import Enum

# Optional LangChain imports (gracefully degrade if unavailable)
try:
    from langchain_community.chat_models import ChatOpenAI  # type: ignore
except Exception:
    ChatOpenAI = None

try:
    from langchain.prompts import PromptTemplate  # type: ignore
except Exception:
    PromptTemplate = None

try:
    from langgraph.graph import StateGraph, END  # type: ignore
except Exception:
    StateGraph = None
    END = None

try:
    import yaml  # type: ignore
except Exception:
    yaml = None

try:
    from langchain_core.tools import tool as lc_tool  # type: ignore
except Exception:
    lc_tool = None
try:
    from langchain.tools import StructuredTool as LCStructuredTool  # type: ignore
except Exception:
    LCStructuredTool = None

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

from app.config import settings
from app.models.log import LogType

def _make_chat_openai(api_key: str, base_url: str, model: str):
    os.environ["OPENAI_API_KEY"] = api_key
    os.environ["OPENAI_BASE_URL"] = base_url
    os.environ["OPENAI_API_BASE"] = base_url
    try:
        logger.debug(f"Initializing ChatOpenAI client: base_url={base_url}, model={model}")
        return ChatOpenAI(model=model, temperature=settings.llm_temperature)
    except Exception as e:
        logger.warning(f"ChatOpenAI init failed: base_url={base_url}, model={model}, error={e}")
        return None
from app.agents.xml_utils import wrap_plan, wrap_document
from app.tools.metadata_tool import get_log_package_metadata_xml
from app.tools.grep_tool import grep_file_xml
from app.tools.fs_tools import read_head_xml, read_tail_xml
from app.tools.search_backend import RegexSearchBackend, ElasticSearchBackend, search_to_xml
from app.tools.archive_tool import auto_extract_archive_xml, list_tree_xml, nested_archives_xml, extract_nested_archive_xml




def get_llm() -> Any:
    """Return an LLM client using the unified DeepSeek configuration."""
    logger.debug("get_llm: provider=deepseek (unified)")
    if not ChatOpenAI:
        logger.error("get_llm: ChatOpenAI unavailable")
        return None

    api_key = getattr(settings, "deepseek_api_key", None)
    base_url = getattr(settings, "deepseek_base_url", None)
    model = getattr(settings, "llm_model_name", None)

    if not api_key or not base_url or not model:
        raise RuntimeError("DeepSeek 配置缺失，无法初始化 LLM")

    llm = _make_chat_openai(api_key, base_url, model)
    if not llm:
        raise RuntimeError("无法初始化 DeepSeek LLM，请检查配置")

    # 确保LLM实例有model_name属性
    if not hasattr(llm, "model_name"):
        llm.model_name = model
    return llm


class ShortTermMemory:
    def __init__(self, window: int = 5):
        self.window = window
        self._messages: List[Dict[str, str]] = []
        self._summaries: List[str] = []

    def add_message(self, role: str, content: str):
        self._messages.append({"role": role, "content": content})
        self._messages = self._messages[-self.window :]

    def add_summary(self, xml_summary: str):
        self._summaries.append(xml_summary)
        self._summaries = self._summaries[-self.window :]

    def context(self) -> str:
        msgs = "".join([wrap_document(m["content"], {"role": m["role"]}) for m in self._messages])
        sums = "".join(self._summaries)
        return f"<short_term_memory>{msgs}{sums}</short_term_memory>"


def _resolve_prompts_config_path() -> str:
    app_dir = os.path.dirname(os.path.dirname(__file__))  # app/
    project_root = os.path.dirname(app_dir)
    default_path = os.path.join(app_dir, "prompts", "prompts_config.yaml")
    path = getattr(settings, "prompts_config_path", default_path)
    if not os.path.isabs(path):
        # 统一以项目根目录为基准解析相对路径，避免出现 app/app 重复
        path = os.path.join(project_root, os.path.normpath(path))
    return path

def _normalize_log_type(log_type: Optional[Any]) -> Optional[str]:
    """规范化日志类型值，兼容枚举与字符串。"""
    if isinstance(log_type, LogType):
        return log_type.value
    if isinstance(log_type, Enum):
        return str(log_type.value).lower()
    if isinstance(log_type, str):
        return log_type.lower()
    return None

def _infer_log_type_from_hints(
    hints: Optional[Dict[str, Any]],
    explicit: Optional[Any] = None,
    current: Optional[str] = None,
) -> Optional[str]:
    """结合显式参数与hints推断日志类型，未匹配时回退当前值。"""
    candidates: List[Any] = [explicit]
    if isinstance(hints, dict):
        candidates.append(hints.get("log_type") or hints.get("logType"))
        filename = hints.get("filename") or hints.get("path")
        if isinstance(filename, str):
            name = filename.lower()
            if "oam" in name or "antenna" in name:
                candidates.append(LogType.OAM_ANTENNA)
            elif "stack" in name:
                candidates.append(LogType.STACK)
    for cand in candidates:
        normalized = _normalize_log_type(cand)
        if normalized:
            return normalized
    return current

def _load_prompts_config() -> Dict[str, Dict[str, Any]]:
    global _PROMPTS_CACHE
    if _PROMPTS_CACHE:
        return _PROMPTS_CACHE
    cfg_path = _resolve_prompts_config_path()
    try:
        with open(cfg_path, "r", encoding="utf-8") as f:
            if cfg_path.lower().endswith((".yaml", ".yml")):
                if yaml:
                    _PROMPTS_CACHE = yaml.safe_load(f) or {}
                else:
                    raise RuntimeError("YAML库未安装，无法解析prompts_config.yaml")
            else:
                _PROMPTS_CACHE = json.load(f)
    except Exception as e:
        # 在异常时记录日志，便于定位问题
        logger.warning("加载提示词配置失败，使用内置回退。路径=%s，错误=%s", cfg_path, e)
        # 内置回退模板，确保功能不受影响
        _PROMPTS_CACHE = {
            "log_types": {
                "default": {
                    "plan_prompt": {
                        "template": (
                            "你是一个日志分析Agent，需要制定执行计划。"
                            "输出使用<plan><step>...</step></plan>的XML结构。"
                            "根据用户需求选择：提取元数据、grep检索、全文检索、读取片段。\n\n"
                            "{memory_context}<用户需求>{user_query}</用户需求>"
                        ),
                        "description": "内置回退：生成执行计划的模板"
                    },
                    "summary_prompt": {
                        "template": (
                            "请对以下日志片段进行简要总结，突出ERROR/WARN及关键事件。\n\n"
                            "<片段>{compact_snippet}</片段>"
                        ),
                        "description": "内置回退：日志片段摘要模板"
                    },
                }
            },
            # 兼容旧结构
            "plan_prompt": {
                "template": (
                    "你是一个日志分析Agent，需要制定执行计划。"
                    "输出使用<plan><step>...</step></plan>的XML结构。"
                    "根据用户需求选择：提取元数据、grep检索、全文检索、读取片段。\n\n"
                    "{memory_context}<用户需求>{user_query}</用户需求>"
                ),
                "description": "内置回退：生成执行计划的模板"
            },
            "summary_prompt": {
                "template": (
                    "请对以下日志片段进行简要总结，突出ERROR/WARN及关键事件。\n\n"
                    "<片段>{compact_snippet}</片段>"
                ),
                "description": "内置回退：日志片段摘要模板"
            },
        }
    return _PROMPTS_CACHE

def _select_prompt_config(key: str, log_type: Optional[Any]) -> Dict[str, Any]:
    """根据日志类型从配置中选择提示词条目，带默认回退。"""
    config = _load_prompts_config()
    lt = _normalize_log_type(log_type)
    log_type_conf = config.get("log_types") if isinstance(config, dict) else None
    if isinstance(log_type_conf, dict):
        if lt and isinstance(log_type_conf.get(lt), dict):
            conf = log_type_conf[lt].get(key)
            if conf:
                return conf
        default_conf = log_type_conf.get("default")
        if isinstance(default_conf, dict) and default_conf.get(key):
            return default_conf.get(key, {})
    return config.get(key, {}) if isinstance(config, dict) else {}

def render_prompt(key: str, log_type: Optional[Any] = None, **kwargs: Any) -> str:
    conf = _select_prompt_config(key, log_type)
    template_str = conf.get("template", "")
    if not template_str:
        return ""
    cache_key = f"{key}:{_normalize_log_type(log_type) or 'default'}"
    if PromptTemplate:
        try:
            pt = _PROMPT_TEMPLATES_CACHE.get(cache_key)
            if not pt:
                input_vars = conf.get("variables") or list(kwargs.keys())
                pt = PromptTemplate(input_variables=input_vars, template=template_str)
                _PROMPT_TEMPLATES_CACHE[cache_key] = pt
            return pt.format(**kwargs)
        except Exception:
            return template_str.format(**kwargs)
    else:
        return template_str.format(**kwargs)

def compress_outputs(outputs: List[str], log_type: Optional[Any] = None) -> str:
    """Compression: extractive truncation + optional LLM summary."""
    n = min(3, len(outputs)) or 1
    compact = "".join(o[: settings.agent_max_snippet_bytes // n] for o in outputs[:n])
    llm = get_llm()
    try:
        prompt = render_prompt("summary_prompt", compact_snippet=compact, log_type=log_type)
        prompt_to_log = prompt[:600] + ("..." if len(prompt) > 600 else "")
        logger.info("\n\n--- START LLM PROMPT [summary] ---\n%s\n--- END LLM PROMPT [summary] ---\n", prompt_to_log)
        if hasattr(llm, "predict"):
            summary_xml = llm.predict(prompt)
            logger.info("\n\n--- (predict)START LLM OUTPUT [summary] ---\ncontent='%s'\n--- END LLM OUTPUT [summary] ---\n", summary_xml)
            return f"<context_summary>{summary_xml}</context_summary>"
        else:
            res = llm.invoke(prompt)
            # Extract content from LangChain response object
            content = res.content if hasattr(res, "content") else str(res)
            logger.info("\n\n--- START LLM OUTPUT [summary] ---\ncontent='%s'\n--- END LLM OUTPUT [summary] ---\n", content)
            # Normalize format: always wrap as <context_summary> so downstream logic can strip it from main content
            return f"<context_summary>{content}</context_summary>"
    except Exception:
        return wrap_document("摘要不可用（降级为提取片段）", {"type": "summary"})


class AgentState(TypedDict):
    query: str
    hints: Optional[Dict[str, Any]]
    plan_xml: str
    steps: List[str]
    idx: int
    outputs: List[str]
    done: bool


class LogAnalysisAgent:
    """Main Agent orchestrating planning and tool execution via LangGraph."""
    def __init__(self):
        self.llm = get_llm()
        logger.info("LogAnalysisAgent.__init__: llm=%s", type(self.llm).__name__)
        self._active_log_type: Optional[str] = None
        
        # 显示当前使用的模型信息
        if hasattr(self.llm, 'model_name'):
            logger.info("LogAnalysisAgent.__init__: current model=%s", self.llm.model_name)
        else:
            logger.info("LogAnalysisAgent.__init__: current model=%s", getattr(settings, "llm_model_name", "unknown"))
            
        self.memory = ShortTermMemory(window=settings.agent_short_term_window)
        self.search_backend = (
            ElasticSearchBackend(url=settings.elasticsearch_url)
            if settings.agent_search_backend == "elasticsearch"
            else RegexSearchBackend(root=settings.agent_root_dir)
        )
        logger.info("LogAnalysisAgent.__init__: backend=%s", type(self.search_backend).__name__)
        self._extracted_dirs: List[str] = []
        try:
            paths: List[str] = []
            logger.debug("Search indexing start: root=%s", settings.agent_root_dir)
            for d, _, files in os.walk(settings.agent_root_dir):
                for f in files:
                    paths.append(os.path.join(d, f))
                if len(paths) > 5000:
                    logger.warning("Indexing truncated at 5000 files to limit scope")
                    break
            self.search_backend.index(paths)
            logger.info("Search indexing done: files=%d", len(paths))
        except Exception as e:
            logger.warning("Search indexing failed: %s", e)

        # Build LangGraph (compact ReAct-style loop)
        if StateGraph:
            graph = StateGraph(AgentState)
            graph.add_node("plan", self._plan_node)
            graph.add_node("act", self._act_node)
            graph.add_edge("plan", "act")
            graph.add_conditional_edges("act", self._should_continue)
            graph.set_entry_point("plan")
            self._app = graph.compile()
        else:
            self._app = None  # Fallback: run() will degrade to sequential execution

    def _build_langchain_tools(self, hints: Optional[Dict[str, Any]]) -> List[Any]:
        if LCStructuredTool is None:
            logger.debug("_build_langchain_tools: LCStructuredTool missing, return empty")
            return []
        tools: List[Any] = []
        hints = hints or {}

        def _metadata_extract(archive_path: Optional[str] = None) -> str:
            path = archive_path or hints.get("archive_path") or settings.agent_root_dir
            try:
                return get_log_package_metadata_xml(path)
            except Exception as e:
                return wrap_document(f"metadata_extract error: {e}", {"tool": "metadata_extract"})

        def _grep_search(path: str, pattern: str, context: int = 2) -> str:
            try:
                # 如果没有指定路径，使用hints中的主要文件
                if not path and hints.get("primary_file"):
                    path = hints["primary_file"]
                elif not path and hints.get("path"):
                    path = hints["path"]
                
                result = grep_file_xml(path, pattern, context=context)
                
                # 如果在主要文件中没有找到结果，且hints中有其他相关文件，提供建议
                if "No matches found" in result and hints.get("relevant_files"):
                    relevant_files = hints["relevant_files"]
                    if len(relevant_files) > 1:
                        other_files = [f for f in relevant_files if f != path][:3]  # 最多建议3个其他文件
                        if other_files:
                            suggestion = f"\n\n建议尝试搜索其他相关文件:\n" + "\n".join([f"- {os.path.basename(f)}" for f in other_files])
                            result = result.replace("</document>", f"{suggestion}</document>")
                
                # 如果hints中有建议的搜索模式，添加到结果中
                if "No matches found" in result and hints.get("suggested_patterns"):
                    patterns = hints["suggested_patterns"][:5]  # 最多显示5个建议模式
                    if patterns:
                        pattern_suggestion = f"\n\n建议尝试的搜索模式:\n" + "\n".join([f"- {p}" for p in patterns])
                        result = result.replace("</document>", f"{pattern_suggestion}</document>")
                
                return result
            except Exception as e:
                return wrap_document(f"grep_search error: {e}", {"tool": "grep_search"})

        def _read_snippet(path: str, head_lines: int = 50, tail_lines: int = 0) -> str:
            try:
                # 如果没有指定路径，使用hints中的主要文件
                if not path and hints.get("primary_file"):
                    path = hints["primary_file"]
                elif not path and hints.get("path"):
                    path = hints["path"]
                
                if head_lines and head_lines > 0:
                    result = read_head_xml(path, n_lines=head_lines)
                elif tail_lines and tail_lines > 0:
                    result = read_tail_xml(path, n_lines=tail_lines)
                else:
                    result = read_head_xml(path, n_lines=50)
                
                # 如果hints中有其他相关文件，在结果中提供建议
                if hints.get("relevant_files") and len(hints["relevant_files"]) > 1:
                    other_files = [f for f in hints["relevant_files"] if f != path][:3]
                    if other_files:
                        suggestion = f"\n\n其他相关文件:\n" + "\n".join([f"- {os.path.basename(f)}" for f in other_files])
                        result = result.replace("</document>", f"{suggestion}</document>")
                
                return result
            except Exception as e:
                return wrap_document(f"read_snippet error: {e}", {"tool": "read_snippet"})

        def _list_tree(root: Optional[str] = None, max_depth: int = 2) -> str:
            try:
                return list_tree_xml(root or settings.agent_root_dir, max_depth=max_depth)
            except Exception as e:
                return wrap_document(f"list_tree error: {e}", {"tool": "list_tree"})

        def _nested_extract(nested_path: Optional[str] = None, extracted_root: Optional[str] = None) -> str:
            r = extracted_root or settings.agent_root_dir
            try:
                if nested_path:
                    dest, xml = extract_nested_archive_xml(nested_path, parent_root=r)
                    try:
                        self._extracted_dirs.append(dest)
                    except Exception:
                        pass
                    return xml
                return nested_archives_xml(r)
            except Exception as e:
                return wrap_document(f"nested_extract error: {e}", {"tool": "nested_extract"})

        def _global_search(query: str, k: int = 10) -> str:
            try:
                return search_to_xml(self.search_backend, query=query, k=k)
            except Exception as e:
                return wrap_document(f"global_search error: {e}", {"tool": "global_search"})

        tools.append(LCStructuredTool.from_function(_metadata_extract, name="metadata_extract", description="提取日志包元数据（tar.gz/zip）"))
        tools.append(LCStructuredTool.from_function(_grep_search, name="grep_search", description="在文本文件中执行模式搜索 (grep)"))
        tools.append(LCStructuredTool.from_function(_read_snippet, name="read_snippet", description="读取文件片段 (head/tail)"))
        tools.append(LCStructuredTool.from_function(_nested_extract, name="nested_extract", description="解压或扫描嵌套归档"))
        tools.append(LCStructuredTool.from_function(_list_tree, name="list_tree", description="列出目录树结构"))
        tools.append(LCStructuredTool.from_function(_global_search, name="global_search", description="使用搜索后转为XML"))
        return tools

    def _plan_node(self, state: AgentState) -> AgentState:
        """Graph node that generates plan XML and step list."""
        query = state.get("query", "")
        plan_xml = self.plan(query, hints=state.get("hints"))
        steps = re.findall(r"<step[^>]*>(.*?)</step>", plan_xml, flags=re.DOTALL)
        return {"plan_xml": plan_xml, "steps": steps}

    def _first_text_file(self) -> Optional[str]:
        for d, _, files in os.walk(settings.agent_root_dir):
            for f in files:
                if f.lower().endswith(('.log', '.txt')):
                    p = os.path.join(d, f)
                    logger.debug('First text file found: %s', p)
                    return p
        logger.debug('First text file not found under root=%s', settings.agent_root_dir)
        return None

    def _select_relevant_files(self, root: str, query: str, max_files: int = 3) -> List[str]:
        """根据查询内容智能选择最相关的日志文件，包括嵌套压缩包中的文件"""
        files = []
        nested_files = []
        
        # 扫描已解压的日志文件
        for d, _, filenames in os.walk(root):
            for f in filenames:
                if f.lower().endswith(('.log', '.txt')):
                    files.append(os.path.join(d, f))
        
        # 检测并处理嵌套压缩包
        try:
            from app.tools.archive_tool import find_nested_archives, safe_extract_archive
            nested_archives = find_nested_archives(root)
            
            for archive_info in nested_archives:
                archive_path = archive_info["path"]
                try:
                    # 解压嵌套压缩包
                    nested_extract_dir = safe_extract_archive(archive_path)
                    logger.info('Extracted nested archive: %s -> %s', archive_path, nested_extract_dir)
                    
                    # 扫描嵌套压缩包中的日志文件
                    for d, _, filenames in os.walk(nested_extract_dir):
                        for f in filenames:
                            if f.lower().endswith(('.log', '.txt')):
                                nested_file_path = os.path.join(d, f)
                                nested_files.append(nested_file_path)
                                logger.debug('Found nested log file: %s', nested_file_path)
                                
                except Exception as e:
                    logger.warning('Failed to extract nested archive %s: %s', archive_path, e)
                    continue
                    
        except ImportError as e:
            logger.debug('Archive tools not available for nested extraction: %s', e)
        except Exception as e:
            logger.warning('Error processing nested archives: %s', e)
        
        # 合并所有文件
        all_files = files + nested_files
        
        if not all_files:
            logger.debug('No log files found under root=%s (including nested archives)', root)
            return []
        
        # 根据查询关键词和文件名相关性排序
        scored_files = []
        query_lower = query.lower()
        
        for file_path in all_files:
            filename = os.path.basename(file_path).lower()
            score = 0
            
            # 基于文件名的相关性评分
            if any(keyword in query_lower for keyword in ['error', '错误', '失败', 'fail', 'exception']):
                if any(pattern in filename for pattern in ['err', 'error', 'exception', 'fail']):
                    score += 10
            
            if any(keyword in query_lower for keyword in ['antenna', '天线', 'ant']):
                if any(pattern in filename for pattern in ['antenna', 'ant']):
                    score += 10
            
            if any(keyword in query_lower for keyword in ['operation', '操作', 'oper']):
                if any(pattern in filename for pattern in ['oper', 'operation', 'op']):
                    score += 5
            
            if any(keyword in query_lower for keyword in ['alarm', '告警', 'alert']):
                if any(pattern in filename for pattern in ['alarm', 'alert', 'warn']):
                    score += 8
            
            if any(keyword in query_lower for keyword in ['system', '系统', 'sys']):
                if any(pattern in filename for pattern in ['system', 'sys']):
                    score += 3
            
            # 通用日志文件优先级较低
            if any(pattern in filename for pattern in ['main', 'general', 'common']):
                score += 1
            
            # 特殊处理：Irun_oam.log 文件在OAM日志分析中很重要
            if 'irun_oam.log' in filename:
                score += 15
                
            # 嵌套文件稍微降低优先级（因为可能需要额外处理）
            if file_path in nested_files:
                score = max(0, score - 1)
                
            scored_files.append((score, file_path))
        
        # 按分数排序，返回最相关的文件
        scored_files.sort(key=lambda x: x[0], reverse=True)
        selected_files = [f[1] for f in scored_files[:max_files]]
        
        logger.info('Selected %d relevant files from %d total files (%d direct, %d nested) for query: %s', 
                   len(selected_files), len(all_files), len(files), len(nested_files), query[:50])
        for i, (score, file_path) in enumerate(scored_files[:max_files]):
            is_nested = file_path in nested_files
            logger.debug('File %d: score=%d, nested=%s, path=%s', i+1, score, is_nested, file_path)
            
        return selected_files

    def _generate_enhanced_hints(self, extracted_dir: str, query: str, archive_path: str) -> Dict[str, Any]:
        """生成增强的hints信息"""
        # 获取智能选择的相关文件
        relevant_files = self._select_relevant_files(extracted_dir, query, max_files=5)
        
        # 统计文件信息
        all_files = []
        log_files = []
        directories = set()
        
        for d, _, filenames in os.walk(extracted_dir):
            rel_dir = os.path.relpath(d, extracted_dir)
            if rel_dir != '.':
                directories.add(rel_dir)
            
            for f in filenames:
                file_path = os.path.join(d, f)
                all_files.append(file_path)
                if f.lower().endswith(('.log', '.txt')):
                    log_files.append(file_path)
        
        # 生成建议的搜索模式
        suggested_patterns = []
        query_lower = query.lower()
        
        if any(keyword in query_lower for keyword in ['error', '错误', '失败', 'fail']):
            suggested_patterns.extend(['error', 'fail', 'exception', '错误', '失败'])
        if any(keyword in query_lower for keyword in ['antenna', '天线']):
            suggested_patterns.extend(['antenna', 'ant', '天线'])
        if any(keyword in query_lower for keyword in ['operation', '操作']):
            suggested_patterns.extend(['operation', 'oper', '操作'])
        if any(keyword in query_lower for keyword in ['alarm', '告警']):
            suggested_patterns.extend(['alarm', 'alert', 'warn', '告警'])
        
        # 去重并限制数量
        suggested_patterns = list(dict.fromkeys(suggested_patterns))[:8]
        
        enhanced_hints = {
            "archive_path": archive_path,
            "extracted_root": extracted_dir,
            "relevant_files": relevant_files,
            "primary_file": relevant_files[0] if relevant_files else None,
            "suggested_patterns": suggested_patterns,
            "file_structure": {
                "total_files": len(all_files),
                "log_files": len(log_files),
                "directories": sorted(list(directories))[:10]  # 限制目录数量
            },
            "query_context": {
                "original_query": query,
                "detected_keywords": self._extract_keywords_from_query(query)
            }
        }
        
        # 保持向后兼容性，设置path为主要文件
        if relevant_files:
            enhanced_hints["path"] = relevant_files[0]
        
        logger.info("Generated enhanced hints: %d relevant files, %d total files, %d directories", 
                   len(relevant_files), len(all_files), len(directories))
        
        return enhanced_hints

    def _extract_keywords_from_query(self, query: str) -> List[str]:
        """从查询中提取关键词"""
        keywords = []
        query_lower = query.lower()
        
        # 定义关键词映射
        keyword_patterns = {
            'error_related': ['error', '错误', '失败', 'fail', 'exception', 'fault'],
            'antenna_related': ['antenna', '天线', 'ant'],
            'operation_related': ['operation', '操作', 'oper', 'process'],
            'alarm_related': ['alarm', '告警', 'alert', 'warn', 'warning'],
            'system_related': ['system', '系统', 'sys'],
            'network_related': ['network', '网络', 'net', 'connection'],
            'performance_related': ['performance', '性能', 'perf', 'slow', 'timeout']
        }
        
        for category, patterns in keyword_patterns.items():
            if any(pattern in query_lower for pattern in patterns):
                keywords.append(category)
        
        return keywords

    def _update_hints_after_tool_execution(self, hints: Dict[str, Any], tool_name: str, tool_result: str, query: str) -> Dict[str, Any]:
        """根据工具执行结果动态更新hints"""
        updated_hints = hints.copy()
        
        # 如果grep_search没有找到结果，建议其他文件或搜索模式
        if tool_name == "grep_search" and "No matches found" in tool_result:
            # 如果有其他相关文件，更新建议
            if hints.get("relevant_files") and len(hints["relevant_files"]) > 1:
                current_file = hints.get("path") or hints.get("primary_file")
                other_files = [f for f in hints["relevant_files"] if f != current_file]
                if other_files:
                    updated_hints["alternative_files"] = other_files[:3]
                    updated_hints["suggestion"] = f"在当前文件中未找到匹配项，建议尝试其他文件: {[os.path.basename(f) for f in other_files[:3]]}"
            
            # 如果有建议的搜索模式，提供替代模式
            if hints.get("suggested_patterns"):
                current_patterns = hints["suggested_patterns"]
                updated_hints["alternative_patterns"] = current_patterns
                updated_hints["pattern_suggestion"] = f"建议尝试其他搜索模式: {current_patterns[:5]}"
        
        # 如果read_snippet成功，可以分析内容并提供进一步的建议
        elif tool_name == "read_snippet" and "error" not in tool_result.lower():
            # 分析文件内容，提取可能的搜索关键词
            content_keywords = self._extract_content_keywords(tool_result)
            if content_keywords:
                updated_hints["content_based_patterns"] = content_keywords
                updated_hints["content_suggestion"] = f"基于文件内容建议的搜索关键词: {content_keywords[:5]}"
        
        # 如果metadata_extract成功，可以更新文件结构信息
        elif tool_name == "metadata_extract" and "error" not in tool_result.lower():
            # 从元数据中提取有用信息
            if "files:" in tool_result.lower():
                updated_hints["metadata_available"] = True
                updated_hints["metadata_suggestion"] = "已获取文件元数据，可以使用list_tree查看详细结构"
        
        logger.debug("Updated hints after %s execution: added %d new keys", 
                    tool_name, len(updated_hints) - len(hints))
        
        return updated_hints

    def _extract_content_keywords(self, content: str) -> List[str]:
        """从文件内容中提取可能的搜索关键词"""
        keywords = []
        content_lower = content.lower()
        
        # 常见的日志级别
        log_levels = ['error', 'warn', 'info', 'debug', 'fatal', 'trace']
        for level in log_levels:
            if level in content_lower:
                keywords.append(level.upper())
        
        # 常见的系统组件
        components = ['database', 'network', 'antenna', 'system', 'service', 'connection']
        for comp in components:
            if comp in content_lower:
                keywords.append(comp)
        
        # 常见的操作
        operations = ['start', 'stop', 'restart', 'init', 'config', 'auth', 'login']
        for op in operations:
            if op in content_lower:
                keywords.append(op)
        
        # 去重并限制数量
        return list(dict.fromkeys(keywords))[:10]

    def _first_text_file_under(self, root: str) -> Optional[str]:
        for d, _, files in os.walk(root):
            for f in files:
                if f.lower().endswith(('.log', '.txt')):
                    p = os.path.join(d, f)
                    logger.debug('First text file found under %s: %s', root, p)
                    return p
        logger.debug('First text file not found under root=%s', root)
        return None

    # Backward-compatible plan() API
    def plan(self, query: str, hints: Optional[Dict[str, Any]] = None, log_type: Optional[Any] = None) -> str:
        logger.info("Plan: start query='%s'", query[:200])
        self._active_log_type = _infer_log_type_from_hints(hints, explicit=log_type, current=self._active_log_type)
        logger.debug("Plan: using log_type=%s", self._active_log_type or "default")
        prompt = render_prompt(
            "plan_prompt",
            memory_context=self.memory.context(),
            user_query=query,
            log_type=self._active_log_type,
        )
        logger.debug("Plan: prompt chars=%d", len(prompt))
        logger.info("\n\n--- START LLM PROMPT [plan] ---\n%s\n--- END LLM PROMPT [plan] ---\n", prompt)
        plan_xml: str = ""
        try:
            logger.debug("Plan: llm=%s", type(self.llm).__name__)
            if hasattr(self.llm, "predict"):
                plan_xml = self.llm.predict(prompt)
            else:
                response = self.llm.invoke(prompt)
                # 正确提取LangChain消息对象的content字段
                if hasattr(response, "content"):
                    plan_xml = response.content
                else:
                    plan_xml = str(response)
        except Exception as e:
            logger.warning("Plan LLM failed, using fallback: %s", e)
            plan_xml = wrap_plan(["读取日志片段", "在相关文件中执行grep搜索"])
        logger.info("\n\n--- START LLM OUTPUT [plan] ---\ncontent='%s'\n--- END LLM OUTPUT [plan] ---\n", plan_xml)
        # Normalize: ensure XML structure
        steps = re.findall(r"<step[^>]*>(.*?)</step>", plan_xml, flags=re.DOTALL)
        if not steps:
            logger.debug("Plan: no <step> found, using fallback plan")
            plan_xml = wrap_plan(["读取日志片段", "在相关文件中执行grep搜索"])
        self.memory.add_message("user", query)
        self.memory.add_message("system", plan_xml)
        logger.info("Plan: steps=%d", len(re.findall(r"<step[^>]*>(.*?)</step>", plan_xml, flags=re.DOTALL)))
        return plan_xml

    # Tool routing (XML-producing, refactored)
    def _execute_step(self, step: str, query: str, hints: Optional[Dict[str, Any]] = None) -> str:
        logger.info("Execute step (refactored): %s", step)
        hints = hints or {}

        # Attempt function calling via llm.bind_tools
        try:
            tools_bound = self._build_langchain_tools(hints)
            if tools_bound and hasattr(self.llm, "bind_tools"):
                tool_map = {t.name: t for t in tools_bound}
                bound_llm = self.llm.bind_tools(tools_bound)
                # 增加日志：记录绑定工具的名称
                try:
                    logger.info("bind_tools: tools=%s", [getattr(t, "name", str(t)) for t in tools_bound])
                except Exception:
                    logger.info("bind_tools: tools bound (names unavailable)")
                # 构建增强的hints说明
                hints_explanation = ""
                if hints.get("relevant_files"):
                    hints_explanation += f"\n相关文件（按相关性排序）: {[os.path.basename(f) for f in hints['relevant_files'][:3]]}"
                if hints.get("primary_file"):
                    hints_explanation += f"\n主要文件: {os.path.basename(hints['primary_file'])}"
                if hints.get("suggested_patterns"):
                    hints_explanation += f"\n建议搜索模式: {hints['suggested_patterns'][:5]}"
                if hints.get("file_structure"):
                    fs = hints["file_structure"]
                    hints_explanation += f"\n文件结构: 共{fs.get('total_files', 0)}个文件，{fs.get('log_files', 0)}个日志文件"
                
                fc_prompt = (
                    "你是一个日志分析Agent的工具路由器。\n"
                    "请基于提供的step、query、hints选择并调用一个工具，使用函数调用（function calling）。\n"
                    "不要输出普通文本，必须返回一个工具调用。\n"
                    f"<step>{step}</step>\n<query>{query}</query>\n"
                    f"<hints>{json.dumps(hints, ensure_ascii=False)}</hints>\n"
                    f"<hints_summary>{hints_explanation}</hints_summary>\n"
                    "\n提示：\n"
                    "- 如果需要搜索文件内容，优先使用grep_search工具\n"
                    "- 如果hints中有suggested_patterns，可以考虑使用这些模式进行搜索\n"
                    "- 如果hints中有relevant_files，优先处理primary_file或第一个相关文件\n"
                    "- 如果需要查看文件内容概览，使用read_snippet工具\n"
                )
                # 增加日志：记录发送给绑定LLM的提示词
                logger.info("\n\n--- START LLM PROMPT [tools_fc] ---\n%s\n--- END LLM PROMPT [tools_fc] ---\n", fc_prompt)
                resp = bound_llm.invoke(fc_prompt)
                tool_calls = getattr(resp, "tool_calls", None)
                if not tool_calls and hasattr(resp, "additional_kwargs"):
                    tool_calls = resp.additional_kwargs.get("tool_calls")
                # 增加日志：记录返回的工具调用
                try:
                    logger.info("bind_tools: tool_calls=%s", tool_calls)
                except Exception:
                    pass
                if tool_calls:
                    tc = tool_calls[0]
                    tname = tc.get("name") or tc.get("tool")
                    targs = tc.get("args") or {}
                    if isinstance(targs, list) and len(targs) == 1 and isinstance(targs[0], dict):
                        targs = targs[0]
                    if tname in tool_map:
                        logger.info("bind_tools selected '%s' with args=%s", tname, targs)
                        try:
                            result = tool_map[tname].invoke(targs)
                            # 动态更新hints（仅记录日志，不影响当前执行）
                            try:
                                updated_hints = self._update_hints_after_tool_execution(hints, tname, result, query)
                                if len(updated_hints) > len(hints):
                                    logger.info("Dynamic hints updated after %s: %d new keys added", 
                                              tname, len(updated_hints) - len(hints))
                            except Exception as e:
                                logger.debug("Failed to update hints dynamically: %s", e)
                            return result
                        except Exception as e:
                            logger.warning("Tool '%s' execution via bind_tools failed: %s", tname, e)
        except Exception as e:
            logger.warning("bind_tools route failed, fallback to manual selection: %s", e)

        tool_specs: Dict[str, Dict[str, Any]] = {
            "metadata_extract": {
                "desc": "提取日志包元数据（tar.gz/zip）",
                "schema": {"archive_path": "str"},
            },
            "grep_search": {
                "desc": "在文本文件中执行模式搜索 (grep)",
                "schema": {"path": "str?", "pattern": "str", "context": "int?"},
            },
            "read_snippet": {
                "desc": "读取文件片段 (head/tail)",
                "schema": {"path": "str?", "head_lines": "int?", "tail_lines": "int?"},
            },
            "nested_extract": {
                "desc": "解压或扫描嵌套归档",
                "schema": {"nested_path": "str?", "extracted_root": "str?"},
            },
            "list_tree": {
                "desc": "列出目录树结构",
                "schema": {"root": "str?", "max_depth": "int?"},
            },
            "global_search": {
                "desc": "使用搜索后转为XML",
                "schema": {"query": "str", "k": "int?"},
            },
        }

        def _extract_json_candidate(s: str) -> Optional[Dict[str, Any]]:
            try:
                s = s.strip()
                if s.startswith("{") and s.endswith("}"):
                    return json.loads(s)
                start = s.find("{")
                end = s.rfind("}")
                if start != -1 and end != -1 and end > start:
                    return json.loads(s[start : end + 1])
            except Exception:
                return None
            return None

        def _fallback_select(step_text: str) -> Dict[str, Any]:
            st = step_text.lower()
            if ("元数据" in st) or ("metadata" in st):
                return {"tool": "metadata_extract", "args": {}}
            if ("grep" in st) or ("查找" in st) or ("搜索" in st):
                return {"tool": "grep_search", "args": {}}
            if ("读取" in st) or ("片段" in st) or ("head" in st) or ("tail" in st):
                return {"tool": "read_snippet", "args": {}}
            if ("解压" in st) or ("extract" in st) or ("decompress" in st):
                return {"tool": "nested_extract", "args": {}}
            if ("树" in st) or ("tree" in st) or ("结构" in st) or ("list" in st):
                return {"tool": "list_tree", "args": {}}
            return {"tool": "global_search", "args": {}}

        selection: Dict[str, Any] = {}
        try:
            tools_text = "\n".join([f"- {name}: {spec['desc']} schema={spec['schema']}" for name, spec in tool_specs.items()])
            prompt = (
                "你是一个日志分析Agent的工具路由器。\n"
                "基于提供的step、query、hints，从下列工具中选择最合适的一个，并给出JSON参数：\n"
                f"{tools_text}\n\n"
                "返回严格的JSON对象，不要包含解释或多余文字。格式：{\"tool\": \"<name>\", \"args\": { ... }}\n"
                f"<step>{step}</step>\n<query>{query}</query>\n<hints>{json.dumps(hints, ensure_ascii=False)}</hints>\n"
            )
            # 记录手动选择提示词
            logger.info("\n\n--- START LLM PROMPT [tool_select] ---\n%s\n--- END LLM PROMPT [tool_select] ---\n", prompt)
            if hasattr(self.llm, "predict"):
                raw = self.llm.predict(prompt)
            else:
                response = self.llm.invoke(prompt)
                # 正确提取LangChain消息对象的content字段
                if hasattr(response, "content"):
                    raw = response.content
                else:
                    raw = str(response)
            # 记录手动选择返回内容
            logger.info("\n\n--- START LLM OUTPUT [tool_select] ---\ncontent='%s'\n--- END LLM OUTPUT [tool_select] ---\n", raw)
            cand = _extract_json_candidate(raw)
            if not cand:
                raise ValueError("LLM未返回可解析的JSON")
            selection = cand
        except Exception as e:
            logger.warning("Tool selection via LLM failed, using fallback: %s", e)
            selection = _fallback_select(step)

        name = str(selection.get("tool", "")).strip()
        args: Dict[str, Any] = selection.get("args", {}) if isinstance(selection.get("args", {}), dict) else {}
        if name not in tool_specs:
            logger.warning("Unknown tool '%s', fallback to global_search", name)
            name = "global_search"

        try:
            if name == "metadata_extract":
                hint_arch = hints.get("archive_path")
                hint_path = hints.get("path")
                ap = args.get("archive_path")
                path = ap or hint_arch or (
                    hint_path if isinstance(hint_path, str) and hint_path.lower().endswith((".tar.gz", ".tgz", ".zip")) else None
                ) or os.path.join(settings.agent_root_dir, "logs.tar.gz")
                logger.info("ToolCall metadata_extract: path=%s", path)
                return get_log_package_metadata_xml(path)

            if name == "grep_search":
                pattern = args.get("pattern") or hints.get("pattern") or query
                path = args.get("path") or hints.get("path") or self._first_text_file()
                context = int(args.get("context") or 2)
                logger.info(
                    "ToolCall grep_search: path=%s pattern=%s context=%d max_matches=%s max_bytes=%s",
                    path,
                    pattern,
                    context,
                    getattr(settings, "agent_max_matches", None),
                    getattr(settings, "agent_max_snippet_bytes", None),
                )
                if not path:
                    return wrap_document("未找到可搜索的文本文件", {"step": step})
                return grep_file_xml(path, pattern, context=context)

            if name == "read_snippet":
                path = args.get("path") or hints.get("path") or self._first_text_file()
                head_n = int(args.get("head_lines") or 50)
                tail_n = int(args.get("tail_lines") or 50)
                logger.info("ToolCall read_snippet: path=%s head_lines=%d tail_lines=%d", path, head_n, tail_n)
                if not path:
                    return wrap_document("未找到可读取的文本文件", {"step": step})
                head = read_head_xml(path, n_lines=head_n)
                tail = read_tail_xml(path, n_lines=tail_n)
                return f"<reads>{head}{tail}</reads>"

            if name == "nested_extract":
                nested_path = args.get("nested_path") or hints.get("nested_path")
                root = args.get("extracted_root") or hints.get("extracted_root") or settings.agent_root_dir
                logger.info("ToolCall nested_extract: nested_path=%s root=%s", nested_path, root)
                if nested_path:
                    dest, xml = extract_nested_archive_xml(nested_path, parent_root=root)
                    try:
                        self._extracted_dirs.append(dest)
                    except Exception:
                        pass
                    logger.info("ToolCall nested_extract: extracted_dir=%s", dest)
                    return xml
                else:
                    return nested_archives_xml(root)

            if name == "list_tree":
                root = args.get("root") or hints.get("extracted_root") or settings.agent_root_dir
                max_depth = int(args.get("max_depth") or 2)
                logger.info("ToolCall list_tree: root=%s max_depth=%d", root, max_depth)
                return list_tree_xml(root, max_depth=max_depth)

            if name == "global_search":
                k = int(args.get("k") or 10)
                logger.info("ToolCall global_search: backend=%s query=%s k=%d", type(self.search_backend).__name__, query, k)
                return search_to_xml(self.search_backend, query=query, k=k)

            logger.warning("Unhandled tool '%s', fallback to global_search", name)
            return search_to_xml(self.search_backend, query=query, k=10)
        except Exception as e:
            logger.warning("Tool '%s' execution failed: %s", name, e)
            label = {
                "metadata_extract": "元数据提取失败",
                "grep_search": "grep失败",
                "read_snippet": "读取失败",
                "nested_extract": "解压/扫描嵌套归档失败",
                "list_tree": "树结构生成失败",
                "global_search": "搜索失败",
            }.get(name, "工具执行失败")
            return wrap_document(f"{label}: {e}", {"step": step})

    # Graph node: act
    def _act_node(self, state: AgentState) -> AgentState:
        steps = state["steps"]
        idx = state.get("idx", 0)
        logger.info("Act: idx=%d/%d", idx, len(steps))
        if idx >= len(steps):
            logger.debug("Act: completed all steps")
            return {"done": True}
        step = steps[idx]
        out = self._execute_step(step, state["query"], hints=state.get("hints"))
        logger.debug("Act: output chars=%d", len(out))
        self.memory.add_summary(out)
        # Generate and print per-act LLM thought
        try:
            step_thought = compress_outputs([out], log_type=self._active_log_type)
            logger.info("\n\n--- START LLM THOUGHT [after_act] ---\n%s\n--- END LLM THOUGHT [after_act] ---\n", step_thought)
        except Exception as e:
            logger.warning("Act: step thought generation failed: %s", e)
        outputs = state.get("outputs", []) + [out]
        return {"outputs": outputs, "idx": idx + 1}

    # Graph edge condition
    def _should_continue(self, state: AgentState):
        idx = state.get("idx", 0)
        steps = state.get("steps", [])
        decision = "act" if idx < len(steps) else "end"
        logger.debug("Continue? idx=%d steps=%d decision=%s", idx, len(steps), decision)
        if idx < len(steps):
            return "act"
        return END

    def run(self, query: str, hints: Optional[Dict[str, Any]] = None) -> str:
        """Run the agent end-to-end using LangGraph when available; fallback sequential otherwise."""
        logger.info("Run: start query='%s'", query)
        hints_local: Dict[str, Any] = dict(hints or {})
        logger.debug("Run: hints=%s", hints_local)
        prev_log_type = self._active_log_type
        self._active_log_type = _infer_log_type_from_hints(hints_local, current=self._active_log_type)
        pre_outputs: List[str] = []
        final_doc: str = ""
        try:
            # 自动解压流程：如果提供了归档路径，则先解压并输出树结构
            archive_path = hints_local.get("archive_path") or (hints_local.get("path") if isinstance(hints_local.get("path"), str) and hints_local.get("path").lower().endswith((".tar.gz", ".tgz", ".zip")) else None)
            if archive_path:
                logger.info("Run: auto-extract archive=%s", archive_path)
                try:
                    extracted_dir, ex_xml = auto_extract_archive_xml(archive_path)
                    logger.info("Run: auto-extract ok extracted_dir=%s", extracted_dir)
                    pre_outputs.append(ex_xml)
                    self.memory.add_summary(ex_xml)
                    
                    # 生成增强的hints
                    enhanced_hints = self._generate_enhanced_hints(extracted_dir, query, archive_path)
                    hints_local.update(enhanced_hints)
                    
                    # 记录解压目录以便完成后清理
                    try:
                        self._extracted_dirs.append(extracted_dir)
                    except Exception:
                        pass
                except Exception as e:
                    logger.warning("Run: auto-extract failed: %s", e)
                    pre_outputs.append(wrap_document(f"自动解压失败: {e}", {"type": "extraction_error"}))
            if self._app:
                logger.debug("Run: using LangGraph pipeline")
                final_state: AgentState = self._app.invoke({
                    "query": query,
                    "hints": hints_local,
                    "plan_xml": "",
                    "steps": [],
                    "idx": 0,
                    "outputs": pre_outputs,
                    "done": False,
                })
                outputs = final_state.get("outputs", [])
                logger.info("Run: outputs via graph=%d", len(outputs))
            else:
                logger.debug("Run: sequential fallback")
                plan_xml = self.plan(query, hints=hints_local)
                steps = re.findall(r"<step[^>]*>(.*?)</step>", plan_xml, flags=re.DOTALL)
                logger.info("Run: executing %d steps sequentially", len(steps))
                outputs: List[str] = pre_outputs[:]
                for step in steps:
                    logger.debug("Run: executing step '%s'", step)
                    out = self._execute_step(step, query, hints=hints_local)
                    outputs.append(out)
                    self.memory.add_summary(out)
            summary = compress_outputs(outputs, log_type=self._active_log_type)
            logger.debug("Run: summary chars=%d", len(summary))
            final_doc = wrap_document("".join(outputs) + summary, {"source": "log_agent"})
            logger.info("Run: final doc chars=%d", len(final_doc))
        finally:
            try:
                self._cleanup_extracted_dirs()
            except Exception as e:
                logger.warning("Run: cleanup extracted dirs failed: %s", e)
            self._active_log_type = prev_log_type
        return final_doc

    def _cleanup_extracted_dirs(self) -> None:
        base = os.path.abspath(os.path.join(settings.agent_root_dir, "_extracted"))
        for d in getattr(self, "_extracted_dirs", []):
            try:
                absd = os.path.abspath(d)
                if os.path.commonpath([absd, base]) != base:
                    logger.warning("Cleanup skipped for non-extracted path: %s", absd)
                    continue
                if os.path.isdir(absd):
                    logger.info("Cleanup: removing extracted dir: %s", absd)
                    shutil.rmtree(absd, ignore_errors=True)
            except Exception as e:
                logger.warning("Cleanup error for %s: %s", d, e)
        self._extracted_dirs = []

    def run_structured(self, query: str, hints: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Run the agent and return structured analysis results for frontend display."""
        import time
        import uuid
        from datetime import datetime
        
        start_time = time.time()
        analysis_id = str(uuid.uuid4())
        
        logger.info("RunStructured: start query='%s' id=%s", query, analysis_id)
        hints_local: Dict[str, Any] = dict(hints or {})
        
        # 初始化结果结构
        result = {
            "id": analysis_id,
            "query": query,
            "status": "processing",
            "timestamp": datetime.now().isoformat(),
            "plan": {
                "content": "",
                "steps": [],
                "total_steps": 0,
                "completed_steps": 0
            },
            "acts": [],
            "final_result": {
                "summary": "",
                "content": "",
                "confidence": 0.0,
                "recommendations": []
            },
            "metadata": {
                "execution_time": 0.0,
                "model_used": "unknown",
                "tokens_used": 0
            }
        }
        
        try:
            # 执行分析流程
            pre_outputs: List[str] = []
            prev_log_type = self._active_log_type
            self._active_log_type = _infer_log_type_from_hints(hints_local, current=self._active_log_type)
            
            # 自动解压流程
            archive_path = hints_local.get("archive_path") or (hints_local.get("path") if isinstance(hints_local.get("path"), str) and hints_local.get("path").lower().endswith((".tar.gz", ".tgz", ".zip")) else None)
            if archive_path:
                logger.info("RunStructured: auto-extract archive=%s", archive_path)
                try:
                    extracted_dir, ex_xml = auto_extract_archive_xml(archive_path)
                    logger.info("RunStructured: auto-extract ok extracted_dir=%s", extracted_dir)
                    pre_outputs.append(ex_xml)
                    self.memory.add_summary(ex_xml)
                    
                    enhanced_hints = self._generate_enhanced_hints(extracted_dir, query, archive_path)
                    hints_local.update(enhanced_hints)
                    
                    try:
                        self._extracted_dirs.append(extracted_dir)
                    except Exception:
                        pass
                except Exception as e:
                    logger.warning("RunStructured: auto-extract failed: %s", e)
                    pre_outputs.append(wrap_document(f"自动解压失败: {e}", {"type": "extraction_error"}))
            
            # 生成计划
            plan_xml = self.plan(query, hints=hints_local)
            result["plan"]["content"] = self._format_plan_markdown(plan_xml)
            
            # 解析步骤
            steps = re.findall(r"<step[^>]*>(.*?)</step>", plan_xml, flags=re.DOTALL)
            result["plan"]["total_steps"] = len(steps)
            result["plan"]["steps"] = [
                {
                    "id": f"step_{i+1}",
                    "title": f"步骤 {i+1}",
                    "description": step.strip(),
                    "status": "pending",
                    "order": i+1
                }
                for i, step in enumerate(steps)
            ]
            
            # 执行步骤
            outputs: List[str] = pre_outputs[:]
            for i, step in enumerate(steps):
                step_id = f"step_{i+1}"
                logger.debug("RunStructured: executing step %s: '%s'", step_id, step)
                
                # 更新步骤状态
                result["plan"]["steps"][i]["status"] = "in_progress"
                
                try:
                    # 执行步骤
                    out = self._execute_step(step, query, hints=hints_local)
                    outputs.append(out)
                    self.memory.add_summary(out)
                    
                    # 生成思考过程
                    thought = self._generate_thought_for_step(step, out)
                    
                    # 创建act结果
                    act_result = {
                        "step_id": step_id,
                        "title": f"步骤 {i+1}: {step.strip()[:50]}...",
                        "status": "completed",
                        "thought": {
                            "reasoning": thought.get("reasoning", ""),
                            "approach": thought.get("approach", ""),
                            "expected_outcome": thought.get("expected_outcome", "")
                        },
                        "execution": {
                            "tool_used": thought.get("tool_used", "unknown"),
                            "raw_output": out,
                            "processed_output": self._format_output_markdown(out),
                            "success": True,
                            "error_message": None
                        },
                        "summary": thought.get("summary", ""),
                        "timestamp": datetime.now().isoformat()
                    }
                    
                    result["acts"].append(act_result)
                    result["plan"]["steps"][i]["status"] = "completed"
                    result["plan"]["completed_steps"] += 1
                    
                except Exception as e:
                    logger.error("RunStructured: step %s failed: %s", step_id, e)
                    
                    # 创建失败的act结果
                    act_result = {
                        "step_id": step_id,
                        "title": f"步骤 {i+1}: {step.strip()[:50]}...",
                        "status": "failed",
                        "thought": {
                            "reasoning": f"执行步骤时遇到错误: {str(e)}",
                            "approach": "尝试执行指定操作",
                            "expected_outcome": "获取相关信息"
                        },
                        "execution": {
                            "tool_used": "unknown",
                            "raw_output": "",
                            "processed_output": f"**执行失败**: {str(e)}",
                            "success": False,
                            "error_message": str(e)
                        },
                        "summary": f"步骤执行失败: {str(e)}",
                        "timestamp": datetime.now().isoformat()
                    }
                    
                    result["acts"].append(act_result)
                    result["plan"]["steps"][i]["status"] = "failed"
            
            # 生成最终结果
            summary = compress_outputs(outputs, log_type=self._active_log_type)
            final_content = "".join(outputs) + summary
            
            result["final_result"] = self._generate_final_result(query, final_content, outputs)
            result["status"] = "completed"
            
        except Exception as e:
            logger.error("RunStructured: execution failed: %s", e)
            result["status"] = "failed"
            result["final_result"]["content"] = f"# 分析失败\n\n执行过程中遇到错误: {str(e)}"
            
        finally:
            # 清理和元数据
            try:
                self._cleanup_extracted_dirs()
            except Exception as e:
                logger.warning("RunStructured: cleanup failed: %s", e)
            
            # 更新元数据
            execution_time = time.time() - start_time
            result["metadata"]["execution_time"] = execution_time
            result["metadata"]["model_used"] = getattr(self.llm, 'model_name', 'unknown')
            
            logger.info("RunStructured: completed id=%s time=%.2fs", analysis_id, execution_time)
            self._active_log_type = prev_log_type
        
        return result

    def _format_plan_markdown(self, plan_xml: str) -> str:
        """将计划XML转换为markdown格式"""
        try:
            steps = re.findall(r"<step[^>]*>(.*?)</step>", plan_xml, flags=re.DOTALL)
            if not steps:
                return "# 分析计划\n\n未能解析到具体步骤。"
            
            markdown = "# 分析计划\n\n## 步骤概览\n\n"
            for i, step in enumerate(steps, 1):
                markdown += f"{i}. **步骤{i}** - {step.strip()}\n"
            
            markdown += "\n## 预期目标\n\n通过以上步骤，系统将对日志进行全面分析，识别问题并提供解决建议。"
            return markdown
        except Exception as e:
            logger.error("Format plan markdown failed: %s", e)
            return "# 分析计划\n\n计划格式化失败。"

    def _format_output_markdown(self, output: str) -> str:
        """将输出转换为markdown格式"""
        try:
            # 简单的格式化处理
            if not output.strip():
                return "*无输出内容*"
            
            # 如果已经是markdown格式，直接返回
            if output.strip().startswith('#') or '```' in output:
                return output
            
            # 否则包装为代码块
            return f"```\n{output}\n```"
        except Exception as e:
            logger.error("Format output markdown failed: %s", e)
            return f"```\n{output}\n```"

    def _generate_thought_for_step(self, step: str, output: str) -> Dict[str, str]:
        """为步骤生成思考过程"""
        try:
            # 简化的思考过程生成
            return {
                "reasoning": f"需要执行: {step.strip()}",
                "approach": "使用相应的工具和方法进行分析",
                "expected_outcome": "获取相关的分析信息",
                "tool_used": "log_analysis_tool",
                "summary": f"完成了步骤: {step.strip()[:100]}..."
            }
        except Exception as e:
            logger.error("Generate thought failed: %s", e)
            return {
                "reasoning": "执行分析步骤",
                "approach": "标准分析流程",
                "expected_outcome": "获取分析结果",
                "tool_used": "unknown",
                "summary": "步骤执行完成"
            }

    def _generate_final_result(self, query: str, content: str, outputs: List[str]) -> Dict[str, Any]:
        """生成最终的分析结果"""
        try:
            # 提取关键信息
            summary = self._extract_summary(content)
            recommendations = self._extract_recommendations(content)
            confidence = self._calculate_confidence(outputs)
            
            # 格式化最终内容
            formatted_content = self._format_final_content(query, content, summary, recommendations)
            
            return {
                "summary": summary,
                "content": formatted_content,
                "confidence": confidence,
                "recommendations": recommendations
            }
        except Exception as e:
            logger.error("Generate final result failed: %s", e)
            return {
                "summary": "分析完成，但结果格式化失败",
                "content": f"# 日志分析结果\n\n{content}",
                "confidence": 0.5,
                "recommendations": ["请检查分析结果的详细内容"]
            }

    def _extract_summary(self, content: str) -> str:
        """从内容中提取摘要 - 提取LLM生成的summary内容，返回纯markdown格式"""
        try:
            # 首先尝试从<context_summary>标签中提取
            summary_match = re.search(r'<context_summary>(.*?)</context_summary>', content, flags=re.DOTALL)
            if summary_match:
                raw = summary_match.group(1).strip()
                # 去除任何残留的XML标签，但保留Markdown符号
                raw = re.sub(r'<[^>]+>', '', raw)
                
                # 如果LLM返回了```markdown代码块，使用嵌套感知的提取方法
                extracted = self._extract_markdown_block(raw)
                if extracted:
                    logger.debug("Extracted markdown block from summary using nested-aware parser: %d chars", len(extracted))
                    return extracted
                
                # 否则直接返回清理后的文本（保留所有Markdown标记）
                # 不再移除markdown格式，让前端markdown-it来处理
                cleaned = raw.strip()
                if cleaned:
                    logger.debug("Using cleaned summary content: %d chars", len(cleaned))
                    return cleaned
            
            # 如果没有找到summary标签，使用原有逻辑但保留markdown格式
            lines = content.split('\n')
            summary_lines = []
            
            for line in lines[:10]:  # 取前10行作为摘要基础
                line = line.strip()
                # 跳过XML标签行和空行
                if line and not line.startswith('<') and not line.endswith('>'):
                    # 仅移除行内XML标签，保留markdown格式
                    clean_line = re.sub(r'<[^>]+>', '', line)
                    if clean_line:
                        summary_lines.append(clean_line)
                if len(summary_lines) >= 3:
                    break
            
            if summary_lines:
                # 保留原始的Markdown符号，用换行符连接（而非空格）
                summary = '\n'.join(summary_lines)
                logger.debug("Generated summary from content lines: %d chars", len(summary))
                return summary
            else:
                return "已完成日志分析，请查看详细结果。"
        except Exception as e:
            logger.warning("Extract summary failed: %s", e)
            return "分析完成"

    def _extract_recommendations(self, content: str) -> List[str]:
        """从内容中提取建议"""
        try:
            recommendations = []
            lines = content.split('\n')
            
            in_recommendation_section = False
            for line in lines:
                line = line.strip()
                
                # 检测是否进入建议部分
                if any(keyword in line.lower() for keyword in ['建议下一步', '建议措施', '下一步建议', '建议']):
                    in_recommendation_section = True
                    continue
                
                # 如果在建议部分，提取列表项
                if in_recommendation_section:
                    # 匹配markdown列表项（- 或 * 开头）
                    if line.startswith(('-', '*', '•')) and len(line) > 2:
                        # 移除列表标记
                        rec = line[1:].strip()
                        # 移除markdown格式标记
                        rec = re.sub(r'\*\*([^*]+)\*\*', r'\1', rec)  # 移除粗体
                        rec = re.sub(r'`([^`]+)`', r'\1', rec)  # 移除行内代码
                        if rec and len(rec) < 200:
                            recommendations.append(rec)
                    # 如果遇到空行或新的标题，结束建议部分
                    elif not line or line.startswith('#'):
                        if recommendations:
                            break
                        in_recommendation_section = False
                
                # 如果还没找到建议部分，继续搜索包含建议关键词的行
                elif not in_recommendation_section and any(keyword in line.lower() for keyword in ['建议', '推荐', 'recommend', 'suggest']):
                    # 移除markdown格式标记
                    clean_line = re.sub(r'\*\*([^*]+)\*\*', r'\1', line)
                    clean_line = re.sub(r'`([^`]+)`', r'\1', clean_line)
                    clean_line = re.sub(r'^[\-\*•]\s+', '', clean_line)
                    if clean_line and len(clean_line) < 200:
                        recommendations.append(clean_line)
                
                if len(recommendations) >= 5:
                    break
            
            if not recommendations:
                recommendations = ["请根据分析结果采取相应措施", "建议定期检查日志状态"]
            
            return recommendations
        except Exception as e:
            logger.warning("Extract recommendations failed: %s", e)
            return ["请查看详细分析结果"]

    def _calculate_confidence(self, outputs: List[str]) -> float:
        """计算分析置信度"""
        try:
            if not outputs:
                return 0.0
            
            # 简单的置信度计算
            total_length = sum(len(output) for output in outputs)
            error_count = sum(1 for output in outputs if 'error' in output.lower() or 'failed' in output.lower())
            
            base_confidence = min(0.9, total_length / 1000)  # 基于输出长度
            error_penalty = error_count * 0.1  # 错误惩罚
            
            return max(0.1, base_confidence - error_penalty)
        except Exception:
            return 0.5

    def _extract_markdown_block(self, content: str) -> Optional[str]:
        """
        从```markdown块中提取内容，正确处理嵌套的代码块
        使用状态机算法追踪嵌套层级
        """
        start = content.find('```markdown')
        if start == -1:
            start = content.find('```md')
            if start == -1:
                return None
        
        # 找到开始标记后的换行位置
        line_end = content.find('\n', start)
        if line_end == -1:
            return None
        
        body_start = line_end + 1
        inside_nested_code_block = False
        i = body_start
        
        while i < len(content):
            # 查找下一个```
            next_fence = content.find('```', i)
            if next_fence == -1:
                return content[body_start:].strip()
            
            # 检查是否在行首
            line_start = content.rfind('\n', 0, next_fence)
            before_fence = content[line_start + 1:next_fence] if line_start != -1 else content[:next_fence]
            is_line_start = before_fence.strip() == ''
            
            if is_line_start:
                if inside_nested_code_block:
                    # 当前在内层代码块中，这是内层代码块的结束
                    inside_nested_code_block = False
                else:
                    # 当前在内层代码块外，判断这是内层代码块的开始还是外层markdown块的结束
                    after_fence_pos = next_fence + 3
                    after_fence = content[after_fence_pos:]
                    
                    # 检查fence后面到下一个换行之间的内容
                    next_line_break = after_fence.find('\n')
                    line_content = after_fence[:next_line_break] if next_line_break >= 0 else after_fence
                    
                    # 如果这一行只有空白且后面没有更多内容，说明这是外层markdown块的结束
                    if line_content.strip() == '' and after_fence.strip() == '':
                        return content[body_start:next_fence].strip()
                    
                    # 否则这是内层代码块的开始
                    inside_nested_code_block = True
            
            i = next_fence + 3
        
        return content[body_start:].strip()

    def _format_final_content(self, query: str, content: str, summary: str, recommendations: List[str]) -> str:
        """格式化最终内容为标准markdown - 返回纯净的markdown格式内容"""
        try:
            # 前端已经有独立的section显示summary和recommendations
            # 这里只返回详细分析内容，移除XML标签和元数据
            
            # 移除<context_summary>标签及其内容（已在summary字段单独显示）
            clean_content = re.sub(r'<context_summary>.*?</context_summary>', '', content, flags=re.DOTALL)

            # 兼容旧格式：移除被包装为<document>且meta.type为summary的整块内容
            clean_content = re.sub(
                r'<document[^>]*>\s*<meta>.*?<type>\s*summary\s*</type>.*?</meta>\s*<content>[\s\S]*?</content>\s*</document>',
                '',
                clean_content,
                flags=re.DOTALL | re.IGNORECASE,
            )
            
            # 尝试从```markdown块中提取内容（使用改进的嵌套处理）
            extracted = self._extract_markdown_block(clean_content)
            if extracted:
                logger.debug("Extracted markdown block from final content using nested-aware parser")
                clean_content = extracted
            else:
                # 移除XML标签（保留内容和markdown格式）
                # 首先移除配对的标签
                clean_content = re.sub(r'<document[^>]*>(.*?)</document>', r'\1', clean_content, flags=re.DOTALL)
                clean_content = re.sub(r'<reads>(.*?)</reads>', r'\1', clean_content, flags=re.DOTALL)
                clean_content = re.sub(r'<meta>.*?</meta>', '', clean_content, flags=re.DOTALL)
                
                # 移除单独的开闭标签
                clean_content = re.sub(r'<document[^>]*>', '', clean_content)
                clean_content = re.sub(r'</document>', '', clean_content)
                clean_content = re.sub(r'<reads>', '', clean_content)
                clean_content = re.sub(r'</reads>', '', clean_content)
                
                # 移除带属性的标签
                clean_content = re.sub(r'<[^>]+\s+type="[^"]*"[^>]*>', '', clean_content)
                clean_content = re.sub(r'<[^>]+\s+tool="[^"]*"[^>]*>', '', clean_content)
                clean_content = re.sub(r'<[^>]+\s+source="[^"]*"[^>]*>', '', clean_content)
                
                # 移除所有剩余的XML标签
                clean_content = re.sub(r'</?[a-zA-Z_][^>]*>', '', clean_content)
                
                # 移除XML属性行（如 tool="xxx"）
                clean_content = re.sub(r'^\s*\w+="[^"]*"\s*$', '', clean_content, flags=re.MULTILINE)
            
            # 移除多余的空行（超过2个连续换行）
            clean_content = re.sub(r'\n{3,}', '\n\n', clean_content)
            
            # 清理首尾空白
            clean_content = clean_content.strip()
            
            # 记录清理后的内容长度
            logger.debug("Formatted final content: %d chars (original: %d chars)", 
                        len(clean_content), len(content))
            
            # 如果内容为空或过短，返回基本信息（使用markdown格式）
            if not clean_content or len(clean_content) < 10:
                clean_content = f"根据查询 **{query}** 的分析已完成。\n\n详细信息已在摘要和建议中提供。"
                logger.debug("Using default content message due to insufficient cleaned content")
            
            return clean_content
        except Exception as e:
            logger.error("Format final content failed: %s", e)
            # 返回原内容而非空字符串，确保有内容显示
            return content





def demo_agent_run(query: str, hints: Optional[Dict[str, Any]] = None) -> str:
    logger.info("demo_agent_run: query='%s'", query)
    logger.debug("demo_agent_run: hints=%s", hints)
    agent = LogAnalysisAgent()
    result = agent.run(query, hints=hints)
    logger.info("demo_agent_run: result chars=%d", len(result))
    return result

# Prompt缓存（全局），用于存储配置与模板实例
_PROMPTS_CACHE: Dict[str, Dict[str, Any]] = {}
_PROMPT_TEMPLATES_CACHE: Dict[str, Any] = {}

class LogAnalysisAgentDuplicate:
    """Main Agent orchestrating planning and tool execution via LangGraph."""
    def __init__(self):
        self.llm = get_llm()
        logger.info("LogAnalysisAgent.__init__: llm=%s", type(self.llm).__name__)
        self._active_log_type: Optional[str] = None
        self.memory = ShortTermMemory(window=settings.agent_short_term_window)
        self.search_backend = (
            ElasticSearchBackend(url=settings.elasticsearch_url)
            if settings.agent_search_backend == "elasticsearch"
            else RegexSearchBackend(root=settings.agent_root_dir)
        )
        logger.info("LogAnalysisAgent.__init__: backend=%s", type(self.search_backend).__name__)
        self._extracted_dirs: List[str] = []
        try:
            paths: List[str] = []
            logger.debug("Search indexing start: root=%s", settings.agent_root_dir)
            for d, _, files in os.walk(settings.agent_root_dir):
                for f in files:
                    paths.append(os.path.join(d, f))
                if len(paths) > 5000:
                    logger.warning("Indexing truncated at 5000 files to limit scope")
                    break
            self.search_backend.index(paths)
            logger.info("Search indexing done: files=%d", len(paths))
        except Exception as e:
            logger.warning("Search indexing failed: %s", e)

        # Build LangGraph (compact ReAct-style loop)
        if StateGraph:
            graph = StateGraph(AgentState)
            graph.add_node("plan", self._plan_node)
            graph.add_node("act", self._act_node)
            graph.add_edge("plan", "act")
            graph.add_conditional_edges("act", self._should_continue)
            graph.set_entry_point("plan")
            self._app = graph.compile()
        else:
            self._app = None  # Fallback: run() will degrade to sequential execution

    def _plan_node(self, state: AgentState) -> AgentState:
        """Graph node that generates plan XML and step list."""
        query = state.get("query", "")
        plan_xml = self.plan(query, hints=state.get("hints"))
        steps = re.findall(r"<step[^>]*>(.*?)</step>", plan_xml, flags=re.DOTALL)
        return {"plan_xml": plan_xml, "steps": steps}

    def _first_text_file(self) -> Optional[str]:
        for d, _, files in os.walk(settings.agent_root_dir):
            for f in files:
                if f.lower().endswith(('.log', '.txt')):
                    p = os.path.join(d, f)
                    logger.debug('First text file found: %s', p)
                    return p
        logger.debug('First text file not found under root=%s', settings.agent_root_dir)
        return None

    def _first_text_file_under(self, root: str) -> Optional[str]:
        for d, _, files in os.walk(root):
            for f in files:
                if f.lower().endswith(('.log', '.txt')):
                    p = os.path.join(d, f)
                    logger.debug('First text file found under %s: %s', root, p)
                    return p
        logger.debug('First text file not found under root=%s', root)
        return None

    # Backward-compatible plan() API
    def plan(self, query: str, hints: Optional[Dict[str, Any]] = None, log_type: Optional[Any] = None) -> str:
        logger.info("Plan: start query='%s'", query[:200])
        self._active_log_type = _infer_log_type_from_hints(hints, explicit=log_type, current=self._active_log_type)
        logger.debug("Plan: using log_type=%s", self._active_log_type or "default")
        prompt = render_prompt(
            "plan_prompt",
            memory_context=self.memory.context(),
            user_query=query,
            log_type=self._active_log_type,
        )
        logger.debug("Plan: prompt chars=%d", len(prompt))
        logger.info("\n\n--- START LLM PROMPT [plan] ---\n%s\n--- END LLM PROMPT [plan] ---\n", prompt)
        plan_xml: str = ""
        try:
            logger.debug("Plan: llm=%s", type(self.llm).__name__)
            if hasattr(self.llm, "predict"):
                plan_xml = self.llm.predict(prompt)
            else:
                response = self.llm.invoke(prompt)
                # 正确提取LangChain消息对象的content字段
                if hasattr(response, "content"):
                    plan_xml = response.content
                else:
                    plan_xml = str(response)
        except Exception as e:
            logger.warning("Plan LLM failed, using fallback: %s", e)
            plan_xml = wrap_plan(["读取日志片段", "在相关文件中执行grep搜索"])
        logger.info("\n\n--- START LLM OUTPUT [plan] ---\ncontent='%s'\n--- END LLM OUTPUT [plan] ---\n", plan_xml)
        # Normalize: ensure XML structure
        steps = re.findall(r"<step[^>]*>(.*?)</step>", plan_xml, flags=re.DOTALL)
        if not steps:
            logger.debug("Plan: no <step> found, using fallback plan")
            plan_xml = wrap_plan(["读取日志片段", "在相关文件中执行grep搜索"])
        self.memory.add_message("user", query)
        self.memory.add_message("system", plan_xml)
        logger.info("Plan: steps=%d", len(re.findall(r"<step[^>]*>(.*?)</step>", plan_xml, flags=re.DOTALL)))
        return plan_xml

    # Tool routing (XML-producing, refactored)
    def _execute_step(self, step: str, query: str, hints: Optional[Dict[str, Any]] = None) -> str:
        logger.info("Execute step (refactored): %s", step)
        hints = hints or {}

        # Attempt function calling via llm.bind_tools
        try:
            tools_bound = self._build_langchain_tools(hints)
            if tools_bound and hasattr(self.llm, "bind_tools"):
                tool_map = {t.name: t for t in tools_bound}
                bound_llm = self.llm.bind_tools(tools_bound)
                fc_prompt = (
                    "你是一个日志分析Agent的工具路由器。\n"
                    "请基于提供的step、query、hints选择并调用一个工具，使用函数调用（function calling）。\n"
                    "不要输出普通文本，必须返回一个工具调用。\n"
                    f"<step>{step}</step>\n<query>{query}</query>\n<hints>{json.dumps(hints, ensure_ascii=False)}</hints>\n"
                )
                resp = bound_llm.invoke(fc_prompt)
                tool_calls = getattr(resp, "tool_calls", None)
                if not tool_calls and hasattr(resp, "additional_kwargs"):
                    tool_calls = resp.additional_kwargs.get("tool_calls")
                if tool_calls:
                    tc = tool_calls[0]
                    tname = tc.get("name") or tc.get("tool")
                    targs = tc.get("args") or {}
                    if isinstance(targs, list) and len(targs) == 1 and isinstance(targs[0], dict):
                        targs = targs[0]
                    if tname in tool_map:
                        logger.info("bind_tools selected '%s' with args=%s", tname, targs)
                        try:
                            return tool_map[tname].invoke(targs)
                        except Exception as e:
                            logger.warning("Tool '%s' execution via bind_tools failed: %s", tname, e)
        except Exception as e:
            logger.warning("bind_tools route failed, fallback to manual selection: %s", e)

        tool_specs: Dict[str, Dict[str, Any]] = {
            "metadata_extract": {
                "desc": "提取日志包元数据（tar.gz/zip）",
                "schema": {"archive_path": "str"},
            },
            "grep_search": {
                "desc": "在文本文件中执行模式搜索 (grep)",
                "schema": {"path": "str?", "pattern": "str", "context": "int?"},
            },
            "read_snippet": {
                "desc": "读取文件片段 (head/tail)",
                "schema": {"path": "str?", "head_lines": "int?", "tail_lines": "int?"},
            },
            "nested_extract": {
                "desc": "解压或扫描嵌套归档",
                "schema": {"nested_path": "str?", "extracted_root": "str?"},
            },
            "list_tree": {
                "desc": "列出目录树结构",
                "schema": {"root": "str?", "max_depth": "int?"},
            },
            "global_search": {
                "desc": "使用搜索后转为XML",
                "schema": {"query": "str", "k": "int?"},
            },
        }

        def _extract_json_candidate(s: str) -> Optional[Dict[str, Any]]:
            try:
                s = s.strip()
                if s.startswith("{") and s.endswith("}"):
                    return json.loads(s)
                start = s.find("{")
                end = s.rfind("}")
                if start != -1 and end != -1 and end > start:
                    return json.loads(s[start : end + 1])
            except Exception:
                return None
            return None

        def _fallback_select(step_text: str) -> Dict[str, Any]:
            st = step_text.lower()
            if ("元数据" in st) or ("metadata" in st):
                return {"tool": "metadata_extract", "args": {}}
            if ("grep" in st) or ("查找" in st) or ("搜索" in st):
                return {"tool": "grep_search", "args": {}}
            if ("读取" in st) or ("片段" in st) or ("head" in st) or ("tail" in st):
                return {"tool": "read_snippet", "args": {}}
            if ("解压" in st) or ("extract" in st) or ("decompress" in st):
                return {"tool": "nested_extract", "args": {}}
            if ("树" in st) or ("tree" in st) or ("结构" in st) or ("list" in st):
                return {"tool": "list_tree", "args": {}}
            return {"tool": "global_search", "args": {}}

        selection: Dict[str, Any] = {}
        try:
            tools_text = "\n".join([f"- {name}: {spec['desc']} schema={spec['schema']}" for name, spec in tool_specs.items()])
            prompt = (
                "你是一个日志分析Agent的工具路由器。\n"
                "基于提供的step、query、hints，从下列工具中选择最合适的一个，并给出JSON参数：\n"
                f"{tools_text}\n\n"
                "返回严格的JSON对象，不要包含解释或多余文字。格式：{\"tool\": \"<name>\", \"args\": { ... }}\n"
                f"<step>{step}</step>\n<query>{query}</query>\n<hints>{json.dumps(hints, ensure_ascii=False)}</hints>\n"
            )
            if hasattr(self.llm, "predict"):
                raw = self.llm.predict(prompt)
            else:
                response = self.llm.invoke(prompt)
                # 正确提取LangChain消息对象的content字段
                if hasattr(response, "content"):
                    raw = response.content
                else:
                    raw = str(response)
            cand = _extract_json_candidate(raw)
            if not cand:
                raise ValueError("LLM未返回可解析的JSON")
            selection = cand
        except Exception as e:
            logger.warning("Tool selection via LLM failed, using fallback: %s", e)
            selection = _fallback_select(step)

        name = str(selection.get("tool", "")).strip()
        args: Dict[str, Any] = selection.get("args", {}) if isinstance(selection.get("args", {}), dict) else {}
        if name not in tool_specs:
            logger.warning("Unknown tool '%s', fallback to global_search", name)
            name = "global_search"

        try:
            if name == "metadata_extract":
                hint_arch = hints.get("archive_path")
                hint_path = hints.get("path")
                ap = args.get("archive_path")
                path = ap or hint_arch or (
                    hint_path if isinstance(hint_path, str) and hint_path.lower().endswith((".tar.gz", ".tgz", ".zip")) else None
                ) or os.path.join(settings.agent_root_dir, "logs.tar.gz")
                logger.info("ToolCall metadata_extract: path=%s", path)
                return get_log_package_metadata_xml(path)

            if name == "grep_search":
                pattern = args.get("pattern") or hints.get("pattern") or query
                path = args.get("path") or hints.get("path") or self._first_text_file()
                context = int(args.get("context") or 2)
                logger.info(
                    "ToolCall grep_search: path=%s pattern=%s context=%d max_matches=%s max_bytes=%s",
                    path,
                    pattern,
                    context,
                    getattr(settings, "agent_max_matches", None),
                    getattr(settings, "agent_max_snippet_bytes", None),
                )
                if not path:
                    return wrap_document("未找到可搜索的文本文件", {"step": step})
                return grep_file_xml(path, pattern, context=context)

            if name == "read_snippet":
                path = args.get("path") or hints.get("path") or self._first_text_file()
                head_n = int(args.get("head_lines") or 50)
                tail_n = int(args.get("tail_lines") or 50)
                logger.info("ToolCall read_snippet: path=%s head_lines=%d tail_lines=%d", path, head_n, tail_n)
                if not path:
                    return wrap_document("未找到可读取的文本文件", {"step": step})
                head = read_head_xml(path, n_lines=head_n)
                tail = read_tail_xml(path, n_lines=tail_n)
                return f"<reads>{head}{tail}</reads>"

            if name == "nested_extract":
                nested_path = args.get("nested_path") or hints.get("nested_path")
                root = args.get("extracted_root") or hints.get("extracted_root") or settings.agent_root_dir
                logger.info("ToolCall nested_extract: nested_path=%s root=%s", nested_path, root)
                if nested_path:
                    dest, xml = extract_nested_archive_xml(nested_path, parent_root=root)
                    try:
                        self._extracted_dirs.append(dest)
                    except Exception:
                        pass
                    logger.info("ToolCall nested_extract: extracted_dir=%s", dest)
                    return xml
                else:
                    return nested_archives_xml(root)

            if name == "list_tree":
                root = args.get("root") or hints.get("extracted_root") or settings.agent_root_dir
                max_depth = int(args.get("max_depth") or 2)
                logger.info("ToolCall list_tree: root=%s max_depth=%d", root, max_depth)
                return list_tree_xml(root, max_depth=max_depth)

            if name == "global_search":
                k = int(args.get("k") or 10)
                logger.info("ToolCall global_search: backend=%s query=%s k=%d", type(self.search_backend).__name__, query, k)
                return search_to_xml(self.search_backend, query=query, k=k)

            logger.warning("Unhandled tool '%s', fallback to global_search", name)
            return search_to_xml(self.search_backend, query=query, k=10)
        except Exception as e:
            logger.warning("Tool '%s' execution failed: %s", name, e)
            label = {
                "metadata_extract": "元数据提取失败",
                "grep_search": "grep失败",
                "read_snippet": "读取失败",
                "nested_extract": "解压/扫描嵌套归档失败",
                "list_tree": "树结构生成失败",
                "global_search": "搜索失败",
            }.get(name, "工具执行失败")
            return wrap_document(f"{label}: {e}", {"step": step})

    # Graph node: act
    def _act_node(self, state: AgentState) -> AgentState:
        steps = state["steps"]
        idx = state.get("idx", 0)
        logger.info("Act: idx=%d/%d", idx, len(steps))
        if idx >= len(steps):
            logger.debug("Act: completed all steps")
            return {"done": True}
        step = steps[idx]
        out = self._execute_step(step, state["query"], hints=state.get("hints"))
        logger.debug("Act: output chars=%d", len(out))
        self.memory.add_summary(out)
        # Generate and print per-act LLM thought
        try:
            step_thought = compress_outputs([out], log_type=self._active_log_type)
            logger.info("LLM Thought [after_act]:\n%s", step_thought)
        except Exception as e:
            logger.warning("Act: step thought generation failed: %s", e)
        outputs = state.get("outputs", []) + [out]
        return {"outputs": outputs, "idx": idx + 1}

    # Graph edge condition
    def _should_continue(self, state: AgentState):
        idx = state.get("idx", 0)
        steps = state.get("steps", [])
        decision = "act" if idx < len(steps) else "end"
        logger.debug("Continue? idx=%d steps=%d decision=%s", idx, len(steps), decision)
        if idx < len(steps):
            return "act"
        return END

    def run(self, query: str, hints: Optional[Dict[str, Any]] = None) -> str:
        """Run the agent end-to-end using LangGraph when available; fallback sequential otherwise."""
        logger.info("Run: start query='%s'", query)
        hints_local: Dict[str, Any] = dict(hints or {})
        logger.debug("Run: hints=%s", hints_local)
        prev_log_type = self._active_log_type
        self._active_log_type = _infer_log_type_from_hints(hints_local, current=self._active_log_type)
        pre_outputs: List[str] = []
        final_doc: str = ""
        try:
            # 自动解压流程：如果提供了归档路径，则先解压并输出树结构
            archive_path = hints_local.get("archive_path") or (hints_local.get("path") if isinstance(hints_local.get("path"), str) and hints_local.get("path").lower().endswith((".tar.gz", ".tgz", ".zip")) else None)
            if archive_path:
                logger.info("Run: auto-extract archive=%s", archive_path)
                try:
                    extracted_dir, ex_xml = auto_extract_archive_xml(archive_path)
                    logger.info("Run: auto-extract ok extracted_dir=%s", extracted_dir)
                    pre_outputs.append(ex_xml)
                    self.memory.add_summary(ex_xml)
                    hints_local["extracted_root"] = extracted_dir
                    # 记录解压目录以便完成后清理
                    try:
                        self._extracted_dirs.append(extracted_dir)
                    except Exception:
                        pass
                    # 如果原始hints.path是归档文件，替换为解压目录下的首个文本文件
                    if hints_local.get("path") and isinstance(hints_local["path"], str) and hints_local["path"].lower().endswith((".tar.gz", ".tgz", ".zip")):
                        hints_local.pop("path", None)
                    if not hints_local.get("path"):
                        p = self._first_text_file_under(extracted_dir)
                        if p:
                            hints_local["path"] = p
                except Exception as e:
                    logger.warning("Run: auto-extract failed: %s", e)
                    pre_outputs.append(wrap_document(f"自动解压失败: {e}", {"type": "extraction_error"}))
            if self._app:
                logger.debug("Run: using LangGraph pipeline")
                final_state: AgentState = self._app.invoke({
                    "query": query,
                    "hints": hints_local,
                    "plan_xml": "",
                    "steps": [],
                    "idx": 0,
                    "outputs": pre_outputs,
                    "done": False,
                })
                outputs = final_state.get("outputs", [])
                logger.info("Run: outputs via graph=%d", len(outputs))
            else:
                logger.debug("Run: sequential fallback")
                plan_xml = self.plan(query, hints=hints_local)
                steps = re.findall(r"<step[^>]*>(.*?)</step>", plan_xml, flags=re.DOTALL)
                logger.info("Run: executing %d steps sequentially", len(steps))
                outputs: List[str] = pre_outputs[:]
                for step in steps:
                    logger.debug("Run: executing step '%s'", step)
                    out = self._execute_step(step, query, hints=hints_local)
                    outputs.append(out)
                    self.memory.add_summary(out)
            summary = compress_outputs(outputs, log_type=self._active_log_type)
            logger.debug("Run: summary chars=%d", len(summary))
            final_doc = wrap_document("".join(outputs) + summary, {"source": "log_agent"})
            logger.info("Run: final doc chars=%d", len(final_doc))
        finally:
            try:
                self._cleanup_extracted_dirs()
            except Exception as e:
                logger.warning("Run: cleanup extracted dirs failed: %s", e)
            self._active_log_type = prev_log_type
        return final_doc

    def _cleanup_extracted_dirs(self) -> None:
        base = os.path.abspath(os.path.join(settings.agent_root_dir, "_extracted"))
        for d in getattr(self, "_extracted_dirs", []):
            try:
                absd = os.path.abspath(d)
                if os.path.commonpath([absd, base]) != base:
                    logger.warning("Cleanup skipped for non-extracted path: %s", absd)
                    continue
                if os.path.isdir(absd):
                    logger.info("Cleanup: removing extracted dir: %s", absd)
                    shutil.rmtree(absd, ignore_errors=True)
            except Exception as e:
                logger.warning("Cleanup error for %s: %s", d, e)
        self._extracted_dirs = []





def demo_agent_run(query: str, hints: Optional[Dict[str, Any]] = None) -> str:
    logger.info("demo_agent_run: query='%s'", query)
    logger.debug("demo_agent_run: hints=%s", hints)
    agent = LogAnalysisAgent()
    result = agent.run(query, hints=hints)
    logger.info("demo_agent_run: result chars=%d", len(result))
    return result

# Prompt缓存（全局），用于存储配置与模板实例
_PROMPTS_CACHE: Dict[str, Dict[str, Any]] = {}
_PROMPT_TEMPLATES_CACHE: Dict[str, Any] = {}

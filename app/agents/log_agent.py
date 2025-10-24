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

logger = logging.getLogger(__name__)

from app.config import settings
from app.agents.xml_utils import wrap_plan, wrap_document
from app.tools.metadata_tool import get_log_package_metadata_xml
from app.tools.grep_tool import grep_file_xml
from app.tools.fs_tools import read_head_xml, read_tail_xml
from app.tools.search_backend import RegexSearchBackend, ElasticSearchBackend, search_to_xml
from app.tools.archive_tool import auto_extract_archive_xml, list_tree_xml, nested_archives_xml, extract_nested_archive_xml


class DummyLLM:
    """Fallback LLM that produces deterministic, safe outputs for demo/testing."""
    def __init__(self, temperature: float = 0.0):
        self.temperature = temperature

    def predict(self, prompt: str) -> str:
        steps: List[str] = []
        p = prompt.lower()
        if "metadata" in p or "元数据" in p:
            steps.append("提取日志包元数据")
        if "grep" in p or "查找" in p or "搜索" in p:
            steps.append("在相关文件中执行grep搜索")
        if not steps:
            steps.append("列出可用日志并读取关键片段")
        return wrap_plan(steps)


def get_llm() -> Any:
    """Return an LLM client with fallback: deepseek → qwen → dummy.
    - Provider 'auto' tries deepseek first, then qwen.
    - Provider 'deepseek' uses deepseek config, falls back to qwen if network/API failure at call time.
    - Provider 'qwen' uses qwen config directly.
    """
    logger.debug(f"get_llm: provider={getattr(settings, 'llm_provider', 'auto')}")
    # If ChatOpenAI class unavailable, use DummyLLM
    if not ChatOpenAI:
        logger.info("get_llm: ChatOpenAI unavailable, using DummyLLM")
        return DummyLLM(temperature=settings.llm_temperature)

    def make_chat_openai(api_key: str, base_url: str, model: str):
        os.environ["OPENAI_API_KEY"] = api_key
        os.environ["OPENAI_BASE_URL"] = base_url
        os.environ["OPENAI_API_BASE"] = base_url
        try:
            logger.debug(f"Initializing ChatOpenAI client: base_url={base_url}, model={model}")
            return ChatOpenAI(model=model, temperature=settings.llm_temperature)
        except Exception as e:
            logger.warning(f"ChatOpenAI init failed: base_url={base_url}, model={model}, error={e}")
            return None

    # 封装一个具有运行时回退能力的LLM包装器：调用失败时自动切换到Qwen
    class _FallbackLLM:
        def __init__(self, primary_conf: Dict[str, str], fallback_conf: Optional[Dict[str, str]], temperature: float):
            self.temperature = temperature
            self._primary_conf = primary_conf
            self._fallback_conf = fallback_conf
            self._primary = make_chat_openai(primary_conf.get("api_key", ""), primary_conf.get("base_url", ""), primary_conf.get("model", ""))
            self._fallback = None

        def invoke(self, prompt: str):
            # 尝试主模型（DeepSeek）
            if self._primary:
                try:
                    logger.debug("FallbackLLM.invoke: using primary model")
                    return self._primary.invoke(prompt)
                except Exception as e:
                    logger.warning(f"Primary model invocation failed, switching to fallback: {e}")
                    # 出现HTTP错误（如404/502/超时等）时切换到备选（Qwen）
                    pass
            # 构建并尝试备选模型（Qwen）
            if self._fallback_conf and not self._fallback:
                logger.debug("FallbackLLM.invoke: building fallback model")
                self._fallback = make_chat_openai(
                    self._fallback_conf.get("api_key", ""),
                    self._fallback_conf.get("base_url", ""),
                    self._fallback_conf.get("model", "")
                )
            if self._fallback:
                try:
                    logger.debug("FallbackLLM.invoke: using fallback model")
                    return self._fallback.invoke(prompt)
                except Exception as e:
                    logger.warning(f"Fallback model invocation failed: {e}")
            # 最终回退到DummyLLM，返回可用的字符串结果
            logger.info("FallbackLLM.invoke: using DummyLLM")
            return DummyLLM(temperature=self.temperature).predict(prompt)

    # Helper: try deepseek, then qwen (初始化阶段)
    def try_deepseek_first_then_qwen():
        # Try DeepSeek
        if getattr(settings, "deepseek_api_key", None) and getattr(settings, "deepseek_base_url", None):
            llm = make_chat_openai(settings.deepseek_api_key, settings.deepseek_base_url, settings.llm_model_name)
            if llm:
                return llm
        # Fallback to Qwen
        if getattr(settings, "qwen_api_key", None) and getattr(settings, "qwen_base_url", None):
            llm = make_chat_openai(settings.qwen_api_key, settings.qwen_base_url, getattr(settings, "qwen_model_name", "qwen-plus-2025-09-11"))
            if llm:
                return llm
        return None

    # Provider routing
    provider = getattr(settings, "llm_provider", "auto")
    if provider == "auto":
        # 优先返回具有运行时回退能力的DeepSeek→Qwen包装器
        if getattr(settings, "deepseek_api_key", None) and getattr(settings, "deepseek_base_url", None):
            primary = {
                "api_key": settings.deepseek_api_key,
                "base_url": settings.deepseek_base_url,
                "model": settings.llm_model_name,
            }
            fallback = None
            if getattr(settings, "qwen_api_key", None) and getattr(settings, "qwen_base_url", None):
                fallback = {
                    "api_key": settings.qwen_api_key,
                    "base_url": settings.qwen_base_url,
                    "model": getattr(settings, "qwen_model_name", "qwen-plus-2025-09-11"),
                }
            return _FallbackLLM(primary, fallback, settings.llm_temperature)
        # 若DeepSeek未配置，尝试直接Qwen
        if getattr(settings, "qwen_api_key", None) and getattr(settings, "qwen_base_url", None):
            llm = make_chat_openai(settings.qwen_api_key, settings.qwen_base_url, getattr(settings, "qwen_model_name", "qwen-plus-2025-09-11"))
            return llm or DummyLLM(temperature=settings.llm_temperature)
        return DummyLLM(temperature=settings.llm_temperature)

    if provider == "deepseek":
        # 始终使用运行时回退包装器：DeepSeek失败时自动切换到Qwen
        primary = {
            "api_key": getattr(settings, "deepseek_api_key", ""),
            "base_url": getattr(settings, "deepseek_base_url", ""),
            "model": getattr(settings, "llm_model_name", "deepseek-v3.1-chat"),
        }
        fallback = None
        if getattr(settings, "qwen_api_key", None) and getattr(settings, "qwen_base_url", None):
            fallback = {
                "api_key": settings.qwen_api_key,
                "base_url": settings.qwen_base_url,
                "model": getattr(settings, "qwen_model_name", "qwen-plus-2025-09-11"),
            }
        return _FallbackLLM(primary, fallback, settings.llm_temperature)

    if provider == "qwen":
        if getattr(settings, "qwen_api_key", None) and getattr(settings, "qwen_base_url", None):
            llm = make_chat_openai(settings.qwen_api_key, settings.qwen_base_url, getattr(settings, "qwen_model_name", "qwen-plus-2025-09-11"))
            if llm:
                return llm
        # fallback if qwen missing
        return DummyLLM(temperature=settings.llm_temperature)

    # OpenAI direct (kept for compatibility)
    if provider == "openai" and getattr(settings, "openai_api_key", None):
        os.environ["OPENAI_API_KEY"] = settings.openai_api_key
        try:
            return ChatOpenAI(model=settings.llm_model_name, temperature=settings.llm_temperature)
        except Exception:
            return DummyLLM(temperature=settings.llm_temperature)

    # Final fallback
    return DummyLLM(temperature=settings.llm_temperature)


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
    base_dir = os.path.dirname(os.path.dirname(__file__))  # app/
    default_path = os.path.join(base_dir, "prompts", "prompts_config.yaml")
    path = getattr(settings, "prompts_config_path", default_path)
    if not os.path.isabs(path):
        path = os.path.join(base_dir, os.path.normpath(path))
    return path

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
    except Exception:
        # 内置回退模板，确保功能不受影响
        _PROMPTS_CACHE = {
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

def render_prompt(key: str, **kwargs: Any) -> str:
    conf = _load_prompts_config().get(key, {})
    template_str = conf.get("template", "")
    if not template_str:
        return ""
    if PromptTemplate:
        try:
            pt = _PROMPT_TEMPLATES_CACHE.get(key)
            if not pt:
                input_vars = conf.get("variables") or list(kwargs.keys())
                pt = PromptTemplate(input_variables=input_vars, template=template_str)
                _PROMPT_TEMPLATES_CACHE[key] = pt
            return pt.format(**kwargs)
        except Exception:
            return template_str.format(**kwargs)
    else:
        return template_str.format(**kwargs)

def compress_outputs(outputs: List[str]) -> str:
    """Compression: extractive truncation + optional LLM summary."""
    n = min(3, len(outputs)) or 1
    compact = "".join(o[: settings.agent_max_snippet_bytes // n] for o in outputs[:n])
    llm = get_llm()
    try:
        prompt = render_prompt("summary_prompt", compact_snippet=compact)
        if hasattr(llm, "predict"):
            summary_xml = llm.predict(prompt)
            return f"<context_summary>{summary_xml}</context_summary>"
        else:
            res = llm.invoke(prompt)
            return wrap_document(str(res), {"type": "summary"})
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
        self.memory = ShortTermMemory(window=settings.agent_short_term_window)
        self.search_backend = (
            ElasticSearchBackend(url=settings.elasticsearch_url)
            if settings.agent_search_backend == "elasticsearch"
            else RegexSearchBackend(root=settings.agent_root_dir)
        )
        logger.info("LogAnalysisAgent.__init__: backend=%s", type(self.search_backend).__name__)
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
        plan_xml = self.plan(query)
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
    def plan(self, query: str) -> str:
        logger.info("Plan: start query='%s'", query[:200])
        prompt = render_prompt(
            "plan_prompt",
            memory_context=self.memory.context(),
            user_query=query,
        )
        logger.debug("Plan: prompt chars=%d", len(prompt))
        plan_xml: str = ""
        try:
            logger.debug("Plan: llm=%s", type(self.llm).__name__)
            if hasattr(self.llm, "predict"):
                plan_xml = self.llm.predict(prompt)
            else:
                plan_xml = str(self.llm.invoke(prompt))
        except Exception as e:
            logger.warning("Plan LLM failed, using fallback: %s", e)
            plan_xml = wrap_plan(["读取日志片段", "在相关文件中执行grep搜索"])
        # Normalize: ensure XML structure
        steps = re.findall(r"<step[^>]*>(.*?)</step>", plan_xml, flags=re.DOTALL)
        if not steps:
            logger.debug("Plan: no <step> found, using fallback plan")
            plan_xml = wrap_plan(["读取日志片段", "在相关文件中执行grep搜索"])
        self.memory.add_message("user", query)
        self.memory.add_message("system", plan_xml)
        logger.info("Plan: steps=%d", len(re.findall(r"<step[^>]*>(.*?)</step>", plan_xml, flags=re.DOTALL)))
        return plan_xml

    # Tool routing (XML-producing)
    def _execute_step(self, step: str, query: str, hints: Optional[Dict[str, Any]] = None) -> str:
        logger.info("Execute step: %s", step)
        step_l = step.lower()
        if "元数据" in step_l or "metadata" in step_l:
            path = (hints or {}).get("archive_path") or os.path.join(settings.agent_root_dir, "logs.tar.gz")
            logger.debug("Tool=metadata path=%s", path)
            try:
                return get_log_package_metadata_xml(path)
            except Exception as e:
                logger.warning("Metadata tool failed: %s", e)
                return wrap_document(f"元数据提取失败: {e}", {"step": step})
        if "grep" in step_l or "查找" in step_l or "搜索" in step_l:
            pattern = (hints or {}).get("pattern") or query
            path = (hints or {}).get("path") or self._first_text_file()
            logger.debug("Tool=grep path=%s pattern=%s", path, pattern)
            if not path:
                return wrap_document("未找到可搜索的文本文件", {"step": step})
            try:
                return grep_file_xml(path, pattern, context=2)
            except Exception as e:
                logger.warning("grep tool failed: %s", e)
                return wrap_document(f"grep失败: {e}", {"step": step})
        if "读取" in step_l or "片段" in step_l or "head" in step_l or "tail" in step_l:
            path = (hints or {}).get("path") or self._first_text_file()
            logger.debug("Tool=reads path=%s", path)
            if not path:
                return wrap_document("未找到可读取的文本文件", {"step": step})
            try:
                head = read_head_xml(path, n_lines=50)
                tail = read_tail_xml(path, n_lines=50)
                return f"<reads>{head}{tail}</reads>"
            except Exception as e:
                logger.warning("read tool failed: %s", e)
                return wrap_document(f"读取失败: {e}", {"step": step})
        # 新增：树结构与嵌套解压支持
        if "解压" in step_l or "extract" in step_l or "decompress" in step_l:
            nested_path = (hints or {}).get("nested_path")
            root = (hints or {}).get("extracted_root") or settings.agent_root_dir
            logger.debug("Tool=extract nested_path=%s root=%s", nested_path, root)
            try:
                if nested_path:
                    _, xml = extract_nested_archive_xml(nested_path, parent_root=root)
                    return xml
                else:
                    return nested_archives_xml(root)
            except Exception as e:
                logger.warning("extract tool failed: %s", e)
                return wrap_document(f"解压/扫描嵌套归档失败: {e}", {"step": step})
        if "树" in step_l or "tree" in step_l or "结构" in step_l or "list" in step_l:
            root = (hints or {}).get("extracted_root") or settings.agent_root_dir
            logger.debug("Tool=tree root=%s", root)
            try:
                return list_tree_xml(root, max_depth=2)
            except Exception as e:
                logger.warning("tree tool failed: %s", e)
                return wrap_document(f"树结构生成失败: {e}", {"step": step})
        try:
            logger.debug("Tool=search query=%s", query)
            return search_to_xml(self.search_backend, query=query, k=10)
        except Exception as e:
            logger.warning("search backend failed: %s", e)
            return wrap_document(f"搜索失败: {e}", {"step": step})

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
        pre_outputs: List[str] = []
        # 自动解压流程：如果提供了归档路径，则先解压并输出树结构
        archive_path = hints_local.get("archive_path")
        if archive_path:
            logger.info("Run: auto-extract archive=%s", archive_path)
            try:
                extracted_dir, ex_xml = auto_extract_archive_xml(archive_path)
                logger.info("Run: auto-extract ok extracted_dir=%s", extracted_dir)
                pre_outputs.append(ex_xml)
                self.memory.add_summary(ex_xml)
                hints_local["extracted_root"] = extracted_dir
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
            plan_xml = self.plan(query)
            steps = re.findall(r"<step[^>]*>(.*?)</step>", plan_xml, flags=re.DOTALL)
            logger.info("Run: executing %d steps sequentially", len(steps))
            outputs: List[str] = pre_outputs[:]
            for step in steps:
                logger.debug("Run: executing step '%s'", step)
                out = self._execute_step(step, query, hints=hints_local)
                outputs.append(out)
                self.memory.add_summary(out)
        summary = compress_outputs(outputs)
        logger.debug("Run: summary chars=%d", len(summary))
        final_doc = wrap_document("".join(outputs) + summary, {"source": "log_agent"})
        logger.info("Run: final doc chars=%d", len(final_doc))
        return final_doc


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
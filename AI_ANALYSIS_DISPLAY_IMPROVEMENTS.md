# AI日志分析显示优化说明

## 问题描述

在前端显示AI分析结果时，显示的内容包含了过多的元数据和重复的结构信息：

1. **LLM输出日志**：包含 `content='...' additional_kwargs={} response_metadata={...}` 等元数据
2. **重复的标题结构**：后端生成的markdown包含 `# 日志分析结果`、`## 📊 执行摘要` 等标题，与前端已有的UI结构重复
3. **XML标签残留**：最终内容中包含 `<document>`、`<context_summary>` 等XML标签

## 解决方案

### 1. 修复LLM响应对象的content提取

**位置**: `compress_outputs()` 函数

**修改前**:
```python
res = llm.invoke(prompt)
logger.info("\n\n--- START LLM OUTPUT [summary] ---\n%s\n--- END LLM OUTPUT [summary] ---\n", str(res))
return wrap_document(str(res), {"type": "summary"})
```

**修改后**:
```python
res = llm.invoke(prompt)
# Extract content from LangChain response object
content = res.content if hasattr(res, "content") else str(res)
logger.info("\n\n--- START LLM OUTPUT [summary] ---\ncontent='%s'\n--- END LLM OUTPUT [summary] ---\n", content)
return wrap_document(content, {"type": "summary"})
```

**说明**: 
- LangChain返回的响应对象有 `.content` 属性存储实际的文本内容
- 直接使用 `str(res)` 会包含所有元数据信息
- 现在只提取和记录纯文本内容

### 2. 优化日志输出格式

**修改的位置**:
- `plan()` 方法的LLM输出日志
- `_execute_step()` 方法的工具选择日志
- `compress_outputs()` 函数的摘要日志

**统一格式**:
```python
logger.info("\n\n--- START LLM OUTPUT [xxx] ---\ncontent='%s'\n--- END LLM OUTPUT [xxx] ---\n", content)
```

**效果**: 日志更清晰，只显示LLM返回的实际内容，便于调试

### 3. 简化最终内容格式化

**位置**: `_format_final_content()` 方法

**修改前**:
```python
def _format_final_content(self, query: str, content: str, summary: str, recommendations: List[str]) -> str:
    """格式化最终内容为标准markdown"""
    markdown = f"""# 日志分析结果

## 📊 执行摘要
{summary}

## 🔍 详细分析
{content}

## 💡 建议措施
...
"""
    return markdown
```

**修改后**:
```python
def _format_final_content(self, query: str, content: str, summary: str, recommendations: List[str]) -> str:
    """格式化最终内容为标准markdown - 仅返回主要发现内容，不包含标题和结构（前端已提供）"""
    # 移除<context_summary>标签及其内容（已在summary字段单独显示）
    clean_content = re.sub(r'<context_summary>.*?</context_summary>', '', content, flags=re.DOTALL)
    
    # 移除其他XML标签但保留内容
    clean_content = re.sub(r'<document[^>]*>|</document>', '', clean_content)
    clean_content = re.sub(r'<[^>]+type="[^"]*"[^>]*>|</[^>]+>', '', clean_content)
    
    # 移除多余的空行
    clean_content = re.sub(r'\n{3,}', '\n\n', clean_content)
    
    return clean_content.strip()
```

**说明**:
- 前端 `AIAnalysisResult.vue` 已经有独立的section显示摘要、建议等
- 后端只需要返回纯净的分析内容，无需添加markdown标题结构
- 移除XML标签和元数据，只保留可读的文本内容

### 4. 改进摘要提取

**位置**: `_extract_summary()` 方法

**改进点**:
1. 优先从 `<context_summary>` 标签中提取LLM生成的摘要
2. 移除XML标签，只保留文本内容
3. 跳过XML标签行，避免元数据污染摘要
4. 限制摘要长度为300字符，便于前端展示

**代码示例**:
```python
# 首先尝试从<context_summary>标签中提取
summary_match = re.search(r'<context_summary>(.*?)</context_summary>', content, flags=re.DOTALL)
if summary_match:
    summary_text = summary_match.group(1).strip()
    # 移除XML标签
    summary_text = re.sub(r'<[^>]+>', '', summary_text)
    if summary_text:
        return summary_text[:300] + ("..." if len(summary_text) > 300 else "")
```

## 前端展示结构

前端 `AIAnalysisResult.vue` 的结构：

```vue
<!-- 执行摘要 -->
<div class="summary-section">
  <h2 class="summary-title">📊 执行摘要</h2>
  <p class="summary-content">{{ result.final_result.summary }}</p>
</div>

<!-- 主要发现 -->
<div class="findings-section">
  <h2 class="findings-title">🔍 主要发现</h2>
  <div class="findings-content prose prose-gray max-w-none" v-html="formatMarkdown(result.final_result.content)"></div>
</div>

<!-- 建议措施 -->
<div class="recommendations-section">
  <h2 class="recommendations-title">💡 建议措施</h2>
  <ul class="recommendations-list">
    <li v-for="(rec, index) in result.final_result.recommendations" :key="index">
      <span class="rec-number">{{ index + 1 }}</span>
      <span class="rec-content">{{ rec }}</span>
    </li>
  </ul>
</div>
```

## 数据流

```
LogAnalysisAgent.run_structured()
  ↓
_generate_final_result()
  ↓
{
  "summary": _extract_summary(content),         // 提取的纯文本摘要
  "content": _format_final_content(...),        // 清理后的分析内容（无XML、无重复标题）
  "recommendations": _extract_recommendations(content)
}
  ↓
前端AIAnalysisResult.vue
  ↓
显示在独立的UI sections中
```

## 效果

### 修改前:
- 日志显示: `content='...' additional_kwargs={...} response_metadata={...}`
- 前端内容: 包含 `# 日志分析结果`、`## 📊 执行摘要` 等重复标题
- 存在XML标签: `<document>`, `<context_summary>` 等

### 修改后:
- 日志显示: 清晰的 `content='...'` 格式
- 前端内容: 纯净的分析文本，由前端UI提供结构和标题
- 无XML标签: 所有元数据和标签已移除

## 注意事项

1. **向后兼容**: 所有修改都保持了API接口不变，只优化了输出格式
2. **错误处理**: 所有格式化方法都有完善的异常处理，确保降级时仍能正常显示
3. **前端渲染**: 前端使用 `formatMarkdown()` 方法将content渲染为HTML，支持基本的markdown语法
4. **日志调试**: 统一的日志格式便于在开发和生产环境中调试LLM输出

## 测试建议

1. 测试AI分析功能，验证前端显示是否清晰无重复
2. 检查日志输出，确认只显示content内容
3. 测试不同类型的日志文件，确保摘要提取正常
4. 验证建议措施的提取和显示是否正确


---

## v2 输出 Schema（Claude Agent SDK 版）

从 Claude Agent SDK 迁移后，`LogRecord.ai_analysis_result` 的 JSON 结构升级为 `schema_version: 2`。

### 完整字段列表

| 字段 | 类型 | 说明 |
|------|------|------|
| `engine` | string | 固定值 `"claude-agent-sdk"` |
| `model` | string | 实际使用的模型 ID（含 provider profile 默认值后解析） |
| `schema_version` | number | `2`（前端可据此与旧 v1 区分） |
| `status` | string | `"ok"` / `"schema_mismatch"` / `"error"` |
| `error_kind` | string? | 见下方枚举，仅 `status="error"` 时存在 |
| `summary` | string | 一段摘要（中文）|
| `severity` | string | `"info"` / `"warn"` / `"error"` / `"critical"` |
| `root_cause_hypotheses` | array | 每项含 `hypothesis`、`evidence`（`["repo:path:line", ...]`）、`confidence` |
| `recommended_actions` | array | 建议措施列表 |
| `related_keywords` | array | 相关关键字 |
| `tool_trace` | array | Agent 工具调用记录，每项含 `name`、`input`（已脱敏）、`output_excerpt`（前 1KiB，已脱敏）|
| `raw` | string | Agent 最终输出原文 |
| `duration_seconds` | number | Agent 运行耗时（秒）|
| `token_usage` | object | `input_tokens`、`output_tokens`、`cache_read_tokens` |

### `error_kind` 枚举

| 值 | 含义 | 建议提示 |
|----|------|---------|
| `missing_archive` | 日志归档文件缺失 | 请上传归档文件后重试 |
| `missing_metadata_json` | 归档中无 `metadata.json` | 请检查日志打包工具是否包含元数据文件 |
| `missing_project_identity` | `metadata.json` 中无项目代号字段 | 请联系日志采集方补全 `project_code` 字段 |
| `project_repo_not_registered` | 项目仓库未在 admin 注册 | 请管理员前往「项目仓库管理」页面添加对应条目 |
| `timeout` | AI 分析超时 | 请联系管理员增大 `ANTHROPIC_REQUEST_TIMEOUT_SECONDS` |
| `schema_mismatch` | Agent 输出未包含合规 JSON | 见 `raw` 字段获取原始输出 |

### 前端兼容建议

1. 检查 `schema_version`：若为 `2`，使用新字段解析；若为 `1` 或不存在，使用旧逻辑。
2. 优先展示 `summary` 与 `root_cause_hypotheses`；`tool_trace` 可折叠展示。
3. `status === "error"` 时，根据 `error_kind` 给出可操作的提示信息（参见上表）。
4. `model` 字段可在 UI 中展示，便于用户了解使用了哪个 AI 服务商。

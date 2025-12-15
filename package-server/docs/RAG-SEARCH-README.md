# RAG 智能搜索功能文档

## 概述

本系统实现了基于 RAG (Retrieval-Augmented Generation) 的智能包搜索功能，使用自然语言查询来搜索和推荐软件包。

## 技术栈

- **后端框架**: Express.js
- **AI 框架**: LangChain
- **大语言模型**: DeepSeek V3.1 (通过 OpenAI 兼容 API)
- **向量嵌入**: @xenova/transformers (本地多语言模型)
- **向量数据库**: FAISS (Facebook AI Similarity Search)
- **前端**: Bootstrap 5 + Vanilla JavaScript

## 功能特性

### 1. 智能搜索
- 使用自然语言描述需求
- AI 自动分析并推荐最合适的包
- 提供详细的选择建议和区别说明

### 2. 相似度搜索
- 基于向量相似度的快速搜索
- 无需调用 LLM，响应更快
- 返回相关度评分

### 3. 索引管理
- 自动向量化所有包信息
- 支持手动重建索引
- 持久化存储，重启后无需重建

### 4. 搜索建议
- AI 生成相关搜索建议
- 提高搜索体验

## API 接口

### 1. 智能搜索
**POST** `/api/search/intelligent`

**请求体**:
```json
{
  "query": "寻找适用于 LingXi-10 的最新完整版本",
  "limit": 5
}
```

**响应**:
```json
{
  "success": true,
  "data": {
    "answer": "AI 生成的详细回答...",
    "relevantPackages": [...],
    "query": "原始查询",
    "searchResultsCount": 5
  }
}
```

### 2. 相似度搜索
**POST** `/api/search/similarity`

**请求体**:
```json
{
  "query": "安全补丁",
  "limit": 5
}
```

**响应**:
```json
{
  "success": true,
  "data": [
    {
      "id": "...",
      "name": "...",
      "relevanceScore": 0.15,
      ...
    }
  ]
}
```

### 3. 重建索引
**POST** `/api/search/rebuild-index`

**响应**:
```json
{
  "success": true,
  "message": "向量索引重建成功，共索引 10 个包"
}
```

### 4. 检查状态
**GET** `/api/search/status`

**响应**:
```json
{
  "success": true,
  "data": {
    "initialized": true,
    "vectorStoreExists": true,
    "embeddingType": "local",
    "totalPackages": 10,
    "config": {
      "baseURL": "http://oneapi.yhroot.com/v1",
      "modelName": "deepseek-v3.1"
    }
  }
}
```

### 5. 获取搜索建议
**POST** `/api/search/suggestions`

**请求体**:
```json
{
  "query": "LingXi"
}
```

**响应**:
```json
{
  "success": true,
  "data": [
    "LingXi 最新版本",
    "LingXi 补丁包",
    ...
  ]
}
```

## 前端使用

### 访问智能搜索页面
打开浏览器访问: `http://localhost:8083/intelligent-search.html`

### 主要功能
1. **自然语言搜索框**: 输入描述性查询
2. **搜索建议**: 点击预设建议快速搜索
3. **AI 回答**: 查看 AI 生成的详细分析
4. **相关包列表**: 浏览匹配的包及相关度评分
5. **包详情**: 查看完整的包信息
6. **直接下载**: 一键下载推荐的包

## 配置说明

### 大模型配置
配置位于 `src/services/RAGService.js`:

```javascript
this.config = {
  apiKey: 'your-api-key',
  baseURL: 'http://oneapi.yhroot.com/v1',
  modelName: 'deepseek-v3.1'
}
```

### 嵌入模型
使用 Xenova 的多语言 MiniLM 模型，自动下载并本地运行。

首次运行时会下载模型文件（约 100MB），请确保网络畅通。

## 搜索示例

### 示例 1: 寻找最新版本
```
查询: "寻找适用于 LingXi-10 的最新完整版本"
结果: 推荐 LingXi-10-V1.3.0-beta-20241114-Full-Stack.tgz
```

### 示例 2: 安全补丁
```
查询: "我需要修复安全漏洞的紧急补丁"
结果: 推荐 LingXi-07A-V2.0.6-patch-20241112-Security-Fix.tgz
```

### 示例 3: 特定组件
```
查询: "包含OAM和核心网组件的包"
结果: 推荐 LingXi-07A-V2.0.5-20241110-OAM-GalaxyCore.tgz
```

### 示例 4: 补丁查询
```
查询: "所有的补丁包"
结果: 列出所有 isPatch 为 true 的包
```

## 性能优化

1. **向量存储持久化**: 索引保存到磁盘，重启后快速加载
2. **本地嵌入模型**: 无需每次调用远程 API
3. **批量处理**: 支持批量向量化
4. **缓存机制**: FAISS 提供高效的向量检索

## 故障排查

### 问题 1: 向量存储未初始化
**解决方案**: 访问智能搜索页面，点击"重建索引"按钮

### 问题 2: 模型下载失败
**解决方案**: 
- 检查网络连接
- 确保有足够的磁盘空间
- 删除 `~/.cache/huggingface` 并重试

### 问题 3: 搜索结果不准确
**解决方案**:
- 尝试使用更具体的描述
- 包含关键词如版本号、组件名称
- 重建索引以确保数据最新

### 问题 4: API 调用失败
**解决方案**:
- 检查 API 密钥是否正确
- 确认 API 服务是否可访问
- 查看服务器日志获取详细错误信息

## 开发和扩展

### 添加新的搜索策略
在 `RAGService.js` 中添加新方法:

```javascript
async customSearch(query, options) {
  // 实现自定义搜索逻辑
}
```

### 修改提示词模板
在 `intelligentSearch` 方法中修改 `PromptTemplate`:

```javascript
const promptTemplate = PromptTemplate.fromTemplate(`
你的自定义提示词...
{context}
{query}
`)
```

### 更换嵌入模型
修改 `LocalEmbeddings` 类中的模型:

```javascript
this.pipelinePromise = pipeline(
  'feature-extraction', 
  'Xenova/your-model-name'
)
```

## 最佳实践

1. **定期重建索引**: 当添加大量新包后
2. **优化查询**: 使用具体、描述性的自然语言
3. **监控性能**: 关注响应时间和资源使用
4. **备份数据**: 定期备份向量存储目录

## 测试数据

使用以下命令生成测试数据:

```bash
cd /path/to/package-server
node scripts/generate-test-data.js
```

这将创建 10 个测试包，包括:
- LingXi-10: 4 个
- LingXi-07A: 3 个
- LingXi-06-TRD: 1 个
- 配置包: 2 个
- 补丁包: 3 个

## 相关文件

- `src/services/RAGService.js`: RAG 服务核心实现
- `src/routes/search.js`: 搜索 API 路由
- `public/intelligent-search.html`: 智能搜索前端页面
- `scripts/generate-test-data.js`: 测试数据生成脚本
- `data/vector-store/`: 向量存储持久化目录

## 未来改进

- [ ] 支持更多语言的查询
- [ ] 添加搜索历史记录
- [ ] 实现用户反馈机制
- [ ] 支持自定义过滤条件
- [ ] 添加搜索分析统计
- [ ] 实现增量索引更新
- [ ] 支持多模态搜索（图片、文档等）

## 许可证

本项目为内部使用，版权归 Galaxy Space 所有。

## 支持

如有问题或建议，请联系开发团队。

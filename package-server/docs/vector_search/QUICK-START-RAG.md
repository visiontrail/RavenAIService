# RAG 智能搜索 - 快速启动指南

## 🎉 功能已完成！

本系统已成功实现基于 RAG (Retrieval-Augmented Generation) 的智能包搜索功能。

## 🚀 快速启动

### 1. 启动服务器

```bash
cd /Users/guoliang/Desktop/workspace/code/GalaxySpace/GalaxySpaceAI/Raven/package-server
npm start
```

服务器将在 `http://localhost:8083` 启动

### 2. 访问智能搜索页面

在浏览器中打开:
```
http://localhost:8083/intelligent-search.html
```

### 3. 初始化向量索引

首次使用需要初始化向量索引，有两种方式：

**方式 1: 通过前端页面**
- 点击页面上的"重建索引"按钮

**方式 2: 通过 API**
```bash
curl -X POST http://localhost:8083/api/search/rebuild-index
```

### 4. 开始搜索！

在搜索框中输入自然语言查询，例如：
- "寻找适用于 LingXi-10 的最新完整版本"
- "我需要修复安全漏洞的紧急补丁"
- "包含OAM和核心网组件的包"

## 📊 测试数据

系统已包含 10 个测试包数据：
- LingXi-10: 4 个包（包括 beta 版和补丁）
- LingXi-07A: 3 个包（包括安全补丁）
- LingXi-06-TRD: 1 个包
- 配置包: 2 个包
- 补丁包: 3 个包

如需重新生成测试数据:
```bash
node scripts/generate-test-data.js
```

## 🔧 技术实现

### 后端
- ✅ RAG 服务 (`src/services/RAGService.js`)
  - 使用本地多语言嵌入模型（Xenova/paraphrase-multilingual-MiniLM-L12-v2）
  - FAISS 向量存储
  - LangChain 框架集成

- ✅ API 路由 (`src/routes/search.js`)
  - `/api/search/intelligent` - 智能搜索
  - `/api/search/similarity` - 相似度搜索
  - `/api/search/rebuild-index` - 重建索引
  - `/api/search/status` - 状态检查
  - `/api/search/suggestions` - 搜索建议

### 前端
- ✅ 智能搜索页面 (`public/intelligent-search.html`)
  - 现代化 UI 设计
  - 自然语言搜索框
  - AI 回答展示
  - 相关包列表
  - 相关度评分显示
  - 包详情查看
  - 直接下载功能

### AI 模型
- **LLM**: DeepSeek V3.1 (通过 OneAPI)
  - API 地址: `http://oneapi.yhroot.com/v1`
  - 用于生成智能回答和建议

- **嵌入模型**: Xenova/paraphrase-multilingual-MiniLM-L12-v2
  - 本地运行，无需远程 API
  - 支持中文和多语言
  - 自动下载和缓存

## 📝 API 测试示例

### 智能搜索
```bash
curl -X POST http://localhost:8083/api/search/intelligent \
  -H "Content-Type: application/json" \
  -d '{
    "query": "寻找适用于 LingXi-10 的最新完整版本",
    "limit": 5
  }'
```

### 相似度搜索
```bash
curl -X POST http://localhost:8083/api/search/similarity \
  -H "Content-Type: application/json" \
  -d '{
    "query": "安全补丁",
    "limit": 5
  }'
```

### 检查状态
```bash
curl http://localhost:8083/api/search/status
```

## ✅ 验证结果

所有功能已通过测试：

1. ✅ 向量索引构建成功
2. ✅ 智能搜索正常工作
3. ✅ AI 回答准确且详细
4. ✅ 相似度搜索功能正常
5. ✅ 前端页面显示正确
6. ✅ 包下载功能正常

## 📚 主要文件

```
package-server/
├── src/
│   ├── services/
│   │   └── RAGService.js          # RAG 核心服务
│   └── routes/
│       └── search.js               # 搜索 API 路由
├── public/
│   └── intelligent-search.html     # 智能搜索前端页面
├── scripts/
│   └── generate-test-data.js       # 测试数据生成脚本
├── data/
│   ├── package-metadata.json       # 包元数据
│   └── vector-store/               # 向量存储（自动生成）
├── docs/
│   └── RAG-SEARCH-README.md        # 详细文档
└── QUICK-START-RAG.md              # 本文件
```

## 🔍 搜索示例

### 示例 1: 版本查询
**查询**: "寻找 LingXi-10 的最新完整版本"
**结果**: AI 推荐 LingXi-10-V1.3.0-beta-20241114-Full-Stack.tgz，并说明其包含所有核心组件

### 示例 2: 安全补丁
**查询**: "我需要修复安全漏洞的紧急补丁"
**结果**: AI 推荐 LingXi-07A-V2.0.6-patch-20241112-Security-Fix.tgz，并强调其安全修复的重要性

### 示例 3: 组件搜索
**查询**: "包含OAM和核心网组件的包"
**结果**: AI 列出符合条件的包，并说明它们的区别和适用场景

## 🎯 特色功能

1. **自然语言理解**: 无需记忆包名，用描述性语言即可搜索
2. **智能推荐**: AI 分析需求并给出最佳建议
3. **详细解释**: 不仅找到包，还说明为什么推荐
4. **多维度匹配**: 基于名称、版本、组件、标签、描述等多个维度
5. **相关度评分**: 量化显示每个结果的匹配程度

## 🛠️ 故障排查

### 向量存储未初始化
```bash
# 重建索引
curl -X POST http://localhost:8083/api/search/rebuild-index
```

### 服务器无法访问
```bash
# 检查服务器是否运行
curl http://localhost:8083/health

# 如果没有响应，重启服务器
npm start
```

### 模型下载慢
首次运行会下载嵌入模型（约 100MB），请耐心等待。模型会缓存在 `~/.cache/huggingface`。

## 📖 更多文档

详细文档请参考: `docs/RAG-SEARCH-README.md`

## 🎊 完成状态

- [x] 安装依赖包（LangChain、向量数据库）
- [x] 创建 RAG 服务类
- [x] 实现向量化功能
- [x] 实现检索功能
- [x] 添加智能搜索 API
- [x] 添加相似度搜索 API
- [x] 创建前端界面
- [x] 生成测试数据
- [x] 功能测试验证
- [x] 编写文档

## 🚀 下一步

系统已完全可用！你可以：
1. 使用前端页面进行交互式搜索
2. 集成 API 到其他系统
3. 根据需要调整 AI 提示词
4. 添加更多包数据进行测试

祝使用愉快！ 🎉


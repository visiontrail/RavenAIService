#!/bin/bash

# Galaxy Space Package Server - ES Module 导入错误修复脚本
# 自动应用修复并重启容器

set -e  # 遇到错误立即退出

CONTAINER_NAME="galaxy-package-server"
PROJECT_ROOT="/home/guoliang/Raven/package-server"
TARGET_FILE="$PROJECT_ROOT/src/services/RAGService.js"

echo "=========================================="
echo "  ES Module 导入错误 - 自动修复"
echo "=========================================="
echo ""

# 检查是否在正确的目录
if [ ! -f "$TARGET_FILE" ]; then
    echo "❌ 错误：找不到文件 $TARGET_FILE"
    echo "   请确保脚本在正确的目录中运行"
    exit 1
fi

echo "1️⃣ 备份原文件..."
BACKUP_FILE="${TARGET_FILE}.backup.$(date +%Y%m%d_%H%M%S)"
cp "$TARGET_FILE" "$BACKUP_FILE"
echo "✅ 已备份到: $BACKUP_FILE"
echo ""

echo "2️⃣ 应用修复补丁..."
cat > /tmp/ragservice_fix.js << 'EOF'
// 使用动态 import 导入 ES Module
let pipelineModule = null

const { FaissStore } = require('@langchain/community/vectorstores/faiss')
const { Document } = require('langchain/document')
const { ChatOpenAI } = require('@langchain/openai')
const { PromptTemplate } = require('@langchain/core/prompts')
const { RunnableSequence } = require('@langchain/core/runnables')
const { StringOutputParser } = require('@langchain/core/output_parsers')
const { Embeddings } = require('@langchain/core/embeddings')
const fs = require('fs-extra')
const path = require('path')

// 动态加载 @xenova/transformers
async function loadPipeline() {
  if (!pipelineModule) {
    const transformers = await import('@xenova/transformers')
    pipelineModule = transformers.pipeline
  }
  return pipelineModule
}

// 自定义本地嵌入类
class LocalEmbeddings extends Embeddings {
  constructor() {
    super({})
    this.pipelinePromise = null
  }

  async ensurePipeline() {
    if (!this.pipelinePromise) {
      console.log('🔄 正在加载本地嵌入模型...')
      const pipeline = await loadPipeline()
      this.pipelinePromise = pipeline('feature-extraction', 'Xenova/paraphrase-multilingual-MiniLM-L12-v2')
      console.log('✅ 本地嵌入模型加载完成')
    }
    return this.pipelinePromise
  }
EOF

# 提取原文件除了前26行的其余部分
tail -n +27 "$TARGET_FILE" >> /tmp/ragservice_fix.js

# 替换原文件
mv /tmp/ragservice_fix.js "$TARGET_FILE"
echo "✅ 修复已应用"
echo ""

echo "3️⃣ 停止旧容器..."
cd "$PROJECT_ROOT"
docker-compose down || echo "⚠️ 容器可能已经停止"
echo ""

echo "4️⃣ 重新构建镜像..."
docker-compose build --no-cache
echo ""

echo "5️⃣ 启动新容器..."
docker-compose up -d
echo ""

echo "6️⃣ 等待容器启动（10秒）..."
sleep 10
echo ""

echo "7️⃣ 检查容器状态..."
docker ps -a | grep $CONTAINER_NAME
echo ""

echo "8️⃣ 查看启动日志..."
docker logs $CONTAINER_NAME --tail=30
echo ""

echo "=========================================="
echo "  修复完成"
echo "=========================================="
echo ""
echo "✅ 如果容器状态显示 'Up'，说明修复成功！"
echo "❌ 如果仍显示 'Restarting'，请查看日志："
echo "   docker logs -f $CONTAINER_NAME"
echo ""
echo "📋 备份文件位置: $BACKUP_FILE"
echo ""


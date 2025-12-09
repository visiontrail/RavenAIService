#!/bin/bash

# Galaxy Space Package Server - 部署检查脚本
# 检查生产环境部署是否准备就绪

set -e

echo "=========================================="
echo "  部署环境检查"
echo "=========================================="
echo ""

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 检查结果
WARNINGS=0
ERRORS=0

# 1. 检查 Docker 是否安装
echo "1. 检查 Docker..."
if command -v docker &> /dev/null; then
    DOCKER_VERSION=$(docker --version)
    echo -e "${GREEN}✓${NC} Docker 已安装: $DOCKER_VERSION"
else
    echo -e "${RED}✗${NC} Docker 未安装"
    ERRORS=$((ERRORS + 1))
fi
echo ""

# 2. 检查 Docker Compose 是否安装
echo "2. 检查 Docker Compose..."
if command -v docker-compose &> /dev/null; then
    COMPOSE_VERSION=$(docker-compose --version)
    echo -e "${GREEN}✓${NC} Docker Compose 已安装: $COMPOSE_VERSION"
elif docker compose version &> /dev/null; then
    COMPOSE_VERSION=$(docker compose version)
    echo -e "${GREEN}✓${NC} Docker Compose V2 已安装: $COMPOSE_VERSION"
else
    echo -e "${RED}✗${NC} Docker Compose 未安装"
    ERRORS=$((ERRORS + 1))
fi
echo ""

# 3. 检查必要文件是否存在
echo "3. 检查项目文件..."
FILES=("Dockerfile" "docker-compose.yml" "package.json" "src/index.js")
for file in "${FILES[@]}"; do
    if [ -f "$file" ]; then
        echo -e "${GREEN}✓${NC} $file"
    else
        echo -e "${RED}✗${NC} $file 不存在"
        ERRORS=$((ERRORS + 1))
    fi
done
echo ""

# 4. 检查依赖配置
echo "4. 检查 RAG 依赖..."
RAG_DEPS=("langchain" "@langchain/openai" "@langchain/community" "faiss-node" "@xenova/transformers")
for dep in "${RAG_DEPS[@]}"; do
    if grep -q "\"$dep\"" package.json; then
        echo -e "${GREEN}✓${NC} $dep 已配置"
    else
        echo -e "${RED}✗${NC} $dep 未配置"
        ERRORS=$((ERRORS + 1))
    fi
done
echo ""

# 5. 检查磁盘空间
echo "5. 检查磁盘空间..."
DISK_USAGE=$(df -h . | awk 'NR==2 {print $5}' | sed 's/%//')
DISK_AVAIL=$(df -h . | awk 'NR==2 {print $4}')
if [ "$DISK_USAGE" -lt 80 ]; then
    echo -e "${GREEN}✓${NC} 磁盘空间充足: $DISK_AVAIL 可用"
else
    echo -e "${YELLOW}!${NC} 磁盘空间紧张: $DISK_AVAIL 可用（使用率 $DISK_USAGE%）"
    WARNINGS=$((WARNINGS + 1))
fi
echo ""

# 6. 检查内存
echo "6. 检查系统内存..."
if command -v free &> /dev/null; then
    TOTAL_MEM=$(free -g | awk 'NR==2 {print $2}')
    AVAIL_MEM=$(free -g | awk 'NR==2 {print $7}')
    if [ "$AVAIL_MEM" -ge 2 ]; then
        echo -e "${GREEN}✓${NC} 可用内存充足: ${AVAIL_MEM}GB / ${TOTAL_MEM}GB"
    else
        echo -e "${YELLOW}!${NC} 可用内存较少: ${AVAIL_MEM}GB / ${TOTAL_MEM}GB（推荐至少 2GB）"
        WARNINGS=$((WARNINGS + 1))
    fi
else
    echo -e "${YELLOW}!${NC} 无法检查内存（非 Linux 系统）"
fi
echo ""

# 7. 检查网络连接
echo "7. 检查网络连接..."
if curl -s --connect-timeout 5 https://registry.npmjs.org &> /dev/null; then
    echo -e "${GREEN}✓${NC} NPM 仓库可访问"
else
    echo -e "${YELLOW}!${NC} NPM 仓库不可访问，建议配置镜像源"
    WARNINGS=$((WARNINGS + 1))
fi

if curl -s --connect-timeout 5 https://huggingface.co &> /dev/null; then
    echo -e "${GREEN}✓${NC} HuggingFace 可访问"
else
    echo -e "${YELLOW}!${NC} HuggingFace 不可访问，模型下载可能失败"
    echo -e "    ${YELLOW}建议：${NC}在 docker-compose.yml 中设置 HF_ENDPOINT=https://hf-mirror.com"
    WARNINGS=$((WARNINGS + 1))
fi
echo ""

# 8. 检查是否有旧容器运行
echo "8. 检查容器状态..."
if docker ps -a | grep -q "galaxy-package-server"; then
    STATUS=$(docker ps -a --filter "name=galaxy-package-server" --format "{{.Status}}")
    echo -e "${YELLOW}!${NC} 发现已存在的容器: $STATUS"
    echo "    提示: 使用 ./scripts/restart.sh 重新部署"
    WARNINGS=$((WARNINGS + 1))
else
    echo -e "${GREEN}✓${NC} 无旧容器冲突"
fi
echo ""

# 9. 检查端口占用
echo "9. 检查端口 8083..."
if command -v lsof &> /dev/null; then
    if lsof -Pi :8083 -sTCP:LISTEN -t &> /dev/null; then
        echo -e "${YELLOW}!${NC} 端口 8083 已被占用"
        lsof -Pi :8083 -sTCP:LISTEN
        WARNINGS=$((WARNINGS + 1))
    else
        echo -e "${GREEN}✓${NC} 端口 8083 可用"
    fi
else
    echo -e "${YELLOW}!${NC} 无法检查端口（lsof 未安装）"
fi
echo ""

# 10. 检查 RAG 服务文件
echo "10. 检查 RAG 服务文件..."
RAG_FILES=("src/services/RAGService.js" "src/routes/search.js" "public/intelligent-search.html")
for file in "${RAG_FILES[@]}"; do
    if [ -f "$file" ]; then
        echo -e "${GREEN}✓${NC} $file"
    else
        echo -e "${RED}✗${NC} $file 不存在"
        ERRORS=$((ERRORS + 1))
    fi
done
echo ""

# 总结
echo "=========================================="
echo "  检查结果"
echo "=========================================="
echo ""

if [ $ERRORS -eq 0 ] && [ $WARNINGS -eq 0 ]; then
    echo -e "${GREEN}✓✓✓ 所有检查通过！环境准备就绪。${NC}"
    echo ""
    echo "可以执行以下命令开始部署："
    echo "  docker-compose up -d --build"
    echo ""
    echo "或使用脚本："
    echo "  ./scripts/restart.sh"
elif [ $ERRORS -eq 0 ]; then
    echo -e "${YELLOW}⚠ 检查完成，发现 $WARNINGS 个警告${NC}"
    echo ""
    echo "可以继续部署，但建议先处理警告项"
else
    echo -e "${RED}✗ 检查失败，发现 $ERRORS 个错误和 $WARNINGS 个警告${NC}"
    echo ""
    echo "请先解决错误项，然后重新运行此检查"
    exit 1
fi

echo ""
echo "=========================================="


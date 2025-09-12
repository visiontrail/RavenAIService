#!/bin/bash

# 日志暂存服务启动脚本

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}🚀 日志暂存服务启动脚本${NC}"
echo "================================"

# 检查Python版本
python_version=$(python3 --version 2>&1)
echo -e "${BLUE}Python版本:${NC} $python_version"

# 检查虚拟环境
if [ ! -d "venv" ]; then
    echo -e "${YELLOW}⚠️  虚拟环境不存在，正在创建...${NC}"
    python3 -m venv venv
    echo -e "${GREEN}✅ 虚拟环境创建成功${NC}"
fi

# 激活虚拟环境
echo -e "${BLUE}🔧 激活虚拟环境...${NC}"
source venv/bin/activate

# 检查并安装依赖
echo -e "${BLUE}📦 检查依赖包...${NC}"
if ! pip show fastapi > /dev/null 2>&1; then
    echo -e "${YELLOW}⚠️  正在安装依赖包...${NC}"
    pip install fastapi uvicorn python-dotenv psutil pydantic pydantic-settings starlette python-multipart click h11 --upgrade --prefer-binary
    echo -e "${GREEN}✅ 依赖包安装完成${NC}"
else
    echo -e "${GREEN}✅ 依赖包已安装${NC}"
fi

# 检查必要目录
echo -e "${BLUE}📁 检查项目目录...${NC}"
mkdir -p logs temp
echo -e "${GREEN}✅ 目录检查完成${NC}"

# 设置环境变量
if [ ! -f ".env" ] && [ -f ".env.example" ]; then
    echo -e "${YELLOW}⚠️  .env文件不存在，从模板复制...${NC}"
    cp .env.example .env
    echo -e "${GREEN}✅ .env文件创建成功${NC}"
fi

# 启动服务
echo -e "${BLUE}🎯 启动日志暂存服务...${NC}"
echo "================================"
echo -e "${GREEN}服务地址: http://localhost:8085${NC}"
echo -e "${GREEN}API文档: http://localhost:8085/docs${NC}"
echo -e "${GREEN}健康检查: http://localhost:8085/health${NC}"
echo "================================"
echo -e "${YELLOW}按 Ctrl+C 停止服务${NC}"
echo ""

# 启动FastAPI应用
uvicorn app.main:app --host 0.0.0.0 --port 8085 --reload
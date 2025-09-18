# 使用Python 3.11 slim镜像作为基础镜像
FROM python:3.11-slim

# 设置环境变量
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    TZ=Asia/Shanghai

# 安装系统依赖
RUN apt-get update && apt-get install -y \
    tar \
    gzip \
    curl \
    wget \
    unzip \
    build-essential \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# 创建应用用户（非root用户）
RUN groupadd -r appuser && useradd -r -g appuser appuser

# 设置工作目录
WORKDIR /app

# 复制requirements文件并安装Python依赖
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# 创建必要的目录
RUN mkdir -p logs temp uploads && \
    chown -R appuser:appuser /app

# 复制应用代码
COPY --chown=appuser:appuser . .

# 复制tool_log_decompress工具（如果存在）
# COPY --chown=appuser:appuser tools/tool_log_decompress /usr/local/bin/
# RUN chmod +x /usr/local/bin/tool_log_decompress

# 设置权限
RUN chmod +x start.sh start_all.sh start_celery.sh && \
    chown -R appuser:appuser /app

# 切换到非root用户
USER appuser

# 暴露端口
EXPOSE 8085

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8085/health || exit 1

# 设置启动命令
CMD ["./start_all.sh"]
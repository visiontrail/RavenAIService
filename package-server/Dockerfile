# 使用官方 Node.js 运行时作为基础镜像
# 注意：faiss-node 需要编译，使用完整版而非 alpine
FROM node:18

# 设置工作目录
WORKDIR /app

# 安装系统依赖（用于编译 faiss-node）
RUN apt-get update && apt-get install -y \
    python3 \
    make \
    g++ \
    cmake \
    && rm -rf /var/lib/apt/lists/*

# 复制 package.json 和 package-lock.json（如果存在）
COPY package*.json ./

# 安装项目依赖
# 注意：不使用 --only=production，因为 faiss-node 需要编译依赖
RUN npm ci

# 复制项目文件
COPY . .

# 创建必要的目录
RUN mkdir -p uploads data

# 预下载嵌入模型（可选，减少首次启动时间）
# 如果不想在构建时下载，可以注释掉这一行
RUN echo "console.log('预加载模型...'); const { pipeline } = require('@xenova/transformers'); pipeline('feature-extraction', 'Xenova/paraphrase-multilingual-MiniLM-L12-v2').then(() => console.log('模型预加载完成')).catch(e => console.log('模型预加载失败（首次运行时会自动下载）:', e.message));" | node || true

# 设置目录权限
RUN chown -R node:node /app && \
    chmod -R 755 /app && \
    chmod -R 777 /app/uploads /app/data

# 切换到非 root 用户
USER node

# 暴露端口
EXPOSE 8083

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
  CMD node -e "require('http').get('http://localhost:8083/health', (res) => { process.exit(res.statusCode === 200 ? 0 : 1); }).on('error', () => process.exit(1));"

# 启动应用
CMD ["npm", "start"]

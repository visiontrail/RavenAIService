const express = require('express')
const path = require('path')
const cors = require('cors')
const fs = require('fs')
const PackageServiceSingleton = require('./services/PackageServiceSingleton')
const getRAGServiceInstance = require('./services/RAGServiceSingleton')
const { getUploadsDir } = require('./config/paths')

// 导入路由
const packagesRouter = require('./routes/packages')
const uploadRouter = require('./routes/upload')
const downloadRouter = require('./routes/download')
const searchRouter = require('./routes/search')

const app = express()
const PORT = process.env.PORT || 8083
const normalizeBasePath = (basePath) => {
  if (!basePath) return '/raven'
  let normalized = basePath.trim()
  if (!normalized.startsWith('/')) normalized = `/${normalized}`
  normalized = normalized.replace(/\/+$/, '')
  return normalized || '/raven'
}
const BASE_PATH = normalizeBasePath(process.env.RAVEN_BASE_PATH || process.env.BASE_PATH)
const API_PREFIX = `${BASE_PATH}/api`
const ENABLE_LEGACY_PATHS = (process.env.RAVEN_ENABLE_LEGACY_PATHS || 'true').toLowerCase() !== 'false'
const escapeJsValue = (value = '') => String(value).replace(/\\/g, '\\\\').replace(/'/g, "\\'")
const FRONTEND_DIST_DIR = path.resolve(__dirname, '../../frontend/dist')
const LEGACY_PUBLIC_DIR = path.resolve(__dirname, '../public')
const FRONTEND_DIR = fs.existsSync(FRONTEND_DIST_DIR) ? FRONTEND_DIST_DIR : LEGACY_PUBLIC_DIR
const LOG_API_BASE_URL =
  (process.env.LOG_API_BASE_URL || process.env.RAVEN_LOG_API_BASE_URL || '').trim()
const LOG_API_PORT = process.env.LOG_API_PORT || process.env.LOG_SERVER_PORT || '8085'
const UPLOAD_DIR = getUploadsDir()
const packageService = new PackageServiceSingleton()
const ragService = getRAGServiceInstance()

// 确保上传目录存在
if (!fs.existsSync(UPLOAD_DIR)) {
  fs.mkdirSync(UPLOAD_DIR, { recursive: true })
}

// 中间件配置
app.use(cors())
app.use(express.json())
app.use(express.urlencoded({ extended: true }))

// 请求日志中间件
app.use((req, res, next) => {
  console.log(`${req.method} ${req.path} - 收到请求`)
  next()
})

// 持久化前端基础配置，供静态页面读取
const writeFrontendConfig = () => {
  const targets = [FRONTEND_DIR]
  if (FRONTEND_DIR !== LEGACY_PUBLIC_DIR) {
    targets.push(LEGACY_PUBLIC_DIR)
  }

  const content = `;(function(){\n` +
    `  const configuredLogApiBase = '${escapeJsValue(LOG_API_BASE_URL)}';\n` +
    `  const serverPort = '${escapeJsValue(PORT)}';\n` +
    `  const fallbackLogPort = '${escapeJsValue(LOG_API_PORT)}';\n` +
    `  const defaultBasePath = '${escapeJsValue(BASE_PATH)}';\n` +
    `  const deriveLogApiBase = () => {\n` +
    `    if (configuredLogApiBase) return configuredLogApiBase;\n` +
    `    if (typeof window === 'undefined') return '';\n` +
    `    const { protocol, hostname, port, origin } = window.location;\n` +
    `    if (port === serverPort && fallbackLogPort) {\n` +
    `      return protocol + '//' + hostname + ':' + fallbackLogPort;\n` +
    `    }\n` +
    `    return origin;\n` +
    `  };\n` +
    `  window.__RAVEN_BASE_PATH__ = defaultBasePath;\n` +
    `  window.__LOG_API_BASE_URL__ = deriveLogApiBase();\n` +
    `  window.__RAVEN_SERVER_PORT__ = serverPort;\n` +
    `})();\n`

  for (const dir of targets) {
    try {
      fs.mkdirSync(dir, { recursive: true })
      const configPath = path.join(dir, 'raven-config.js')
      const existing = fs.existsSync(configPath) ? fs.readFileSync(configPath, 'utf8') : ''
      if (existing.trim() !== content.trim()) {
        fs.writeFileSync(configPath, content, 'utf8')
      }
    } catch (error) {
      console.warn('⚠️ 无法写入 Raven 前端配置文件:', error.message || error)
    }
  }
}

writeFrontendConfig()

// 静态文件服务（优先使用与 8085 同步的前端构建产物）
app.use(
  BASE_PATH,
  express.static(FRONTEND_DIR, {
    index: 'index.html'
  })
)

// 兼容直接访问根路径
if (ENABLE_LEGACY_PATHS && BASE_PATH !== '/') {
  app.use(
    '/',
    express.static(FRONTEND_DIR, {
      index: 'index.html'
    })
  )
}

const assetsDir = path.join(FRONTEND_DIR, 'assets')
if (fs.existsSync(assetsDir)) {
  app.use('/assets', express.static(assetsDir))
}

const viteSvgPath = path.join(FRONTEND_DIR, 'vite.svg')
if (fs.existsSync(viteSvgPath)) {
  app.get('/vite.svg', (req, res) => res.sendFile(viteSvgPath))
}

const ravenConfigPath = fs.existsSync(path.join(FRONTEND_DIR, 'raven-config.js'))
  ? path.join(FRONTEND_DIR, 'raven-config.js')
  : path.join(LEGACY_PUBLIC_DIR, 'raven-config.js')
if (fs.existsSync(ravenConfigPath)) {
  app.get('/raven-config.js', (req, res) => res.sendFile(ravenConfigPath))
}

// 保留智能搜索独立页面（文档引用的旧版入口）
app.get(
  [
    `${BASE_PATH}/intelligent-search`,
    `${BASE_PATH}/intelligent-search.html`,
    '/intelligent-search',
    '/intelligent-search.html'
  ],
  (req, res, next) => {
    const target = path.join(LEGACY_PUBLIC_DIR, 'intelligent-search.html')
    if (!fs.existsSync(target)) return next()
    res.sendFile(target)
  }
)

// API 路由
app.use(`${API_PREFIX}/packages`, packagesRouter)
app.use(`${API_PREFIX}/upload`, uploadRouter)
app.use(`${API_PREFIX}/download`, downloadRouter)
app.use(`${API_PREFIX}/search`, searchRouter)

// 兼容旧版 /api 前缀
if (ENABLE_LEGACY_PATHS && BASE_PATH !== '/') {
  app.use('/api/packages', packagesRouter)
  app.use('/api/upload', uploadRouter)
  app.use('/api/download', downloadRouter)
  app.use('/api/search', searchRouter)
}

// 健康检查
app.get('/health', (req, res) => {
  res.json({
    status: 'ok',
    timestamp: new Date().toISOString(),
    uptime: process.uptime()
  })
})

// SPA 路由回退，确保与 8085 端口的前端展示一致
app.get('*', (req, res, next) => {
  if (req.method !== 'GET') return next()

  // 跳过 API 和健康检查
  if (req.path === '/health') return next()
  if (req.path.startsWith(API_PREFIX) || (ENABLE_LEGACY_PATHS && req.path.startsWith('/api'))) return next()

  // 跳过静态资源请求
  if (req.path.includes('.')) return next()

  const indexPath = path.join(FRONTEND_DIR, 'index.html')
  if (!fs.existsSync(indexPath)) return next()

  return res.sendFile(indexPath)
})

// 启动时检查并初始化智能搜索向量索引
async function initializeRagIndexOnStartup() {
  try {
    console.log('🧠 启动检查: 正在验证智能搜索向量索引状态...')
    const packages = await packageService.getAllPackages()
    const ready = await ragService.ensureInitialized(packages)

    if (ready) {
      console.log('✅ 智能搜索服务在线，向量索引已就绪')
    } else if (packages.length === 0) {
      console.log('ℹ️ 暂无包数据，跳过向量索引初始化')
    } else {
      console.warn('⚠️ 向量索引未初始化完成，请稍后尝试手动重建')
    }
  } catch (error) {
    console.error('❌ 启动时检查智能搜索索引失败:', error)
  }
}

initializeRagIndexOnStartup()

// 404 处理
app.use('*', (req, res) => {
  res.status(404).json({
    success: false,
    message: '接口不存在'
  })
})

// 错误处理中间件
app.use((error, req, res, next) => {
  console.error('Server error:', error)
  const status = error?.status || 500
  res.status(status).json({
    success: false,
    message: error?.message || '服务器内部错误'
  })
})

// 启动服务器
const server = app.listen(PORT, () => {
  console.log(`\n🚀 Galaxy Package Server 启动成功!`)
  console.log(`📦 服务地址: http://localhost:${PORT}${BASE_PATH}`)
  console.log(`📁 上传目录: ${UPLOAD_DIR}`)
  console.log(`📂 路由前缀: ${BASE_PATH} (API: ${API_PREFIX})`)
  console.log(`⚡ 环境: ${process.env.NODE_ENV || 'development'}`)
  console.log(`\n访问 http://localhost:${PORT}${BASE_PATH} 开始使用包管理系统\n`)
})

// 移除默认超时时间，避免大文件上传被意外中断
server.headersTimeout = 0
server.requestTimeout = 0

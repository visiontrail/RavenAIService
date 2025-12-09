const express = require('express')
const getRAGServiceInstance = require('../services/RAGServiceSingleton')
const PackageServiceSingleton = require('../services/PackageServiceSingleton')

const router = express.Router()

// 创建服务实例
const ragService = getRAGServiceInstance()
const packageService = new PackageServiceSingleton()

/**
 * POST /api/search/intelligent
 * 智能搜索接口
 */
router.post('/intelligent', async (req, res) => {
  try {
    const { query, limit = 5 } = req.body

    if (!query || query.trim().length === 0) {
      return res.status(400).json({
        success: false,
        message: '搜索查询不能为空'
      })
    }

    console.log(`🔍 收到智能搜索请求: "${query}"`)

    // 获取所有包用于初始化和详细信息检索
    const packages = await packageService.getAllPackages()
    await ragService.ensureInitialized(packages)

    // 执行智能搜索
    const result = await ragService.intelligentSearch(query, packages, parseInt(limit))

    res.json({
      success: true,
      data: result
    })
  } catch (error) {
    console.error('❌ 智能搜索失败:', error)
    res.status(500).json({
      success: false,
      message: '智能搜索失败: ' + error.message
    })
  }
})

/**
 * POST /api/search/suggestions
 * 获取搜索建议
 */
router.post('/suggestions', async (req, res) => {
  try {
    const { query } = req.body

    if (!query || query.trim().length === 0) {
      return res.json({
        success: true,
        data: []
      })
    }

    console.log(`💡 获取搜索建议: "${query}"`)

    const suggestions = await ragService.getSearchSuggestions(query)

    res.json({
      success: true,
      data: suggestions
    })
  } catch (error) {
    console.error('❌ 获取搜索建议失败:', error)
    res.status(500).json({
      success: false,
      message: '获取搜索建议失败: ' + error.message
    })
  }
})

/**
 * POST /api/search/rebuild-index
 * 重建向量索引
 */
router.post('/rebuild-index', async (req, res) => {
  try {
    console.log('🔄 开始重建向量索引...')

    const packages = await packageService.getAllPackages()
    await ragService.rebuildVectorStore(packages)

    res.json({
      success: true,
      message: `向量索引重建成功，共索引 ${packages.length} 个包`
    })
  } catch (error) {
    console.error('❌ 重建向量索引失败:', error)
    res.status(500).json({
      success: false,
      message: '重建向量索引失败: ' + error.message
    })
  }
})

/**
 * GET /api/search/status
 * 获取 RAG 服务状态
 */
router.get('/status', async (req, res) => {
  try {
    const packages = await packageService.getAllPackages()
    await ragService.ensureInitialized(packages)
    const status = ragService.getStatus()

    res.json({
      success: true,
      data: {
        ...status,
        totalPackages: packages.length
      }
    })
  } catch (error) {
    console.error('❌ 获取服务状态失败:', error)
    res.status(500).json({
      success: false,
      message: '获取服务状态失败: ' + error.message
    })
  }
})

/**
 * POST /api/search/similarity
 * 简单的相似度搜索（不使用 LLM）
 */
router.post('/similarity', async (req, res) => {
  try {
    const { query, limit = 5 } = req.body

    if (!query || query.trim().length === 0) {
      return res.status(400).json({
        success: false,
        message: '搜索查询不能为空'
      })
    }

    console.log(`🔍 收到相似度搜索请求: "${query}"`)

    // 确保向量存储已初始化
    const packages = await packageService.getAllPackages()
    await ragService.ensureInitialized(packages)

    // 执行相似度搜索
    const results = await ragService.similaritySearch(query, parseInt(limit))

    // 获取完整的包信息
    const enrichedResults = results.map(result => {
      const pkg = packages.find(p => p.id === result.id)
      return pkg ? { ...pkg, relevanceScore: result.score } : null
    }).filter(pkg => pkg !== null)

    res.json({
      success: true,
      data: enrichedResults
    })
  } catch (error) {
    console.error('❌ 相似度搜索失败:', error)
    res.status(500).json({
      success: false,
      message: '相似度搜索失败: ' + error.message
    })
  }
})

module.exports = router

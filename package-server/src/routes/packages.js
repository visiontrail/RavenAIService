const express = require('express')
const PackageServiceSingleton = require('../services/PackageServiceSingleton')
const router = express.Router()

// 创建PackageService单例实例
const packageService = new PackageServiceSingleton()

// 获取所有包列表
router.get('/', async (req, res) => {
  try {
    console.log('GET /api/packages - 请求参数:', req.query)

    const {
      page = 1,
      limit = 10,
      search = '',
      type = '',
      tags = '',
      isPatch = '',
      sortBy = 'createdAt',
      sortOrder = 'desc'
    } = req.query

    let packages = await packageService.getAllPackages()
    console.log('获取到的包数量:', packages.length)

    // 搜索过滤
    if (search) {
      const searchLower = search.toLowerCase()
      packages = packages.filter(
        (pkg) => pkg.name.toLowerCase().includes(searchLower) || pkg.version.toLowerCase().includes(searchLower)
      )
    }

    // 包类型过滤 (使用packageType字段)
    if (type) {
      packages = packages.filter((pkg) => pkg.packageType === type)
    }

    // 标签过滤
    if (tags) {
      const tagsLower = tags.toLowerCase()
      packages = packages.filter((pkg) => {
        if (!pkg.metadata || !pkg.metadata.tags) return false
        return pkg.metadata.tags.some((tag) => tag.toLowerCase().includes(tagsLower))
      })
    }

    // 补丁类型过滤
    if (isPatch !== '') {
      const isPatchBool = isPatch === 'true'
      packages = packages.filter((pkg) => {
        if (!pkg.metadata) return false
        return pkg.metadata.isPatch === isPatchBool
      })
    }

    // 排序
    packages.sort((a, b) => {
      let aVal = a[sortBy]
      let bVal = b[sortBy]

      if (sortBy === 'createdAt') {
        aVal = new Date(aVal)
        bVal = new Date(bVal)
      }

      if (sortOrder === 'desc') {
        return bVal > aVal ? 1 : -1
      } else {
        return aVal > bVal ? 1 : -1
      }
    })

    // 分页
    const startIndex = (page - 1) * limit
    const endIndex = startIndex + parseInt(limit)
    const paginatedPackages = packages.slice(startIndex, endIndex)

    res.json({
      success: true,
      data: {
        packages: paginatedPackages,
        pagination: {
          currentPage: parseInt(page),
          totalPages: Math.ceil(packages.length / limit),
          totalItems: packages.length,
          itemsPerPage: parseInt(limit)
        }
      }
    })
  } catch (error) {
    console.error('Error fetching packages:', error)
    res.status(500).json({
      success: false,
      message: '获取包列表失败'
    })
  }
})

// 根据ID获取单个包信息
router.get('/:id', async (req, res) => {
  try {
    const { id } = req.params
    const packageInfo = await packageService.getPackageById(id)

    if (!packageInfo) {
      return res.status(404).json({
        success: false,
        message: '包不存在'
      })
    }

    res.json({
      success: true,
      data: packageInfo
    })
  } catch (error) {
    console.error('Error fetching package:', error)
    res.status(500).json({
      success: false,
      message: '获取包信息失败'
    })
  }
})

// 删除包
router.delete('/:id', async (req, res) => {
  try {
    const { id } = req.params
    const success = await packageService.deletePackage(id)

    if (success) {
      res.json({
        success: true,
        message: '包删除成功'
      })
    } else {
      res.status(404).json({
        success: false,
        message: '包不存在或删除失败'
      })
    }
  } catch (error) {
    console.error('Error deleting package:', error)
    res.status(500).json({
      success: false,
      message: '删除包失败'
    })
  }
})

// 手动扫描uploads目录
router.post('/scan', async (req, res) => {
  try {
    console.log('POST /api/packages/scan - 手动扫描uploads目录')
    await packageService.scanUploadsDirectory()

    res.json({
      success: true,
      message: '扫描完成'
    })
  } catch (error) {
    console.error('Error scanning uploads directory:', error)
    res.status(500).json({
      success: false,
      message: '扫描失败'
    })
  }
})

// 获取统计信息
router.get('/stats/overview', async (req, res) => {
  try {
    console.log('GET /api/packages/stats/overview - 请求统计信息')
    const packages = await packageService.getAllPackages()
    console.log('统计信息 - 包数量:', packages.length)

    const stats = {
      totalPackages: packages.length,
      packagesByType: {},
      recentPackages: packages
        .sort((a, b) => new Date(b.createdAt) - new Date(a.createdAt))
        .slice(0, 5)
        .map((pkg) => ({
          id: pkg.id,
          name: pkg.name,
          version: pkg.version,
          createdAt: pkg.createdAt
        }))
    }

    // 按类型统计
    packages.forEach((pkg) => {
      const type = pkg.packageType || 'unknown'
      stats.packagesByType[type] = (stats.packagesByType[type] || 0) + 1
    })

    res.json({
      success: true,
      data: stats
    })
  } catch (error) {
    console.error('Error fetching stats:', error)
    res.status(500).json({
      success: false,
      message: '获取统计信息失败'
    })
  }
})

module.exports = router

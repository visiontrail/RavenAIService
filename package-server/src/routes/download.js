const express = require('express')
const fs = require('fs-extra')
const archiver = require('archiver')
const PackageServiceSingleton = require('../services/PackageServiceSingleton')

const router = express.Router()
const packageService = new PackageServiceSingleton()

// 根据ID下载单个包
router.get('/:id', async (req, res) => {
  try {
    const packageId = req.params.id
    const packageInfo = await packageService.getPackageById(packageId)

    if (!packageInfo) {
      return res.status(404).json({ error: 'Package not found' })
    }

    const filePath = packageInfo.path

    // Check if file exists
    if (!(await fs.pathExists(filePath))) {
      return res.status(404).json({ error: 'Package file not found' })
    }

    // Set appropriate headers
    res.setHeader('Content-Disposition', `attachment; filename="${packageInfo.name}"`)
    res.setHeader('Content-Type', 'application/gzip')

    // Stream the file
    const fileStream = fs.createReadStream(filePath)
    fileStream.pipe(res)

    fileStream.on('error', (error) => {
      console.error('File stream error:', error)
      if (!res.headersSent) {
        res.status(500).json({ error: 'Failed to download package' })
      }
    })
  } catch (error) {
    console.error('Download error:', error)
    res.status(500).json({ error: 'Failed to download package' })
  }
})

// 批量下载多个包（打包成zip）
router.post('/batch', async (req, res) => {
  try {
    const { packageIds } = req.body

    if (!packageIds || !Array.isArray(packageIds) || packageIds.length === 0) {
      return res.status(400).json({ error: 'Package IDs are required' })
    }

    // Get package information for all requested IDs
    const packages = []
    for (const id of packageIds) {
      const packageInfo = await packageService.getPackageById(id)
      if (packageInfo && (await fs.pathExists(packageInfo.path))) {
        packages.push(packageInfo)
      }
    }

    if (packages.length === 0) {
      return res.status(404).json({ error: 'No valid packages found' })
    }

    // Set response headers for zip download
    const timestamp = new Date().toISOString().replace(/[:.]/g, '-')
    const zipFilename = `packages-${timestamp}.zip`

    res.setHeader('Content-Disposition', `attachment; filename="${zipFilename}"`)
    res.setHeader('Content-Type', 'application/zip')

    // Create zip archive
    const archive = archiver('zip', {
      zlib: { level: 9 } // Maximum compression
    })

    // Handle archive errors
    archive.on('error', (error) => {
      console.error('Archive error:', error)
      if (!res.headersSent) {
        res.status(500).json({ error: 'Failed to create archive' })
      }
    })

    // Pipe archive to response
    archive.pipe(res)

    // Add files to archive
    for (const pkg of packages) {
      archive.file(pkg.path, { name: pkg.name })
    }

    // Finalize the archive
    await archive.finalize()
  } catch (error) {
    console.error('Batch download error:', error)
    if (!res.headersSent) {
      res.status(500).json({ error: 'Failed to download packages' })
    }
  }
})

// 根据类型批量下载包
router.get('/type/:packageType', async (req, res) => {
  try {
    const { packageType } = req.params
    const { version } = req.query

    // Get all packages of the specified type
    const allPackages = await packageService.getAllPackages()
    let filteredPackages = allPackages.filter((pkg) => pkg.packageType === packageType)

    // Filter by version if specified
    if (version) {
      filteredPackages = filteredPackages.filter((pkg) => pkg.version === version)
    }

    if (filteredPackages.length === 0) {
      return res.status(404).json({ error: 'No packages found for the specified criteria' })
    }

    // If only one package, download it directly
    if (filteredPackages.length === 1) {
      const packageInfo = filteredPackages[0]
      const filePath = packageInfo.path

      if (!(await fs.pathExists(filePath))) {
        return res.status(404).json({ error: 'Package file not found' })
      }

      res.setHeader('Content-Disposition', `attachment; filename="${packageInfo.name}"`)
      res.setHeader('Content-Type', 'application/gzip')

      const fileStream = fs.createReadStream(filePath)
      fileStream.pipe(res)

      return
    }

    // Multiple packages - create zip archive
    const timestamp = new Date().toISOString().replace(/[:.]/g, '-')
    const zipFilename = `${packageType}-packages-${timestamp}.zip`

    res.setHeader('Content-Disposition', `attachment; filename="${zipFilename}"`)
    res.setHeader('Content-Type', 'application/zip')

    const archive = archiver('zip', {
      zlib: { level: 9 }
    })

    archive.on('error', (error) => {
      console.error('Archive error:', error)
      if (!res.headersSent) {
        res.status(500).json({ error: 'Failed to create archive' })
      }
    })

    archive.pipe(res)

    // Add valid packages to archive
    for (const pkg of filteredPackages) {
      if (await fs.pathExists(pkg.path)) {
        archive.file(pkg.path, { name: pkg.name })
      }
    }

    await archive.finalize()
  } catch (error) {
    console.error('Type download error:', error)
    if (!res.headersSent) {
      res.status(500).json({ error: 'Failed to download packages' })
    }
  }
})

// 获取下载统计
router.get('/stats', async (req, res) => {
  try {
    const packages = await packageService.getPackages()

    const stats = {
      totalDownloads: 0, // TODO: 实现下载计数
      popularPackages: packages.slice(0, 5), // 前5个包作为热门包
      downloadsByType: {}
    }

    // 按类型统计
    packages.forEach((pkg) => {
      if (!stats.downloadsByType[pkg.type]) {
        stats.downloadsByType[pkg.type] = 0
      }
      stats.downloadsByType[pkg.type]++
    })

    res.json({
      success: true,
      data: stats
    })
  } catch (error) {
    console.error('Download stats error:', error)
    res.status(500).json({
      success: false,
      message: '获取下载统计失败'
    })
  }
})

module.exports = router

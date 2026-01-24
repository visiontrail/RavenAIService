const express = require('express')
const multer = require('multer')
const path = require('path')
const fs = require('fs-extra')
const PackageServiceSingleton = require('../services/PackageServiceSingleton')
const getRAGServiceInstance = require('../services/RAGServiceSingleton')
const { getUploadsDir } = require('../config/paths')

const router = express.Router()
const UPLOAD_DIR = getUploadsDir()
const packageService = new PackageServiceSingleton()
const ragService = getRAGServiceInstance()

// Configure multer for file uploads
const storage = multer.diskStorage({
  destination: (req, file, cb) => {
    fs.ensureDirSync(UPLOAD_DIR)
    cb(null, UPLOAD_DIR)
  },
  filename: (req, file, cb) => {
    // Keep original filename
    cb(null, file.originalname)
  }
})

const MAX_FILE_SIZE_MB = parseInt(process.env.UPLOAD_MAX_SIZE_MB || '500', 10)
const upload = multer({
  storage,
  limits: {
    fileSize: MAX_FILE_SIZE_MB * 1024 * 1024 // configurable (default 500MB)
  },
  fileFilter: (req, file, cb) => {
    // Only allow .tgz and .tar.gz files
    const allowedExtensions = ['.tgz', '.tar.gz']
    const isValidExtension = allowedExtensions.some((ext) => file.originalname.toLowerCase().endsWith(ext))

    if (isValidExtension) {
      cb(null, true)
    } else {
      cb(new Error('Only .tgz and .tar.gz files are allowed'), false)
    }
  }
})

/**
 * Wrap multer middleware so we can catch and normalize errors
 */
const withMulter = (multerMiddleware) => (req, res, next) => {
  let aborted = false

  req.on('aborted', () => {
    aborted = true
    console.warn('⚠️ 上传请求在传输过程中被客户端中断')
  })

  multerMiddleware(req, res, async (err) => {
    if (!err) return next()

    console.error('❌ 上传中间件错误:', err)

    // 清理已写入的临时文件
    const cleanupTargets = []
    if (req.file?.path) cleanupTargets.push(req.file.path)
    if (Array.isArray(req.files)) {
      req.files.forEach((f) => f?.path && cleanupTargets.push(f.path))
    }
    await Promise.all(
      cleanupTargets.map((p) =>
        fs
          .remove(p)
          .catch((cleanupErr) => console.warn('⚠️ 清理临时文件失败:', p, cleanupErr.message || cleanupErr))
      )
    )

    // 常见错误类型友好提示
    if (err.code === 'LIMIT_FILE_SIZE') {
      return res.status(413).json({
        success: false,
        error: `文件过大，超过 ${MAX_FILE_SIZE_MB}MB 限制`
      })
    }

    if (err.code === 'LIMIT_UNEXPECTED_FILE' || err.message === 'Unexpected end of form') {
      return res.status(400).json({
        success: false,
        error: '上传请求体不完整或被中断，请重试（可检查网络/反向代理的 body 大小限制）'
      })
    }

    if (aborted) {
      return res.status(499).json({
        success: false,
        error: '上传已被客户端中断'
      })
    }

    return res.status(400).json({
      success: false,
      error: err.message || '上传失败'
    })
  })
}

// Upload single package
router.post('/', withMulter(upload.single('file')), async (req, res) => {
  console.log('POST /api/upload - 收到上传请求')

  try {
    if (!req.file) {
      return res.status(400).json({ error: '没有上传文件' })
    }

    console.log('上传文件信息:', req.file)

    // 打印原始HTTP请求信息
    console.log('=== 服务器端接收到的HTTP请求详细信息 ===')
    console.log('请求方法:', req.method)
    console.log('请求URL:', req.url)
    console.log('请求头:', JSON.stringify(req.headers, null, 2))
    console.log('请求体字段 (req.body):', JSON.stringify(req.body, null, 2))
    console.log('上传文件信息 (req.file):', JSON.stringify(req.file, null, 2))

    // Check if complete package info was sent from client
    let finalPackageInfo
    if (req.body.packageInfo) {
      console.log('收到客户端发送的完整包信息')
      const clientPackageInfo = JSON.parse(req.body.packageInfo)
      console.log('解析后的客户端包信息:', JSON.stringify(clientPackageInfo, null, 2))

      // Use client package info but update the file path to the uploaded location
      finalPackageInfo = {
        ...clientPackageInfo,
        path: req.file.path,
        // Update size with actual uploaded file size
        size: req.file.size
      }
      console.log('使用客户端包信息，更新文件路径:', finalPackageInfo)
    } else {
      // Fallback: Extract package metadata from file (legacy behavior)
      console.log('未收到客户端包信息，开始提取包元数据...')
      const extractedPackageInfo = await packageService.extractPackageMetadata(req.file.path)
      console.log('提取的包信息:', extractedPackageInfo)

      // Extract version and other base fields from request body
      const { version, packageType, ...metadataFields } = req.body
      // Merge with any additional metadata from request body
      const metadata = {
        ...extractedPackageInfo.metadata,
        ...metadataFields
      }

      finalPackageInfo = {
        ...extractedPackageInfo,
        metadata,
        // Override base fields if provided in request
        ...(version && { version }),
        ...(packageType && { packageType })
      }
    }

    // Add package to service
    console.log('开始添加包到服务...')
    const result = await packageService.addPackage(finalPackageInfo)
    console.log('添加包结果:', result)

    let vectorIndexRebuild = 'skipped'
    if (result) {
      console.log('🔄 上传完成，开始重建向量索引...')
      try {
        const packages = await packageService.getAllPackages()
        await ragService.rebuildVectorStore(packages)
        vectorIndexRebuild = 'success'
        console.log('✅ 向量索引重建完成（上传触发）')
      } catch (err) {
        vectorIndexRebuild = `failed: ${err.message || err}`
        console.error('⚠️ 向量索引重建失败（已忽略，上传继续）:', err)
      }
    } else {
      console.warn('⚠️ 包添加失败，跳过索引重建')
    }

    const response = {
      success: true,
      message: '包上传成功',
      package: finalPackageInfo
    }

    if (vectorIndexRebuild !== 'success') {
      response.vectorIndexRebuild = vectorIndexRebuild
      response.warning = '包已上传，但向量索引未完成，请稍后重试重建索引'
    }

    res.json(response)
  } catch (error) {
    console.error('Upload error:', error)

    // Clean up uploaded file on error
    if (req.file && req.file.path) {
      try {
        await fs.remove(req.file.path)
      } catch (cleanupError) {
        console.error('Failed to cleanup file:', cleanupError)
      }
    }

    res.status(500).json({
      success: false,
      error: error.message || '上传失败'
    })
  }
})

// Upload multiple packages
router.post('/batch', withMulter(upload.array('files', 10)), async (req, res) => {
  try {
    if (!req.files || req.files.length === 0) {
      return res.status(400).json({ error: '没有上传文件' })
    }

    const results = []
    const errors = []

    for (const file of req.files) {
      try {
        // Extract package metadata
        const packageInfo = await packageService.extractPackageMetadata(file.path)

        // Merge with any additional metadata from request body
        const metadata = {
          ...packageInfo.metadata,
          ...req.body
        }

        const finalPackageInfo = {
          ...packageInfo,
          metadata
        }

        // Add package to service
        await packageService.addPackage(finalPackageInfo)
        results.push(finalPackageInfo)
      } catch (error) {
        console.error(`Error processing file ${file.originalname}:`, error)
        errors.push({
          filename: file.originalname,
          error: error.message
        })

        // Clean up file on error
        try {
          await fs.remove(file.path)
        } catch (cleanupError) {
          console.error('Failed to cleanup file:', cleanupError)
        }
      }
    }

    let vectorIndexRebuild = 'skipped'
    if (results.length > 0) {
      console.log('🔄 批量上传完成，开始重建向量索引...')
      try {
        const packages = await packageService.getAllPackages()
        await ragService.rebuildVectorStore(packages)
        vectorIndexRebuild = 'success'
        console.log('✅ 批量上传触发的向量索引重建完成')
      } catch (err) {
        vectorIndexRebuild = `failed: ${err.message || err}`
        console.error('⚠️ 批量上传后向量索引重建失败（已忽略）:', err)
      }
    }

    res.json({
      success: true,
      message: `成功上传 ${results.length} 个包`,
      packages: results,
      errors: errors.length > 0 ? errors : undefined,
      ...(vectorIndexRebuild !== 'success' && {
        vectorIndexRebuild,
        warning: '部分包已上传，但向量索引未完成，请稍后重试重建索引'
      })
    })
  } catch (error) {
    console.error('Batch upload error:', error)
    res.status(500).json({
      success: false,
      error: error.message || '批量上传失败'
    })
  }
})

// Get upload progress (for future implementation with WebSocket or SSE)
router.get('/progress/:uploadId', (req, res) => {
  // This would be implemented with a proper upload progress tracking system
  // For now, return a simple response
  res.json({
    uploadId: req.params.uploadId,
    progress: 100,
    status: 'completed'
  })
})

module.exports = router

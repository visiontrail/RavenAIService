// API 基础配置
const DEFAULT_BASE_PATH = '/raven'
const RAVEN_BASE_PATH =
  (window.__RAVEN_BASE_PATH__ || DEFAULT_BASE_PATH).replace(/\/$/, '') || DEFAULT_BASE_PATH
const API_BASE = `${RAVEN_BASE_PATH}/api`
const PACKAGES_API = `${API_BASE}/packages`
const UPLOAD_API = `${API_BASE}/upload`
const DOWNLOAD_API = `${API_BASE}/download`

// 全局状态
let currentPage = 1
let totalPages = 1
let currentPackages = []

// 页面初始化
document.addEventListener('DOMContentLoaded', function () {
  initializeApp()
  setupEventListeners()
})

// 初始化应用
function initializeApp() {
  console.log('🚀 初始化应用开始')
  syncNavigationLinks()

  // 检查关键DOM元素是否存在
  const packageListSection = document.getElementById('packageListSection')
  const packageList = document.getElementById('packageList')
  const searchSection = document.getElementById('searchSection')

  console.log('📋 DOM元素检查:')
  console.log('- packageListSection:', packageListSection ? '存在' : '不存在')
  console.log('- packageList:', packageList ? '存在' : '不存在')
  console.log('- searchSection:', searchSection ? '存在' : '不存在')

  // loadPackageTypes()
  loadPackages()
  // loadStats()
  setupEventListeners()
  showPackages()

  console.log('✅ 初始化应用完成')
}

function syncNavigationLinks() {
  const homeUrl = `${RAVEN_BASE_PATH}/`
  document.querySelectorAll('.navbar-brand, [data-raven-link="home"]').forEach((link) => {
    link.setAttribute('href', homeUrl)
  })
  document.querySelectorAll('[data-raven-link="upload"]').forEach((link) => {
    link.setAttribute('href', `${homeUrl}#uploadSection`)
  })
  document.querySelectorAll('[data-raven-link="search"]').forEach((link) => {
    link.setAttribute('href', `${RAVEN_BASE_PATH}/intelligent-search.html`)
  })
}

// 设置事件监听器
function setupEventListeners() {
  // 搜索输入框事件
  document.getElementById('searchInput').addEventListener('input', debounce(searchPackages, 300))

  // 筛选器事件
  document.getElementById('typeFilter').addEventListener('change', searchPackages)
  document.getElementById('versionFilter').addEventListener('input', debounce(searchPackages, 300))
  document.getElementById('tagsFilter').addEventListener('input', debounce(searchPackages, 300))
  document.getElementById('patchFilter').addEventListener('change', searchPackages)

  // 文件上传事件
  const fileInput = document.getElementById('fileInput')
  const uploadZone = document.getElementById('uploadZone')

  fileInput.addEventListener('change', handleFileSelect)

  // 拖拽上传事件
  uploadZone.addEventListener('dragover', handleDragOver)
  uploadZone.addEventListener('dragleave', handleDragLeave)
  uploadZone.addEventListener('drop', handleDrop)
  uploadZone.addEventListener('click', () => fileInput.click())

  // 标签输入功能
  setupTagsInput()
  setupComponentsInput()

  // 取消上传按钮事件
  document.getElementById('cancelUploadBtn').addEventListener('click', cancelUpload)
}

// 防抖函数
function debounce(func, wait) {
  let timeout
  return function executedFunction(...args) {
    const later = () => {
      clearTimeout(timeout)
      func(...args)
    }
    clearTimeout(timeout)
    timeout = setTimeout(later, wait)
  }
}

// 显示提示信息
function showAlert(message, type = 'info') {
  const alertId = 'alert-' + Date.now()

  // 定义不同类型的颜色和图标
  const alertConfig = {
    success: { color: '#059669', bgColor: '#d1fae5', icon: 'bi-check-circle-fill' },
    error: { color: '#dc2626', bgColor: '#fee2e2', icon: 'bi-x-circle-fill' },
    warning: { color: '#d97706', bgColor: '#fef3c7', icon: 'bi-exclamation-triangle-fill' },
    info: { color: '#2563eb', bgColor: '#dbeafe', icon: 'bi-info-circle-fill' }
  }

  const config = alertConfig[type] || alertConfig.info

  const alertHtml = `
    <div id="${alertId}" class="toast-alert" style="
      position: fixed;
      top: 20px;
      right: 20px;
      z-index: 9999;
      width: min(400px, calc(100vw - 40px));
      max-width: calc(100vw - 40px);
      background: white;
      border-radius: 12px;
      box-shadow: 0 10px 25px rgba(0, 0, 0, 0.15);
      border-left: 4px solid ${config.color};
      padding: 16px 20px;
      display: flex;
      align-items: center;
      gap: 12px;
      animation: slideInRight 0.3s ease-out;
      font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
    ">
      <div style="
        width: 24px;
        height: 24px;
        border-radius: 50%;
        background: ${config.bgColor};
        display: flex;
        align-items: center;
        justify-content: center;
        flex-shrink: 0;
      ">
        <i class="bi ${config.icon}" style="color: ${config.color}; font-size: 14px;"></i>
      </div>
      <div style="flex: 1; color: #374151; font-size: 14px; line-height: 1.4;">
        ${message}
      </div>
      <button onclick="document.getElementById('${alertId}').remove()" style="
        background: none;
        border: none;
        color: #9ca3af;
        cursor: pointer;
        padding: 4px;
        border-radius: 4px;
        display: flex;
        align-items: center;
        justify-content: center;
        transition: all 0.2s ease;
      " onmouseover="this.style.background='#f3f4f6'; this.style.color='#6b7280'" onmouseout="this.style.background='none'; this.style.color='#9ca3af'">
        <i class="bi bi-x" style="font-size: 16px;"></i>
      </button>
    </div>
  `

  // 添加CSS动画样式（如果还没有添加）
  if (!document.getElementById('toast-alert-styles')) {
    const style = document.createElement('style')
    style.id = 'toast-alert-styles'
    style.textContent = `
      @keyframes slideInRight {
        from {
          transform: translateX(100%);
          opacity: 0;
        }
        to {
          transform: translateX(0);
          opacity: 1;
        }
      }
      
      @keyframes slideOutRight {
        from {
          transform: translateX(0);
          opacity: 1;
        }
        to {
          transform: translateX(100%);
          opacity: 0;
        }
      }
      
      .toast-alert.removing {
        animation: slideOutRight 0.3s ease-in forwards;
      }

      @media (max-width: 768px) {
        .toast-alert {
          top: 12px !important;
          left: 12px !important;
          right: 12px !important;
          width: calc(100vw - 24px) !important;
          max-width: calc(100vw - 24px) !important;
          padding: 12px 14px !important;
        }
      }
    `
    document.head.appendChild(style)
  }

  document.body.insertAdjacentHTML('beforeend', alertHtml)

  // 自动移除提示
  setTimeout(() => {
    const alert = document.getElementById(alertId)
    if (alert) {
      alert.classList.add('removing')
      setTimeout(() => {
        alert.remove()
      }, 300)
    }
  }, 5000)
}

// 格式化文件大小
function formatFileSize(bytes) {
  if (bytes === 0) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i]
}

// 将文本中的特殊字符进行 HTML 转义，避免 XSS
function escapeHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

// 简易 Markdown 解析器（在 marked 不可用时的回退实现）
function basicMarkdownToHtml(md) {
  if (!md) return ''

  const lines = String(md).split(/\r?\n/)
  let html = ''
  let inUl = false
  let inOl = false
  let inCode = false
  let codeBuffer = []

  const flushLists = () => {
    if (inUl) {
      html += '</ul>'
      inUl = false
    }
    if (inOl) {
      html += '</ol>'
      inOl = false
    }
  }

  const flushCode = () => {
    if (inCode) {
      html += `<pre><code>${codeBuffer.join('\n')}</code></pre>`
      inCode = false
      codeBuffer = []
    }
  }

  for (let rawLine of lines) {
    const line = rawLine

    // 代码块切换
    if (/^```/.test(line)) {
      if (!inCode) {
        flushLists()
        inCode = true
        codeBuffer = []
      } else {
        // 结束代码块
        html += `<pre><code>${codeBuffer.join('\n')}</code></pre>`
        inCode = false
        codeBuffer = []
      }
      continue
    }

    if (inCode) {
      codeBuffer.push(escapeHtml(line))
      continue
    }

    // 水平分割线
    if (/^---+$/.test(line.trim())) {
      flushLists()
      html += '<hr>'
      continue
    }

    // 标题（#、##、###）
    if (/^###\s+/.test(line)) {
      flushLists()
      html += `<h6>${escapeHtml(line.replace(/^###\s+/, ''))}</h6>`
      continue
    }
    if (/^##\s+/.test(line)) {
      flushLists()
      html += `<h5>${escapeHtml(line.replace(/^##\s+/, ''))}</h5>`
      continue
    }
    if (/^#\s+/.test(line)) {
      flushLists()
      html += `<h4>${escapeHtml(line.replace(/^#\s+/, ''))}</h4>`
      continue
    }

    // 无序列表项
    if (/^\s*[-*+]\s+/.test(line)) {
      if (!inUl) {
        flushCode()
        html += '<ul>'
        inUl = true
      }
      const content = line.replace(/^\s*[-*+]\s+/, '')
      html += `<li>${escapeHtml(content)}</li>`
      continue
    }

    // 有序列表项
    if (/^\s*\d+\.\s+/.test(line)) {
      if (!inOl) {
        flushCode()
        html += '<ol>'
        inOl = true
      }
      const content = line.replace(/^\s*\d+\.\s+/, '')
      html += `<li>${escapeHtml(content)}</li>`
      continue
    }

    // 普通段落或空行
    if (line.trim() === '') {
      flushLists()
      html += '<br>'
    } else {
      flushLists()
      let text = escapeHtml(line)
      // 加粗 **text**
      text = text.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
      // 斜体 *text*
      text = text.replace(/(^|\s)\*(.+?)\*(?=\s|$)/g, '$1<em>$2</em>')
      // 行内代码 `code`
      text = text.replace(/`([^`]+)`/g, '<code>$1</code>')
      // 链接 [text](url)
      text = text.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>')
      html += `<p>${text}</p>`
    }
  }

  // 收尾
  flushLists()
  flushCode()
  return html
}

// 安全地渲染 Markdown 内容（优先使用 marked，失败则使用回退解析器）
function renderMarkdown(text) {
  if (!text) return ''

  // 优先使用 marked（若可用）
  if (typeof window !== 'undefined' && window.marked) {
    try {
      window.marked.setOptions({
        breaks: true,
        gfm: true,
        // 新版 marked 移除了 sanitize；关闭 headerIds/mangle 以避免不必要的处理
        headerIds: false,
        mangle: false,
        smartLists: true,
        smartypants: true
      })
      return window.marked.parse(text)
    } catch (error) {
      console.error('Marked 渲染失败，使用回退解析器:', error)
      return basicMarkdownToHtml(text)
    }
  }

  // 当 CDN 不可达或未加载 marked 时，使用本地回退解析器
  return basicMarkdownToHtml(text)
}

// 格式化日期
function formatDate(dateString) {
  const date = new Date(dateString)
  return date.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit'
  })
}

// 获取包类型显示名称
function getPackageTypeDisplay(type) {
  const typeMap = {
    'lingxi-10': 'LingXi-10',
    'lingxi-07a': 'LingXi-07A',
    'ka-tx': 'KaTx',
    'ka-rx': 'KaRx',
    config: '配置包',
    'lingxi-06-thrid': 'LingXi-06-TRD',
    unknown: '未知类型'
  }
  return typeMap[type] || type
}

// 获取包类型颜色
function getPackageTypeColor(type) {
  const colorMap = {
    'lingxi-10': 'primary',
    'lingxi-07a': 'success',
    'ka-tx': 'danger',
    'ka-rx': 'dark',
    config: 'warning',
    'lingxi-06-thrid': 'info',
    unknown: 'secondary'
  }
  return colorMap[type] || 'secondary'
}

// 加载统计信息（在统计DOM缺失时安全跳过）
async function loadStats() {
  try {
    // 若统计信息区域未渲染（例如在 index.html 中被注释），则直接跳过
    const totalEl = document.getElementById('totalPackages')
    const sizeEl = document.getElementById('totalSize')
    const recentEl = document.getElementById('recentUploads')
    const typesEl = document.getElementById('packageTypes')

    if (!totalEl || !sizeEl || !recentEl || !typesEl) {
      console.log('统计信息区域不存在，跳过加载统计信息')
      return
    }

    const response = await fetch(`${PACKAGES_API}/stats/overview`)
    if (!response.ok) throw new Error('获取统计信息失败')

    const result = await response.json()

    if (result.success && result.data) {
      const stats = result.data
      totalEl.textContent = stats.totalPackages || 0
      sizeEl.textContent = formatFileSize(stats.totalSize || 0)
      recentEl.textContent = stats.recentPackages ? stats.recentPackages.length : 0
      typesEl.textContent = Object.keys(stats.packagesByType || {}).length
    } else {
      throw new Error(result.message || '获取统计信息失败')
    }
  } catch (error) {
    console.error('加载统计信息失败:', error)
    showAlert('加载统计信息失败', 'warning')
  }
}

// 加载包列表
async function loadPackages(page = 1) {
  try {
    console.log('📦 loadPackages called with page:', page)
    showLoading(true)

    // 安全获取DOM元素值
    const searchInput = document.getElementById('searchInput')
    const typeFilter = document.getElementById('typeFilter')
    const versionFilter = document.getElementById('versionFilter')
    const tagsFilter = document.getElementById('tagsFilter')
    const patchFilter = document.getElementById('patchFilter')
    const dateFromFilter = document.getElementById('dateFromFilter')
    const dateToFilter = document.getElementById('dateToFilter')

    console.log('🔍 表单元素检查:')
    console.log('- searchInput:', searchInput ? '存在' : '不存在')
    console.log('- typeFilter:', typeFilter ? '存在' : '不存在')
    console.log('- versionFilter:', versionFilter ? '存在' : '不存在')
    console.log('- tagsFilter:', tagsFilter ? '存在' : '不存在')
    console.log('- patchFilter:', patchFilter ? '存在' : '不存在')
    console.log('- dateFromFilter:', dateFromFilter ? '存在' : '不存在')
    console.log('- dateToFilter:', dateToFilter ? '存在' : '不存在')

    const params = new URLSearchParams({
      page: page,
      limit: 10,
      search: searchInput ? searchInput.value || '' : '',
      type: typeFilter ? typeFilter.value || '' : '',
      version: versionFilter ? versionFilter.value || '' : '',
      tags: tagsFilter ? tagsFilter.value || '' : '',
      isPatch: patchFilter ? patchFilter.value || '' : '',
      dateFrom: dateFromFilter ? dateFromFilter.value || '' : '',
      dateTo: dateToFilter ? dateToFilter.value || '' : ''
    })

    console.log('Fetching packages with params:', params.toString())
    const response = await fetch(`${PACKAGES_API}?${params}`)
    if (!response.ok) throw new Error('获取包列表失败')

    const result = await response.json()
    console.log('API response:', result)

    if (result.success && result.data) {
      currentPackages = result.data.packages || []
      currentPage = result.data.pagination?.currentPage || 1
      totalPages = result.data.pagination?.totalPages || 1
      console.log('Set currentPackages to:', currentPackages)
    } else {
      throw new Error(result.message || '获取包列表失败')
    }

    renderPackageList()
    renderPagination()
  } catch (error) {
    console.error('加载包列表失败:', error)
    showAlert('加载包列表失败', 'danger')
  } finally {
    showLoading(false)
  }
}

// 渲染包列表
function renderPackageList() {
  console.log('🎨 renderPackageList called with currentPackages:', currentPackages)
  const packageList = document.getElementById('packageList')

  if (!packageList) {
    console.error('❌ packageList 元素不存在')
    return
  }

  console.log('📦 当前包数量:', currentPackages ? currentPackages.length : 0)

  if (!currentPackages || currentPackages.length === 0) {
    console.log('📭 显示空状态')
    packageList.innerHTML = `
            <div class="text-center py-5">
                <i class="bi bi-inbox fs-1 text-muted mb-3"></i>
                <h5 class="text-muted">暂无包文件</h5>
                <p class="text-muted">点击上传按钮添加新的包文件</p>
            </div>
        `
    return
  }

  console.log('🎯 开始渲染包列表')

  const packagesHtml = currentPackages
    .map((pkg) => {
      // 安全地转义字符串以防止HTML注入和JavaScript错误
      const escapedId = pkg.id.replace(/'/g, "\\'").replace(/"/g, '&quot;')
      const escapedName = pkg.name.replace(/'/g, "\\'").replace(/"/g, '&quot;')
      // 使用SHA-256哈希值替代文件路径显示，如果没有则显示文件路径
      const displayValue = pkg.metadata && pkg.metadata.sha256 ? pkg.metadata.sha256 : pkg.path
      const escapedDisplayValue = displayValue.replace(/'/g, "\\'").replace(/"/g, '&quot;')

      return `
        <div class="package-item card mb-3" onclick="showPackageDetail('${escapedId}')" style="cursor: pointer;">
            <div class="card-body">
                <div class="package-row">
                    <div class="package-main">
                        <h6 class="mb-1">
                            <i class="bi bi-box-seam me-2 text-primary"></i>
                            ${escapedName}
                        </h6>
                        <p class="mb-1 text-muted small package-hash">sha256: ${escapedDisplayValue}</p>
                        <div class="d-flex align-items-center flex-wrap gap-1">
                            <span class="badge bg-${getPackageTypeColor(pkg.packageType)} package-type-badge me-2">
                                ${getPackageTypeDisplay(pkg.packageType)}
                            </span>
                            <span class="badge bg-light text-dark package-type-badge me-2">
                                v${pkg.version}
                            </span>
                            ${(() => {
                              const components = getComponentsArray(pkg.metadata?.components)
                              return components && components.length > 0
                                ? components
                                    .map(
                                      (c) =>
                                        `<span class="badge bg-success text-white package-type-badge">${c.name}</span>`
                                    )
                                    .join(' ')
                                : ''
                            })()}
                            ${(() => {
                              const tags = getTagsArray(pkg.metadata?.tags)
                              return tags && tags.length > 0
                                ? tags
                                    .map(
                                      (tag) =>
                                        `<span class="badge package-type-badge" style="background-color: #b794f6; color: white;">${tag}</span>`
                                    )
                                    .join(' ')
                                : ''
                            })()}
                        </div>
                        ${(() => {
                          const desc = pkg.metadata?.description
                          if (!desc) return ''
                          const escapedDesc = desc.replace(/"/g, '&quot;')
                          return `<div class="mt-2 text-muted small" style="white-space: nowrap; overflow: hidden; text-overflow: ellipsis;" title="${escapedDesc}">${desc}</div>`
                        })()}
                    </div>
                    <div class="package-meta text-end">
                        <small class="text-muted d-block">
                            <i class="bi bi-calendar3 me-1"></i>
                            ${formatDate(pkg.createdAt)}
                        </small>
                        <small class="file-size d-block">
                            <i class="bi bi-hdd me-1"></i>
                            ${formatFileSize(pkg.size)}
                        </small>
                    </div>
                    <div class="package-actions text-end">
                        <div class="btn-group" role="group">
                            <button class="btn btn-outline-primary btn-sm" onclick="event.stopPropagation(); downloadPackage('${escapedId}')">
                                <i class="bi bi-download"></i>
                            </button>
                            <button class="btn btn-outline-info btn-sm" onclick="event.stopPropagation(); showPackageDetail('${escapedId}')">
                                <i class="bi bi-eye"></i>
                            </button>
                            <button class="btn btn-outline-danger btn-sm" onclick="event.stopPropagation(); confirmDeletePackage('${escapedId}', '${escapedName}')">
                                <i class="bi bi-trash"></i>
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        </div>
        `
    })
    .join('')

  packageList.innerHTML = packagesHtml
}

// 渲染分页
function renderPagination() {
  const pagination = document.getElementById('pagination')

  if (totalPages <= 1) {
    pagination.innerHTML = ''
    return
  }

  let paginationHtml = '<ul class="pagination">'

  // 上一页
  paginationHtml += `
        <li class="page-item ${currentPage === 1 ? 'disabled' : ''}">
            <a class="page-link" href="#" onclick="loadPackages(${currentPage - 1})">
                <i class="bi bi-chevron-left"></i>
            </a>
        </li>
    `

  // 页码
  const startPage = Math.max(1, currentPage - 2)
  const endPage = Math.min(totalPages, currentPage + 2)

  for (let i = startPage; i <= endPage; i++) {
    paginationHtml += `
            <li class="page-item ${i === currentPage ? 'active' : ''}">
                <a class="page-link" href="#" onclick="loadPackages(${i})">${i}</a>
            </li>
        `
  }

  // 下一页
  paginationHtml += `
        <li class="page-item ${currentPage === totalPages ? 'disabled' : ''}">
            <a class="page-link" href="#" onclick="loadPackages(${currentPage + 1})">
                <i class="bi bi-chevron-right"></i>
            </a>
        </li>
    `

  paginationHtml += '</ul>'
  pagination.innerHTML = paginationHtml
}

// 显示/隐藏加载状态
function showLoading(show) {
  const loadingSpinner = document.getElementById('loadingSpinner')
  const packageList = document.getElementById('packageList')

  if (show) {
    loadingSpinner.style.display = 'block'
    packageList.style.display = 'none'
  } else {
    loadingSpinner.style.display = 'none'
    packageList.style.display = 'block'
  }
}

// 搜索包
function searchPackages() {
  currentPage = 1
  loadPackages(1)
}

// 清除筛选条件
// eslint-disable-next-line @typescript-eslint/no-unused-vars
function clearFilters() {
  document.getElementById('searchInput').value = ''
  document.getElementById('typeFilter').value = ''
  document.getElementById('versionFilter').value = ''
  document.getElementById('tagsFilter').value = ''
  document.getElementById('patchFilter').value = ''
  searchPackages()
}

// 刷新包列表
function refreshPackages() {
  loadPackages(currentPage)
  loadStats()
}

// 显示包列表页面
function showPackages() {
  console.log('📦 显示包列表页面')

  const packageListSection = document.getElementById('packageListSection')
  const uploadSection = document.getElementById('uploadSection')
  const searchSection = document.getElementById('searchSection')

  if (packageListSection) {
    packageListSection.style.display = 'block'
    console.log('✅ packageListSection 设置为显示')
  } else {
    console.error('❌ packageListSection 元素不存在')
  }

  if (uploadSection) {
    uploadSection.style.display = 'none'
  }

  if (searchSection) {
    searchSection.style.display = 'block'
    console.log('✅ searchSection 设置为显示')
  }

  console.log('📦 包列表页面显示完成')
}

// 显示上传页面
// eslint-disable-next-line @typescript-eslint/no-unused-vars
function showUpload() {
  document.getElementById('packageListSection').style.display = 'none'
  document.getElementById('uploadSection').style.display = 'block'
  document.getElementById('searchSection').style.display = 'none'
}

// 显示统计页面 - 暂时注释掉未使用的函数
// function showStats() {
//   showPackages()
//   loadStats()
// }

// 文件选择处理
function handleFileSelect(event) {
  const files = event.target.files
  if (files.length > 0) {
    displaySelectedFiles(files)
    showMetadataForm()
  }
}

// 拖拽处理
function handleDragOver(event) {
  event.preventDefault()
  event.currentTarget.classList.add('dragover')
}

function handleDragLeave(event) {
  event.preventDefault()
  event.currentTarget.classList.remove('dragover')
}

function handleDrop(event) {
  event.preventDefault()
  event.currentTarget.classList.remove('dragover')

  const files = event.dataTransfer.files
  if (files.length > 0) {
    // 设置文件到input中
    document.getElementById('fileInput').files = files
    displaySelectedFiles(files)
    showMetadataForm()
  }
}

// 显示选中的文件
function displaySelectedFiles(files) {
  const selectedFilesDisplay = document.getElementById('selectedFilesDisplay')
  const selectedFilesList = document.getElementById('selectedFilesList')

  if (files.length === 0) {
    selectedFilesDisplay.style.display = 'none'
    return
  }

  let filesHtml = ''
  for (let i = 0; i < files.length; i++) {
    const file = files[i]
    const fileSize = formatFileSize(file.size)
    const fileIcon =
      file.name.endsWith('.tgz') || file.name.endsWith('.tar.gz') ? 'bi-file-earmark-zip' : 'bi-file-earmark'

    filesHtml += `
      <div class="d-flex align-items-center justify-content-between mb-2 p-2 border rounded bg-white">
        <div class="d-flex align-items-center">
          <i class="bi ${fileIcon} text-primary me-2"></i>
          <div>
            <div class="fw-medium">${file.name}</div>
            <small class="text-muted">${fileSize}</small>
          </div>
        </div>
        <button class="btn btn-sm btn-outline-danger" onclick="removeSelectedFile(${i})">
          <i class="bi bi-x"></i>
        </button>
      </div>
    `
  }

  selectedFilesList.innerHTML = filesHtml
  selectedFilesDisplay.style.display = 'block'
}

// 移除选中的文件
function removeSelectedFile(index) {
  const fileInput = document.getElementById('fileInput')
  const dt = new DataTransfer()

  for (let i = 0; i < fileInput.files.length; i++) {
    if (i !== index) {
      dt.items.add(fileInput.files[i])
    }
  }

  fileInput.files = dt.files

  if (fileInput.files.length === 0) {
    document.getElementById('selectedFilesDisplay').style.display = 'none'
    document.getElementById('metadataForm').style.display = 'none'
  } else {
    displaySelectedFiles(fileInput.files)
  }
}

// 上传文件
// 显示metadata表单
function showMetadataForm() {
  document.getElementById('metadataForm').style.display = 'block'
}

// 重置metadata表单
function resetMetadataForm() {
  document.getElementById('isPatch').value = 'false'
  document.getElementById('description').value = ''
  clearAllComponents()
  document.getElementById('packageType').value = 'lingxi-10'
  document.getElementById('version').value = ''
  document.getElementById('metadataForm').style.display = 'none'
  document.getElementById('fileInput').value = ''
  document.getElementById('selectedFilesDisplay').style.display = 'none'
  clearAllTags()
  // 重置标签输入框
  const tagInput = document.getElementById('tagInput')
  if (tagInput) tagInput.value = ''
  const componentInput = document.getElementById('componentInput')
  if (componentInput) componentInput.value = ''
}

// 收集metadata数据
function collectMetadata() {
  const isPatch = document.getElementById('isPatch').value === 'true'
  const description = document.getElementById('description').value.trim()
  const packageType = document.getElementById('packageType').value
  const version = document.getElementById('version').value.trim()

  // 处理组件列表
  const components = getAllComponents()

  // 获取标签
  const tags = getAllTags()

  return {
    isPatch,
    components,
    description,
    tags,
    packageType,
    version
  }
}

// 带metadata的上传函数 - 在HTML中通过onclick调用
async function uploadWithMetadata() {
  const fileInput = document.getElementById('fileInput')
  const files = fileInput.files

  if (files.length === 0) {
    showAlert('请先选择要上传的文件', 'warning')
    return
  }

  try {
    const metadata = collectMetadata()
    await uploadFiles(files, metadata)
  } catch (error) {
    showAlert(error.message, 'danger')
  }
}

// 将函数添加到全局作用域供HTML调用
window.uploadWithMetadata = uploadWithMetadata
window.resetMetadataForm = resetMetadataForm
window.removeTag = removeTag
window.removeComponent = removeComponent
window.removeSelectedFile = removeSelectedFile

// 标签管理功能
function setupTagsInput() {
  const tagInput = document.getElementById('tagInput')
  const tagsContainer = document.getElementById('tagsContainer')

  if (!tagInput || !tagsContainer) return

  tagInput.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' || e.key === ',') {
      e.preventDefault()
      addTag(this.value.trim())
      this.value = ''
    }
  })

  tagInput.addEventListener('blur', function () {
    if (this.value.trim()) {
      addTag(this.value.trim())
      this.value = ''
    }
  })

  // 点击容器时聚焦到输入框
  tagsContainer.addEventListener('click', function () {
    tagInput.focus()
  })
}

function addTag(tagText) {
  if (!tagText) return

  const tagsDisplay = document.getElementById('tagsDisplay')
  if (!tagsDisplay) return

  // 检查是否已存在相同标签
  const existingTags = Array.from(tagsDisplay.querySelectorAll('.tag-item')).map((tag) =>
    tag.textContent.replace('×', '').trim()
  )
  if (existingTags.includes(tagText)) return

  const tagElement = document.createElement('span')
  tagElement.className = 'tag-item'
  tagElement.innerHTML = `${tagText} <span class="tag-remove" onclick="removeTag(this)">×</span>`

  tagsDisplay.appendChild(tagElement)
}

function removeTag(element) {
  element.closest('.tag-item').remove()
}

function getAllTags() {
  const tagsDisplay = document.getElementById('tagsDisplay')
  if (!tagsDisplay) return []

  return Array.from(tagsDisplay.querySelectorAll('.tag-item')).map((tag) => tag.textContent.replace('×', '').trim())
}

function clearAllTags() {
  const tagsDisplay = document.getElementById('tagsDisplay')
  if (tagsDisplay) {
    tagsDisplay.innerHTML = ''
  }
}

// 组件管理功能
function setupComponentsInput() {
  const componentInput = document.getElementById('componentInput')
  const componentsContainer = document.getElementById('componentsContainer')

  if (!componentInput || !componentsContainer) return

  componentInput.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' || e.key === ',') {
      e.preventDefault()
      addComponent(this.value.trim())
      this.value = ''
    }
  })

  componentInput.addEventListener('blur', function () {
    if (this.value.trim()) {
      addComponent(this.value.trim())
      this.value = ''
    }
  })

  // 点击容器时聚焦到输入框
  componentsContainer.addEventListener('click', function () {
    componentInput.focus()
  })
}

function addComponent(componentText) {
  if (!componentText) return

  const componentsDisplay = document.getElementById('componentsDisplay')
  if (!componentsDisplay) return

  // 检查是否已存在相同组件
  const existingComponents = Array.from(componentsDisplay.querySelectorAll('.tag-item')).map((comp) =>
    comp.textContent.replace('×', '').trim()
  )
  if (existingComponents.includes(componentText)) return

  const componentElement = document.createElement('span')
  componentElement.className = 'tag-item' // Using same style as tags
  componentElement.innerHTML = `${componentText} <span class="tag-remove" onclick="removeComponent(this)">×</span>`

  componentsDisplay.appendChild(componentElement)
}

function removeComponent(element) {
  element.closest('.tag-item').remove()
}

function getAllComponents() {
  const componentsDisplay = document.getElementById('componentsDisplay')
  if (!componentsDisplay) return []

  return Array.from(componentsDisplay.querySelectorAll('.tag-item')).map((comp) =>
    comp.textContent.replace('×', '').trim()
  )
}

function clearAllComponents() {
  const componentsDisplay = document.getElementById('componentsDisplay')
  if (componentsDisplay) {
    componentsDisplay.innerHTML = ''
  }
}

// 全局变量用于存储当前上传的XMLHttpRequest对象
let currentUploadXHR = null

async function uploadFiles(files, metadata = null) {
  if (files.length === 0) return

  // 验证文件类型
  const validFiles = Array.from(files).filter((file) => {
    const isValid = file.name.endsWith('.tgz') || file.name.endsWith('.tar.gz')
    if (!isValid) {
      showAlert(`文件 ${file.name} 格式不支持，仅支持 .tgz 和 .tar.gz 格式`, 'warning')
    }
    return isValid
  })

  if (validFiles.length === 0) return

  const formData = new FormData()
  validFiles.forEach((file) => {
    formData.append('file', file)
  })

  // 如果有metadata，将各个字段添加到formData中
  if (metadata) {
    formData.append('isPatch', metadata.isPatch)
    formData.append('description', metadata.description)
    formData.append('components', JSON.stringify(metadata.components))
    formData.append('tags', JSON.stringify(metadata.tags))
    formData.append('packageType', metadata.packageType)
    formData.append('version', metadata.version)
  }

  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    currentUploadXHR = xhr // 保存当前上传的xhr对象
    let startTime = Date.now()
    let lastLoaded = 0
    let lastTime = startTime

    // 显示进度模态窗口
    showUploadProgressModal(true, validFiles)
    updateUploadModalProgress(0, '', 0)

    // 监听上传进度
    xhr.upload.addEventListener('progress', (event) => {
      if (event.lengthComputable) {
        const currentTime = Date.now()
        const percentComplete = (event.loaded / event.total) * 100

        // 计算上传速度
        const timeDiff = currentTime - lastTime
        const loadedDiff = event.loaded - lastLoaded

        if (timeDiff > 500) {
          // 每500ms更新一次速度
          const speed = loadedDiff / (timeDiff / 1000) // bytes per second
          const speedText = formatUploadSpeed(speed)
          const remainingBytes = event.total - event.loaded
          const eta = speed > 0 ? Math.round(remainingBytes / speed) : 0

          updateUploadModalProgress(percentComplete, speedText, eta)
          updateUploadModalStatus('上传中...')

          lastTime = currentTime
          lastLoaded = event.loaded
        } else {
          // 仍然更新进度条，但不重新计算速度，保持之前的速度和ETA显示
          updateUploadModalProgress(percentComplete, null, null)
        }
      }
    })

    // 监听上传完成
    xhr.addEventListener('load', () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          const response = JSON.parse(xhr.responseText)
          const totalTime = (Date.now() - startTime) / 1000
          updateUploadModalProgress(100, '', 0)
          updateUploadModalStatus(`上传完成 (耗时: ${totalTime.toFixed(1)}秒)`)

          showAlert(`成功上传 ${validFiles.length} 个文件`, 'success')

          // 重置表单
          resetMetadataForm()

          // 刷新列表
          refreshPackages()

          // 返回包列表页面
          setTimeout(() => {
            showPackages()
            showUploadProgressModal(false)
          }, 2000)

          resolve(response)
        } catch (error) {
          reject(new Error('响应解析失败'))
        }
      } else {
        try {
          const error = JSON.parse(xhr.responseText)
          reject(new Error(error.message || '上传失败'))
        } catch {
          reject(new Error(`上传失败: HTTP ${xhr.status}`))
        }
      }
    })

    // 监听上传错误
    xhr.addEventListener('error', () => {
      reject(new Error('网络错误，上传失败'))
    })

    // 监听上传中止
    xhr.addEventListener('abort', () => {
      reject(new Error('上传被用户取消'))
    })

    // 错误处理
    xhr.addEventListener('loadend', () => {
      currentUploadXHR = null // 清除当前上传的xhr对象
      if (xhr.status < 200 || xhr.status >= 300) {
        showUploadProgressModal(false)
      }
    })

    // 发送请求
    const url = validFiles.length === 1 ? UPLOAD_API : `${UPLOAD_API}/batch`
    xhr.open('POST', url)
    xhr.send(formData)
  }).catch((error) => {
    console.error('上传失败:', error)
    showAlert(`上传失败: ${error.message}`, 'error')
    showUploadProgressModal(false)
    currentUploadXHR = null
    throw error
  })
}

// 显示/隐藏上传进度模态窗口
function showUploadProgressModal(show, files = []) {
  const modal = document.getElementById('uploadProgressModal')
  const uploadZone = document.getElementById('uploadZone')

  if (show) {
    // 显示模态窗口
    if (window.bootstrap) {
      const bootstrapModal = new window.bootstrap.Modal(modal)
      bootstrapModal.show()
    } else {
      modal.style.display = 'block'
      modal.classList.add('show')
    }

    // 禁用上传区域
    uploadZone.style.pointerEvents = 'none'
    uploadZone.style.opacity = '0.6'

    // 设置文件名
    const fileNameElement = document.getElementById('uploadModalFileName')
    if (files.length > 0) {
      if (files.length === 1) {
        fileNameElement.textContent = files[0].name
      } else {
        fileNameElement.textContent = `${files.length} 个文件`
      }
    }

    // 重置进度
    updateUploadModalProgress(0, '', 0)
    updateUploadModalStatus('正在初始化上传...')
  } else {
    // 隐藏模态窗口
    if (window.bootstrap) {
      const bootstrapModal = window.bootstrap.Modal.getInstance(modal)
      if (bootstrapModal) {
        bootstrapModal.hide()
      }
    } else {
      modal.style.display = 'none'
      modal.classList.remove('show')
    }

    // 恢复上传区域
    uploadZone.style.pointerEvents = 'auto'
    uploadZone.style.opacity = '1'
  }
}

// 更新模态窗口进度条
function updateUploadModalProgress(percentage, speedText = '', eta = 0) {
  const progressBar = document.getElementById('uploadModalProgressBar')
  const progressPercent = document.getElementById('uploadModalProgressPercent')
  const speedElement = document.getElementById('uploadModalSpeedText')
  const etaElement = document.getElementById('uploadModalEtaText')

  if (progressBar) {
    const roundedPercentage = Math.round(percentage * 100) / 100
    progressBar.style.width = `${roundedPercentage}%`
    progressBar.setAttribute('aria-valuenow', roundedPercentage)
  }

  if (progressPercent) {
    progressPercent.textContent = `${Math.round(percentage)}%`
  }

  if (speedElement && speedText !== null) {
    if (speedText) {
      speedElement.textContent = `速度: ${speedText}`
    } else {
      speedElement.textContent = ''
    }
  }

  if (etaElement && eta !== null) {
    if (eta > 0 && percentage < 100) {
      etaElement.textContent = `预计剩余: ${formatTime(eta)}`
    } else {
      etaElement.textContent = ''
    }
  }
}

// 更新模态窗口状态文本
function updateUploadModalStatus(text) {
  const statusElement = document.getElementById('uploadModalStatus')
  if (statusElement) {
    statusElement.textContent = text
  }
}

// 取消上传
function cancelUpload() {
  if (currentUploadXHR) {
    currentUploadXHR.abort()
    currentUploadXHR = null
    showUploadProgressModal(false)
    showAlert('上传已取消', 'warning')
  }
}

// 格式化上传速度
function formatUploadSpeed(bytesPerSecond) {
  if (bytesPerSecond < 1024) {
    return `${bytesPerSecond.toFixed(0)} B/s`
  } else if (bytesPerSecond < 1024 * 1024) {
    return `${(bytesPerSecond / 1024).toFixed(1)} KB/s`
  } else {
    return `${(bytesPerSecond / (1024 * 1024)).toFixed(1)} MB/s`
  }
}

// 格式化时间
function formatTime(seconds) {
  if (seconds < 60) {
    return `${seconds}秒`
  } else if (seconds < 3600) {
    const minutes = Math.floor(seconds / 60)
    const remainingSeconds = seconds % 60
    return `${minutes}分${remainingSeconds}秒`
  } else {
    const hours = Math.floor(seconds / 3600)
    const minutes = Math.floor((seconds % 3600) / 60)
    return `${hours}小时${minutes}分钟`
  }
}

// 辅助函数：将字符串或数组转换为数组
function getComponentsArray(components) {
  if (!components) return []
  let arr = []
  if (Array.isArray(components)) {
    arr = components
  } else if (typeof components === 'string') {
    try {
      const parsed = JSON.parse(components)
      arr = Array.isArray(parsed) ? parsed : []
    } catch {
      arr = []
    }
  } else {
    return []
  }
  return arr
    .map((item) => {
      if (typeof item === 'string') return { name: item }
      if (item && typeof item === 'object') {
        const name = item.name || ''
        const version = item.version || ''
        if (!name) return null
        return version ? { name, version } : { name }
      }
      return null
    })
    .filter(Boolean)
}

// 辅助函数：将字符串或数组转换为数组
function getTagsArray(tags) {
  if (!tags) return []
  if (Array.isArray(tags)) return tags
  if (typeof tags === 'string') {
    try {
      const parsed = JSON.parse(tags)
      return Array.isArray(parsed) ? parsed : []
    } catch {
      return []
    }
  }
  return []
}

// 显示包详情（跳转到可分享的新页面）
// eslint-disable-next-line @typescript-eslint/no-unused-vars
function showPackageDetail(packageId) {
  if (!packageId) {
    showAlert('未找到包 ID', 'warning')
    return
  }
  const encodedId = encodeURIComponent(packageId)
  window.location.href = `${RAVEN_BASE_PATH}/package/${encodedId}`
}

// 下载包
async function downloadPackage(packageId) {
  try {
    const response = await fetch(`${DOWNLOAD_API}/${packageId}`)
    if (!response.ok) throw new Error('下载失败')

    // 获取文件名
    const contentDisposition = response.headers.get('Content-Disposition')
    let filename = 'package.tgz'
    if (contentDisposition) {
      const filenameMatch = contentDisposition.match(/filename="(.+)"/)
      if (filenameMatch) {
        filename = filenameMatch[1]
      }
    }

    // 创建下载链接
    const blob = await response.blob()
    const url = window.URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    window.URL.revokeObjectURL(url)

    showAlert('下载开始', 'success')
  } catch (error) {
    console.error('下载失败:', error)
    showAlert('下载失败', 'danger')
  }
}

// 确认删除包
function confirmDeletePackage(packageId, packageName) {
  if (confirm(`确定要删除包 "${packageName}" 吗？此操作不可撤销。`)) {
    deletePackage(packageId)
  }
}

// 删除包
async function deletePackage(packageId) {
  try {
    const response = await fetch(`${PACKAGES_API}/${packageId}`, {
      method: 'DELETE'
    })

    if (!response.ok) throw new Error('删除失败')

    showAlert('包删除成功', 'success')

    // 刷新列表
    refreshPackages()
  } catch (error) {
    console.error('删除失败:', error)
    showAlert('删除失败', 'danger')
  }
}

// 阻止默认的拖拽行为
document.addEventListener('dragover', function (e) {
  e.preventDefault()
})

document.addEventListener('drop', function (e) {
  e.preventDefault()
})

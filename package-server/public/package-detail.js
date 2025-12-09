const DEFAULT_BASE_PATH = '/raven'
const RAVEN_BASE_PATH =
  (window.__RAVEN_BASE_PATH__ || DEFAULT_BASE_PATH).replace(/\/$/, '') || DEFAULT_BASE_PATH
const API_BASE = `${RAVEN_BASE_PATH}/api`
const PACKAGES_API = `${API_BASE}/packages`
const DOWNLOAD_API = `${API_BASE}/download`

const state = {
  packageId: null,
  packageData: null
}

document.addEventListener('DOMContentLoaded', () => {
  syncNavigationLinks()
  const packageId = getPackageIdFromUrl()
  state.packageId = packageId

  if (!packageId) {
    showError('未找到包 ID，请从包列表重新进入。')
    return
  }

  setupStaticActions()
  loadPackageDetail(packageId)
})

function setupStaticActions() {
  const { packageId } = state
  const retryBtn = document.getElementById('retryBtn')
  retryBtn?.addEventListener('click', () => loadPackageDetail(packageId))

  const copyLinkBtn = document.getElementById('copyLinkBtn')
  copyLinkBtn?.addEventListener('click', copyCurrentLink)

  const copyDownloadLinkBtn = document.getElementById('copyDownloadLinkBtn')
  copyDownloadLinkBtn?.addEventListener('click', () => copyDownloadLink(packageId))

  const downloadBtn = document.getElementById('downloadPackageBtn')
  downloadBtn?.addEventListener('click', () => downloadPackage(packageId))

  const deleteBtn = document.getElementById('deletePackageBtn')
  deleteBtn?.addEventListener('click', () => confirmDeletePackage(packageId))
}

function getPackageIdFromUrl() {
  const pathMatch = window.location.pathname.match(/\/package\/([^/]+)\/?$/)
  if (pathMatch && pathMatch[1]) {
    return decodeURIComponent(pathMatch[1])
  }
  const params = new URLSearchParams(window.location.search)
  return params.get('id')
}

async function loadPackageDetail(packageId) {
  toggleLoading(true)
  hideError()
  try {
    const response = await fetch(`${PACKAGES_API}/${encodeURIComponent(packageId)}`)
    const result = await response.json()
    if (!response.ok || !result.success || !result.data) {
      throw new Error(result.message || '获取包详情失败')
    }

    state.packageData = result.data
    renderPackageDetail(result.data)
  } catch (error) {
    console.error('加载包详情失败:', error)
    showError(error.message || '加载包详情失败')
  } finally {
    toggleLoading(false)
  }
}

function renderPackageDetail(pkg) {
  if (!pkg) return

  document.title = `${pkg.name || '包详情'} - Raven 包管理系统`
  setText('packageName', pkg.name || '未知包名')

  const versionBadge = document.getElementById('packageVersion')
  if (versionBadge) {
    versionBadge.textContent = pkg.version ? `v${pkg.version}` : '版本未知'
  }

  const typeBadge = document.getElementById('packageTypeBadge')
  if (typeBadge) {
    typeBadge.textContent = getPackageTypeDisplay(pkg.packageType)
    typeBadge.className = `badge bg-${getPackageTypeColor(pkg.packageType)} text-white`
  }

  setText('packageCreated', pkg.createdAt ? `创建于 ${formatDate(pkg.createdAt)}` : '创建时间未知')
  setText('packageId', pkg.id || '-')
  setText('packageSize', formatFileSize(pkg.size))
  setText('packageSha', pkg.metadata?.sha256 || pkg.sha256 || '未知')
  setText('packagePatch', pkg.metadata?.isPatch === true || pkg.metadata?.isPatch === 'true' ? '是' : '否')
  setText('packagePath', pkg.path || '未知')

  renderTags(getTagsArray(pkg.metadata?.tags))
  renderComponents(getComponentsArray(pkg.metadata?.components))
  renderDescription(pkg.metadata?.description)
}

function renderTags(tags) {
  const container = document.getElementById('tagsContainer')
  if (!container) return

  if (!tags || tags.length === 0) {
    container.innerHTML = '<span class="empty-hint">暂无标签</span>'
    return
  }

  container.innerHTML = tags
    .map((tag) => `<span class="pill"><i class="bi bi-tag"></i>${escapeHtml(tag)}</span>`)
    .join('')
}

function renderComponents(components) {
  const container = document.getElementById('componentsContainer')
  if (!container) return

  const formatVersionLabel = (version) => {
    if (version === undefined || version === null) return ''
    const versionStr = String(version).trim()
    if (!versionStr) return ''
    return /^[vV]/.test(versionStr) ? versionStr : `v${versionStr}`
  }

  if (!components || components.length === 0) {
    container.innerHTML = '<span class="empty-hint">暂无组件信息</span>'
    return
  }

  container.innerHTML = components
    .map((c) => {
      const versionLabel = formatVersionLabel(c.version)
      return `<span class="pill"><i class="bi bi-cpu"></i>${escapeHtml(c.name)}${
        versionLabel ? `<span class="version">${escapeHtml(versionLabel)}</span>` : ''
      }</span>`
    })
    .join('')
}

function renderDescription(desc) {
  const descriptionEl = document.getElementById('descriptionContent')
  if (!descriptionEl) return

  if (!desc) {
    descriptionEl.classList.add('empty-hint')
    descriptionEl.textContent = '暂无描述'
    return
  }

  descriptionEl.classList.remove('empty-hint')
  descriptionEl.innerHTML = renderMarkdown(desc)
}

async function downloadPackage(packageId) {
  if (!packageId) {
    showAlert('缺少包 ID，无法下载', 'danger')
    return
  }

  try {
    const response = await fetch(`${DOWNLOAD_API}/${encodeURIComponent(packageId)}`)
    if (!response.ok) throw new Error('下载失败')

    const contentDisposition = response.headers.get('Content-Disposition')
    let filename = 'package.tgz'
    if (contentDisposition) {
      const filenameMatch = contentDisposition.match(/filename="(.+)"/)
      if (filenameMatch) {
        filename = filenameMatch[1]
      }
    }

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

function confirmDeletePackage(packageId) {
  const name = state.packageData?.name ? ` "${state.packageData.name}"` : ''
  if (confirm(`确定要删除包${name}吗？此操作不可撤销。`)) {
    deletePackage(packageId)
  }
}

async function deletePackage(packageId) {
  if (!packageId) {
    showAlert('缺少包 ID，无法删除', 'danger')
    return
  }

  try {
    const response = await fetch(`${PACKAGES_API}/${encodeURIComponent(packageId)}`, { method: 'DELETE' })
    if (!response.ok) throw new Error('删除失败')

    showAlert('包删除成功', 'success')
    setTimeout(() => {
      window.location.href = RAVEN_BASE_PATH
    }, 600)
  } catch (error) {
    console.error('删除失败:', error)
    showAlert('删除失败', 'danger')
  }
}

function copyCurrentLink() {
  const link = window.location.href
  console.info('[copy-link] start copy', { link })

  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard
      .writeText(link)
      .then(() => {
        console.info('[copy-link] clipboard.writeText success')
        showAlert('链接已复制，可分享给其他用户', 'success')
      })
      .catch((err) => {
        console.warn('[copy-link] clipboard.writeText failed, fallback to execCommand', err)
        fallbackCopy(link)
      })
    return
  }

  console.warn('[copy-link] navigator.clipboard unavailable, fallback to execCommand')
  fallbackCopy(link)
}

function copyDownloadLink(packageId) {
  if (!packageId) {
    showAlert('缺少包 ID，无法生成下载链接', 'warning')
    console.warn('[copy-download-link] missing packageId')
    return
  }
  const downloadLink = `${window.location.origin}${DOWNLOAD_API}/${encodeURIComponent(packageId)}`
  console.info('[copy-download-link] start copy', { downloadLink })

  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard
      .writeText(downloadLink)
      .then(() => {
        console.info('[copy-download-link] clipboard.writeText success')
        showAlert('下载链接已复制，可直接分享', 'success')
      })
      .catch((err) => {
        console.warn('[copy-download-link] clipboard.writeText failed, fallback to execCommand', err)
        fallbackCopy(downloadLink, {
          successMessage: '下载链接已复制，可直接分享',
          warnMessage: '复制下载链接失败，请手动复制地址栏',
          logPrefix: 'copy-download-link'
        })
      })
    return
  }

  console.warn('[copy-download-link] navigator.clipboard unavailable, fallback to execCommand')
  fallbackCopy(downloadLink, {
    successMessage: '下载链接已复制，可直接分享',
    warnMessage: '复制下载链接失败，请手动复制地址栏',
    logPrefix: 'copy-download-link'
  })
}

function fallbackCopy(text, options = {}) {
  const {
    successMessage = '链接已复制，可分享给其他用户',
    warnMessage = '复制链接失败，请手动复制地址栏',
    logPrefix = 'copy-link'
  } = options

  try {
    const textarea = document.createElement('textarea')
    textarea.value = text
    textarea.style.position = 'fixed'
    textarea.style.opacity = '0'
    document.body.appendChild(textarea)
    textarea.select()
    const succeeded = document.execCommand('copy')
    document.body.removeChild(textarea)

    if (succeeded) {
      console.info(`[${logPrefix}] execCommand copy success`)
      showAlert(successMessage, 'success')
    } else {
      console.warn(`[${logPrefix}] execCommand copy returned false`)
      showAlert(warnMessage, 'warning')
    }
  } catch (error) {
    console.error(`[${logPrefix}] execCommand copy threw error`, error)
    showAlert(warnMessage, 'warning')
  }
}

function toggleLoading(isLoading) {
  const loadingEl = document.getElementById('loadingState')
  const contentEl = document.getElementById('detailContent')

  loadingEl?.classList.toggle('d-none', !isLoading)
  contentEl?.classList.toggle('d-none', isLoading)
}

function hideError() {
  const errorEl = document.getElementById('errorState')
  if (errorEl) {
    errorEl.classList.add('d-none')
  }
}

function showError(message) {
  const errorEl = document.getElementById('errorState')
  const messageEl = document.getElementById('errorMessage')

  if (messageEl) {
    messageEl.textContent = message || '未知错误'
  }

  document.getElementById('detailContent')?.classList.add('d-none')
  document.getElementById('loadingState')?.classList.add('d-none')
  errorEl?.classList.remove('d-none')
}

function setText(id, value) {
  const el = document.getElementById(id)
  if (el) {
    el.textContent = value === undefined || value === null ? '-' : value
  }
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

// ======================
//  下方为通用工具函数
// ======================

function formatFileSize(bytes) {
  if (!bytes || Number.isNaN(bytes)) return '0 B'
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB']
  const i = Math.floor(Math.log(bytes) / Math.log(1024))
  return `${(bytes / Math.pow(1024, i)).toFixed(2)} ${sizes[i]}`
}

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
  return typeMap[type] || type || '未知类型'
}

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

function escapeHtml(unsafe) {
  if (typeof unsafe !== 'string') return unsafe
  return unsafe
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;')
}

function basicMarkdownToHtml(text) {
  const lines = text.split('\n')
  let html = ''
  let inCodeBlock = false
  let inUl = false
  let inOl = false

  const flushCode = () => {
    if (inCodeBlock) {
      html += '</pre>'
      inCodeBlock = false
    }
  }

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

  for (const line of lines) {
    if (/^```/.test(line)) {
      if (inCodeBlock) {
        html += '</code></pre>'
      } else {
        flushLists()
        html += '<pre><code>'
      }
      inCodeBlock = !inCodeBlock
      continue
    }

    if (inCodeBlock) {
      html += escapeHtml(line) + '\n'
      continue
    }

    const headingMatch = line.match(/^(#{1,6})\s+(.*)/)
    if (headingMatch) {
      const level = headingMatch[1].length
      const content = escapeHtml(headingMatch[2])
      html += `<h${level}>${content}</h${level}>`
      continue
    }

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

    if (line.trim() === '') {
      flushLists()
      html += '<br>'
    } else {
      flushLists()
      let content = escapeHtml(line)
      content = content.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
      content = content.replace(/(^|\s)\*(.+?)\*(?=\s|$)/g, '$1<em>$2</em>')
      content = content.replace(/`([^`]+)`/g, '<code>$1</code>')
      content = content.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>')
      html += `<p>${content}</p>`
    }
  }

  flushLists()
  flushCode()
  return html
}

function renderMarkdown(text) {
  if (!text) return ''

  if (typeof window !== 'undefined' && window.marked) {
    try {
      window.marked.setOptions({
        breaks: true,
        gfm: true,
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

  return basicMarkdownToHtml(text)
}

function showAlert(message, type = 'info') {
  const alertId = 'alert-' + Date.now()
  const alertConfig = {
    success: { color: '#059669', bgColor: '#d1fae5', icon: 'bi-check-circle-fill' },
    error: { color: '#dc2626', bgColor: '#fee2e2', icon: 'bi-x-circle-fill' },
    warning: { color: '#d97706', bgColor: '#fef3c7', icon: 'bi-exclamation-triangle-fill' },
    info: { color: '#2563eb', bgColor: '#dbeafe', icon: 'bi-info-circle-fill' },
    danger: { color: '#dc2626', bgColor: '#fee2e2', icon: 'bi-x-circle-fill' }
  }

  const config = alertConfig[type] || alertConfig.info

  const alertHtml = `
    <div id="${alertId}" class="toast-alert" style="
      position: fixed;
      top: 20px;
      right: 20px;
      z-index: 9999;
      min-width: 300px;
      max-width: 400px;
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
    `
    document.head.appendChild(style)
  }

  document.body.insertAdjacentHTML('beforeend', alertHtml)

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

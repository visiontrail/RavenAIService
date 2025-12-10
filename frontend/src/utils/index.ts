// 格式化文件大小
export const formatFileSize = (bytes: number): string => {
  if (bytes === 0) return '0 B'
  
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  
  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i]
}

const parseDateToLocal = (dateString?: string): Date | null => {
  if (!dateString) return null
  const trimmed = dateString.trim()
  const hasTimezone = /(Z|[+-]\d{2}:?\d{2})$/i.test(trimmed)
  // 后端存储的是UTC时间但未带时区信息，这里默认按UTC解析再转换到本地
  const normalized = hasTimezone ? trimmed : `${trimmed.replace(' ', 'T')}Z`
  const date = new Date(normalized)
  return isNaN(date.getTime()) ? null : date
}

// 格式化日期时间
export const formatDateTime = (dateString: string): string => {
  const date = parseDateToLocal(dateString)
  if (!date) return '-'
  return date.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  })
}

// 格式化相对时间
export const formatRelativeTime = (dateString: string): string => {
  const date = parseDateToLocal(dateString)
  if (!date) return '-'
  const now = new Date()
  const diff = now.getTime() - date.getTime()
  
  const seconds = Math.floor(diff / 1000)
  const minutes = Math.floor(seconds / 60)
  const hours = Math.floor(minutes / 60)
  const days = Math.floor(hours / 24)
  
  if (days > 0) return `${days}天前`
  if (hours > 0) return `${hours}小时前`
  if (minutes > 0) return `${minutes}分钟前`
  return '刚刚'
}

// 获取文件扩展名
export const getFileExtension = (filename: string): string => {
  return filename.split('.').pop()?.toLowerCase() || ''
}

// 获取状态颜色
export const getStatusColor = (status: string): string => {
  const colors: Record<string, string> = {
    pending: 'warning',
    processing: 'primary',
    completed: 'success',
    failed: 'danger',
  }
  return colors[status] || 'info'
}

// 获取状态文本
export const getStatusText = (status: string): string => {
  const texts: Record<string, string> = {
    pending: '待处理',
    processing: '处理中',
    completed: '已完成',
    failed: '失败',
  }
  return texts[status] || status
}

// 下载文件 - 支持两种方式：直接URL下载和Blob下载
export const downloadFile = (blobOrUrl: Blob | string, filename?: string): void => {
  if (typeof blobOrUrl === 'string') {
    // 直接URL下载 - 立即触发浏览器下载，不等待完整响应
    const link = document.createElement('a')
    link.href = blobOrUrl
    if (filename) {
      link.download = filename
    }
    link.target = '_blank' // 在新标签页打开，避免页面跳转
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
  } else {
    // Blob下载 - 用于已获取的blob数据
    const url = window.URL.createObjectURL(blobOrUrl)
    const link = document.createElement('a')
    link.href = url
    if (filename) {
      link.download = filename
    }
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    window.URL.revokeObjectURL(url)
  }
}

// 直接URL下载 - 立即触发下载，不显示加载状态
export const downloadFileByUrl = (url: string, filename?: string): void => {
  downloadFile(url, filename)
}

// 复制到剪贴板
export const copyToClipboard = async (text: string): Promise<boolean> => {
  try {
    const clipboard = typeof navigator !== 'undefined' ? navigator.clipboard : undefined
    if (clipboard && typeof clipboard.writeText === 'function') {
      await clipboard.writeText(text)
      return true
    }

    if (typeof document === 'undefined') return false

    // 回退到 execCommand 以兼容不支持 navigator.clipboard 的环境
    const textarea = document.createElement('textarea')
    textarea.value = text
    textarea.setAttribute('readonly', '')
    textarea.style.position = 'fixed'
    textarea.style.opacity = '0'
    textarea.style.pointerEvents = 'none'
    document.body.appendChild(textarea)
    textarea.select()
    const success = document.execCommand('copy')
    document.body.removeChild(textarea)
    return success
  } catch (error) {
    console.error('Failed to copy to clipboard:', error)
    return false
  }
}

// 防抖函数
export const debounce = <T extends (...args: any[]) => any>(
  func: T,
  wait: number
): ((...args: Parameters<T>) => void) => {
  let timeout: number | null = null
  
  return (...args: Parameters<T>) => {
    if (timeout) clearTimeout(timeout)
    timeout = setTimeout(() => func(...args), wait)
  }
}

// 节流函数
export const throttle = <T extends (...args: any[]) => any>(
  func: T,
  limit: number
): ((...args: Parameters<T>) => void) => {
  let inThrottle: boolean = false
  
  return (...args: Parameters<T>) => {
    if (!inThrottle) {
      func(...args)
      inThrottle = true
      setTimeout(() => (inThrottle = false), limit)
    }
  }
}

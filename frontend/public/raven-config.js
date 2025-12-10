;(function () {
  const defaultBasePath = '/raven'
  const existingBasePath = typeof window !== 'undefined' ? window.__RAVEN_BASE_PATH__ : undefined
  const existingLogApiBase = typeof window !== 'undefined' ? window.__LOG_API_BASE_URL__ : undefined

  const deriveLogApiBase = () => {
    if (existingLogApiBase) return existingLogApiBase
    if (typeof window === 'undefined') return ''

    const { protocol, hostname, port, origin } = window.location

    // 当直接通过 8083 访问包管理服务时，默认使用同主机的 8085 端口提供日志服务
    if (port === '8083') {
      return `${protocol}//${hostname}:8085`
    }

    return origin
  }

  window.__RAVEN_BASE_PATH__ = existingBasePath || defaultBasePath
  window.__LOG_API_BASE_URL__ = deriveLogApiBase()
})()

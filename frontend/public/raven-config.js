;(function () {
  const defaultBasePath = '/raven'
  const existingBasePath = typeof window !== 'undefined' ? window.__RAVEN_BASE_PATH__ : undefined
  const existingLogApiBase = typeof window !== 'undefined' ? window.__LOG_API_BASE_URL__ : undefined
  const existingRavenPort = typeof window !== 'undefined' ? window.__RAVEN_SERVER_PORT__ : undefined

  const deriveRavenPort = () => (existingRavenPort ? String(existingRavenPort) : '')

  const deriveLogApiBase = () => {
    if (existingLogApiBase) return existingLogApiBase
    if (typeof window === 'undefined') return ''

    const { protocol, hostname, port, origin } = window.location
    const ravenPort = deriveRavenPort()

    // 兼容历史独立包服务端口；统一后端部署默认使用当前 origin
    if (ravenPort && port === ravenPort) {
      return `${protocol}//${hostname}:8085`
    }

    return origin
  }

  const ravenPort = deriveRavenPort()

  window.__RAVEN_BASE_PATH__ = existingBasePath || defaultBasePath
  window.__LOG_API_BASE_URL__ = deriveLogApiBase()
  window.__RAVEN_SERVER_PORT__ = ravenPort
})()

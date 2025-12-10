;(function () {
  const defaultBasePath = '/raven'
  const defaultRavenPort = '8083'
  const existingBasePath = typeof window !== 'undefined' ? window.__RAVEN_BASE_PATH__ : undefined
  const existingLogApiBase = typeof window !== 'undefined' ? window.__LOG_API_BASE_URL__ : undefined
  const existingRavenPort = typeof window !== 'undefined' ? window.__RAVEN_SERVER_PORT__ : undefined

  const deriveRavenPort = () => (existingRavenPort ? String(existingRavenPort) : defaultRavenPort)

  const deriveLogApiBase = () => {
    if (existingLogApiBase) return existingLogApiBase
    if (typeof window === 'undefined') return ''

    const { protocol, hostname, port, origin } = window.location
    const ravenPort = deriveRavenPort()

    // 当直接通过包管理服务端口访问时，默认使用同主机的 8085 端口提供日志服务
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

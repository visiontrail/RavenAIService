;(function(){
  const configuredLogApiBase = '';
  const serverPort = '18083';
  const fallbackLogPort = '8085';
  const defaultBasePath = '/raven';
  const deriveLogApiBase = () => {
    if (configuredLogApiBase) return configuredLogApiBase;
    if (typeof window === 'undefined') return '';
    const { protocol, hostname, port, origin } = window.location;
    if (port === serverPort && fallbackLogPort) {
      return protocol + '//' + hostname + ':' + fallbackLogPort;
    }
    return origin;
  };
  window.__RAVEN_BASE_PATH__ = defaultBasePath;
  window.__LOG_API_BASE_URL__ = deriveLogApiBase();
  window.__RAVEN_SERVER_PORT__ = serverPort;
})();

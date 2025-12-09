const RAGService = require('./RAGService')

let instance = null

function getRAGServiceInstance() {
  if (!instance) {
    console.log('创建RAGService单例实例')
    instance = new RAGService()
  }
  return instance
}

getRAGServiceInstance.reset = () => {
  instance = null
}

module.exports = getRAGServiceInstance

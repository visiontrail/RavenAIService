const PackageService = require('./PackageService')

// 单例模式的PackageService
class PackageServiceSingleton {
  constructor() {
    if (PackageServiceSingleton.instance) {
      return PackageServiceSingleton.instance
    }

    console.log('创建PackageService单例实例')
    this.service = new PackageService()
    PackageServiceSingleton.instance = this
  }

  // 代理所有方法到实际的service实例
  async getAllPackages() {
    return this.service.getAllPackages()
  }

  async getPackageById(id) {
    return this.service.getPackageById(id)
  }

  async addPackage(packageInfo) {
    return this.service.addPackage(packageInfo)
  }

  async updatePackageMetadata(id, metadata) {
    return this.service.updatePackageMetadata(id, metadata)
  }

  async deletePackage(id) {
    return this.service.deletePackage(id)
  }

  async extractPackageMetadata(filePath) {
    return this.service.extractPackageMetadata(filePath)
  }

  async scanUploadsDirectory() {
    return this.service.scanUploadsDirectory()
  }
}

// 重置单例实例（用于测试）
PackageServiceSingleton.reset = () => {
  PackageServiceSingleton.instance = null
}

module.exports = PackageServiceSingleton

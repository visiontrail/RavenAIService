const fs = require('fs-extra')
const path = require('path')
const crypto = require('crypto')
const { v4: uuidv4 } = require('uuid')

// 测试数据生成脚本
const testPackages = [
  {
    name: 'LingXi-10-V1.2.0-20241113-CUCP-CUUP-DU.tgz',
    version: '1.2.0',
    packageType: 'lingxi-10',
    size: 524288000, // 500MB
    metadata: {
      isPatch: false,
      components: [
        { name: 'CUCP', version: '1.2.0' },
        { name: 'CUUP', version: '1.2.0' },
        { name: 'DU', version: '1.2.0' }
      ],
      description: 'LingXi-10完整版本，包含CUCP、CUUP和DU三个核心组件，适用于卫星通信系统的基站部署',
      tags: ['complete', 'production', 'satellite'],
      customFields: {
        targetPlatform: 'Linux ARM64',
        minMemory: '16GB',
        minStorage: '100GB'
      }
    }
  },
  {
    name: 'LingXi-10-V1.2.1-patch-20241115-CUCP.tgz',
    version: '1.2.1',
    packageType: 'lingxi-10',
    size: 52428800, // 50MB
    metadata: {
      isPatch: true,
      components: [{ name: 'CUCP', version: '1.2.1' }],
      description: 'LingXi-10 CUCP组件的补丁包，修复了信令处理中的内存泄漏问题和连接稳定性优化',
      tags: ['patch', 'bugfix', 'critical'],
      customFields: {
        basedOnVersion: '1.2.0',
        fixedIssues: ['ISSUE-1234', 'ISSUE-1235']
      }
    }
  },
  {
    name: 'LingXi-07A-V2.0.5-20241110-OAM-GalaxyCore.tgz',
    version: '2.0.5',
    packageType: 'lingxi-07a',
    size: 314572800, // 300MB
    metadata: {
      isPatch: false,
      components: [
        { name: 'OAM', version: '2.0.5' },
        { name: 'galaxy_core_network', version: '2.0.5' }
      ],
      description: 'LingXi-07A完整版本，包含OAM运维管理和Galaxy核心网组件，支持5G NTN网络部署',
      tags: ['complete', '5g-ntn', 'core-network'],
      customFields: {
        targetPlatform: 'Linux x86_64',
        supportedBands: ['n255', 'n256', 'n257']
      }
    }
  },
  {
    name: 'LingXi-07A-V2.0.6-patch-20241112-Security-Fix.tgz',
    version: '2.0.6',
    packageType: 'lingxi-07a',
    size: 31457280, // 30MB
    metadata: {
      isPatch: true,
      components: [{ name: 'OAM', version: '2.0.6' }],
      description: 'LingXi-07A安全补丁，修复了认证模块的安全漏洞，强烈建议所有用户升级',
      tags: ['patch', 'security', 'critical'],
      customFields: {
        basedOnVersion: '2.0.5',
        securityLevel: 'Critical',
        cveIds: ['CVE-2024-XXXX']
      }
    }
  },
  {
    name: 'LingXi-06-TRD-V1.0.3-20241105-Complete.tgz',
    version: '1.0.3',
    packageType: 'lingxi-06-thrid',
    size: 209715200, // 200MB
    metadata: {
      isPatch: false,
      components: [
        { name: 'satellite_app_server', version: '1.0.3' },
        { name: 'TRD-Module', version: '1.0.3' }
      ],
      description: 'LingXi-06-TRD测试研发版本，包含卫星应用服务器和TRD测试模块',
      tags: ['development', 'testing', 'experimental'],
      customFields: {
        testingPhase: 'Beta',
        expiryDate: '2024-12-31'
      }
    }
  },
  {
    name: 'Config-Package-V3.1.0-20241108-System-Config.tgz',
    version: '3.1.0',
    packageType: 'config',
    size: 10485760, // 10MB
    metadata: {
      isPatch: false,
      components: [{ name: 'system-config', version: '3.1.0' }],
      description: '系统配置包，包含LingXi系列产品的通用配置文件和参数模板',
      tags: ['config', 'system', 'templates'],
      customFields: {
        compatibleVersions: ['1.x', '2.x', '3.x'],
        configFormat: 'YAML/JSON'
      }
    }
  },
  {
    name: 'LingXi-10-V1.1.5-20241101-CUUP-Only.tgz',
    version: '1.1.5',
    packageType: 'lingxi-10',
    size: 157286400, // 150MB
    metadata: {
      isPatch: false,
      components: [{ name: 'CUUP', version: '1.1.5' }],
      description: 'LingXi-10 CUUP用户面组件独立包，适用于只需要升级CUUP模块的场景',
      tags: ['component', 'userplane', 'cuup'],
      customFields: {
        standalone: true,
        minCoreVersion: '1.1.0'
      }
    }
  },
  {
    name: 'LingXi-10-V1.3.0-beta-20241114-Full-Stack.tgz',
    version: '1.3.0-beta',
    packageType: 'lingxi-10',
    size: 629145600, // 600MB
    metadata: {
      isPatch: false,
      components: [
        { name: 'CUCP', version: '1.3.0-beta' },
        { name: 'CUUP', version: '1.3.0-beta' },
        { name: 'DU', version: '1.3.0-beta' },
        { name: 'OAM', version: '1.3.0-beta' }
      ],
      description: 'LingXi-10 V1.3.0测试版，全栈部署包，包含所有核心组件和新特性预览',
      tags: ['beta', 'full-stack', 'preview', 'new-features'],
      customFields: {
        releaseStatus: 'Beta',
        newFeatures: ['AI优化', '能源管理', '自动故障恢复'],
        warningNote: '此为测试版本，不建议在生产环境使用'
      }
    }
  },
  {
    name: 'LingXi-07A-V2.1.0-20241116-Enhanced-Performance.tgz',
    version: '2.1.0',
    packageType: 'lingxi-07a',
    size: 419430400, // 400MB
    metadata: {
      isPatch: false,
      components: [
        { name: 'OAM', version: '2.1.0' },
        { name: 'galaxy_core_network', version: '2.1.0' },
        { name: 'Performance-Module', version: '2.1.0' }
      ],
      description: 'LingXi-07A性能增强版本，优化了核心网处理能力，新增性能监控模块',
      tags: ['performance', 'monitoring', 'production'],
      customFields: {
        performanceGain: '40%',
        newMetrics: ['延迟监控', '吞吐量分析', '资源利用率'],
        recommendedFor: '大规模部署'
      }
    }
  },
  {
    name: 'Emergency-Patch-All-Products-V1.0.0-20241117.tgz',
    version: '1.0.0',
    packageType: 'config',
    size: 5242880, // 5MB
    metadata: {
      isPatch: true,
      components: [{ name: 'emergency-fix', version: '1.0.0' }],
      description: '紧急补丁包，修复所有LingXi系列产品的时间同步问题，适用于所有版本',
      tags: ['emergency', 'critical', 'universal', 'time-sync'],
      customFields: {
        applicableProducts: ['lingxi-10', 'lingxi-07a', 'lingxi-06-thrid'],
        urgencyLevel: 'Emergency',
        deploymentTime: '<5 minutes',
        rollbackSupported: true
      }
    }
  }
]

// 生成随机SHA256
function generateRandomSHA256() {
  return crypto.randomBytes(32).toString('hex')
}

// 创建测试包数据
async function generateTestData() {
  console.log('🔧 开始生成测试数据...')

  const dataDir = path.join(__dirname, '../data')
  const uploadsDir = path.join(__dirname, '../uploads')
  const metadataFile = path.join(dataDir, 'package-metadata.json')

  // 确保目录存在
  await fs.ensureDir(dataDir)
  await fs.ensureDir(uploadsDir)

  // 生成包元数据
  const packages = testPackages.map((pkg) => ({
    id: uuidv4(),
    name: pkg.name,
    path: path.join(uploadsDir, pkg.name),
    size: pkg.size,
    createdAt: new Date(Date.now() - Math.random() * 30 * 24 * 60 * 60 * 1000), // 最近30天内随机时间
    packageType: pkg.packageType,
    version: pkg.version,
    metadata: {
      ...pkg.metadata,
      sha256: generateRandomSHA256()
    }
  }))

  // 保存元数据
  await fs.writeJSON(metadataFile, packages, { spaces: 2 })
  console.log(`✅ 已生成 ${packages.length} 个包的元数据`)

  // 创建模拟的包文件（空文件，仅用于测试）
  console.log('📦 创建模拟包文件...')
  for (const pkg of packages) {
    // 创建一个小的空文件作为占位符
    await fs.writeFile(pkg.path, `# Mock package file for ${pkg.name}\n`)
    console.log(`  ✅ ${pkg.name}`)
  }

  console.log('\n🎉 测试数据生成完成!')
  console.log(`📁 元数据文件: ${metadataFile}`)
  console.log(`📁 包文件目录: ${uploadsDir}`)
  console.log(`\n总共生成了 ${packages.length} 个测试包，包括：`)
  console.log(`  - LingXi-10: ${packages.filter((p) => p.packageType === 'lingxi-10').length} 个`)
  console.log(`  - LingXi-07A: ${packages.filter((p) => p.packageType === 'lingxi-07a').length} 个`)
  console.log(`  - LingXi-06-TRD: ${packages.filter((p) => p.packageType === 'lingxi-06-thrid').length} 个`)
  console.log(`  - 配置包: ${packages.filter((p) => p.packageType === 'config').length} 个`)
  console.log(`  - 补丁包: ${packages.filter((p) => p.metadata.isPatch).length} 个`)
  console.log(`\n可以使用以下命令启动服务器:`)
  console.log(`  cd ${path.join(__dirname, '..')}`)
  console.log(`  npm start`)
}

// 执行生成
generateTestData().catch((error) => {
  console.error('❌ 生成测试数据失败:', error)
  process.exit(1)
})


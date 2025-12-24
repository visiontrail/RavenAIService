// 使用动态 import 导入 ES Module
let pipelineModule = null

const { FaissStore } = require('@langchain/community/vectorstores/faiss')
const { Document } = require('langchain/document')
const { ChatOpenAI } = require('@langchain/openai')
const { PromptTemplate } = require('@langchain/core/prompts')
const { RunnableSequence } = require('@langchain/core/runnables')
const { StringOutputParser } = require('@langchain/core/output_parsers')
const { Embeddings } = require('@langchain/core/embeddings')
const fs = require('fs-extra')
const path = require('path')
const { getVectorStorePath } = require('../config/paths')

// 环境变量配置
const EMBEDDING_PROVIDER = process.env.RAG_EMBEDDING_PROVIDER || 'local'
const EMBEDDING_MODEL = process.env.RAG_EMBEDDING_MODEL || 'text-embedding-v3'
const ALIBABA_API_KEY = process.env.ALIBABA_API_KEY
const OPENAI_API_KEY = process.env.OPENAI_API_KEY
const OPENAI_BASE_URL = process.env.OPENAI_BASE_URL

// 动态加载 @xenova/transformers
async function loadPipeline() {
  if (!pipelineModule) {
    const transformers = await import('@xenova/transformers')
    pipelineModule = transformers.pipeline
  }
  return pipelineModule
}

// 自定义本地嵌入类
class LocalEmbeddings extends Embeddings {
  constructor() {
    super({})
    this.pipelinePromise = null
  }

  async ensurePipeline() {
    if (!this.pipelinePromise) {
      console.log('🔄 正在加载本地嵌入模型...')
      const pipeline = await loadPipeline()
      this.pipelinePromise = pipeline('feature-extraction', 'Xenova/paraphrase-multilingual-MiniLM-L12-v2')
      console.log('✅ 本地嵌入模型加载完成')
    }
    return this.pipelinePromise
  }

  async embedDocuments(texts) {
    const extractor = await this.ensurePipeline()
    const embeddings = []

    for (const text of texts) {
      const output = await extractor(text, { pooling: 'mean', normalize: true })
      embeddings.push(Array.from(output.data))
    }

    return embeddings
  }

  async embedQuery(text) {
    const extractor = await this.ensurePipeline()
    const output = await extractor(text, { pooling: 'mean', normalize: true })
    return Array.from(output.data)
  }
}

// 通义千问 Embeddings 包装类（区分 document 和 query）
class TongyiEmbeddingsWrapper extends Embeddings {
  constructor(modelName, apiKey) {
    super({})
    const { AlibabaTongyiEmbeddings } = require('@langchain/community/embeddings/alibaba_tongyi')
    
    // 创建两个实例：一个用于文档，一个用于查询
    this.docEmb = new AlibabaTongyiEmbeddings({
      modelName: modelName,
      alibabaApiKey: apiKey,
      parameters: { text_type: 'document' }
    })
    
    this.queryEmb = new AlibabaTongyiEmbeddings({
      modelName: modelName,
      alibabaApiKey: apiKey,
      parameters: { text_type: 'query' }
    })
    
    this.modelName = modelName
  }

  async embedDocuments(texts) {
    return await this.docEmb.embedDocuments(texts)
  }

  async embedQuery(text) {
    return await this.queryEmb.embedQuery(text)
  }
}

class RAGService {
  constructor() {
    console.log(`🤖 初始化 RAG 服务 (Embedding Provider: ${EMBEDDING_PROVIDER})...`)

    // OpenAI 配置
    this.config = {
      apiKey: 'sk-rebTXHBiV7Nr1PRzaODQOZKztKqpv7bPoQE10dNItF9yIyBh',
      baseURL: 'http://oneapi.yhroot.com/v1',
      modelName: 'deepseek-v3.1'
    }

    // 初始化 embeddings（根据环境变量选择）
    this.embeddings = this.createEmbeddings()
    this.embeddingProvider = EMBEDDING_PROVIDER
    this.embeddingModel = EMBEDDING_MODEL

    // 初始化 LLM
    this.llm = new ChatOpenAI({
      openAIApiKey: this.config.apiKey,
      modelName: this.config.modelName,
      temperature: 0.3,
      configuration: {
        baseURL: this.config.baseURL
      }
    })

    this.vectorStore = null
    this.vectorStorePath = getVectorStorePath()
    this.vectorStoreMetaPath = `${this.vectorStorePath}.meta.json`
    this.isInitialized = false
    this.isRebuilding = false
    this.initializationPromise = null

    console.log(`✅ RAG 服务初始化完成 (Provider: ${this.embeddingProvider}, Model: ${this.embeddingModel || 'N/A'})`)
  }

  /**
   * 创建 Embeddings 实例（根据环境变量）
   */
  createEmbeddings() {
    switch (EMBEDDING_PROVIDER) {
      case 'tongyi':
        if (!ALIBABA_API_KEY) {
          console.warn('⚠️ ALIBABA_API_KEY 未设置，回退到本地嵌入模型')
          return new LocalEmbeddings()
        }
        console.log(`📦 使用通义千问 Embeddings (Model: ${EMBEDDING_MODEL})`)
        return new TongyiEmbeddingsWrapper(EMBEDDING_MODEL, ALIBABA_API_KEY)

      case 'openai_compatible':
        if (!OPENAI_API_KEY) {
          console.warn('⚠️ OPENAI_API_KEY 未设置，回退到本地嵌入模型')
          return new LocalEmbeddings()
        }
        const { OpenAIEmbeddings } = require('@langchain/openai')
        console.log(`📦 使用 OpenAI-compatible Embeddings (Model: ${EMBEDDING_MODEL})`)
        return new OpenAIEmbeddings({
          openAIApiKey: OPENAI_API_KEY,
          modelName: EMBEDDING_MODEL,
          configuration: OPENAI_BASE_URL ? { baseURL: OPENAI_BASE_URL } : undefined
        })

      case 'local':
      default:
        console.log('📦 使用本地嵌入模型')
        return new LocalEmbeddings()
    }
  }

  /**
   * 读取向量存储元信息
   */
  async readVectorStoreMeta() {
    try {
      if (await fs.pathExists(this.vectorStoreMetaPath)) {
        const metaContent = await fs.readFile(this.vectorStoreMetaPath, 'utf-8')
        return JSON.parse(metaContent)
      }
    } catch (error) {
      console.warn('⚠️ 读取向量存储元信息失败:', error.message)
    }
    return null
  }

  /**
   * 写入向量存储元信息
   */
  async writeVectorStoreMeta() {
    try {
      const meta = {
        provider: this.embeddingProvider,
        modelName: this.embeddingModel || 'N/A',
        createdAt: new Date().toISOString()
      }
      await fs.writeFile(this.vectorStoreMetaPath, JSON.stringify(meta, null, 2), 'utf-8')
      console.log(`📝 向量存储元信息已保存: ${JSON.stringify(meta)}`)
    } catch (error) {
      console.warn('⚠️ 写入向量存储元信息失败:', error.message)
    }
  }

  /**
   * 检查是否需要重建向量存储（provider/model 变更）
   */
  async shouldRebuildVectorStore() {
    const existingMeta = await this.readVectorStoreMeta()
    
    if (!existingMeta) {
      // 元信息不存在：可能是旧数据，允许尝试加载
      // 但如果后续检索报错，会在错误处理中触发重建
      console.log('ℹ️ 未找到向量存储元信息，将尝试加载现有向量库')
      return false
    }

    const providerChanged = existingMeta.provider !== this.embeddingProvider
    const modelChanged = existingMeta.modelName !== this.embeddingModel

    if (providerChanged || modelChanged) {
      console.log(`🔄 检测到 Embedding 配置变更:`)
      console.log(`   旧配置: provider=${existingMeta.provider}, model=${existingMeta.modelName}`)
      console.log(`   新配置: provider=${this.embeddingProvider}, model=${this.embeddingModel}`)
      console.log(`   将删除旧向量库并重建...`)
      return true
    }

    console.log(`✅ 向量存储元信息匹配 (provider=${this.embeddingProvider}, model=${this.embeddingModel})`)
    return false
  }

  /**
   * 将包信息转换为可搜索的文档文本
   */
  packageToText(pkg) {
    const components = pkg.metadata?.components?.map((c) => c.name).join(', ') || '无'
    const tags = pkg.metadata?.tags?.join(', ') || '无'
    const isPatch = pkg.metadata?.isPatch ? '是' : '否'

    return `
包名称: ${pkg.name}
包ID: ${pkg.id}
版本: ${pkg.version}
包类型: ${pkg.packageType}
是否为补丁: ${isPatch}
组件: ${components}
标签: ${tags}
描述: ${pkg.metadata?.description || '无描述'}
文件大小: ${(pkg.size / 1024 / 1024).toFixed(2)} MB
创建时间: ${new Date(pkg.createdAt).toLocaleString('zh-CN')}
SHA256: ${pkg.metadata?.sha256 || '无'}
`.trim()
  }

  /**
   * 初始化或加载向量存储
   */
  async initializeVectorStore(packages = []) {
    const initStart = Date.now()
    this.isRebuilding = true
    this.isInitialized = false
    try {
      console.log('🔄 初始化向量存储...')

      // 检查是否需要重建（provider/model 变更）
      const needRebuild = await this.shouldRebuildVectorStore()
      if (needRebuild) {
        // 删除旧的向量存储和元信息
        if (await fs.pathExists(this.vectorStorePath)) {
          await fs.remove(this.vectorStorePath)
          console.log('🗑️ 已删除旧向量存储目录')
        }
        if (await fs.pathExists(this.vectorStoreMetaPath)) {
          await fs.remove(this.vectorStoreMetaPath)
          console.log('🗑️ 已删除旧向量存储元信息')
        }
      }

      // 尝试加载已存在的向量存储
      if (await fs.pathExists(this.vectorStorePath) && !needRebuild) {
        console.log('📂 发现已存在的向量存储，正在加载...')
        try {
          this.vectorStore = await FaissStore.load(this.vectorStorePath, this.embeddings)
          console.log(`✅ 向量存储加载成功（耗时 ${Date.now() - initStart} ms）`)
          this.isInitialized = true
          
          // 确保元信息存在（兼容旧数据）
          const existingMeta = await this.readVectorStoreMeta()
          if (!existingMeta) {
            await this.writeVectorStoreMeta()
          }
          
          return true
        } catch (error) {
          // 如果是维度不匹配错误，触发重建
          const isDimensionError = error.message && (
            error.message.includes('dimension') ||
            error.message.includes('维度') ||
            error.message.includes('shape') ||
            error.message.includes('size')
          )
          
          if (isDimensionError) {
            console.warn('⚠️ 向量维度不匹配，将删除旧向量库并重建:', error.message)
          } else {
            console.warn('⚠️ 加载向量存储失败，将重新创建:', error.message)
          }
          
          // 删除损坏的向量存储和元信息
          if (await fs.pathExists(this.vectorStorePath)) {
            await fs.remove(this.vectorStorePath)
          }
          if (await fs.pathExists(this.vectorStoreMetaPath)) {
            await fs.remove(this.vectorStoreMetaPath)
          }
        }
      }

      // 创建新的向量存储
      if (packages.length === 0) {
        console.log('⚠️ 没有包数据，跳过向量存储创建')
        console.log(`⏱️ 向量存储初始化耗时 ${Date.now() - initStart} ms`)
        return false
      }

      console.log(`📝 正在为 ${packages.length} 个包创建向量存储...`)

      // 将包信息转换为文档
      const documents = packages.map((pkg) => {
        const content = this.packageToText(pkg)
        return new Document({
          pageContent: content,
          metadata: {
            id: pkg.id,
            name: pkg.name,
            version: pkg.version,
            packageType: pkg.packageType,
            createdAt: pkg.createdAt.toString()
          }
        })
      })

      console.log('🔄 正在生成向量嵌入，这可能需要一些时间...')

      // 创建向量存储
      this.vectorStore = await FaissStore.fromDocuments(documents, this.embeddings)

      // 保存向量存储
      await fs.ensureDir(path.dirname(this.vectorStorePath))
      await this.vectorStore.save(this.vectorStorePath)

      // 保存元信息
      await this.writeVectorStoreMeta()

      console.log(`✅ 向量存储创建并保存成功（耗时 ${Date.now() - initStart} ms）`)
      this.isInitialized = true
      return true
    } catch (error) {
      console.error('❌ 初始化向量存储失败:', error)
      this.isInitialized = false
      throw error
    } finally {
      this.isRebuilding = false
    }
  }

  /**
   * 确保向量存储已初始化，避免重复初始化
   */
  async ensureInitialized(packagesOrLoader = []) {
    if (this.isInitialized && this.vectorStore) {
      return true
    }

    if (this.isRebuilding && !this.initializationPromise) {
      return false
    }

    if (this.initializationPromise) {
      await this.initializationPromise
      return this.isInitialized && this.vectorStore !== null
    }

    const loadPackages = async () => {
      if (typeof packagesOrLoader === 'function') {
        return packagesOrLoader()
      }
      if (Array.isArray(packagesOrLoader)) {
        return packagesOrLoader
      }
      return []
    }

    this.initializationPromise = (async () => {
      const packages = (await loadPackages()) || []
      await this.initializeVectorStore(packages)
    })()

    try {
      await this.initializationPromise
      return this.isInitialized && this.vectorStore !== null
    } catch (error) {
      console.error('❌ 确保向量存储初始化失败:', error)
      return false
    } finally {
      this.initializationPromise = null
    }
  }

  /**
   * 重建向量存储（当包数据更新时）
   */
  async rebuildVectorStore(packages) {
    const rebuildStart = Date.now()
    this.isRebuilding = true
    this.isInitialized = false
    try {
      console.log('🔄 重建向量存储...')

      // 删除旧的向量存储和元信息
      if (await fs.pathExists(this.vectorStorePath)) {
        await fs.remove(this.vectorStorePath)
      }
      if (await fs.pathExists(this.vectorStoreMetaPath)) {
        await fs.remove(this.vectorStoreMetaPath)
      }

      // 重新初始化
      await this.initializeVectorStore(packages)

      console.log(`✅ 向量存储重建完成（耗时 ${Date.now() - rebuildStart} ms）`)
      return true
    } catch (error) {
      console.error('❌ 重建向量存储失败:', error)
      throw error
    } finally {
      this.isRebuilding = false
    }
  }

  /**
   * 添加单个包到向量存储
   */
  async addPackage(pkg) {
    try {
      if (!this.isInitialized || !this.vectorStore) {
        console.log('⚠️ 向量存储未初始化，跳过添加')
        return false
      }

      console.log(`📝 添加包到向量存储: ${pkg.name}`)

      const content = this.packageToText(pkg)
      const document = new Document({
        pageContent: content,
        metadata: {
          id: pkg.id,
          name: pkg.name,
          version: pkg.version,
          packageType: pkg.packageType,
          createdAt: pkg.createdAt.toString()
        }
      })

      await this.vectorStore.addDocuments([document])
      await this.vectorStore.save(this.vectorStorePath)

      console.log('✅ 包已添加到向量存储')
      return true
    } catch (error) {
      console.error('❌ 添加包到向量存储失败:', error)
      throw error
    }
  }

  /**
   * 执行相似度搜索
   */
  async similaritySearch(query, k = 5) {
    const searchStart = Date.now()
    try {
      if (!this.isInitialized || !this.vectorStore) {
        throw new Error('向量存储未初始化')
      }

      console.log(`🔍 执行相似度搜索: "${query}"`)

      const results = await this.vectorStore.similaritySearchWithScore(query, k)

      console.log(`✅ 找到 ${results.length} 个相关结果（耗时 ${Date.now() - searchStart} ms）`)

      return results.map(([doc, score]) => ({
        id: doc.metadata.id,
        name: doc.metadata.name,
        version: doc.metadata.version,
        packageType: doc.metadata.packageType,
        score: score,
        content: doc.pageContent
      }))
    } catch (error) {
      console.error('❌ 相似度搜索失败:', error)
      throw error
    }
  }

  /**
   * 使用 RAG 进行智能搜索
   */
  async intelligentSearch(query, packages, k = 5) {
    const totalStart = Date.now()
    try {
      console.log(`🤖 执行智能搜索: "${query}"`)

      if (!this.isInitialized || !this.vectorStore) {
        console.log('⚠️ 向量存储未初始化，返回空结果')
        console.log(`⏱️ 智能搜索流程耗时 ${Date.now() - totalStart} ms`)
        return {
          answer: '向量存储未初始化，请先重建索引。',
          relevantPackages: [],
          query: query
        }
      }

      // 1. 执行向量搜索获取相关包
      const searchResults = await this.similaritySearch(query, k)
      console.log('🧭 相似度搜索命中ID:', searchResults.map((r) => r.id).join(', ') || '无')

      // 2. 根据ID获取完整的包信息
      const missingPackageIds = []
      const relevantPackages = searchResults
        .map((result) => {
          const pkg = packages.find((p) => p.id === result.id)
          if (!pkg) {
            missingPackageIds.push(result.id)
            return null
          }
          return { ...pkg, relevanceScore: result.score }
        })
        .filter((pkg) => pkg !== null)

      console.log(`📦 成功匹配到 ${relevantPackages.length} 个包（请求期望 ${searchResults.length} 个）`)

      if (missingPackageIds.length > 0) {
        console.warn('⚠️ 向量存储命中但在包元数据中未找到的ID:', missingPackageIds.join(', '))
      }

      // 3. 构建上下文
      const context = searchResults.map((result, index) => `[包${index + 1}]\n${result.content}`).join('\n\n')

      // 4. 创建提示模板
      const promptTemplate = PromptTemplate.fromTemplate(`
你是一个专业的软件包管理助手。请根据用户的问题和相关的包信息，提供准确、有帮助的回答。

相关包信息：
{context}

用户问题：{query}

请用中文回答，并提供以下信息：
1. 对用户问题的直接回答
2. 推荐的包及其原因
3. 如果有多个相关包，请说明它们之间的区别和选择建议

回答：
`)

      const formattedPrompt = await promptTemplate.format({
        context,
        query
      })
      console.log('📝 发送给 LLM 的 Prompt:\n' + formattedPrompt)

      // 5. 创建 RAG 链
      const chain = RunnableSequence.from([promptTemplate, this.llm, new StringOutputParser()])

      // 6. 执行查询
      console.log('🤖 正在调用 LLM 生成回答...')
      const llmStart = Date.now()
      const answer = await chain.invoke({
        context: context,
        query: query
      })
      console.log(`⏱️ LLM 调用耗时 ${Date.now() - llmStart} ms`)
      console.log('🤖 LLM 原始回答:\n' + answer)

      const recommendedPackageIds = this.extractRecommendedPackageIds(answer, relevantPackages)
      console.log('⭐️ AI 推荐包:', recommendedPackageIds.length > 0 ? recommendedPackageIds.join(', ') : '无')

      console.log('✅ 智能搜索完成')

      console.log(`⏱️ 智能搜索流程耗时 ${Date.now() - totalStart} ms`)

      return {
        answer: answer,
        relevantPackages: relevantPackages,
        query: query,
        searchResultsCount: searchResults.length,
        recommendedPackageIds
      }
    } catch (error) {
      console.error('❌ 智能搜索失败:', error)
      throw error
    }
  }

  /**
   * 获取搜索建议
   */
  async getSearchSuggestions(query) {
    try {
      console.log(`💡 获取搜索建议: "${query}"`)

      const promptTemplate = PromptTemplate.fromTemplate(`
你是一个软件包管理系统的搜索助手。用户输入了一个搜索查询，请生成3-5个相关的搜索建议。

用户查询：{query}

请生成与Galaxy Space卫星软件包相关的搜索建议，包括：
- 不同版本的查询
- 特定组件的查询
- 补丁或更新的查询
- 按类型分类的查询

以JSON数组格式返回建议，每个建议是一个字符串。只返回JSON数组，不要有其他内容。
例如：["建议1", "建议2", "建议3"]
`)

      const chain = RunnableSequence.from([promptTemplate, this.llm, new StringOutputParser()])

      const result = await chain.invoke({ query })

      // 尝试解析JSON
      try {
        const suggestions = JSON.parse(result)
        console.log(`✅ 生成了 ${suggestions.length} 个搜索建议`)
        return suggestions
      } catch (e) {
        console.warn('⚠️ 解析搜索建议JSON失败，返回默认建议')
        return [`${query} 最新版本`, `${query} 补丁包`, `${query} 完整版`, `lingxi-10 ${query}`, `lingxi-07a ${query}`]
      }
    } catch (error) {
      console.error('❌ 获取搜索建议失败:', error)
      return []
    }
  }

  extractRecommendedPackageIds(answer, relevantPackages) {
    if (!answer || !Array.isArray(relevantPackages) || relevantPackages.length === 0) {
      return []
    }

    const recommendedSection = this.extractSectionByHeading(answer, ['推荐', '建议'])
    const keywordLines = recommendedSection || this.extractLinesWithKeywords(answer, ['推荐', '建议'])

    if (!keywordLines) {
      return []
    }

    const normalizedText = keywordLines.toLowerCase()
    const recommended = []

    relevantPackages.forEach((pkg, index) => {
      const tokens = [
        pkg.name,
        pkg.version,
        `包${index + 1}`,
        `包 ${index + 1}`,
        `[包${index + 1}]`,
        `package ${index + 1}`,
        `pkg${index + 1}`
      ]

      const hit = tokens.some((token) => {
        if (!token) return false
        return normalizedText.includes(token.toLowerCase())
      })

      if (hit) {
        recommended.push(pkg.id)
      }
    })

    return Array.from(new Set(recommended))
  }

  extractSectionByHeading(answer, keywords) {
    if (!answer) return null
    const headingRegex = /^#{1,6}\s.*$/gm
    const matches = []
    let match

    while ((match = headingRegex.exec(answer)) !== null) {
      matches.push({
        title: match[0],
        start: match.index
      })
    }

    if (matches.length === 0) {
      return null
    }

    for (let i = 0; i < matches.length; i++) {
      const titleLower = matches[i].title.toLowerCase()
      const hasKeyword = keywords.some((keyword) => titleLower.includes(keyword.toLowerCase()))
      if (hasKeyword) {
        const start = matches[i].start
        const end = i + 1 < matches.length ? matches[i + 1].start : answer.length
        return answer.slice(start, end)
      }
    }

    return null
  }

  extractLinesWithKeywords(answer, keywords) {
    if (!answer) return null
    const lines = answer.split('\n')
    const filtered = lines.filter((line) =>
      keywords.some((keyword) => line.toLowerCase().includes(keyword.toLowerCase()))
    )
    return filtered.length > 0 ? filtered.join('\n') : null
  }

  /**
   * 检查服务状态
   */
  getStatus() {
    return {
      initialized: this.isInitialized,
      vectorStoreExists: this.vectorStore !== null,
      rebuilding: this.isRebuilding,
      embeddingProvider: this.embeddingProvider,
      embeddingModel: this.embeddingModel || 'N/A',
      config: {
        baseURL: this.config.baseURL,
        modelName: this.config.modelName
      }
    }
  }
}

module.exports = RAGService

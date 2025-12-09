const { pipeline } = require('@xenova/transformers')
const { FaissStore } = require('@langchain/community/vectorstores/faiss')
const { Document } = require('langchain/document')
const { ChatOpenAI } = require('@langchain/openai')
const { PromptTemplate } = require('@langchain/core/prompts')
const { RunnableSequence } = require('@langchain/core/runnables')
const { StringOutputParser } = require('@langchain/core/output_parsers')
const { Embeddings } = require('@langchain/core/embeddings')
const fs = require('fs-extra')
const path = require('path')

// 自定义本地嵌入类
class LocalEmbeddings extends Embeddings {
  constructor() {
    super({})
    this.pipelinePromise = null
  }

  async ensurePipeline() {
    if (!this.pipelinePromise) {
      console.log('🔄 正在加载本地嵌入模型...')
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

class RAGService {
  constructor() {
    console.log('🤖 初始化 RAG 服务 (本地嵌入版本)...')
    
    // OpenAI 配置
    this.config = {
      apiKey: 'sk-rebTXHBiV7Nr1PRzaODQOZKztKqpv7bPoQE10dNItF9yIyBh',
      baseURL: 'http://oneapi.yhroot.com/v1',
      modelName: 'deepseek-v3.1-chat'
    }

    // 初始化本地 embeddings
    this.embeddings = new LocalEmbeddings()

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
    this.vectorStorePath = path.join(__dirname, '../../data/vector-store')
    this.isInitialized = false

    console.log('✅ RAG 服务初始化完成')
  }

  /**
   * 将包信息转换为可搜索的文档文本
   */
  packageToText(pkg) {
    const components = pkg.metadata?.components?.map(c => c.name).join(', ') || '无'
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
  async initializeVectorStore(packages) {
    try {
      console.log('🔄 初始化向量存储...')
      
      // 尝试加载已存在的向量存储
      if (await fs.pathExists(this.vectorStorePath)) {
        console.log('📂 发现已存在的向量存储，正在加载...')
        try {
          this.vectorStore = await FaissStore.load(
            this.vectorStorePath,
            this.embeddings
          )
          console.log('✅ 向量存储加载成功')
          this.isInitialized = true
          return true
        } catch (error) {
          console.warn('⚠️ 加载向量存储失败，将重新创建:', error.message)
          // 删除损坏的向量存储
          await fs.remove(this.vectorStorePath)
        }
      }

      // 创建新的向量存储
      if (packages.length === 0) {
        console.log('⚠️ 没有包数据，跳过向量存储创建')
        return false
      }

      console.log(`📝 正在为 ${packages.length} 个包创建向量存储...`)
      
      // 将包信息转换为文档
      const documents = packages.map(pkg => {
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
      this.vectorStore = await FaissStore.fromDocuments(
        documents,
        this.embeddings
      )

      // 保存向量存储
      await fs.ensureDir(path.dirname(this.vectorStorePath))
      await this.vectorStore.save(this.vectorStorePath)
      
      console.log('✅ 向量存储创建并保存成功')
      this.isInitialized = true
      return true
    } catch (error) {
      console.error('❌ 初始化向量存储失败:', error)
      throw error
    }
  }

  /**
   * 重建向量存储（当包数据更新时）
   */
  async rebuildVectorStore(packages) {
    try {
      console.log('🔄 重建向量存储...')
      
      // 删除旧的向量存储
      if (await fs.pathExists(this.vectorStorePath)) {
        await fs.remove(this.vectorStorePath)
      }

      // 重新初始化
      await this.initializeVectorStore(packages)
      
      console.log('✅ 向量存储重建完成')
      return true
    } catch (error) {
      console.error('❌ 重建向量存储失败:', error)
      throw error
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
    try {
      if (!this.isInitialized || !this.vectorStore) {
        throw new Error('向量存储未初始化')
      }

      console.log(`🔍 执行相似度搜索: "${query}"`)
      
      const results = await this.vectorStore.similaritySearchWithScore(query, k)
      
      console.log(`✅ 找到 ${results.length} 个相关结果`)
      
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
    try {
      console.log(`🤖 执行智能搜索: "${query}"`)

      if (!this.isInitialized || !this.vectorStore) {
        console.log('⚠️ 向量存储未初始化，返回空结果')
        return {
          answer: '向量存储未初始化，请先重建索引。',
          relevantPackages: [],
          query: query
        }
      }

      // 1. 执行向量搜索获取相关包
      const searchResults = await this.similaritySearch(query, k)
      
      // 2. 根据ID获取完整的包信息
      const relevantPackages = searchResults
        .map(result => {
          const pkg = packages.find(p => p.id === result.id)
          return pkg ? { ...pkg, relevanceScore: result.score } : null
        })
        .filter(pkg => pkg !== null)

      // 3. 构建上下文
      const context = searchResults
        .map((result, index) => `[包${index + 1}]\n${result.content}`)
        .join('\n\n')

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

      // 5. 创建 RAG 链
      const chain = RunnableSequence.from([
        promptTemplate,
        this.llm,
        new StringOutputParser()
      ])

      // 6. 执行查询
      console.log('🤖 正在调用 LLM 生成回答...')
      const answer = await chain.invoke({
        context: context,
        query: query
      })

      console.log('✅ 智能搜索完成')

      return {
        answer: answer,
        relevantPackages: relevantPackages,
        query: query,
        searchResultsCount: searchResults.length
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

      const chain = RunnableSequence.from([
        promptTemplate,
        this.llm,
        new StringOutputParser()
      ])

      const result = await chain.invoke({ query })
      
      // 尝试解析JSON
      try {
        const suggestions = JSON.parse(result)
        console.log(`✅ 生成了 ${suggestions.length} 个搜索建议`)
        return suggestions
      } catch (e) {
        console.warn('⚠️ 解析搜索建议JSON失败，返回默认建议')
        return [
          `${query} 最新版本`,
          `${query} 补丁包`,
          `${query} 完整版`,
          `lingxi-10 ${query}`,
          `lingxi-07a ${query}`
        ]
      }
    } catch (error) {
      console.error('❌ 获取搜索建议失败:', error)
      return []
    }
  }

  /**
   * 检查服务状态
   */
  getStatus() {
    return {
      initialized: this.isInitialized,
      vectorStoreExists: this.vectorStore !== null,
      embeddingType: 'local',
      config: {
        baseURL: this.config.baseURL,
        modelName: this.config.modelName
      }
    }
  }
}

module.exports = RAGService


/**
 * AI分析结果格式适配器
 * 支持处理各种可能的输出格式，确保完美呈现表格、列表等复杂内容
 */

import { marked } from 'marked'

// 数据结构定义
export interface AIAnalysisResult {
  id: string
  query: string
  status: 'pending' | 'processing' | 'completed' | 'failed'
  timestamp: string
  plan: {
    content: string
    steps: PlanStep[]
    total_steps: number
    completed_steps: number
  }
  acts: ActResult[]
  final_result: {
    content: string
    summary: string
    recommendations: string[]
  }
  metadata: {
    execution_time: number
    model_used: string
    tokens_used?: number
  }
}

export interface PlanStep {
  id: string
  title: string
  description: string
  status: 'pending' | 'in_progress' | 'completed' | 'failed'
}

export interface ActResult {
  step_id: string
  title: string
  status: 'completed' | 'failed'
  timestamp: string
  thought: {
    reasoning: string
    approach: string
    expected_outcome: string
  }
  execution: {
    tool_used: string
    raw_output: string
    processed_output: string
  }
  summary: string
}

/**
 * 格式适配器类
 */
export class FormatAdapter {
  private static instance: FormatAdapter
  
  private constructor() {
    this.configureMarked()
  }
  
  public static getInstance(): FormatAdapter {
    if (!FormatAdapter.instance) {
      FormatAdapter.instance = new FormatAdapter()
    }
    return FormatAdapter.instance
  }
  
  /**
   * 配置marked解析器
   */
  private configureMarked() {
    marked.setOptions({
      gfm: true,
      breaks: true
    })
    
    // 自定义渲染器
    const renderer = new marked.Renderer()
    
    // 表格渲染
    renderer.table = (token: any) => {
      return `
        <div class="table-container">
          <table class="analysis-table">
            <thead>${token.header}</thead>
            <tbody>${token.body}</tbody>
          </table>
        </div>
      `
    }
    
    // 代码块渲染
    renderer.code = (token: any) => {
      const lang = token.lang || 'text'
      return `
        <div class="code-block-container">
          <div class="code-block-header">
            <span class="code-language">${lang}</span>
            <button class="copy-code-btn" onclick="copyCode(this)">复制</button>
          </div>
          <pre class="code-block"><code class="language-${lang}">${this.escapeHtml(token.text)}</code></pre>
        </div>
      `
    }
    
    // 列表渲染
    renderer.list = (token: any) => {
      const tag = token.ordered ? 'ol' : 'ul'
      const className = token.ordered ? 'ordered-list' : 'unordered-list'
      return `<${tag} class="${className}">${token.body}</${tag}>`
    }
    
    // 列表项渲染
    renderer.listitem = (token: any) => {
      return `<li class="list-item">${token.text}</li>`
    }
    
    // 引用渲染
    renderer.blockquote = (token: any) => {
      return `<blockquote class="analysis-quote">${token.text}</blockquote>`
    }
    
    // 链接渲染
    renderer.link = (token: any) => {
      const titleAttr = token.title ? ` title="${token.title}"` : ''
      return `<a href="${token.href}" class="analysis-link" target="_blank" rel="noopener noreferrer"${titleAttr}>${token.text}</a>`
    }
    
    // 图片渲染
    renderer.image = (token: any) => {
      const titleAttr = token.title ? ` title="${token.title}"` : ''
      return `
        <div class="image-container">
          <img src="${token.href}" alt="${token.text}" class="analysis-image"${titleAttr} />
          ${token.text ? `<p class="image-caption">${token.text}</p>` : ''}
        </div>
      `
    }
    
    marked.use({ renderer })
  }
  
  /**
   * 主要的格式适配方法
   */
  public adaptResult(rawResult: any): AIAnalysisResult {
    try {
      // 如果已经是标准格式，直接返回
      if (this.isStandardFormat(rawResult)) {
        return this.processStandardFormat(rawResult)
      }
      
      // 尝试从不同格式转换
      if (typeof rawResult === 'string') {
        return this.adaptFromString(rawResult)
      }
      
      if (this.isLegacyFormat(rawResult)) {
        return this.adaptFromLegacyFormat(rawResult)
      }
      
      if (this.isStateGraphFormat(rawResult)) {
        return this.adaptFromStateGraphFormat(rawResult)
      }
      
      // 如果都不匹配，尝试通用适配
      return this.adaptFromGenericFormat(rawResult)
      
    } catch (error) {
      console.error('格式适配失败:', error)
      return this.createErrorResult(rawResult, error as Error)
    }
  }
  
  /**
   * 检查是否为标准格式
   */
  private isStandardFormat(data: any): boolean {
    return data && 
           typeof data === 'object' &&
           data.id &&
           data.query &&
           data.status &&
           data.plan &&
           data.acts &&
           data.final_result
  }
  
  /**
   * 处理标准格式
   */
  private processStandardFormat(data: any): AIAnalysisResult {
    return {
      ...data,
      plan: {
        ...data.plan,
        content: this.processMarkdown(data.plan.content)
      },
      acts: data.acts.map((act: any) => ({
        ...act,
        execution: {
          ...act.execution,
          processed_output: this.processMarkdown(act.execution.processed_output)
        }
      })),
      final_result: {
        ...data.final_result,
        content: this.processMarkdown(data.final_result.content)
      }
    }
  }
  
  /**
   * 检查是否为遗留格式
   */
  private isLegacyFormat(data: any): boolean {
    return data && 
           typeof data === 'object' &&
           (data.final_doc || data.result || data.analysis)
  }
  
  /**
   * 从遗留格式适配
   */
  private adaptFromLegacyFormat(data: any): AIAnalysisResult {
    const content = data.final_doc || data.result || data.analysis || ''
    const timestamp = new Date().toISOString()
    
    return {
      id: this.generateId(),
      query: data.query || '日志分析',
      status: 'completed',
      timestamp,
      plan: {
        content: '执行计划已完成',
        steps: [],
        total_steps: 1,
        completed_steps: 1
      },
      acts: [],
      final_result: {
        content: this.processMarkdown(content),
        summary: this.extractSummary(content),
        recommendations: this.extractRecommendations(content)
      },
      metadata: {
        execution_time: data.execution_time || 0,
        model_used: data.model || 'unknown',
        tokens_used: data.tokens
      }
    }
  }
  
  /**
   * 检查是否为StateGraph格式
   */
  private isStateGraphFormat(data: any): boolean {
    return data && 
           typeof data === 'object' &&
           (data.plan_xml || data.steps || data.outputs)
  }
  
  /**
   * 从StateGraph格式适配
   */
  private adaptFromStateGraphFormat(data: any): AIAnalysisResult {
    const timestamp = new Date().toISOString()
    
    // 解析计划
    const planContent = data.plan_xml || ''
    const steps = data.steps || []
    const outputs = data.outputs || []
    
    // 构建acts
    const acts: ActResult[] = outputs.map((output: any, index: number) => ({
      step_id: `step_${index + 1}`,
      title: steps[index]?.title || `步骤 ${index + 1}`,
      status: 'completed',
      timestamp,
      thought: {
        reasoning: output.reasoning || '执行分析步骤',
        approach: output.approach || '使用工具进行分析',
        expected_outcome: output.expected || '获取分析结果'
      },
      execution: {
        tool_used: output.tool || 'unknown',
        raw_output: output.raw || output.content || '',
        processed_output: this.processMarkdown(output.content || output.raw || '')
      },
      summary: output.summary || this.extractSummary(output.content || output.raw || '')
    }))
    
    // 构建最终结果
    const finalContent = outputs.map((o: any) => o.content || o.raw || '').join('\n\n')
    
    return {
      id: this.generateId(),
      query: data.query || '日志分析',
      status: 'completed',
      timestamp,
      plan: {
        content: this.processMarkdown(planContent),
        steps: steps.map((step: any, index: number) => ({
          id: `step_${index + 1}`,
          title: step.title || step.description || `步骤 ${index + 1}`,
          description: step.description || step.title || '',
          status: 'completed'
        })),
        total_steps: steps.length,
        completed_steps: steps.length
      },
      acts,
      final_result: {
        content: this.processMarkdown(finalContent),
        summary: this.extractSummary(finalContent),
        recommendations: this.extractRecommendations(finalContent)
      },
      metadata: {
        execution_time: data.execution_time || 0,
        model_used: data.model || 'unknown',
        tokens_used: data.tokens
      }
    }
  }
  
  /**
   * 从字符串适配
   */
  private adaptFromString(content: string): AIAnalysisResult {
    const timestamp = new Date().toISOString()
    
    return {
      id: this.generateId(),
      query: '日志分析',
      status: 'completed',
      timestamp,
      plan: {
        content: '分析已完成',
        steps: [],
        total_steps: 1,
        completed_steps: 1
      },
      acts: [],
      final_result: {
        content: this.processMarkdown(content),
        summary: this.extractSummary(content),
        recommendations: this.extractRecommendations(content)
      },
      metadata: {
        execution_time: 0,
        model_used: 'unknown'
      }
    }
  }
  
  /**
   * 从通用格式适配
   */
  private adaptFromGenericFormat(data: any): AIAnalysisResult {
    const timestamp = new Date().toISOString()
    const content = JSON.stringify(data, null, 2)
    
    return {
      id: this.generateId(),
      query: '数据分析',
      status: 'completed',
      timestamp,
      plan: {
        content: '数据处理完成',
        steps: [],
        total_steps: 1,
        completed_steps: 1
      },
      acts: [],
      final_result: {
        content: `\`\`\`json\n${content}\n\`\`\``,
        summary: '已处理原始数据',
        recommendations: ['请检查数据格式', '考虑使用标准化输出']
      },
      metadata: {
        execution_time: 0,
        model_used: 'unknown'
      }
    }
  }
  
  /**
   * 创建错误结果
   */
  private createErrorResult(rawData: any, error: Error): AIAnalysisResult {
    const timestamp = new Date().toISOString()
    
    return {
      id: this.generateId(),
      query: '分析失败',
      status: 'failed',
      timestamp,
      plan: {
        content: '分析过程中出现错误',
        steps: [],
        total_steps: 0,
        completed_steps: 0
      },
      acts: [],
      final_result: {
        content: `**错误信息:** ${error.message}\n\n**原始数据:**\n\`\`\`json\n${JSON.stringify(rawData, null, 2)}\n\`\`\``,
        summary: '分析过程中出现错误',
        recommendations: ['检查输入数据格式', '联系技术支持']
      },
      metadata: {
        execution_time: 0,
        model_used: 'unknown'
      }
    }
  }
  
  /**
   * 处理Markdown内容
   */
  public processMarkdown(content: string): string {
    if (!content) return ''
    
    try {
      // 预处理内容
      let processed = this.preprocessContent(content)
      
      // 转换为HTML
      let html = marked(processed) as string
      
      // 后处理HTML
      html = this.postprocessHtml(html)
      
      // 简单的HTML清理
      return html
    } catch (error) {
      console.error('Markdown处理失败:', error)
      return this.escapeHtml(content)
    }
  }
  
  /**
   * 简单的HTML清理
   */
  private sanitizeHtml(html: string): string {
    // 移除潜在危险的标签和属性
    return html
      .replace(/<script[^>]*>.*?<\/script>/gi, '')
      .replace(/<iframe[^>]*>.*?<\/iframe>/gi, '')
      .replace(/on\w+="[^"]*"/gi, '')
      .replace(/javascript:/gi, '')
  }
  
  /**
   * 预处理内容
   */
  private preprocessContent(content: string): string {
    return content
      // 移除log_agent相关的XML标签
      .replace(/<document[^>]*>.*?<\/document>/gs, '')
      .replace(/<document[^>]*>/g, '')
      .replace(/<\/document>/g, '')
      .replace(/<meta[^>]*>.*?<\/meta>/gs, '')
      .replace(/<meta[^>]*>/g, '')
      .replace(/<\/meta>/g, '')
      .replace(/<type[^>]*>.*?<\/type>/gs, '')
      .replace(/<type[^>]*>/g, '')
      .replace(/<\/type>/g, '')
      .replace(/<context_summary>.*?<\/context_summary>/gs, '')
      .replace(/<reads[^>]*>.*?<\/reads>/gs, '')
      .replace(/<reads[^>]*>/g, '')
      .replace(/<\/reads>/g, '')
      .replace(/<source[^>]*>.*?<\/source>/gs, '')
      .replace(/<source[^>]*>/g, '')
      .replace(/<\/source>/g, '')
      // 移除孤立的XML属性标签
      .replace(/<[^>]+type="[^"]*"[^>]*>/g, '')
      .replace(/<[^>]+source="[^"]*"[^>]*>/g, '')
      // 清理多余的空行
      .replace(/\n{3,}/g, '\n\n')
      // 修复表格格式
      .replace(/\|([^|\n]+)\|/g, (match, cell) => `|${cell.trim()}|`)
      // 修复列表格式
      .replace(/^(\s*)[-*+]\s+/gm, '$1- ')
      // 修复代码块
      .replace(/```(\w+)?\n([\s\S]*?)```/g, (match, lang, code) => {
        return `\`\`\`${lang || ''}\n${code.trim()}\n\`\`\``
      })
      // 修复链接格式
      .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '[$1]($2)')
      .trim()
  }
  
  /**
   * 后处理HTML
   */
  private postprocessHtml(html: string): string {
    return html
      // 添加表格容器类
      .replace(/<table>/g, '<table class="analysis-table">')
      // 添加代码块容器
      .replace(/<pre><code/g, '<pre class="code-block"><code')
      // 添加列表类
      .replace(/<ul>/g, '<ul class="unordered-list">')
      .replace(/<ol>/g, '<ol class="ordered-list">')
      .replace(/<li>/g, '<li class="list-item">')
      // 添加引用类
      .replace(/<blockquote>/g, '<blockquote class="analysis-quote">')
      // 添加链接类
      .replace(/<a href/g, '<a class="analysis-link" href')
  }
  
  /**
   * 提取摘要
   */
  private extractSummary(content: string): string {
    if (!content) return '无摘要信息'
    
    // 尝试提取第一段或前100个字符
    const firstParagraph = content.split('\n')[0]
    if (firstParagraph.length > 10) {
      return firstParagraph.substring(0, 200) + (firstParagraph.length > 200 ? '...' : '')
    }
    
    // 移除markdown标记后提取
    const plainText = content.replace(/[#*`_\[\]()]/g, '').trim()
    return plainText.substring(0, 200) + (plainText.length > 200 ? '...' : '')
  }
  
  /**
   * 提取建议
   */
  private extractRecommendations(content: string): string[] {
    const recommendations: string[] = []
    
    // 查找建议相关的段落
    const lines = content.split('\n')
    let inRecommendations = false
    
    for (const line of lines) {
      const trimmed = line.trim()
      
      // 检查是否是建议标题
      if (/^#+\s*(建议|推荐|recommendation)/i.test(trimmed)) {
        inRecommendations = true
        continue
      }
      
      // 检查是否是其他标题（结束建议部分）
      if (inRecommendations && /^#+\s*/.test(trimmed)) {
        break
      }
      
      // 提取建议项
      if (inRecommendations) {
        const match = trimmed.match(/^[-*+]\s*(.+)/) || trimmed.match(/^\d+\.\s*(.+)/)
        if (match) {
          recommendations.push(match[1])
        }
      }
    }
    
    // 如果没找到专门的建议部分，尝试查找包含建议关键词的句子
    if (recommendations.length === 0) {
      const sentences = content.split(/[.!?。！？]/)
      for (const sentence of sentences) {
        if (/建议|推荐|应该|需要|可以考虑/i.test(sentence)) {
          const cleaned = sentence.replace(/[#*`_\[\]()]/g, '').trim()
          if (cleaned.length > 10 && cleaned.length < 200) {
            recommendations.push(cleaned)
          }
        }
      }
    }
    
    return recommendations.slice(0, 5) // 最多返回5个建议
  }
  
  /**
   * 生成唯一ID
   */
  private generateId(): string {
    return `analysis_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`
  }
  
  /**
   * HTML转义
   */
  private escapeHtml(text: string): string {
    const div = document.createElement('div')
    div.textContent = text
    return div.innerHTML
  }
  
  /**
   * 格式化文件大小
   */
  public formatFileSize(bytes: number): string {
    if (bytes === 0) return '0 B'
    
    const k = 1024
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB']
    const i = Math.floor(Math.log(bytes) / Math.log(k))
    
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i]
  }
  
  /**
   * 格式化时间差
   */
  public formatTimeDiff(timestamp: string): string {
    const now = new Date()
    const time = new Date(timestamp)
    const diff = now.getTime() - time.getTime()
    
    const seconds = Math.floor(diff / 1000)
    const minutes = Math.floor(seconds / 60)
    const hours = Math.floor(minutes / 60)
    const days = Math.floor(hours / 24)
    
    if (days > 0) return `${days}天前`
    if (hours > 0) return `${hours}小时前`
    if (minutes > 0) return `${minutes}分钟前`
    return `${seconds}秒前`
  }
  
  /**
   * 验证数据完整性
   */
  public validateResult(result: AIAnalysisResult): { valid: boolean; errors: string[] } {
    const errors: string[] = []
    
    if (!result.id) errors.push('缺少分析ID')
    if (!result.query) errors.push('缺少查询内容')
    if (!result.timestamp) errors.push('缺少时间戳')
    if (!result.final_result?.content) errors.push('缺少分析结果内容')
    
    return {
      valid: errors.length === 0,
      errors
    }
  }
}

// 导出单例实例
export const formatAdapter = FormatAdapter.getInstance()

// 全局方法（用于HTML中的onclick等）
declare global {
  interface Window {
    copyCode: (button: HTMLElement) => void
  }
}

window.copyCode = function(button: HTMLElement) {
  const codeBlock = button.parentElement?.nextElementSibling?.querySelector('code')
  if (codeBlock) {
    navigator.clipboard.writeText(codeBlock.textContent || '').then(() => {
      button.textContent = '已复制'
      setTimeout(() => {
        button.textContent = '复制'
      }, 2000)
    })
  }
}

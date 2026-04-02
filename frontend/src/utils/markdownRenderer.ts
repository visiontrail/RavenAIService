/**
 * Professional Markdown Renderer using markdown-it + highlight.js
 * 
 * Features:
 * - Code syntax highlighting
 * - Tables support
 * - XML/metadata cleanup
 * - Safe HTML rendering
 * - Tailwind CSS styling
 */

import MarkdownIt from 'markdown-it'
import hljs from 'highlight.js'

/**
 * XML标签清理配置
 */
const XML_CLEANUP_PATTERNS = [
  // 移除log_metadata标签及其内容
  /<log_metadata[^>]*>.*?<\/log_metadata>/gs,
  // 移除log_package标签及其内容
  /<log_package[^>]*>.*?<\/log_package>/gs,
  // 移除file_list标签及其内容
  /<file_list[^>]*>.*?<\/file_list>/gs,
  // 移除file标签及其内容
  /<file[^>]*>.*?<\/file>/gs,
  // 移除extraction标签（单个词）
  /^extraction\s*/gm,
  // 移除document标签及其属性
  /<document[^>]*>.*?<\/document>/gs,
  /<document[^>]*>/g,
  /<\/document>/g,
  // 移除meta标签及其内容
  /<meta[^>]*>.*?<\/meta>/gs,
  /<meta[^>]*>/g,
  /<\/meta>/g,
  // 移除type标签及其内容
  /<type[^>]*>.*?<\/type>/gs,
  /<type[^>]*>/g,
  /<\/type>/g,
  // 移除其他XML标签（但保留context_summary的内容）
  /<context_summary>(.*?)<\/context_summary>/gs,  // 这个会被后面的规则处理，只移除标签本身
  /<reads[^>]*>.*?<\/reads>/gs,
  /<reads[^>]*>/g,
  /<\/reads>/g,
  /<source[^>]*>.*?<\/source>/gs,
  // 移除孤立的XML标签
  /<[^>]+type="[^"]*"[^>]*>/g,
  /<[^>]+source="[^"]*"[^>]*>/g,
  /<[^>]+path="[^"]*"[^>]*>/g,
  // 移除任何剩余的XML标签（但保留内容）
  /<\/?[a-zA-Z_][^>]*>/g,
  // 移除看起来像元数据的行
  /^\d+$/gm,
  /^(true|false)$/gm,
  /^\d{4}-\d{2}-\d{2}T[\d:\.]+Z$/gm,
]

/**
 * 从顶层 ```markdown / ```md 包裹块中提取内容。
 * 规则：
 * 1. 仅当内容整体被 markdown 代码块包裹时才提取；
 * 2. 使用最后一个行首 ``` 作为外层结束标记，避免内层代码块被误截断。
 */
function extractMarkdownBlock(content: string): string | null {
  if (!content || typeof content !== 'string') return null

  const normalized = content.replace(/\r\n/g, '\n')
  const trimmed = normalized.trim()
  if (!trimmed) return null

  const openMatch = trimmed.match(/^```(?:markdown|md)\s*\n/i)
  if (!openMatch) return null

  const bodyStart = openMatch[0].length

  // 必须是行首 ``` 且后面只允许空白，取最后一个作为外层关闭标记
  const closeRegex = /\n```[ \t]*$/gm
  let closeStart = -1
  let m: RegExpExecArray | null
  while ((m = closeRegex.exec(trimmed)) !== null) {
    closeStart = m.index
  }

  if (closeStart < bodyStart) {
    // 没有合法结束标记时，返回起始后的内容，尽量容错
    return trimmed.slice(bodyStart).trim()
  }

  return trimmed.slice(bodyStart, closeStart).trim()
}

/**
 * 清理内容中的XML标签和元数据
 */
function cleanXmlAndMetadata(content: string): string {
  if (!content || typeof content !== 'string') {
    return ''
  }

  // 首先尝试从```markdown块中提取
  const extracted = extractMarkdownBlock(content)
  if (extracted !== null) {
    return extracted
  }

  // 特殊处理：先提取context_summary的内容（保留内容，只删除标签）
  let cleaned = content
  cleaned = cleaned.replace(/<context_summary>(.*?)<\/context_summary>/gs, '$1')
  
  // 然后应用其他清理规则（跳过context_summary规则）
  for (const pattern of XML_CLEANUP_PATTERNS) {
    // 跳过context_summary的pattern（已经在上面处理过了）
    if (pattern.source && pattern.source.includes('context_summary')) {
      continue
    }
    cleaned = cleaned.replace(pattern, '')
  }

  // 清理多余的空行
  cleaned = cleaned.replace(/\n{3,}/g, '\n\n').trim()

  return cleaned
}

/**
 * 配置markdown-it实例
 */
function createMarkdownRenderer(): MarkdownIt {
  const md = new MarkdownIt({
    html: true,        // 允许HTML标签
    linkify: true,     // 自动转换URL为链接
    typographer: true, // 启用一些语言中立的替换 + 引号美化
    breaks: false,     // 转换段落里的 '\n' 到 <br>
    highlight: function (str, lang) {
      // 代码高亮处理
      if (lang && hljs.getLanguage(lang)) {
        try {
          const highlighted = hljs.highlight(str, { 
            language: lang,
            ignoreIllegals: true 
          }).value
          
          return `<pre class="hljs language-${lang}"><code class="language-${lang}">${highlighted}</code></pre>`
        } catch (e) {
          console.warn('Syntax highlighting failed:', e)
        }
      }
      
      // 无语言标识或高亮失败时的fallback
      const escaped = md.utils.escapeHtml(str)
      return `<pre class="hljs"><code>${escaped}</code></pre>`
    }
  })

  // 自定义表格渲染规则
  md.renderer.rules.table_open = () => '<div class="table-wrapper"><table class="markdown-table">\n'
  md.renderer.rules.table_close = () => '</table></div>\n'
  
  // 自定义链接渲染规则（添加target="_blank"和安全属性）
  const defaultLinkRender = md.renderer.rules.link_open || function(tokens, idx, options, env, self) {
    return self.renderToken(tokens, idx, options)
  }
  
  md.renderer.rules.link_open = function (tokens, idx, options, env, self) {
    const aIndex = tokens[idx].attrIndex('target')
    
    if (aIndex < 0) {
      tokens[idx].attrPush(['target', '_blank'])
    } else {
      tokens[idx].attrs![aIndex][1] = '_blank'
    }
    
    tokens[idx].attrPush(['rel', 'noopener noreferrer'])
    
    return defaultLinkRender(tokens, idx, options, env, self)
  }

  return md
}

// 创建单例渲染器实例
let rendererInstance: MarkdownIt | null = null

/**
 * 获取markdown渲染器实例（单例）
 */
export function getMarkdownRenderer(): MarkdownIt {
  if (!rendererInstance) {
    rendererInstance = createMarkdownRenderer()
  }
  return rendererInstance
}

/**
 * 渲染markdown内容为HTML
 * 
 * @param content - 原始markdown内容（可能包含XML标签）
 * @param options - 渲染选项
 * @returns 渲染后的HTML字符串
 */
export function renderMarkdown(
  content: string,
  options: {
    cleanXml?: boolean      // 是否清理XML标签，默认true
    wrapperClass?: string   // 包装div的class名称
  } = {}
): string {
  const {
    cleanXml = true,
    wrapperClass = 'markdown-content'
  } = options

  // 安全检查
  if (!content || typeof content !== 'string') {
    return `<div class="${wrapperClass}"><p class="text-gray-500">暂无内容</p></div>`
  }

  // 清理XML标签
  const cleaned = cleanXml ? cleanXmlAndMetadata(content) : content

  // 如果清理后为空
  if (!cleaned) {
    return `<div class="${wrapperClass}"><p class="text-gray-500">暂无内容</p></div>`
  }

  // 渲染markdown
  const md = getMarkdownRenderer()
  const html = md.render(cleaned)

  // 包装在容器中
  return `<div class="${wrapperClass}">${html}</div>`
}

/**
 * 仅清理XML标签，不渲染markdown
 */
export function cleanContent(content: string): string {
  return cleanXmlAndMetadata(content)
}

/**
 * 提取纯文本（移除markdown和HTML标签）
 */
export function extractPlainText(content: string): string {
  const cleaned = cleanXmlAndMetadata(content)
  const md = getMarkdownRenderer()
  const html = md.render(cleaned)
  
  // 简单的HTML标签移除
  return html.replace(/<[^>]+>/g, '').replace(/\s+/g, ' ').trim()
}

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
  // 移除其他XML标签
  /<context_summary>.*?<\/context_summary>/gs,
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
 * 从顶层```markdown块中提取内容，支持嵌套代码块
 */
function extractMarkdownBlock(content: string): string | null {
  const start = content.indexOf('```markdown')
  if (start === -1) return null

  let startBackticks = 3
  while (content[start + startBackticks] === '`') startBackticks++

  let lineEnd = content.indexOf('\n', start + startBackticks)
  if (lineEnd === -1) lineEnd = content.length
  let bodyStart = lineEnd + 1
  if (bodyStart > content.length) bodyStart = content.length

  // 从末尾向前查找最后一个行首围栏作为顶层结束
  let endPos = -1
  let search = content.length
  while (true) {
    const idx = content.lastIndexOf('```', search)
    if (idx <= start) break
    const isLineStart = idx === 0 || content[idx - 1] === '\n' || content[idx - 1] === '\r'
    if (!isLineStart) {
      search = idx - 1
      continue
    }
    let count = 3
    while (content[idx + count] === '`') count++
    if (count >= startBackticks) {
      endPos = idx
      break
    }
    search = idx - 1
  }

  return content.slice(bodyStart, endPos !== -1 ? endPos : content.length).trim()
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

  // 否则使用正则清理
  let cleaned = content
  for (const pattern of XML_CLEANUP_PATTERNS) {
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


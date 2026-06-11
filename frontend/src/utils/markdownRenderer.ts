import { i18n } from '@/i18n'
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
import { loadMermaid } from './mermaidLoader'

/**
 * 模块级自增计数器，用于 mermaid.render() 的临时 DOM id。
 * 与容器 id 解耦，保证即使两个图表源码相同（容器 id 一致）也不会发生
 * 渲染时 id 冲突。
 */
let mermaidRenderSeq = 0

/**
 * 根据内容生成稳定的短哈希（djb2）。
 *
 * Mermaid 容器 id 必须由源码内容**确定性**派生，而非自增计数器：
 * `renderMarkdown` 会在组件每次重渲染时被 v-html 调用，若 id 每次不同，
 * 输出的 HTML 字符串就会变化，触发 Vue 重新 patch innerHTML，抹掉
 * `processMermaidBlocks()` 异步插入的 SVG（表现为图表一直“渲染中…”）。
 * 相同内容产出相同 id ⇒ 相同 HTML ⇒ Vue 跳过 patch ⇒ SVG 得以保留。
 */
function hashString(value: string): string {
  let hash = 5381
  for (let i = 0; i < value.length; i++) {
    hash = ((hash << 5) + hash + value.charCodeAt(i)) | 0
  }
  return (hash >>> 0).toString(36)
}

const escapeHtml = (value: string): string =>
  value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')

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
  const md: MarkdownIt = new MarkdownIt({
    html: true,        // 允许HTML标签
    linkify: true,     // 自动转换URL为链接
    typographer: true, // 启用一些语言中立的替换 + 引号美化
    breaks: false,     // 转换段落里的 '\n' 到 <br>
    highlight: function (str: string, lang: string): string {
      // Mermaid 代码块：输出占位容器，稍后由 processMermaidBlocks() 异步渲染为 SVG。
      if (lang === 'mermaid') {
        // 容器 id 由源码哈希派生，保证同一内容多次渲染产出一致的 HTML。
        const id = `mermaid-${hashString(str)}`
        const escapedSource = escapeHtml(str)
        // data-mermaid-source 保存原始源码（HTML 实体编码，读取 dataset 时自动解码），
        // 供异步渲染、错误降级与复制源码功能使用。
        return (
          `<div class="mermaid-container" data-mermaid-id="${id}" ` +
          `data-mermaid-source="${escapedSource}" data-mermaid-state="pending">` +
          `<div class="mermaid-loading">${i18n.global.t('markdown.mermaidLoading')}</div>` +
          `<pre class="hljs mermaid-source language-mermaid"><code>${escapedSource}</code></pre>` +
          `</div>`
        )
      }

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
      const escaped = escapeHtml(str)
      return `<pre class="hljs"><code>${escaped}</code></pre>`
    }
  })

  // 自定义表格渲染规则
  md.renderer.rules.table_open = () => '<div class="table-wrapper"><table class="markdown-table">\n'
  md.renderer.rules.table_close = () => '</table></div>\n'
  
  // 自定义链接渲染规则（添加target="_blank"和安全属性）
  type LinkOpenRule = NonNullable<typeof md.renderer.rules.link_open>
  const defaultLinkRender = md.renderer.rules.link_open
  
  const linkOpenRule: LinkOpenRule = function (tokens, idx, options, env, self) {
    const aIndex = tokens[idx].attrIndex('target')
    
    if (aIndex < 0) {
      tokens[idx].attrPush(['target', '_blank'])
    } else {
      tokens[idx].attrs![aIndex][1] = '_blank'
    }
    
    tokens[idx].attrPush(['rel', 'noopener noreferrer'])
    
    return defaultLinkRender
      ? defaultLinkRender(tokens, idx, options, env, self)
      : self.renderToken(tokens, idx, options)
  }
  md.renderer.rules.link_open = linkOpenRule

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
    return `<div class="${wrapperClass}"><p class="text-gray-500">${i18n.global.t('markdown.noContent')}</p></div>`
  }

  // 清理XML标签
  const cleaned = cleanXml ? cleanXmlAndMetadata(content) : content

  // 如果清理后为空
  if (!cleaned) {
    return `<div class="${wrapperClass}"><p class="text-gray-500">${i18n.global.t('markdown.noContent')}</p></div>`
  }

  // 渲染markdown
  const md = getMarkdownRenderer()
  const html = md.render(cleaned)

  // 包装在容器中
  return `<div class="${wrapperClass}">${html}</div>`
}

/**
 * 处理容器内所有 Mermaid 占位元素，将其异步渲染为 SVG 图表。
 *
 * 行为：
 * - 查找所有处于 `pending` 状态的 `.mermaid-container`；
 * - 懒加载 Mermaid 实例后，对每个容器调用 `mermaid.render()`；
 * - 渲染成功：替换为 SVG，并附加“复制源码”按钮；
 * - 渲染失败：显示带高亮的原始源码 + 错误提示（优雅降级）；
 * - 库加载失败：所有占位元素降级为普通源码块。
 *
 * 该函数幂等：仅处理 `data-mermaid-state="pending"` 的容器，可安全重复调用。
 *
 * @param containerEl - 包含 Mermaid 占位元素的 DOM 容器（如消息列表根节点）
 */
export async function processMermaidBlocks(containerEl: HTMLElement | null): Promise<void> {
  if (!containerEl) return

  const containers = Array.from(
    containerEl.querySelectorAll<HTMLElement>('.mermaid-container[data-mermaid-state="pending"]')
  )
  if (containers.length === 0) return

  // 标记为处理中，避免并发重复渲染同一容器
  containers.forEach((el) => {
    el.dataset.mermaidState = 'rendering'
  })

  let mermaid
  try {
    mermaid = await loadMermaid()
  } catch (err) {
    // 库加载失败：降级为普通源码块（占位容器已内置 <pre> 源码，保留即可）
    console.warn(i18n.global.t('markdown.mermaidLoadFail'), err)
    containers.forEach((el) => {
      el.dataset.mermaidState = 'error'
      el.classList.add('is-error')
      const loading = el.querySelector('.mermaid-loading')
      if (loading) loading.remove()
    })
    return
  }

  await Promise.all(
    containers.map(async (el) => {
      const source = el.dataset.mermaidSource || ''
      const renderId = `mermaid-render-${++mermaidRenderSeq}`
      try {
        const { svg } = await mermaid.render(renderId, source)
        el.innerHTML =
          `<div class="mermaid-svg">${svg}</div>` +
          `<button class="mermaid-copy-btn" type="button" aria-label="${i18n.global.t('markdown.copySource')}">${i18n.global.t('markdown.copySource')}</button>`
        el.dataset.mermaidState = 'done'
        el.classList.add('is-rendered')
      } catch (err) {
        const message = err instanceof Error ? err.message : String(err)
        el.innerHTML =
          `<div class="mermaid-error">${i18n.global.t('markdown.mermaidRenderFail', { msg: escapeHtml(message) })}</div>` +
          `<pre class="hljs mermaid-source language-mermaid"><code>${escapeHtml(source)}</code></pre>` +
          `<button class="mermaid-copy-btn" type="button" aria-label="${i18n.global.t('markdown.copySource')}">${i18n.global.t('markdown.copySource')}</button>`
        el.dataset.mermaidState = 'error'
        el.classList.add('is-error')
      }
    })
  )
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

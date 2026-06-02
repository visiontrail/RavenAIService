/**
 * Mermaid 库懒加载器
 *
 * Mermaid.js 完整包体积较大（~2MB），不适合包含在首屏 bundle 中。
 * 本模块通过动态 import 按需加载 Mermaid，并使用模块级 Promise 缓存
 * 确保整个页面生命周期内只加载和初始化一次。
 *
 * 初始化配置：
 * - securityLevel: 'strict'  —— 禁止执行脚本/HTML 标签，防止 XSS
 * - theme: 'default'         —— 浅色主题，深色文字 + 浅色方框，保证可读性
 *                              （旧版 dark 主题会出现“黑底黑字黑框”难以辨识）
 * - flowchart.htmlLabels:false—— 标签渲染为 SVG <text> 而非 foreignObject，
 *                              既保证浅色背景对比度，也让导出 PNG 不会污染 canvas
 * - themeVariables           —— 浅色配色，与整体浅色聊天界面协调
 */

import type { Mermaid } from 'mermaid'

// 模块级 Promise 缓存，确保只加载并初始化一次
let mermaidPromise: Promise<Mermaid> | null = null

/**
 * 动态加载并初始化 Mermaid 实例。
 * 多次调用返回同一个缓存的 Promise。
 */
export function loadMermaid(): Promise<Mermaid> {
  if (!mermaidPromise) {
    mermaidPromise = import('mermaid')
      .then((module) => {
        const mermaid = module.default

        mermaid.initialize({
          startOnLoad: false,
          securityLevel: 'strict',
          theme: 'default',
          flowchart: { htmlLabels: false, useMaxWidth: true },
          fontFamily:
            'ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif',
          themeVariables: {
            // 浅色配色：深色文字 + 浅色方框，确保在白色容器上清晰可读
            background: '#ffffff',
            primaryColor: '#eff6ff',
            primaryBorderColor: '#3b82f6',
            primaryTextColor: '#1f2937',
            secondaryColor: '#f1f5f9',
            tertiaryColor: '#f8fafc',
            lineColor: '#64748b',
            textColor: '#1f2937',
            mainBkg: '#eff6ff',
            nodeBorder: '#3b82f6',
            clusterBkg: '#f8fafc',
            clusterBorder: '#cbd5e1',
            titleColor: '#1f2937',
            edgeLabelBackground: '#ffffff',
          },
        })

        return mermaid
      })
      .catch((error) => {
        // 加载失败时清空缓存，允许后续重试
        mermaidPromise = null
        throw error
      })
  }

  return mermaidPromise
}

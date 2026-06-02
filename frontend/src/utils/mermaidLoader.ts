/**
 * Mermaid 库懒加载器
 *
 * Mermaid.js 完整包体积较大（~2MB），不适合包含在首屏 bundle 中。
 * 本模块通过动态 import 按需加载 Mermaid，并使用模块级 Promise 缓存
 * 确保整个页面生命周期内只加载和初始化一次。
 *
 * 初始化配置：
 * - securityLevel: 'strict'  —— 禁止执行脚本/HTML 标签，防止 XSS
 * - theme: 'dark'            —— 与现有 github-dark 代码块主题协调
 * - themeVariables           —— 微调配色匹配 .hljs（#0d1117 背景）
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
          theme: 'dark',
          fontFamily:
            'ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif',
          themeVariables: {
            // 与 github-dark (.hljs) 代码块风格保持一致
            background: '#0d1117',
            primaryColor: '#161b22',
            primaryBorderColor: '#30363d',
            primaryTextColor: '#c9d1d9',
            secondaryColor: '#21262d',
            tertiaryColor: '#161b22',
            lineColor: '#8b949e',
            textColor: '#c9d1d9',
            mainBkg: '#161b22',
            nodeBorder: '#30363d',
            clusterBkg: '#0d1117',
            clusterBorder: '#30363d',
            titleColor: '#c9d1d9',
            edgeLabelBackground: '#0d1117',
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

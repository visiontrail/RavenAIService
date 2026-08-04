/**
 * Mermaid 库懒加载器
 *
 * Mermaid.js 完整包体积较大（~2MB），不适合包含在首屏 bundle 中。
 * 本模块通过动态 import 按需加载 Mermaid，并使用模块级 Promise 缓存
 * 确保整个页面生命周期内只加载一次。
 *
 * 初始化配置：
 * - securityLevel: 'strict'  —— 禁止执行脚本/HTML 标签，防止 XSS
 * - flowchart.htmlLabels:false—— 标签渲染为 SVG <text> 而非 foreignObject，
 *                              既保证背景对比度，也让导出 PNG 不会污染 canvas
 * - themeVariables           —— 随 html.dark class 在浅色/深色两套配色间切换，
 *                              与 styles/theme.css 的 --rw-* 令牌保持一致。
 *
 * 深色配色刻意不使用 Mermaid 自带的 `dark` 主题（旧版会出现「黑底黑字黑框」
 * 难以辨识），而是基于 `base` 主题 + darkMode 显式给全套变量，确保
 * 深色卡片上文字/边框都有足够对比度。主题切换时调用 `loadMermaid()` 会自动
 * 重新 initialize，配合 `refreshMermaidBlocks()` 重绘已有图表。
 */

import type { Mermaid } from 'mermaid'

/** Mermaid 配色模式，与 <html> 上的 dark class 对应。 */
export type MermaidThemeMode = 'light' | 'dark'

/** 浅色配色：深色文字 + 浅色方框，确保在白色容器上清晰可读 */
const LIGHT_THEME_VARIABLES: Record<string, string> = {
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
}

/** 深色配色：浅色文字 + 深色方框，对应 --rw-surface-card 与 --rw-ink 令牌 */
const DARK_THEME_VARIABLES: Record<string, string | boolean> = {
  darkMode: true,
  background: '#17171d',
  primaryColor: '#232330',
  primaryBorderColor: '#8caaff',
  primaryTextColor: '#f7f7fb',
  secondaryColor: '#2a2a3a',
  secondaryBorderColor: '#5d7dd6',
  secondaryTextColor: '#e6e8ef',
  tertiaryColor: '#1f1f28',
  tertiaryBorderColor: '#35354a',
  tertiaryTextColor: '#d8dae2',
  lineColor: '#8b90a0',
  textColor: '#d8dae2',
  mainBkg: '#232330',
  nodeBorder: '#8caaff',
  nodeTextColor: '#f7f7fb',
  clusterBkg: '#1b1b22',
  clusterBorder: '#35354a',
  titleColor: '#f7f7fb',
  edgeLabelBackground: '#232330',
  labelBackground: '#232330',
  labelTextColor: '#d8dae2',
  errorBkgColor: '#3a1f24',
  errorTextColor: '#ff9d9d',
}

// 模块级 Promise 缓存，确保库本身只加载一次
let mermaidPromise: Promise<Mermaid> | null = null
// 当前已应用的配色模式；与页面主题不一致时重新 initialize
let initializedMode: MermaidThemeMode | null = null

/** 读取当前页面配色模式（SSR / 测试环境无 document 时按浅色处理）。 */
export function currentMermaidThemeMode(): MermaidThemeMode {
  if (typeof document === 'undefined') return 'light'
  return document.documentElement.classList.contains('dark') ? 'dark' : 'light'
}

function initializeMermaid(mermaid: Mermaid, mode: MermaidThemeMode): void {
  mermaid.initialize({
    startOnLoad: false,
    securityLevel: 'strict',
    theme: mode === 'dark' ? 'base' : 'default',
    flowchart: { htmlLabels: false, useMaxWidth: true },
    fontFamily:
      'ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif',
    themeVariables: mode === 'dark' ? DARK_THEME_VARIABLES : LIGHT_THEME_VARIABLES,
  })
  initializedMode = mode
}

/**
 * 动态加载并初始化 Mermaid 实例。
 * 库只加载一次；每次调用都会校验配色模式，主题切换后自动重新 initialize。
 */
export function loadMermaid(): Promise<Mermaid> {
  const mode = currentMermaidThemeMode()

  if (!mermaidPromise) {
    mermaidPromise = import('mermaid')
      .then((module) => {
        const mermaid = module.default
        initializeMermaid(mermaid, mode)
        return mermaid
      })
      .catch((error) => {
        // 加载失败时清空缓存，允许后续重试
        mermaidPromise = null
        initializedMode = null
        throw error
      })

    return mermaidPromise
  }

  return mermaidPromise.then((mermaid) => {
    if (initializedMode !== mode) initializeMermaid(mermaid, mode)
    return mermaid
  })
}

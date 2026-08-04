import { beforeEach, describe, expect, it, vi } from 'vitest'

const renderCalls: string[] = []

// Mermaid 本体在 node 环境跑不起来，用假实例验证「重置 → 重绘」的控制流。
vi.mock('@/utils/mermaidLoader', () => ({
  currentMermaidThemeMode: () => 'dark',
  loadMermaid: vi.fn(async () => ({
    render: async (_id: string, source: string) => {
      renderCalls.push(source)
      if (source.includes('boom')) throw new Error('bad syntax')
      return { svg: `<svg data-source="${source}"></svg>` }
    },
  })),
}))

const { refreshMermaidBlocks } = await import('@/utils/markdownRenderer')

class StubClassList {
  private readonly classes: Set<string>

  constructor(initial: string[]) {
    this.classes = new Set(initial)
  }

  add(...names: string[]): void {
    names.forEach((name) => this.classes.add(name))
  }

  remove(...names: string[]): void {
    names.forEach((name) => this.classes.delete(name))
  }

  contains(name: string): boolean {
    return this.classes.has(name)
  }
}

interface StubElement {
  dataset: { mermaidSource: string; mermaidState: string }
  classList: StubClassList
  innerHTML: string
  querySelector: () => null
}

function makeContainer(source: string, state: string, classes: string[] = []): StubElement {
  return {
    dataset: { mermaidSource: source, mermaidState: state },
    classList: new StubClassList(['mermaid-container', ...classes]),
    innerHTML: '<svg>stale colours</svg>',
    querySelector: () => null,
  }
}

/** 只按选择器里的 data-mermaid-state 过滤，保证选择器写错时测试会失败。 */
function makeRoot(children: StubElement[]): HTMLElement {
  return {
    querySelectorAll: (selector: string) => {
      const states = [...selector.matchAll(/data-mermaid-state="([^"]+)"/g)].map((m) => m[1])
      return children.filter((el) => states.includes(el.dataset.mermaidState))
    },
  } as unknown as HTMLElement
}

beforeEach(() => {
  renderCalls.length = 0
})

describe('refreshMermaidBlocks', () => {
  it('re-renders diagrams that were already drawn with the previous theme', async () => {
    const done = makeContainer('graph TD;A-->B;', 'done', ['is-rendered'])
    await refreshMermaidBlocks(makeRoot([done]))

    expect(renderCalls).toEqual(['graph TD;A-->B;'])
    expect(done.dataset.mermaidState).toBe('done')
    expect(done.innerHTML).toContain('<svg data-source="graph TD;A-->B;">')
    expect(done.classList.contains('is-rendered')).toBe(true)
  })

  it('retries containers that previously failed to render', async () => {
    const failed = makeContainer('graph TD;A-->B;', 'error', ['is-error'])
    await refreshMermaidBlocks(makeRoot([failed]))

    expect(renderCalls).toEqual(['graph TD;A-->B;'])
    expect(failed.classList.contains('is-error')).toBe(false)
    expect(failed.classList.contains('is-rendered')).toBe(true)
  })

  it('keeps the source fallback when the reset diagram still fails to render', async () => {
    const done = makeContainer('boom --> ?', 'done', ['is-rendered'])
    await refreshMermaidBlocks(makeRoot([done]))

    expect(done.dataset.mermaidState).toBe('error')
    expect(done.classList.contains('is-error')).toBe(true)
    expect(done.innerHTML).toContain('boom --&gt; ?')
  })

  it('leaves pending and in-flight containers alone', async () => {
    const pending = makeContainer('graph TD;A-->B;', 'pending')
    const rendering = makeContainer('graph TD;C-->D;', 'rendering')
    await refreshMermaidBlocks(makeRoot([pending, rendering]))

    // 没有已渲染的图表 ⇒ 不做任何事，避免打断在途渲染。
    expect(renderCalls).toEqual([])
    expect(pending.dataset.mermaidState).toBe('pending')
    expect(rendering.dataset.mermaidState).toBe('rendering')
  })

  it('ignores a null container', async () => {
    await expect(refreshMermaidBlocks(null)).resolves.toBeUndefined()
    expect(renderCalls).toEqual([])
  })
})

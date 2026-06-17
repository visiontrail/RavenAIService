import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const getPublic = vi.fn()

vi.mock('@/api/share', () => ({
  shareApi: {
    get: vi.fn(),
    createOrRefresh: vi.fn(),
    revoke: vi.fn(),
    getPublic: (...args: unknown[]) => getPublic(...args),
  },
}))

import { useSharedConversation } from '@/composables/useSharedConversation'
import { renderMarkdown } from '@/utils/markdownRenderer'

describe('useSharedConversation', () => {
  beforeEach(() => {
    getPublic.mockReset()
    vi.spyOn(console, 'warn').mockImplementation(() => {})
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('loads a valid snapshot', async () => {
    getPublic.mockResolvedValue({
      title: '排障对话',
      shared_at: '2026-06-16T10:00:00Z',
      message_count: 2,
      messages: [
        { role: 'user', content: '你好', created_at: '2026-06-16T09:59:00Z' },
        { role: 'ai', content: '你好，有什么可以帮你', created_at: '2026-06-16T10:00:00Z' },
      ],
    })
    const page = useSharedConversation()

    await page.load('tok_valid')

    expect(getPublic).toHaveBeenCalledWith('tok_valid')
    expect(page.loading.value).toBe(false)
    expect(page.notFound.value).toBe(false)
    expect(page.snapshot.value?.title).toBe('排障对话')
    expect(page.snapshot.value?.messages).toHaveLength(2)
  })

  it('maps a 404 / error to the empty state without leaking content', async () => {
    getPublic.mockRejectedValue({ response: { status: 404 } })
    const page = useSharedConversation()

    await page.load('tok_revoked')

    expect(page.notFound.value).toBe(true)
    expect(page.snapshot.value).toBeNull()
    expect(page.loading.value).toBe(false)
  })

  it('treats a missing token as not found and does not call the API', async () => {
    const page = useSharedConversation()

    await page.load('')

    expect(getPublic).not.toHaveBeenCalled()
    expect(page.notFound.value).toBe(true)
    expect(page.snapshot.value).toBeNull()
  })
})

describe('shared conversation rendering parity', () => {
  it('renders Mermaid code blocks as deferred mermaid containers', () => {
    const html = renderMarkdown('```mermaid\ngraph TD;A-->B;\n```', {
      wrapperClass: 'markdown-content text-ink',
    })
    expect(html).toContain('mermaid-container')
    expect(html).toContain('data-mermaid-state="pending"')
  })

  it('renders Markdown tables and fenced code the same way as the main chat', () => {
    const html = renderMarkdown('| a | b |\n| - | - |\n| 1 | 2 |\n\n```js\nconst x = 1\n```', {
      wrapperClass: 'markdown-content text-ink',
    })
    expect(html).toContain('markdown-table')
    expect(html).toContain('hljs')
  })
})

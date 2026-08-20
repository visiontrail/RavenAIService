import { nextTick, ref } from 'vue'
import { describe, expect, it, vi } from 'vitest'

import { useMermaidPreview } from '@/composables/useMermaidPreview'

const flushPreviewWatcher = async () => {
  await nextTick()
  await nextTick()
}

describe('useMermaidPreview', () => {
  it('waits until the preview root exists before processing Mermaid blocks', async () => {
    const containerRef = ref<HTMLElement | null>(null)
    const renderedHtml = ref('<div class="mermaid-container"></div>')
    const processor = vi.fn(async () => undefined)

    useMermaidPreview(containerRef, renderedHtml, processor)
    await flushPreviewWatcher()

    expect(processor).not.toHaveBeenCalled()
  })

  it('processes the current root after a conditional preview mounts', async () => {
    const containerRef = ref<HTMLElement | null>(null)
    const renderedHtml = ref('<div class="mermaid-container"></div>')
    const processor = vi.fn(async () => undefined)
    const mountedContainer = {} as HTMLElement

    useMermaidPreview(containerRef, renderedHtml, processor)
    containerRef.value = mountedContainer
    await flushPreviewWatcher()

    expect(processor).toHaveBeenCalledOnce()
    expect(processor).toHaveBeenCalledWith(mountedContainer)
  })

  it('processes new Markdown rendered inside an already-mounted preview root', async () => {
    const mountedContainer = {} as HTMLElement
    const containerRef = ref<HTMLElement | null>(mountedContainer)
    const renderedHtml = ref('<p>first file</p>')
    const processor = vi.fn(async () => undefined)

    useMermaidPreview(containerRef, renderedHtml, processor)
    renderedHtml.value = '<div class="mermaid-container">second file</div>'
    await flushPreviewWatcher()

    expect(processor).toHaveBeenCalledOnce()
    expect(processor).toHaveBeenCalledWith(mountedContainer)
  })

  it('uses the latest preview root if the conditional branch changes before the next tick', async () => {
    const oldContainer = {} as HTMLElement
    const newContainer = {} as HTMLElement
    const containerRef = ref<HTMLElement | null>(oldContainer)
    const renderedHtml = ref('<p>first file</p>')
    const processor = vi.fn(async () => undefined)

    useMermaidPreview(containerRef, renderedHtml, processor)
    renderedHtml.value = '<div class="mermaid-container">second file</div>'
    containerRef.value = newContainer
    await flushPreviewWatcher()

    expect(processor).toHaveBeenCalledOnce()
    expect(processor).toHaveBeenCalledWith(newContainer)
  })
})

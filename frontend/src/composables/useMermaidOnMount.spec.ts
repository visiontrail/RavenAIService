import { nextTick, ref } from 'vue'
import { describe, expect, it, vi } from 'vitest'

import { useMermaidOnMount } from '@/composables/useMermaidOnMount'

describe('useMermaidOnMount', () => {
  it('processes Mermaid after a conditional container is mounted', async () => {
    const containerRef = ref<HTMLElement | null>(null)
    const processor = vi.fn(async () => undefined)
    const mountedContainer = {} as HTMLElement

    useMermaidOnMount(containerRef, processor)

    // Mirrors the loading branch: no transcript DOM exists yet.
    await nextTick()
    expect(processor).not.toHaveBeenCalled()

    // Mirrors loading becoming false and Vue assigning the transcript ref.
    containerRef.value = mountedContainer
    await nextTick()

    expect(processor).toHaveBeenCalledOnce()
    expect(processor).toHaveBeenCalledWith(mountedContainer)
  })
})

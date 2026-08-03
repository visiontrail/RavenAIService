import { watch, type Ref } from 'vue'

import { processMermaidBlocks } from '@/utils/markdownRenderer'

export type MermaidBlockProcessor = (container: HTMLElement | null) => Promise<void>

/**
 * Process deferred Mermaid placeholders when a conditional DOM container mounts.
 *
 * A post-flush watcher is important for containers hidden behind `v-if`: data can
 * be ready while Vue is still displaying a loading branch, where the template
 * ref remains null.
 */
export function useMermaidOnMount(
  containerRef: Ref<HTMLElement | null>,
  processor: MermaidBlockProcessor = processMermaidBlocks,
): void {
  watch(
    containerRef,
    (container) => {
      if (container) void processor(container)
    },
    { flush: 'post' },
  )
}

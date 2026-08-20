import { nextTick, watch, type Ref } from 'vue'

import { processMermaidBlocks } from '@/utils/markdownRenderer'
import type { MermaidBlockProcessor } from '@/composables/useMermaidOnMount'

/**
 * Render deferred Mermaid blocks in a Markdown preview after Vue commits its DOM.
 *
 * Watching both the conditional preview root and the rendered HTML is necessary:
 * the root mounts when a Markdown file is opened for the first time, but remains
 * mounted while the user switches between Markdown files and only `v-html`
 * changes underneath it.
 */
export function useMermaidPreview(
  containerRef: Ref<HTMLElement | null>,
  renderedHtml: Readonly<Ref<string>>,
  processor: MermaidBlockProcessor = processMermaidBlocks,
): void {
  watch(
    [containerRef, renderedHtml],
    async () => {
      // A post-flush watcher runs after the component patch. The extra tick also
      // covers conditional branches whose ref is assigned by that same patch.
      await nextTick()
      const container = containerRef.value
      if (container) void processor(container)
    },
    { flush: 'post' },
  )
}

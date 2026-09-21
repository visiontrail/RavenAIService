import { onScopeDispose, ref, watch } from 'vue'
import { userApi } from '@/api/user'
import type { ChatSessionSearchResult } from '@/types'

/** 每次输入立即作废旧请求，包括防抖等待和中文输入法组词阶段。 */
export function useConversationSearch() {
  const query = ref('')
  const composing = ref(false)
  const items = ref<ChatSessionSearchResult[]>([])
  const loading = ref(false)
  const error = ref(false)
  const hasMore = ref(false)
  let generation = 0
  let controller: AbortController | undefined
  let timer: ReturnType<typeof setTimeout> | undefined
  let offset = 0

  function invalidate() {
    generation += 1
    controller?.abort()
    clearTimeout(timer)
  }

  async function fetchPage(append = false) {
    invalidate()
    const current = generation
    controller = new AbortController()
    loading.value = true
    error.value = false
    try {
      const response = await userApi.searchSessions(query.value.trim(), append ? offset : 0, controller.signal)
      if (current !== generation) return
      if (!response.success || !response.data) throw new Error('Search failed')
      const page = response.data.items
      const previous = append ? items.value : []
      const seen = new Set(previous.map(item => item.id))
      items.value = [...previous, ...page.filter(item => !seen.has(item.id))]
      offset = (append ? offset : 0) + page.length
      hasMore.value = response.data.has_more
    } catch {
      if (current === generation) error.value = true
    } finally {
      if (current === generation) loading.value = false
    }
  }

  watch([query, composing], () => {
    invalidate()
    items.value = []
    offset = 0
    hasMore.value = false
    error.value = false
    loading.value = true
    if (!composing.value) {
      timer = setTimeout(() => { void fetchPage() }, query.value.trim() ? 250 : 0)
    }
  }, { immediate: true, flush: 'sync' })

  onScopeDispose(invalidate)
  return {
    query, composing, items, loading, error, hasMore,
    retry: () => fetchPage(items.value.length > 0),
    loadMore: () => { if (!loading.value && hasMore.value) return fetchPage(true) },
  }
}

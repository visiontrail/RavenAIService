import { ref } from 'vue'
import { shareApi } from '@/api/share'
import type { PublicShareSnapshot } from '@/types'

/**
 * Loads a public, read-only conversation snapshot by token.
 *
 * Decoupled from the page markup so the load / 404 state machine is unit
 * testable in the node test harness (the page's ``onMounted`` fetch does not
 * run under SSR). A 404 / network error maps to ``notFound`` with no snapshot,
 * so the page never renders partial or leaked content.
 */
export function useSharedConversation() {
  const loading = ref(true)
  const notFound = ref(false)
  const snapshot = ref<PublicShareSnapshot | null>(null)

  const load = async (token: string): Promise<void> => {
    loading.value = true
    notFound.value = false
    if (!token) {
      notFound.value = true
      snapshot.value = null
      loading.value = false
      return
    }
    try {
      snapshot.value = await shareApi.getPublic(token)
    } catch {
      notFound.value = true
      snapshot.value = null
    } finally {
      loading.value = false
    }
  }

  return { loading, notFound, snapshot, load }
}

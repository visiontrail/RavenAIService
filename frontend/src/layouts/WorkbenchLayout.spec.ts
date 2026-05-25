import { beforeEach, describe, expect, it } from 'vitest'
import { createSSRApp, h } from 'vue'
import { renderToString } from '@vue/server-renderer'
import { createMemoryHistory, createRouter } from 'vue-router'
import { createPinia, setActivePinia } from 'pinia'

import WorkbenchLayout from '@/layouts/WorkbenchLayout.vue'
import { useChatSessionStore } from '@/stores/chatSession'
import { useConversationRunsStore } from '@/stores/conversationRuns'
import { useUserStore } from '@/stores/user'
import type { ChatSessionSummary } from '@/types'

const now = new Date('2026-05-25T10:00:00.000Z').toISOString()

const session = (id: string, title: string, runStatus?: string | null): ChatSessionSummary => ({
  id,
  title,
  created_at: now,
  updated_at: now,
  last_message_at: now,
  message_count: 1,
  active_run_id: runStatus === 'running' ? `run-${id}` : null,
  run_status: runStatus || null,
})

const createHarness = async () => {
  const pinia = createPinia()
  const EmptyPage = { template: '<div />' }
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/workbench', name: 'Workbench', component: EmptyPage },
      { path: '/logs', name: 'Logs', component: EmptyPage },
      { path: '/devices', name: 'Devices', component: EmptyPage },
      { path: '/raven-manager', name: 'RavenManager', component: EmptyPage },
    ],
  })
  setActivePinia(pinia)

  const userStore = useUserStore(pinia)
  userStore.setToken('token-for-test')
  userStore.setProfile({
    id: 'user-1',
    username: 'tester',
    email: 'tester@example.com',
    display_name: 'Tester',
    role: 'user',
    is_active: true,
    created_at: now,
    updated_at: now,
  })

  await router.push('/workbench')
  await router.isReady()

  const render = () => {
    const app = createSSRApp({ render: () => h(WorkbenchLayout) })
    app.use(pinia)
    app.use(router)
    return renderToString(app)
  }

  return { pinia, render }
}

describe('WorkbenchLayout running session sidebar', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('renders a spinner for backend-reported running sessions only', async () => {
    const { pinia, render } = await createHarness()
    const sessionStore = useChatSessionStore(pinia)
    sessionStore.sessions = [
      session('session-a', 'Running conversation', 'running'),
      session('session-b', 'Idle conversation'),
    ]

    const html = await render()

    expect(html).toContain('Running conversation')
    expect(html).toContain('Idle conversation')
    expect(html.match(/aria-label="正在运行"/g)).toHaveLength(1)
  })

  it('uses the local running overlay and removes it after terminal status', async () => {
    const { pinia, render } = await createHarness()
    const sessionStore = useChatSessionStore(pinia)
    const runsStore = useConversationRunsStore(pinia)
    sessionStore.sessions = [session('session-a', 'Local overlay conversation')]

    const state = runsStore.ensureState('session-a')
    runsStore.mergeSnapshot(state, {
      run_id: 'run-a',
      session_id: 'session-a',
      status: 'running',
      agent_kind: 'device',
      trace_events: [],
    })

    expect(await render()).toContain('aria-label="正在运行"')

    runsStore.markTerminal(state, 'succeeded')

    expect(await render()).not.toContain('aria-label="正在运行"')
  })
})

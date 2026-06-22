<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useSharedConversation } from '@/composables/useSharedConversation'
import { renderMarkdown, processMermaidBlocks } from '@/utils/markdownRenderer'
import AgentTraceStream from '@/components/AgentTraceStream.vue'
import type { AgentTraceEvent } from '@/types/agentTrace'
import type { PublicShareMessage } from '@/types'

const route = useRoute()
const { t } = useI18n()

const { loading, notFound, snapshot, load } = useSharedConversation()
const threadRef = ref<HTMLElement | null>(null)

// Reuse the exact same Markdown/Mermaid renderer as the main conversation so
// rendering (code highlighting, tables, Mermaid diagrams) is identical.
const renderAi = (content: string) =>
  renderMarkdown(content || '', { wrapperClass: 'markdown-content text-ink' })

// Agent trace (thinking + tool calls) captured into the snapshot at share time.
// Rendered read-only via the same AgentTraceStream component as the live chat;
// older snapshots without a trace return an empty list (nothing renders).
const traceEventsOf = (msg: PublicShareMessage): AgentTraceEvent[] =>
  Array.isArray(msg.trace_events) ? (msg.trace_events as AgentTraceEvent[]) : []

const sharedAtLabel = computed(() => {
  const raw = snapshot.value?.shared_at
  if (!raw) return ''
  const date = new Date(raw)
  if (Number.isNaN(date.getTime())) return String(raw)
  return date.toLocaleString()
})

onMounted(async () => {
  const token = String(route.params.token || '')
  await load(token)
  if (snapshot.value) {
    if (typeof document !== 'undefined') {
      document.title = `${snapshot.value.title} · RavenAI`
    }
    await nextTick()
    if (threadRef.value) {
      // Render any Mermaid placeholders to SVG, identical to the main chat.
      await processMermaidBlocks(threadRef.value)
    }
  }
})
</script>

<template>
  <div class="shared-conversation">
    <header class="sc-header">
      <div class="sc-brand">
        <span class="sc-brand-dot" aria-hidden="true"></span>
        <span class="sc-brand-name">RavenAI</span>
      </div>
      <span class="sc-brand-tag">{{ t('sharedConversation.subtitle') }}</span>
    </header>

    <main class="sc-main">
      <!-- Loading -->
      <div v-if="loading" class="sc-loading">{{ t('sharedConversation.loading') }}</div>

      <!-- Invalid / revoked token -->
      <div v-else-if="notFound || !snapshot" class="sc-empty">
        <div class="sc-empty-icon" aria-hidden="true">
          <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M8 12h8"/></svg>
        </div>
        <h1 class="sc-empty-title">{{ t('sharedConversation.notFoundTitle') }}</h1>
        <p class="sc-empty-desc">{{ t('sharedConversation.notFoundDesc') }}</p>
        <router-link to="/" class="sc-cta">{{ t('sharedConversation.backHome') }}</router-link>
      </div>

      <!-- Snapshot -->
      <template v-else>
        <div class="sc-titlebar">
          <h1 class="sc-title">{{ snapshot.title }}</h1>
          <div class="sc-meta">
            <span v-if="sharedAtLabel">{{ t('sharedConversation.snapshotAt', { time: sharedAtLabel }) }}</span>
            <span class="sc-meta-dot">·</span>
            <span>{{ t('sharedConversation.messageCount', { count: snapshot.message_count }) }}</span>
          </div>
        </div>

        <div ref="threadRef" class="sc-thread">
          <div
            v-for="(msg, idx) in snapshot.messages"
            :key="idx"
            :class="['sc-msg', msg.role === 'user' ? 'is-user' : 'is-ai']"
          >
            <template v-if="msg.role === 'user'">
              <div class="sc-user-bubble">{{ msg.content }}</div>
              <div class="sc-user-label">{{ t('sharedConversation.userLabel') }}</div>
            </template>
            <template v-else>
              <div class="sc-ai-name">{{ t('sharedConversation.aiLabel') }}</div>
              <AgentTraceStream
                v-if="traceEventsOf(msg).length"
                class="sc-ai-trace"
                :events="traceEventsOf(msg)"
                :running="false"
              />
              <div class="sc-ai-text" v-html="renderAi(msg.content)"></div>
            </template>
          </div>
        </div>

        <footer class="sc-footer">
          <span class="sc-footer-note">{{ t('sharedConversation.footerNote') }}</span>
          <router-link to="/" class="sc-cta sc-cta-small">{{ t('sharedConversation.backHome') }}</router-link>
        </footer>
      </template>
    </main>
  </div>
</template>

<style scoped>
.shared-conversation {
  --sc-canvas: #ffffff;
  --sc-soft: #fafafa;
  --sc-ink: #171717;
  --sc-body: #60646c;
  --sc-muted: #999999;
  --sc-hairline: #ececef;
  --sc-hairline-strong: #dcdee0;
  --sc-accent: #171717;
  min-height: 100vh;
  background: var(--sc-soft);
  color: var(--sc-ink);
  font-family: 'Inter', -apple-system, system-ui, 'PingFang SC', 'Microsoft YaHei', sans-serif;
  display: flex;
  flex-direction: column;
}
.sc-header {
  display: flex; align-items: center; justify-content: space-between;
  height: 56px; padding: 0 20px;
  background: var(--sc-canvas);
  border-bottom: 1px solid var(--sc-hairline);
  position: sticky; top: 0; z-index: 10;
}
.sc-brand { display: flex; align-items: center; gap: 8px; }
.sc-brand-dot { width: 10px; height: 10px; border-radius: 50%; background: var(--sc-accent); }
.sc-brand-name { font-weight: 700; font-size: 15px; letter-spacing: .2px; }
.sc-brand-tag { font-size: 12px; color: var(--sc-muted); }
.sc-main { flex: 1; width: 100%; max-width: 820px; margin: 0 auto; padding: 28px 20px 64px; }
.sc-loading { padding: 60px 0; text-align: center; color: var(--sc-muted); font-size: 14px; }
.sc-empty { padding: 80px 16px; text-align: center; display: flex; flex-direction: column; align-items: center; gap: 12px; }
.sc-empty-icon { color: var(--sc-muted); }
.sc-empty-title { font-size: 20px; font-weight: 600; margin: 4px 0 0; }
.sc-empty-desc { font-size: 14px; color: var(--sc-body); margin: 0; max-width: 420px; line-height: 1.6; }
.sc-cta {
  margin-top: 8px; display: inline-flex; align-items: center;
  height: 38px; padding: 0 18px; border-radius: 8px;
  background: var(--sc-accent); color: #fff; font-size: 14px; font-weight: 500;
  text-decoration: none;
}
.sc-cta:hover { background: #2e2e2e; }
.sc-cta-small { height: 32px; padding: 0 14px; font-size: 13px; }
.sc-titlebar { margin-bottom: 22px; }
.sc-title { font-size: 22px; font-weight: 700; margin: 0; line-height: 1.3; word-break: break-word; }
.sc-meta { margin-top: 8px; font-size: 12.5px; color: var(--sc-muted); display: flex; gap: 6px; flex-wrap: wrap; }
.sc-meta-dot { color: var(--sc-hairline-strong); }
.sc-thread { display: flex; flex-direction: column; gap: 26px; }
.sc-msg.is-user { display: flex; flex-direction: column; align-items: flex-end; }
.sc-user-bubble {
  max-width: 90%;
  background: var(--sc-accent); color: #fff;
  padding: 11px 15px; border-radius: 14px 14px 4px 14px;
  font-size: 14.5px; line-height: 1.6; white-space: pre-wrap; word-break: break-word;
}
.sc-user-label { margin-top: 6px; font-size: 11.5px; color: var(--sc-muted); }
.sc-msg.is-ai { display: flex; flex-direction: column; gap: 6px; }
.sc-ai-name { font-size: 11.5px; font-weight: 600; letter-spacing: .4px; color: var(--sc-body); }
.sc-ai-trace { margin: 2px 0 6px; }
.sc-ai-text { font-size: 14.5px; line-height: 1.7; }
.sc-footer {
  margin-top: 48px; padding-top: 20px;
  border-top: 1px solid var(--sc-hairline);
  display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap;
}
.sc-footer-note { font-size: 12.5px; color: var(--sc-muted); }
@media (max-width: 600px) {
  .sc-main { padding: 20px 14px 48px; }
  .sc-title { font-size: 19px; }
}
</style>

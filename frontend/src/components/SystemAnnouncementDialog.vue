<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { Megaphone, X } from 'lucide-vue-next'
import { useAnnouncementStore } from '@/stores/announcement'
import { useAppStore } from '@/stores/app'
import { renderAnnouncementMarkdown } from '@/utils/markdownRenderer'

const { t } = useI18n()
const appStore = useAppStore()
const announcementStore = useAnnouncementStore()

const announcement = computed(() => announcementStore.pending)
const announcementHtml = computed(() => (
  announcement.value ? renderAnnouncementMarkdown(announcement.value.content) : ''
))

const formatPublishedAt = (value: string) => {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat(undefined, {
    year: 'numeric',
    month: 'short',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date)
}

const closeAnnouncement = async () => {
  try {
    const dismissed = await announcementStore.dismiss()
    if (!dismissed) throw new Error(t('workbench.announcement.dismissFailed'))
  } catch (error: any) {
    const detail = error?.response?.data?.detail || error?.message
    appStore.showNotification({
      title: t('workbench.announcement.dismissFailed'),
      message: typeof detail === 'string' ? detail : t('workbench.notifications.tryAgainLater'),
      type: 'error',
    })
  }
}
</script>

<template>
  <div v-if="announcement" class="announcement-backdrop">
    <section
      class="announcement-dialog"
      role="dialog"
      aria-modal="true"
      aria-labelledby="system-announcement-title"
      aria-describedby="system-announcement-content"
    >
      <div class="announcement-accent" aria-hidden="true"></div>
      <header class="announcement-header">
        <div class="announcement-icon" aria-hidden="true">
          <Megaphone :size="23" :stroke-width="1.8" />
        </div>
        <div class="announcement-heading">
          <span class="announcement-kicker">{{ t('workbench.announcement.kicker') }}</span>
          <h2 id="system-announcement-title">{{ announcement.title }}</h2>
        </div>
        <button
          type="button"
          class="announcement-close"
          :disabled="announcementStore.dismissing"
          :aria-label="t('workbench.announcement.acknowledge')"
          @click="closeAnnouncement"
        >
          <X :size="18" />
        </button>
      </header>

      <div
        id="system-announcement-content"
        class="announcement-content"
        v-html="announcementHtml"
      ></div>

      <footer class="announcement-footer">
        <div class="announcement-meta">
          <span>{{ t('workbench.announcement.publishedBy', { name: announcement.published_by }) }}</span>
          <span aria-hidden="true">·</span>
          <time :datetime="announcement.published_at">{{ formatPublishedAt(announcement.published_at) }}</time>
        </div>
        <button
          type="button"
          class="announcement-ack"
          :disabled="announcementStore.dismissing"
          @click="closeAnnouncement"
        >
          {{ announcementStore.dismissing
            ? t('workbench.announcement.acknowledging')
            : t('workbench.announcement.acknowledge') }}
        </button>
      </footer>
    </section>
  </div>
</template>

<style scoped>
.announcement-backdrop {
  position: fixed;
  inset: 0;
  z-index: 120;
  display: grid;
  place-items: center;
  padding: 1rem;
  background:
    radial-gradient(circle at 50% 28%, rgba(34, 211, 238, 0.12), transparent 38%),
    rgba(2, 6, 23, 0.72);
  backdrop-filter: blur(8px);
}

.announcement-dialog {
  position: relative;
  width: min(100%, 610px);
  overflow: hidden;
  color: #dce7f4;
  background: #101a2b;
  border: 1px solid rgba(148, 163, 184, 0.24);
  border-radius: 18px;
  box-shadow: 0 30px 80px rgba(2, 6, 23, 0.5), 0 0 0 1px rgba(34, 211, 238, 0.06);
}

.announcement-accent {
  height: 3px;
  background: linear-gradient(90deg, #22d3ee, #38bdf8 48%, rgba(56, 189, 248, 0));
}

.announcement-header {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  gap: 0.9rem;
  align-items: start;
  padding: 1.35rem 1.4rem 1rem;
}

.announcement-icon {
  display: grid;
  width: 44px;
  height: 44px;
  place-items: center;
  color: #0f172a;
  background: #22d3ee;
  border-radius: 13px;
  box-shadow: 0 8px 24px rgba(34, 211, 238, 0.2);
}

.announcement-heading { min-width: 0; }
.announcement-kicker {
  display: block;
  margin-bottom: 0.25rem;
  color: #67e8f9;
  font-size: 0.68rem;
  font-weight: 800;
  letter-spacing: 0.13em;
  text-transform: uppercase;
}

.announcement-heading h2 {
  margin: 0;
  color: #f8fafc;
  font-size: clamp(1.18rem, 3vw, 1.45rem);
  font-weight: 750;
  line-height: 1.3;
  overflow-wrap: anywhere;
}

.announcement-close {
  display: grid;
  width: 34px;
  height: 34px;
  place-items: center;
  color: #94a3b8;
  background: transparent;
  border: 1px solid transparent;
  border-radius: 9px;
  transition: 150ms ease;
}
.announcement-close:hover:not(:disabled) {
  color: #f8fafc;
  background: rgba(148, 163, 184, 0.1);
  border-color: rgba(148, 163, 184, 0.16);
}

.announcement-content {
  max-height: min(46vh, 360px);
  margin: 0 1.4rem;
  padding: 1.2rem 1.25rem;
  overflow-y: auto;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  color: #cbd5e1;
  background: rgba(15, 23, 42, 0.68);
  border: 1px solid rgba(100, 116, 139, 0.22);
  border-radius: 13px;
  font-size: 0.95rem;
  line-height: 1.75;
}

.announcement-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  padding: 1.1rem 1.4rem 1.35rem;
}

.announcement-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.4rem;
  color: #64748b;
  font-size: 0.72rem;
}

.announcement-ack {
  flex: 0 0 auto;
  min-width: 104px;
  padding: 0.68rem 1rem;
  color: #082f49;
  background: #22d3ee;
  border: 0;
  border-radius: 10px;
  font-size: 0.82rem;
  font-weight: 800;
  box-shadow: 0 8px 22px rgba(34, 211, 238, 0.16);
  transition: transform 150ms ease, background 150ms ease;
}
.announcement-ack:hover:not(:disabled) { transform: translateY(-1px); background: #67e8f9; }
.announcement-ack:disabled, .announcement-close:disabled { opacity: 0.55; cursor: wait; }

@media (max-width: 560px) {
  .announcement-header { padding: 1.1rem 1rem 0.85rem; gap: 0.7rem; }
  .announcement-content { margin: 0 1rem; padding: 1rem; }
  .announcement-footer { align-items: stretch; flex-direction: column; padding: 1rem; }
  .announcement-ack { width: 100%; }
}

/* Theme tokens: light by default, with system and explicit app-theme hooks. */
.announcement-backdrop {
  --ann-overlay: rgba(15, 23, 42, 0.38);
  --ann-glow: rgba(8, 145, 178, 0.14);
  --ann-surface: #ffffff;
  --ann-surface-raised: #f8fafc;
  --ann-border: #dbe4ee;
  --ann-title: #0f172a;
  --ann-text: #334155;
  --ann-muted: #64748b;
  --ann-accent: #0891b2;
  --ann-accent-strong: #0e7490;
  --ann-accent-soft: #ecfeff;
  --ann-accent-border: #a5f3fc;
  --ann-close-hover: #f1f5f9;
  --ann-button: #0f172a;
  --ann-button-hover: #1e293b;
  --ann-button-text: #f8fafc;
  --ann-code-soft: #eef2f7;
  --ann-shadow: 0 30px 80px rgba(15, 23, 42, 0.22), 0 2px 10px rgba(15, 23, 42, 0.08);
  color-scheme: light;
  background:
    radial-gradient(circle at 50% 26%, var(--ann-glow), transparent 40%),
    var(--ann-overlay);
  animation: announcement-fade 180ms ease-out both;
}

@media (prefers-color-scheme: dark) {
  .announcement-backdrop {
    --ann-overlay: rgba(2, 6, 23, 0.76);
    --ann-glow: rgba(34, 211, 238, 0.13);
    --ann-surface: #101827;
    --ann-surface-raised: #0b1322;
    --ann-border: rgba(148, 163, 184, 0.24);
    --ann-title: #f8fafc;
    --ann-text: #cbd5e1;
    --ann-muted: #8190a5;
    --ann-accent: #67e8f9;
    --ann-accent-strong: #67e8f9;
    --ann-accent-soft: rgba(34, 211, 238, 0.08);
    --ann-accent-border: rgba(34, 211, 238, 0.26);
    --ann-close-hover: rgba(148, 163, 184, 0.1);
    --ann-button: #22d3ee;
    --ann-button-hover: #67e8f9;
    --ann-button-text: #083344;
    --ann-code-soft: rgba(148, 163, 184, 0.12);
    --ann-shadow: 0 30px 80px rgba(2, 6, 23, 0.52), 0 0 0 1px rgba(34, 211, 238, 0.04);
    color-scheme: dark;
  }
}

:global(html.dark) .announcement-backdrop,
:global(html[data-theme='dark']) .announcement-backdrop,
:global(body.dark) .announcement-backdrop,
:global(body[data-theme='dark']) .announcement-backdrop {
  --ann-overlay: rgba(2, 6, 23, 0.76);
  --ann-glow: rgba(34, 211, 238, 0.13);
  --ann-surface: #101827;
  --ann-surface-raised: #0b1322;
  --ann-border: rgba(148, 163, 184, 0.24);
  --ann-title: #f8fafc;
  --ann-text: #cbd5e1;
  --ann-muted: #8190a5;
  --ann-accent: #67e8f9;
  --ann-accent-strong: #67e8f9;
  --ann-accent-soft: rgba(34, 211, 238, 0.08);
  --ann-accent-border: rgba(34, 211, 238, 0.26);
  --ann-close-hover: rgba(148, 163, 184, 0.1);
  --ann-button: #22d3ee;
  --ann-button-hover: #67e8f9;
  --ann-button-text: #083344;
  --ann-code-soft: rgba(148, 163, 184, 0.12);
  --ann-shadow: 0 30px 80px rgba(2, 6, 23, 0.52), 0 0 0 1px rgba(34, 211, 238, 0.04);
  color-scheme: dark;
}

:global(html.light) .announcement-backdrop,
:global(html[data-theme='light']) .announcement-backdrop,
:global(body.light) .announcement-backdrop,
:global(body[data-theme='light']) .announcement-backdrop {
  --ann-overlay: rgba(15, 23, 42, 0.38);
  --ann-glow: rgba(8, 145, 178, 0.14);
  --ann-surface: #ffffff;
  --ann-surface-raised: #f8fafc;
  --ann-border: #dbe4ee;
  --ann-title: #0f172a;
  --ann-text: #334155;
  --ann-muted: #64748b;
  --ann-accent: #0891b2;
  --ann-accent-strong: #0e7490;
  --ann-accent-soft: #ecfeff;
  --ann-accent-border: #a5f3fc;
  --ann-close-hover: #f1f5f9;
  --ann-button: #0f172a;
  --ann-button-hover: #1e293b;
  --ann-button-text: #f8fafc;
  --ann-code-soft: #eef2f7;
  --ann-shadow: 0 30px 80px rgba(15, 23, 42, 0.22), 0 2px 10px rgba(15, 23, 42, 0.08);
  color-scheme: light;
}

.announcement-dialog {
  color: var(--ann-text);
  background: var(--ann-surface);
  border-color: var(--ann-border);
  box-shadow: var(--ann-shadow);
  animation: announcement-rise 240ms cubic-bezier(.22, .8, .28, 1) both;
}
.announcement-accent { background: linear-gradient(90deg, var(--ann-accent), #38bdf8 48%, transparent); }
.announcement-icon { color: #083344; background: #22d3ee; }
.announcement-kicker { color: var(--ann-accent-strong); }
.announcement-heading h2 { color: var(--ann-title); }
.announcement-close { color: var(--ann-muted); }
.announcement-close:hover:not(:disabled) { color: var(--ann-title); background: var(--ann-close-hover); border-color: var(--ann-border); }
.announcement-content { color: var(--ann-text); background: var(--ann-surface-raised); border-color: var(--ann-border); white-space: normal; scrollbar-color: var(--ann-border) transparent; }
.announcement-meta { color: var(--ann-muted); }
.announcement-ack { color: var(--ann-button-text); background: var(--ann-button); }
.announcement-ack:hover:not(:disabled) { color: var(--ann-button-text); background: var(--ann-button-hover); }

.announcement-content :deep(.announcement-markdown) { color: var(--ann-text); font-size: inherit; line-height: 1.72; }
.announcement-content :deep(.announcement-markdown > :first-child) { margin-top: 0; }
.announcement-content :deep(.announcement-markdown > :last-child) { margin-bottom: 0; }
.announcement-content :deep(.announcement-markdown h1) { margin: 1.15rem 0 .7rem; padding-bottom: .45rem; color: var(--ann-title); border-bottom: 1px solid var(--ann-border); font-size: 1.3rem; font-weight: 760; line-height: 1.3; }
.announcement-content :deep(.announcement-markdown h2) { margin: 1.05rem 0 .6rem; color: var(--ann-title); font-size: 1.12rem; font-weight: 750; line-height: 1.35; }
.announcement-content :deep(.announcement-markdown h3) { margin: .9rem 0 .5rem; color: var(--ann-title); font-size: 1rem; font-weight: 750; }
.announcement-content :deep(.announcement-markdown h4),
.announcement-content :deep(.announcement-markdown h5),
.announcement-content :deep(.announcement-markdown h6) { margin: .8rem 0 .45rem; color: var(--ann-title); font-size: .94rem; font-weight: 750; line-height: 1.4; }
.announcement-content :deep(.announcement-markdown p) { margin: .65rem 0; color: var(--ann-text); }
.announcement-content :deep(.announcement-markdown strong) { color: var(--ann-title); font-weight: 760; }
.announcement-content :deep(.announcement-markdown em) { color: var(--ann-text); }
.announcement-content :deep(.announcement-markdown ul),
.announcement-content :deep(.announcement-markdown ol) { margin: .7rem 0; padding-left: 1.4rem; }
.announcement-content :deep(.announcement-markdown ul) { list-style-type: disc; }
.announcement-content :deep(.announcement-markdown ol) { list-style-type: decimal; }
.announcement-content :deep(.announcement-markdown ul ul) { list-style-type: circle; }
.announcement-content :deep(.announcement-markdown ul ul ul) { list-style-type: square; }
.announcement-content :deep(.announcement-markdown li) { margin: .28rem 0; color: var(--ann-text); }
.announcement-content :deep(.announcement-markdown li::marker) { color: var(--ann-accent-strong); }
.announcement-content :deep(.announcement-markdown li > p) { margin: .25rem 0; }
.announcement-content :deep(.announcement-markdown li > ul),
.announcement-content :deep(.announcement-markdown li > ol) { margin: .3rem 0; }
.announcement-content :deep(.announcement-markdown blockquote) { margin: .85rem 0; padding: .58rem .78rem; color: var(--ann-text); background: var(--ann-accent-soft); border-left: 3px solid var(--ann-accent); border-radius: 0 .5rem .5rem 0; }
.announcement-content :deep(.announcement-markdown blockquote p) { margin: 0; }
.announcement-content :deep(.announcement-markdown a) { color: var(--ann-accent-strong); text-decoration: underline; text-decoration-color: var(--ann-accent-border); text-underline-offset: 3px; }
.announcement-content :deep(.announcement-markdown code:not(pre code)) { padding: .12rem .34rem; color: var(--ann-title); background: var(--ann-code-soft); border: 1px solid var(--ann-border); border-radius: .34rem; font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; font-size: .88em; }
.announcement-content :deep(.announcement-markdown pre) { margin: .85rem 0; border: 1px solid var(--ann-border); border-radius: .58rem; box-shadow: none; }
.announcement-content :deep(.announcement-markdown .table-wrapper) { margin: .85rem 0; overflow-x: auto; border: 1px solid var(--ann-border); border-radius: .58rem; }
.announcement-content :deep(.announcement-markdown table) { width: 100%; border-collapse: collapse; background: transparent; }
.announcement-content :deep(.announcement-markdown th),
.announcement-content :deep(.announcement-markdown td) { padding: .52rem .62rem; color: var(--ann-text); border-bottom: 1px solid var(--ann-border); font-size: .82rem; text-align: left; }
.announcement-content :deep(.announcement-markdown th) { color: var(--ann-title); background: var(--ann-code-soft); font-weight: 750; }
.announcement-content :deep(.announcement-markdown tr:last-child td) { border-bottom: 0; }
.announcement-content :deep(.announcement-markdown hr) { margin: 1rem 0; border: 0; border-top: 1px solid var(--ann-border); }
.announcement-content :deep(.announcement-markdown img) { display: block; max-width: 100%; height: auto; margin: .85rem 0; border: 1px solid var(--ann-border); border-radius: .58rem; }

@keyframes announcement-fade { from { opacity: 0; } to { opacity: 1; } }
@keyframes announcement-rise { from { opacity: 0; transform: translateY(12px) scale(.985); } to { opacity: 1; transform: translateY(0) scale(1); } }

@media (prefers-reduced-motion: reduce) {
  .announcement-backdrop, .announcement-dialog { animation: none; }
  .announcement-close, .announcement-ack { transition: none; }
}
</style>

<script setup lang="ts">
import { computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useAppStore } from '@/stores/app'
import { useConversationShare } from '@/composables/useConversationShare'

const props = defineProps<{
  visible: boolean
  sessionId: string | null
  messageCount: number
}>()

const emit = defineEmits<{ (e: 'close'): void }>()

const { t } = useI18n()
const appStore = useAppStore()
const share = useConversationShare()

// Re-fetch the share status whenever the modal opens for a session.
watch(
  () => [props.visible, props.sessionId] as const,
  ([visible, sessionId]) => {
    if (visible && sessionId) {
      void share.load(sessionId)
    }
  },
  { immediate: true },
)

const sharedAtLabel = computed(() => {
  const raw = share.sharedAt.value
  if (!raw) return ''
  const date = new Date(raw)
  if (Number.isNaN(date.getTime())) return String(raw)
  return date.toLocaleString()
})

const onGenerate = async () => {
  if (!props.sessionId) return
  const wasShared = share.isShared.value
  const ok = await share.generate(props.sessionId)
  if (ok) {
    appStore.showNotification({
      title: wasShared ? t('aiChat.share.updated') : t('aiChat.share.created'),
      type: 'success',
    })
  } else {
    appStore.showNotification({ title: t('aiChat.share.generateFailed'), type: 'error' })
  }
}

const onCopy = async () => {
  const ok = await share.copy()
  appStore.showNotification({
    title: ok ? t('aiChat.share.copied') : t('aiChat.share.copyFailed'),
    type: ok ? 'success' : 'error',
  })
}

const onPreview = () => {
  const url = share.shareUrl.value
  if (url && typeof window !== 'undefined') {
    window.open(url, '_blank', 'noopener')
  }
}

const onRevoke = async () => {
  if (!props.sessionId) return
  const ok = await share.revoke(props.sessionId)
  appStore.showNotification({
    title: ok ? t('aiChat.share.revoked') : t('aiChat.share.revokeFailed'),
    type: ok ? 'success' : 'error',
  })
}

const close = () => emit('close')
</script>

<template>
  <div v-if="visible" class="rw-share-backdrop" @click.self="close">
    <div class="rw-share-modal">
      <div class="rw-share-head">
        <div>
          <h3 class="rw-share-title">{{ t('aiChat.share.title') }}</h3>
          <p class="rw-share-sub">{{ t('aiChat.share.subtitle') }}</p>
        </div>
        <button class="rw-share-close" @click="close" :aria-label="t('common.close')">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M6 6l12 12M18 6 6 18"/></svg>
        </button>
      </div>

      <div class="rw-share-body">
        <!-- Loading status -->
        <div v-if="share.loading.value" class="rw-share-loading">{{ t('aiChat.share.loading') }}</div>

        <!-- Unshared state -->
        <template v-else-if="!share.isShared.value">
          <p class="rw-share-blurb">{{ t('aiChat.share.unsharedHint') }}</p>
          <button
            type="button"
            class="rw-share-btn-primary rw-share-generate"
            :disabled="share.working.value || !sessionId"
            @click="onGenerate"
          >
            {{ share.working.value ? t('aiChat.share.generating') : t('aiChat.share.generate') }}
          </button>
        </template>

        <!-- Shared state -->
        <template v-else>
          <label class="rw-share-field">
            <span class="rw-share-label">{{ t('aiChat.share.linkLabel') }}</span>
            <div class="rw-share-link-row">
              <input class="rw-share-input" type="text" readonly :value="share.shareUrl.value" @focus="(e) => (e.target as HTMLInputElement).select()" />
              <button type="button" class="rw-share-btn-primary" @click="onCopy">{{ t('aiChat.share.copy') }}</button>
            </div>
          </label>

          <p v-if="sharedAtLabel" class="rw-share-snapshot">
            {{ t('aiChat.share.snapshotHint', { time: sharedAtLabel }) }}
          </p>
          <p class="rw-share-warning">{{ t('aiChat.share.publicWarning') }}</p>

          <div class="rw-share-actions">
            <button type="button" class="rw-share-btn-ghost" @click="onPreview">{{ t('aiChat.share.openPreview') }}</button>
            <button type="button" class="rw-share-btn-ghost" :disabled="share.working.value" @click="onGenerate">
              {{ share.working.value ? t('aiChat.share.updating') : t('aiChat.share.update') }}
            </button>
            <button type="button" class="rw-share-btn-danger" :disabled="share.working.value" @click="onRevoke">
              {{ t('aiChat.share.revoke') }}
            </button>
          </div>
        </template>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* Tokens (--rw-*) inherit from the ancestor .raven-workbench through the CSS
   custom-property cascade, so this modal matches the workbench theme. */
.rw-share-backdrop {
  position: fixed; inset: 0;
  background: rgba(0, 0, 0, .4);
  backdrop-filter: blur(4px);
  display: flex; align-items: center; justify-content: center;
  padding: 16px; z-index: 100;
}
.rw-share-modal {
  width: 100%; max-width: 440px;
  background: var(--rw-canvas, #fff);
  border: 1px solid var(--rw-hairline-strong, #dcdee0);
  border-radius: 14px;
  padding: 22px;
  box-shadow: 0 24px 64px rgba(0, 0, 0, .18);
  color: var(--rw-ink, #171717);
  font-family: var(--rw-sans, system-ui, sans-serif);
}
.rw-share-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.rw-share-title { font-size: 16px; font-weight: 600; color: var(--rw-ink, #171717); margin: 0; }
.rw-share-sub { font-size: 12px; color: var(--rw-muted, #999); margin: 4px 0 0; }
.rw-share-close { width: 28px; height: 28px; border-radius: 6px; display: grid; place-items: center; color: var(--rw-body, #60646c); border: none; background: none; cursor: pointer; }
.rw-share-close:hover { background: var(--rw-surface-strong, #f0f0f3); color: var(--rw-ink, #171717); }
.rw-share-body { margin-top: 16px; display: flex; flex-direction: column; gap: 12px; }
.rw-share-loading { font-size: 13px; color: var(--rw-muted, #999); padding: 8px 0; }
.rw-share-blurb { font-size: 13px; color: var(--rw-body, #60646c); margin: 0; line-height: 1.6; }
.rw-share-field { display: flex; flex-direction: column; gap: 6px; }
.rw-share-label { font-size: 12px; color: var(--rw-body, #60646c); font-weight: 500; }
.rw-share-link-row { display: flex; gap: 8px; }
.rw-share-input {
  flex: 1; height: 38px;
  border: 1px solid var(--rw-hairline-strong, #dcdee0); border-radius: 8px;
  padding: 0 12px; font-size: 13px; outline: none;
  background: var(--rw-surface-strong, #f0f0f3); color: var(--rw-ink, #171717);
  font-family: var(--rw-mono, monospace);
}
.rw-share-snapshot { font-size: 12px; color: var(--rw-muted, #999); margin: 0; line-height: 1.5; }
.rw-share-warning { font-size: 12px; color: var(--rw-danger, #c0382b); margin: 0; line-height: 1.5; }
.rw-share-actions { display: flex; gap: 10px; padding-top: 4px; flex-wrap: wrap; }
.rw-share-btn-primary {
  height: 36px; padding: 0 16px;
  background: var(--rw-primary, #171717); color: var(--rw-on-primary, #fff);
  border-radius: 8px; font-size: 13.5px; font-weight: 500;
  border: none; cursor: pointer; white-space: nowrap;
  transition: background .15s;
}
.rw-share-btn-primary:hover:not(:disabled) { background: var(--rw-primary-hover, #2e2e2e); }
.rw-share-btn-primary:disabled { opacity: .6; cursor: default; }
.rw-share-generate { width: 100%; }
.rw-share-btn-ghost {
  height: 36px; padding: 0 14px;
  background: var(--rw-canvas, #fff); color: var(--rw-ink, #171717);
  border: 1px solid var(--rw-hairline-strong, #dcdee0);
  border-radius: 8px; font-size: 13.5px; font-weight: 500;
  cursor: pointer;
}
.rw-share-btn-ghost:hover:not(:disabled) { background: var(--rw-surface-strong, #f0f0f3); }
.rw-share-btn-ghost:disabled { opacity: .6; cursor: default; }
.rw-share-btn-danger {
  height: 36px; padding: 0 14px;
  background: var(--rw-canvas, #fff); color: var(--rw-danger, #c0382b);
  border: 1px solid var(--rw-danger, #c0382b);
  border-radius: 8px; font-size: 13.5px; font-weight: 500;
  cursor: pointer; margin-left: auto;
}
.rw-share-btn-danger:hover:not(:disabled) { background: rgba(192, 56, 43, .08); }
.rw-share-btn-danger:disabled { opacity: .6; cursor: default; }
</style>

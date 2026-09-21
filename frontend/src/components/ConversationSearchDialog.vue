<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ArrowUpLeft, MessageCircle, Plus, Search, X } from 'lucide-vue-next'
import { useConversationSearch } from '@/composables/useConversationSearch'
import { highlightSearchText, searchDateGroup } from '@/utils/conversationSearch'
import type { ChatSessionSearchResult } from '@/types'

const emit = defineEmits<{
  close: []
  select: [session: ChatSessionSearchResult]
  newChat: []
}>()
const { t } = useI18n()
const { query, composing, items, loading, error, hasMore, retry, loadMore } = useConversationSearch()
const dialog = ref<HTMLDialogElement | null>(null)
const input = ref<HTMLInputElement | null>(null)
const active = ref(0)
const isRecent = computed(() => !query.value.trim())
const optionCount = computed(() => items.value.length + (isRecent.value ? 1 : 0))
const resultIndex = (index: number) => index + (isRecent.value ? 1 : 0)
const optionId = (index: number) => `conversation-search-option-${index}`
const activeId = computed(() => optionCount.value ? optionId(active.value) : undefined)
const rows = computed(() => items.value.map((item, index) => ({
  item,
  index: resultIndex(index),
  group: index === 0 || searchDateGroup(item.last_message_at) !== searchDateGroup(items.value[index - 1].last_message_at)
    ? t(`workbench.sessionGroups.${searchDateGroup(item.last_message_at)}`) : '',
})))
watch(query, () => { active.value = 0 })
watch(optionCount, count => { active.value = Math.max(0, Math.min(active.value, count - 1)) })

function selectActive() {
  if (isRecent.value && active.value === 0) emit('newChat')
  else {
    const item = items.value[active.value - (isRecent.value ? 1 : 0)]
    if (item) emit('select', item)
  }
}
async function handleInputKey(event: KeyboardEvent) {
  if (event.isComposing || composing.value || event.keyCode === 229) return
  if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
    event.preventDefault()
    if (!optionCount.value) return
    active.value = (active.value + (event.key === 'ArrowDown' ? 1 : -1) + optionCount.value) % optionCount.value
    await nextTick()
    document.getElementById(optionId(active.value))?.scrollIntoView({ block: 'nearest' })
  } else if (event.key === 'Enter') {
    event.preventDefault()
    selectActive()
  }
}
async function loadNextPage() {
  await loadMore()
  await nextTick()
  // 最后一页会移除分页按钮，把键盘焦点交回输入框。
  if (!hasMore.value) input.value?.focus()
}
let previousOverflow = ''
let returnFocus: HTMLElement | null = null
onMounted(() => {
  returnFocus = document.activeElement as HTMLElement | null
  previousOverflow = document.body.style.overflow
  document.body.style.overflow = 'hidden'
  dialog.value?.showModal()
  input.value?.focus()
})
onBeforeUnmount(() => {
  dialog.value?.close()
  document.body.style.overflow = previousOverflow
  returnFocus?.focus()
})
let backdropPointerDown = false
function onBackdropClick(event: MouseEvent) {
  if (backdropPointerDown && event.target === dialog.value) emit('close')
  backdropPointerDown = false
}
</script>

<template>
  <dialog
    ref="dialog" class="cs-dialog" :aria-label="t('workbench.searchConversations')"
    @cancel.prevent="!composing && emit('close')"
    @pointerdown="backdropPointerDown = $event.target === dialog"
    @click="onBackdropClick" @keydown.esc.stop
  >
    <div class="cs-panel">
      <div class="cs-search-bar">
        <Search :size="20" :stroke-width="1.6" aria-hidden="true" />
        <input
          ref="input" v-model="query" class="cs-input" type="text" maxlength="200"
          role="combobox" aria-autocomplete="list" aria-expanded="true"
          aria-controls="conversation-search-results" :aria-activedescendant="activeId"
          :aria-label="t('workbench.searchConversations')" :placeholder="t('workbench.search.placeholder')"
          autocomplete="off" spellcheck="false" autofocus
          @keydown="handleInputKey" @compositionstart="composing = true" @compositionend="composing = false"
        />
        <button v-if="query" class="cs-icon" :aria-label="t('workbench.search.clear')" @click="query = ''; input?.focus()">
          <X :size="16" aria-hidden="true" />
        </button>
        <button class="cs-close" :aria-label="t('common.close')" @click="emit('close')"><kbd>Esc</kbd></button>
      </div>
      <div class="cs-scroll">
        <div id="conversation-search-results" role="listbox" :aria-label="t('workbench.searchConversations')" :aria-busy="loading">
          <div
            v-if="isRecent" :id="optionId(0)" role="option" :aria-selected="active === 0"
            class="cs-result cs-new" :class="{ 'is-active': active === 0 }"
            @mousemove="active = 0" @click="emit('newChat')"
          >
            <Plus :size="19" :stroke-width="1.6" aria-hidden="true" /><span>{{ t('workbench.newChat') }}</span>
          </div>
          <template v-for="row in rows" :key="row.item.id">
            <div v-if="row.group" class="cs-group" role="presentation">{{ row.group }}</div>
            <div
              :id="optionId(row.index)" class="cs-result" :class="{ 'is-active': active === row.index }"
              role="option" :aria-selected="active === row.index"
              @mousemove="active = row.index" @click="emit('select', row.item)"
            >
              <MessageCircle class="cs-chat-icon" :size="19" :stroke-width="1.5" aria-hidden="true" />
              <div class="cs-result-copy">
                <div class="cs-title"><template v-for="(part, i) in highlightSearchText(row.item.title || t('workbench.untitledSession'), query)" :key="i"><mark v-if="part.match">{{ part.text }}</mark><template v-else>{{ part.text }}</template></template></div>
                <div v-if="!isRecent && row.item.snippet" class="cs-snippet"><template v-for="(part, i) in highlightSearchText(row.item.snippet, query)" :key="i"><mark v-if="part.match">{{ part.text }}</mark><template v-else>{{ part.text }}</template></template></div>
              </div>
              <ArrowUpLeft class="cs-open-icon" :size="17" aria-hidden="true" />
            </div>
          </template>
        </div>
        <div v-if="loading" class="cs-status" role="status"><span class="cs-spinner" />{{ t('workbench.search.loading') }}</div>
        <div v-else-if="error" class="cs-state" role="alert">
          <p>{{ t('workbench.search.error') }}</p><button class="cs-action" @click="retry">{{ t('workbench.search.retry') }}</button>
        </div>
        <div v-else-if="!items.length" class="cs-state" role="status">
          <Search :size="28" :stroke-width="1.3" aria-hidden="true" />
          <p>{{ t(isRecent ? 'workbench.search.emptyHistory' : 'workbench.search.noResults') }}</p>
          <span>{{ t(isRecent ? 'workbench.search.historyHint' : 'workbench.search.tryAnother') }}</span>
        </div>
        <button v-if="hasMore && !error" class="cs-more" :disabled="loading" @click="loadNextPage">{{ t('workbench.search.loadMore') }}</button>
      </div>
      <div class="cs-footer"><span><kbd>↑</kbd><kbd>↓</kbd> {{ t('workbench.search.navigate') }}</span><span><kbd>↵</kbd> {{ t('workbench.search.open') }}</span></div>
    </div>
  </dialog>
</template>

<style scoped>
.cs-dialog { margin: auto; inset: 0; padding: 0; border: 1px solid var(--rw-hairline-strong); border-radius: 18px; width: min(640px, calc(100vw - 32px)); max-width: none; max-height: calc(100dvh - 48px); background: var(--rw-canvas); color: var(--rw-ink); box-shadow: 0 24px 80px #0003; overflow: hidden; font-family: var(--rw-sans); }
.cs-dialog::backdrop { background: rgb(0 0 0 / 35%); }
.cs-panel { display: flex; flex-direction: column; max-height: calc(100dvh - 50px); }
.cs-search-bar { flex-shrink: 0; display: flex; align-items: center; gap: 12px; padding: 18px 20px; border-bottom: 1px solid var(--rw-hairline); color: var(--rw-muted); }
.cs-input { flex: 1; min-width: 0; border: 0; outline: 0; background: transparent; color: var(--rw-ink); font: inherit; font-size: 16px; }
.cs-input::placeholder { color: var(--rw-muted); }
.cs-icon, .cs-close { display: grid; place-items: center; padding: 5px; border-radius: 6px; color: var(--rw-muted); background: transparent; border: 0; cursor: pointer; }
.cs-icon:hover, .cs-close:hover { background: var(--rw-surface-strong); color: var(--rw-ink); }
kbd { font: 11px var(--rw-mono, monospace); border: 1px solid var(--rw-hairline-strong); border-radius: 4px; padding: 2px 4px; }
.cs-scroll { min-height: 0; height: 410px; overflow-y: auto; overscroll-behavior: contain; padding: 8px; scrollbar-width: thin; }
.cs-result { display: flex; align-items: center; gap: 14px; padding: 12px; margin: 2px 0; border-radius: 10px; cursor: pointer; }
.cs-result.is-active { background: var(--rw-surface-strong); }
.cs-new { min-height: 46px; font-size: 14px; }
.cs-group { font-size: 12px; font-weight: 500; color: var(--rw-muted); padding: 16px 12px 6px; }
.cs-result-copy { min-width: 0; flex: 1; }
.cs-title { font-size: 14px; line-height: 1.55; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.cs-snippet { margin-top: 4px; color: var(--rw-muted); font-size: 12px; line-height: 1.6; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; overflow-wrap: anywhere; }
.cs-chat-icon { flex-shrink: 0; color: var(--rw-body); }
.cs-open-icon { flex-shrink: 0; opacity: 0; color: var(--rw-muted); }
.is-active .cs-open-icon { opacity: 1; }
mark { background: transparent; color: var(--rw-ink); font-weight: 650; text-decoration: underline; text-decoration-color: var(--rw-muted); text-underline-offset: 3px; }
.cs-status { padding: 32px 16px; display: flex; align-items: center; justify-content: center; gap: 10px; font-size: 13px; color: var(--rw-muted); }
.cs-state { padding: 50px 20px; display: flex; align-items: center; flex-direction: column; text-align: center; color: var(--rw-muted); }
.cs-state p { margin: 14px 0 6px; font-size: 14px; color: var(--rw-ink); }
.cs-state span { font-size: 12px; }
.cs-action, .cs-more { border: 1px solid var(--rw-hairline-strong); border-radius: 8px; padding: 8px 14px; background: transparent; color: var(--rw-ink); font-size: 13px; cursor: pointer; }
.cs-more { display: block; margin: 16px auto; }
.cs-more:disabled { opacity: .5; cursor: wait; }
.cs-footer { flex-shrink: 0; border-top: 1px solid var(--rw-hairline); padding: 12px 20px; display: flex; gap: 20px; font-size: 11px; color: var(--rw-muted); }
.cs-footer span { display: flex; align-items: center; gap: 4px; }
.cs-spinner { width: 14px; height: 14px; border: 1.5px solid var(--rw-hairline-strong); border-top-color: var(--rw-muted); border-radius: 50%; animation: cs-spin .7s linear infinite; }
button:focus-visible { outline: 2px solid var(--rw-muted); outline-offset: 2px; }
@keyframes cs-spin { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) { .cs-spinner { animation: none; } }
@media (max-width: 600px) { .cs-dialog { width: calc(100vw - 20px); border-radius: 14px; } .cs-search-bar { padding: 16px; gap: 8px; } .cs-scroll { height: 55dvh; min-height: 0; } }
</style>

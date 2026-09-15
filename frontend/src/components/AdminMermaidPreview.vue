<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'
import { ElDialog } from 'element-plus'
import { useI18n } from 'vue-i18n'
import { loadMermaid } from '@/utils/mermaidLoader'

const props = defineProps<{ source: string | null }>()
const emit = defineEmits<{ close: [] }>()
const { t } = useI18n()
const host = ref<HTMLElement | null>(null)
const scale = ref(1)
const error = ref(false)
let revision = 0
watch(() => props.source, () => { revision++; scale.value = 1; error.value = false })
async function render() {
  const current = revision
  const source = props.source
  if (!source) return
  await nextTick()
  try {
    const mermaid = await loadMermaid()
    const { svg } = await mermaid.render(`admin-mermaid-zoom-${Date.now()}-${current}`, source)
    if (revision !== current || !host.value) return
    host.value.innerHTML = svg
    const diagram = host.value.querySelector('svg')
    if (diagram) {
      const box = diagram.viewBox.baseVal
      diagram.style.maxWidth = 'none'
      if (box.width && box.height) {
        diagram.setAttribute('width', String(box.width))
        diagram.setAttribute('height', String(box.height))
      }
    }
  } catch {
    if (revision === current) error.value = true
  }
}
</script>

<template>
  <ElDialog class="admin-mermaid-dialog" :model-value="source !== null" :title="t('admin.metrics.diagramPreview')"
    width="min(1200px, 95vw)" align-center append-to-body :z-index="2200"
    :close-on-click-modal="false" :close-on-press-escape="false" destroy-on-close
    @close="emit('close')" @opened="render">
    <div class="diagram-toolbar">
      <button :aria-label="t('aiChat.mermaid.zoomOut')" :disabled="scale <= 0.25" @click="scale = Math.max(0.25, scale - 0.25)">−</button>
      <span>{{ Math.round(scale * 100) }}%</span>
      <button :aria-label="t('aiChat.mermaid.zoomIn')" :disabled="scale >= 5" @click="scale = Math.min(5, scale + 0.25)">＋</button>
      <button @click="scale = 1">{{ t('aiChat.mermaid.reset') }}</button>
    </div>
    <div class="diagram-scroll">
      <p v-if="error" role="alert">{{ t('admin.metrics.diagramError') }}</p>
      <div v-else ref="host" class="diagram-host" :style="{ zoom: scale }"></div>
    </div>
  </ElDialog>
</template>

<style scoped>
:global(.el-dialog.admin-mermaid-dialog) { margin: auto !important; }
.diagram-toolbar { display: flex; gap: 1rem; align-items: center; margin-bottom: 1rem; }
.diagram-toolbar button { border: 1px solid var(--el-border-color); border-radius: 6px; padding: .25rem .7rem; }
.diagram-scroll { overflow: auto; max-height: 72vh; min-height: 180px; }
.diagram-host { width: max-content; min-width: 100%; padding: 1rem; }
</style>

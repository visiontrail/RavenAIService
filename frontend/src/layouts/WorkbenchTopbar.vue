<script setup lang="ts">
defineProps<{
  title: string
  meta?: string
}>()
</script>

<template>
  <header class="rw-topbar">
    <div class="rw-topbar-left">
      <span class="rw-crumb">{{ title }}</span>
      <span v-if="meta" class="rw-crumb-meta">· {{ meta }}</span>
    </div>
    <div class="rw-topbar-right">
      <slot name="actions" />
    </div>
  </header>
</template>

<style scoped>
.rw-topbar {
  height: 56px; flex-shrink: 0;
  border-bottom: 1px solid var(--rw-hairline, #f0f0f3);
  display: flex; align-items: center;
  padding: 0 28px; gap: 14px;
  background: var(--rw-canvas, #ffffff);
}
.rw-topbar-left { display: flex; align-items: center; gap: 10px; flex: 1; min-width: 0; }
.rw-crumb { font-size: 14.5px; font-weight: 600; color: var(--rw-ink, #171717); letter-spacing: -0.1px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.rw-crumb-meta { font-size: 12px; color: var(--rw-muted, #999); font-family: var(--rw-mono, monospace); flex-shrink: 0; }
.rw-topbar-right { display: flex; align-items: center; gap: 8px; }
@media (max-width: 900px) {
  .rw-topbar { padding: 0 16px; }
}
</style>

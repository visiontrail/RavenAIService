<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { Monitor, Moon, Sun } from 'lucide-vue-next'
import { useAppStore, type ThemePreference } from '@/stores/app'

const { t } = useI18n()
const appStore = useAppStore()

const options: { value: ThemePreference; icon: typeof Sun }[] = [
  { value: 'light', icon: Sun },
  { value: 'dark', icon: Moon },
  { value: 'system', icon: Monitor },
]
</script>

<template>
  <span class="theme-toggle" role="group" :aria-label="t('theme.switchTo')">
    <button
      v-for="opt in options"
      :key="opt.value"
      type="button"
      class="theme-toggle-opt"
      :class="{ active: appStore.theme === opt.value }"
      :title="t(`theme.${opt.value}`)"
      :aria-label="t(`theme.${opt.value}`)"
      :aria-pressed="appStore.theme === opt.value"
      @click="appStore.setTheme(opt.value)"
    >
      <component :is="opt.icon" :size="13" />
    </button>
  </span>
</template>

<style scoped>
.theme-toggle {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  padding: 2px;
  border-radius: 6px;
  background: var(--rw-surface-strong);
}

.theme-toggle-opt {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 20px;
  padding: 0;
  border: none;
  border-radius: 4px;
  background: transparent;
  color: var(--rw-muted);
  cursor: pointer;
  transition: background 0.15s ease, color 0.15s ease;
}

.theme-toggle-opt:hover {
  color: var(--rw-ink);
}

.theme-toggle-opt.active {
  background: var(--rw-canvas);
  color: var(--rw-ink);
  box-shadow: var(--rw-shadow-soft);
}
</style>

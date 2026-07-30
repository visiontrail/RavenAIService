<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import {
  Activity,
  BarChart3,
  ChevronRight,
  ListOrdered,
  Moon,
  RadioTower,
  Settings2,
  Sun,
} from 'lucide-vue-next'
import DashboardView from '@/views/DashboardView.vue'
import ProbesView from '@/views/ProbesView.vue'
import SettingsView from '@/views/SettingsView.vue'

type Page = 'dashboard' | 'probes' | 'settings'

const HASHES: Record<Page, string> = {
  dashboard: '#/',
  probes: '#/probes',
  settings: '#/settings',
}

function pageFromHash(): Page {
  if (window.location.hash === '#/settings') return 'settings'
  if (window.location.hash === '#/probes') return 'probes'
  return 'dashboard'
}

const page = ref<Page>(pageFromHash())
const dark = ref(document.documentElement.classList.contains('dark'))

const PAGE_META: Record<Page, { eyebrow: string; title: string }> = {
  dashboard: { eyebrow: 'OBSERVABILITY', title: '运行态势' },
  probes: { eyebrow: 'EVENT ARCHIVE', title: '探测记录' },
  settings: { eyebrow: 'CONTROL PLANE', title: '监控设置' },
}

const pageMeta = computed(() => PAGE_META[page.value])

function navigate(target: Page) {
  window.location.hash = HASHES[target]
  page.value = target
  window.scrollTo(0, 0)
}

function syncHash() {
  page.value = pageFromHash()
  window.scrollTo(0, 0)
}

function toggleTheme() {
  dark.value = !dark.value
  document.documentElement.classList.toggle('dark', dark.value)
  localStorage.setItem('sentinel-theme', dark.value ? 'dark' : 'light')
}

onMounted(() => {
  history.scrollRestoration = 'manual'
  window.scrollTo(0, 0)
  window.requestAnimationFrame(() => window.scrollTo(0, 0))
  window.addEventListener('hashchange', syncHash)
})
onBeforeUnmount(() => window.removeEventListener('hashchange', syncHash))
</script>

<template>
  <div class="app-shell">
    <aside class="sidebar">
      <button class="brand" aria-label="返回运行态势" @click="navigate('dashboard')">
        <span class="brand-mark">
          <i></i><i></i><i></i>
          <RadioTower :size="18" stroke-width="1.7" />
        </span>
        <span class="brand-copy">
          <strong>模型哨塔</strong>
          <small>MODEL SENTINEL</small>
        </span>
      </button>

      <nav class="primary-nav" aria-label="主导航">
        <span class="nav-caption">工作台</span>
        <button :class="{ active: page === 'dashboard' }" @click="navigate('dashboard')">
          <span class="nav-icon"><BarChart3 :size="18" stroke-width="1.8" /></span>
          <span><strong>运行态势</strong><small>可用率与容量信号</small></span>
          <ChevronRight :size="15" class="nav-chevron" />
        </button>
        <button :class="{ active: page === 'probes' }" @click="navigate('probes')">
          <span class="nav-icon"><ListOrdered :size="18" stroke-width="1.8" /></span>
          <span><strong>探测记录</strong><small>全量探测流水</small></span>
          <ChevronRight :size="15" class="nav-chevron" />
        </button>
        <button :class="{ active: page === 'settings' }" @click="navigate('settings')">
          <span class="nav-icon"><Settings2 :size="18" stroke-width="1.8" /></span>
          <span><strong>监控设置</strong><small>被测模型与工况</small></span>
          <ChevronRight :size="15" class="nav-chevron" />
        </button>
      </nav>

      <div class="sidebar-foot">
        <div class="always-on">
          <span class="always-on__orb"><Activity :size="15" /></span>
          <span><strong>7 × 24</strong><small>独立观测进程</small></span>
        </div>
        <p>数据保存在独立 SQLite 卷中，不写入 Raven 数据库。</p>
      </div>
    </aside>

    <div class="workspace">
      <header class="topbar">
        <div>
          <span>{{ pageMeta.eyebrow }}</span>
          <strong>{{ pageMeta.title }}</strong>
        </div>
        <button class="theme-button" :aria-label="dark ? '切换至浅色模式' : '切换至深色模式'" @click="toggleTheme">
          <Sun v-if="dark" :size="17" />
          <Moon v-else :size="17" />
        </button>
      </header>

      <main>
        <DashboardView
          v-if="page === 'dashboard'"
          @open-settings="navigate('settings')"
          @open-probes="navigate('probes')"
        />
        <ProbesView v-else-if="page === 'probes'" @back-dashboard="navigate('dashboard')" />
        <SettingsView v-else @back-dashboard="navigate('dashboard')" />
      </main>
    </div>

    <nav class="mobile-nav" aria-label="移动端导航">
      <button :class="{ active: page === 'dashboard' }" @click="navigate('dashboard')">
        <BarChart3 :size="19" /><span>态势</span>
      </button>
      <button :class="{ active: page === 'probes' }" @click="navigate('probes')">
        <ListOrdered :size="19" /><span>记录</span>
      </button>
      <button class="mobile-brand" @click="navigate('dashboard')">
        <RadioTower :size="20" />
      </button>
      <button :class="{ active: page === 'settings' }" @click="navigate('settings')">
        <Settings2 :size="19" /><span>设置</span>
      </button>
    </nav>
  </div>
</template>

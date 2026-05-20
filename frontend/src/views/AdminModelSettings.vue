<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { LogOut, Menu, PanelLeftClose } from 'lucide-vue-next'
import { adminApi, adminToken } from '@/api/admin'
import { useAppStore } from '@/stores/app'
import { adminNavItems, resolveAdminNavKey } from '@/utils/adminNav'
import type { LightModelSettings } from '@/types'

const appStore = useAppStore()
const route = useRoute()
const router = useRouter()

const navItems = adminNavItems

const isAuthenticated = ref(false)
const isLoggingIn = ref(false)
const loading = ref(false)
const saving = ref(false)
const settings = ref<LightModelSettings | null>(null)
const apiKeyTouched = ref(false)

const authForm = reactive({ username: '', password: '' })

const form = reactive({
  model_name: '',
  base_url: '',
  api_key: '',
  temperature: 0.2,
  clear_api_key: false,
})

const navVisible = computed(() => appStore.adminSidebarVisible)
const activeNavKey = computed(() => resolveAdminNavKey(route.path))

const parseErrorMessage = (err: any) => {
  if (err?.response?.data?.detail) return err.response.data.detail
  if (err?.response?.data?.message) return err.response.data.message
  if (err?.message) return err.message
  return '操作失败'
}

const persistToken = (token: string) => {
  adminToken.set(token)
}

const clearAuth = () => {
  adminToken.clear()
  isAuthenticated.value = false
  authForm.password = ''
}

const handleNavClick = (item: (typeof navItems)[number]) => {
  if (item.path && route.path !== item.path) router.push(item.path)
}

const toggleNavVisibility = () => {
  appStore.toggleAdminSidebar()
}

const applySettings = (data: LightModelSettings) => {
  settings.value = data
  form.model_name = data.llm_light_model_name || ''
  form.base_url = data.llm_light_base_url || ''
  form.temperature = data.llm_light_temperature ?? 0.2
  form.api_key = ''
  form.clear_api_key = false
  apiKeyTouched.value = false
}

const fetchSettings = async () => {
  if (!isAuthenticated.value) return
  loading.value = true
  try {
    const resp = await adminApi.fetchLightModelSettings()
    if (!resp?.success || !resp.data) throw new Error(resp?.message || '加载失败')
    applySettings(resp.data)
  } catch (err: any) {
    appStore.showNotification({ title: '加载失败', message: parseErrorMessage(err), type: 'error' })
  } finally {
    loading.value = false
  }
}

const handleSave = async () => {
  if (saving.value) return
  saving.value = true
  try {
    const payload: any = {
      model_name: form.model_name.trim(),
      base_url: form.base_url.trim(),
      temperature: Number(form.temperature) || 0,
      clear_api_key: form.clear_api_key,
    }
    if (apiKeyTouched.value && form.api_key.trim()) {
      payload.api_key = form.api_key.trim()
    }
    const resp = await adminApi.updateLightModelSettings(payload)
    if (!resp?.success || !resp.data) throw new Error(resp?.message || '保存失败')
    applySettings(resp.data)
    appStore.showNotification({ title: '已保存', message: '轻量级模型设置已生效', type: 'success' })
  } catch (err: any) {
    appStore.showNotification({ title: '保存失败', message: parseErrorMessage(err), type: 'error' })
  } finally {
    saving.value = false
  }
}

const handleClearApiKey = () => {
  form.clear_api_key = true
  form.api_key = ''
  apiKeyTouched.value = false
}

const handleLogin = async () => {
  if (!authForm.username || !authForm.password) {
    appStore.showNotification({ title: '请输入用户名和密码', type: 'warning' })
    return
  }
  isLoggingIn.value = true
  try {
    const resp = await adminApi.login(authForm.username.trim(), authForm.password)
    if (!resp?.success || !resp.data) throw new Error(resp?.message || '登录失败')
    persistToken(resp.data.token)
    isAuthenticated.value = true
    appStore.showNotification({ title: '登录成功', message: `欢迎，${resp.data.username}`, type: 'success' })
    await fetchSettings()
  } catch (err: any) {
    appStore.showNotification({ title: '登录失败', message: parseErrorMessage(err), type: 'error' })
  } finally {
    isLoggingIn.value = false
  }
}

const handleLogout = async () => {
  try {
    await adminApi.logout()
  } catch {
    // ignore
  } finally {
    clearAuth()
    settings.value = null
    appStore.showNotification({ title: '已退出登录', type: 'info' })
  }
}

const bootstrap = async () => {
  const token = adminToken.get()
  if (!token) return
  try {
    const resp = await adminApi.me()
    if (resp?.success) {
      isAuthenticated.value = true
      await fetchSettings()
    } else {
      clearAuth()
    }
  } catch {
    clearAuth()
  }
}

onMounted(() => {
  bootstrap()
})
</script>

<template>
  <div class="admin-console admin-users-page">
    <header class="admin-topbar">
      <div class="admin-topbar-inner">
        <div class="admin-topbar-left">
          <button
            class="admin-icon-btn"
            :disabled="!isAuthenticated"
            @click="toggleNavVisibility"
            :title="navVisible ? '隐藏侧边栏' : '显示侧边栏'"
            aria-label="切换侧边栏"
          >
            <PanelLeftClose v-if="navVisible" :size="18" />
            <Menu v-else :size="18" />
          </button>
          <div>
            <h1 class="admin-title">后台管理</h1>
            <p class="admin-subtitle">模型设置</p>
          </div>
        </div>
        <div class="admin-topbar-right">
          <span class="px-3 py-1 text-xs font-semibold rounded-full bg-slate-700 text-slate-100">
            {{ isAuthenticated ? '运行期配置' : '未登录' }}
          </span>
          <button v-if="isAuthenticated" class="admin-logout-btn" @click="handleLogout">
            <LogOut :size="14" />
            <span>退出</span>
          </button>
        </div>
      </div>
    </header>

    <button
      v-if="isAuthenticated && navVisible"
      class="admin-sidebar-backdrop"
      @click="toggleNavVisibility"
      aria-label="关闭侧边栏"
    ></button>

    <aside v-if="isAuthenticated" class="admin-sidebar" :class="{ 'is-hidden': !navVisible }">
      <div class="space-y-2">
        <button
          v-for="item in navItems"
          :key="item.key"
          class="admin-side-nav-item"
          :class="{ 'is-active': activeNavKey === item.key }"
          @click="handleNavClick(item)"
        >
          <div class="text-sm font-semibold">{{ item.label }}</div>
          <p v-if="item.description" class="text-xs mt-1 text-slate-400">{{ item.description }}</p>
        </button>
      </div>
    </aside>

    <main class="admin-main" :class="{ 'is-sidebar-hidden': !isAuthenticated || !navVisible }">
      <section v-if="!isAuthenticated" class="admin-login-wrap">
        <div class="bg-white rounded-2xl shadow-sm border border-slate-200 p-6">
          <div class="flex items-center justify-between mb-4">
            <div>
              <h2 class="text-lg font-semibold text-slate-900">登录后台</h2>
              <p class="text-sm text-slate-500">请输入管理员凭证继续</p>
            </div>
          </div>
          <form class="space-y-4 max-w-md" @submit.prevent="handleLogin">
            <label class="block">
              <span class="text-sm text-slate-700">用户名</span>
              <input
                v-model="authForm.username"
                type="text"
                class="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm focus:border-cyan-500 focus:ring-2 focus:ring-cyan-100 outline-none"
                placeholder="admin"
                autocomplete="username"
              />
            </label>
            <label class="block">
              <span class="text-sm text-slate-700">密码</span>
              <input
                v-model="authForm.password"
                type="password"
                class="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm focus:border-cyan-500 focus:ring-2 focus:ring-cyan-100 outline-none"
                placeholder="••••••••"
                autocomplete="current-password"
              />
            </label>
            <button
              type="submit"
              class="px-4 py-2 bg-cyan-600 text-white rounded-lg text-sm font-semibold hover:bg-cyan-700 transition disabled:opacity-50"
              :disabled="isLoggingIn"
            >
              {{ isLoggingIn ? '登录中…' : '登录' }}
            </button>
          </form>
        </div>
      </section>

      <section v-else class="space-y-4">
        <div class="bg-white rounded-2xl shadow-sm border border-slate-200 p-5">
          <div class="flex items-center justify-between mb-4">
            <div>
              <h2 class="text-lg font-semibold text-slate-900">轻量级模型</h2>
              <p class="text-sm text-slate-500">用于会话摘要、标题生成等低延迟、低消耗的任务。留空则回退到主模型。</p>
            </div>
            <button
              class="text-sm text-slate-600 hover:text-slate-900"
              :disabled="loading"
              @click="fetchSettings"
            >
              {{ loading ? '同步中…' : '刷新' }}
            </button>
          </div>

          <div v-if="loading" class="text-sm text-slate-500">正在加载...</div>
          <div v-else-if="settings" class="grid md:grid-cols-2 gap-4">
            <label class="text-sm text-slate-700">
              <span class="font-medium">模型名称</span>
              <input
                v-model="form.model_name"
                type="text"
                class="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm focus:border-cyan-500 focus:ring-2 focus:ring-cyan-100 outline-none"
                :placeholder="`留空则使用主模型 (${settings.fallback_model_name || '未配置'})`"
              />
              <p class="mt-1 text-xs text-slate-500">
                当前生效：{{ settings.llm_light_model_name || settings.fallback_model_name || '—' }}
              </p>
            </label>

            <label class="text-sm text-slate-700">
              <span class="font-medium">Base URL</span>
              <input
                v-model="form.base_url"
                type="text"
                class="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm focus:border-cyan-500 focus:ring-2 focus:ring-cyan-100 outline-none"
                :placeholder="`留空则沿用 (${settings.fallback_base_url || '未配置'})`"
              />
              <p class="mt-1 text-xs text-slate-500">
                兼容 OpenAI 接口的服务地址（例如 https://your-llm/v1）
              </p>
            </label>

            <label class="text-sm text-slate-700">
              <span class="font-medium">API Key</span>
              <input
                v-model="form.api_key"
                type="password"
                class="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm focus:border-cyan-500 focus:ring-2 focus:ring-cyan-100 outline-none"
                :placeholder="settings.llm_light_api_key_set ? '已配置（留空则保持不变）' : '留空则沿用主模型 Key'"
                @input="apiKeyTouched = true"
              />
              <div class="mt-1 flex items-center justify-between text-xs text-slate-500">
                <span>当前：{{ settings.llm_light_api_key_set ? '已设置' : '未设置（继承主模型）' }}</span>
                <button
                  v-if="settings.llm_light_api_key_set"
                  type="button"
                  class="text-amber-600 hover:text-amber-700"
                  @click="handleClearApiKey"
                >
                  清除已存储 Key
                </button>
              </div>
              <p v-if="form.clear_api_key" class="mt-1 text-xs text-rose-600">保存后将清除已存储的 API Key。</p>
            </label>

            <label class="text-sm text-slate-700">
              <span class="font-medium">Temperature</span>
              <input
                v-model.number="form.temperature"
                type="number"
                step="0.1"
                min="0"
                max="2"
                class="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm focus:border-cyan-500 focus:ring-2 focus:ring-cyan-100 outline-none"
              />
              <p class="mt-1 text-xs text-slate-500">摘要任务建议 0~0.3</p>
            </label>
          </div>

          <div class="mt-5 flex justify-end gap-2">
            <button
              class="px-4 py-2 bg-cyan-600 text-white rounded-lg text-sm font-semibold hover:bg-cyan-700 transition disabled:opacity-60"
              :disabled="saving || loading"
              @click="handleSave"
            >
              {{ saving ? '保存中…' : '保存' }}
            </button>
          </div>
        </div>

        <div class="bg-white rounded-2xl shadow-sm border border-slate-200 p-5 text-sm text-slate-600 space-y-2">
          <p>· 该配置存储于 <code>data/runtime_settings.json</code>，修改后立即生效，无需重启。</p>
          <p>· 模型名称留空时会自动回退到主模型；用于会话首条消息的<strong>立即摘要</strong>。</p>
          <p>· 未来其他轻量任务（标签、关键词、短摘要等）也会复用同一模型。</p>
        </div>
      </section>
    </main>
  </div>
</template>

<style scoped>
.admin-console {
  --admin-topbar-height: 72px;
  --admin-sidebar-width: 280px;
  min-height: 100vh;
  background: linear-gradient(180deg, #f1f5f9 0%, #e2e8f0 100%);
}

.admin-topbar {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  width: 100%;
  height: var(--admin-topbar-height);
  z-index: 70;
  background: rgba(15, 23, 42, 0.96);
  border-bottom: 1px solid rgba(148, 163, 184, 0.3);
  backdrop-filter: blur(10px);
}

.admin-topbar-inner {
  height: 100%;
  padding: 0 1rem;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
}

.admin-topbar-left {
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.admin-icon-btn {
  width: 2.25rem;
  height: 2.25rem;
  border: 1px solid rgba(148, 163, 184, 0.35);
  border-radius: 0.625rem;
  color: #f8fafc;
  background: rgba(51, 65, 85, 0.6);
}

.admin-icon-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.admin-title {
  color: #f8fafc;
  font-size: 0.95rem;
  font-weight: 700;
  line-height: 1.1;
}

.admin-subtitle {
  color: #94a3b8;
  font-size: 0.75rem;
}

.admin-topbar-right {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.admin-logout-btn {
  border: 1px solid rgba(148, 163, 184, 0.35);
  border-radius: 0.55rem;
  color: #e2e8f0;
  background: rgba(51, 65, 85, 0.45);
  font-size: 0.75rem;
  font-weight: 600;
  padding: 0.45rem 0.7rem;
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
}

.admin-sidebar {
  position: fixed;
  left: 0;
  top: 0;
  width: var(--admin-sidebar-width);
  height: 100vh;
  z-index: 60;
  background: #0f172a;
  border-right: 1px solid rgba(148, 163, 184, 0.25);
  padding: calc(var(--admin-topbar-height) + 1rem) 1rem 1rem;
  transition: transform 0.25s ease;
  overflow-y: auto;
}

.admin-sidebar.is-hidden {
  transform: translateX(calc(-1 * var(--admin-sidebar-width)));
}

.admin-side-nav-item {
  width: 100%;
  text-align: left;
  padding: 0.8rem;
  border-radius: 0.75rem;
  border: 1px solid rgba(100, 116, 139, 0.45);
  color: #cbd5e1;
  background: rgba(30, 41, 59, 0.45);
}

.admin-side-nav-item.is-active {
  color: #0f172a;
  background: #22d3ee;
  border-color: #22d3ee;
}

.admin-main {
  min-height: 100vh;
  padding: calc(var(--admin-topbar-height) + 1rem) 1rem 1rem calc(var(--admin-sidebar-width) + 1rem);
  transition: padding-left 0.25s ease;
}

.admin-main.is-sidebar-hidden {
  padding-left: 1rem;
}

.admin-login-wrap {
  max-width: 720px;
  margin: 1.25rem auto 0;
}

.admin-sidebar-backdrop {
  display: none;
}

@media (max-width: 768px) {
  .admin-console {
    --admin-sidebar-width: min(84vw, 320px);
  }
  .admin-main.is-sidebar-hidden {
    padding-left: 1rem;
  }
  .admin-sidebar-backdrop {
    display: block;
    position: fixed;
    inset: 0;
    z-index: 55;
    background: rgba(15, 23, 42, 0.45);
    border: 0;
  }
}
</style>

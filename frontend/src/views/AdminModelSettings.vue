<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { LogOut, Menu, PanelLeftClose, RotateCcw, Save } from 'lucide-vue-next'
import {
  adminApi,
  adminToken,
  type ModelSettingsData,
  type UpdateModelSettingsPayload,
} from '@/api/admin'
import ThemeToggle from '@/components/ThemeToggle.vue'
import { useAppStore } from '@/stores/app'
import { resolveAdminNavKey, type AdminNavItem } from '@/utils/adminNav'
import { useAdminScope } from '@/composables/useAdminScope'

const { t } = useI18n()
const appStore = useAppStore()
const route = useRoute()
const router = useRouter()

const { visibleNavItems } = useAdminScope()

const isAuthenticated = ref(false)
const isLoggingIn = ref(false)

const authForm = reactive({ username: '', password: '' })

// ── Model settings state ──────────────────────────────────────────────────
const loadingSettings = ref(false)
const savingSettings = ref(false)
const resettingSettings = ref(false)
const settingsData = ref<ModelSettingsData | null>(null)

const form = reactive({
  anthropic_provider: 'anthropic',
  anthropic_api_key: '',
  anthropic_base_url: '',
  anthropic_model: '',
  anthropic_small_fast_model: '',
  anthropic_max_tokens: 8192,
  ocr_enabled: true,
  ocr_api_key: '',
  ocr_base_url: '',
  ocr_model: '',
  ocr_provider: '',
})

// Secrets are never returned by the API; only whether one is currently set.
const anthropicKeySet = ref(false)
const ocrKeySet = ref(false)

const providerOptions = computed(() => settingsData.value?.provider_options ?? [])
const selectedProfile = computed(
  () =>
    settingsData.value?.provider_profiles.find(
      (p) => p.name === form.anthropic_provider
    ) ?? null
)
const isCustomProvider = computed(() => form.anthropic_provider === 'custom')

const sourceOf = (key: string) => settingsData.value?.fields?.[key]?.source ?? 'env'
const sourceLabel = (key: string) => {
  const src = sourceOf(key)
  if (src === 'override') return t('admin.modelSettings.sourceOverride')
  if (src === 'unset') return t('admin.modelSettings.sourceUnset')
  return t('admin.modelSettings.sourceEnv')
}

const populateForm = (data: ModelSettingsData) => {
  settingsData.value = data
  const f = data.fields || {}
  form.anthropic_provider = String(f.anthropic_provider?.value ?? 'anthropic')
  form.anthropic_base_url = String(f.anthropic_base_url?.value ?? '')
  form.anthropic_model = String(f.anthropic_model?.value ?? '')
  form.anthropic_small_fast_model = String(f.anthropic_small_fast_model?.value ?? '')
  form.anthropic_max_tokens = Number(f.anthropic_max_tokens?.value ?? 8192)
  form.ocr_enabled = Boolean(f.ocr_enabled?.value ?? true)
  form.ocr_base_url = String(f.ocr_base_url?.value ?? '')
  form.ocr_model = String(f.ocr_model?.value ?? '')
  form.ocr_provider = String(f.ocr_provider?.value ?? '')
  // Reset secret inputs — only their "is set" state is known.
  form.anthropic_api_key = ''
  form.ocr_api_key = ''
  anthropicKeySet.value = Boolean(f.anthropic_api_key?.is_set)
  ocrKeySet.value = Boolean(f.ocr_api_key?.is_set)
}

const fetchModelSettings = async () => {
  if (!isAuthenticated.value) return
  loadingSettings.value = true
  try {
    const resp = await adminApi.getModelSettings()
    if (!resp?.success || !resp.data) {
      throw new Error(resp?.message || t('admin.modelSettings.loadFail'))
    }
    populateForm(resp.data)
  } catch (err: any) {
    appStore.showNotification({
      title: t('admin.modelSettings.loadFail'),
      message: parseErrorMessage(err),
      type: 'error',
    })
  } finally {
    loadingSettings.value = false
  }
}

const handleSaveSettings = async () => {
  savingSettings.value = true
  try {
    const payload: UpdateModelSettingsPayload = {
      anthropic_provider: form.anthropic_provider,
      anthropic_base_url: form.anthropic_base_url.trim(),
      anthropic_model: form.anthropic_model.trim(),
      anthropic_small_fast_model: form.anthropic_small_fast_model.trim(),
      anthropic_max_tokens: Number(form.anthropic_max_tokens),
      ocr_enabled: form.ocr_enabled,
      ocr_base_url: form.ocr_base_url.trim(),
      ocr_model: form.ocr_model.trim(),
      ocr_provider: form.ocr_provider.trim(),
    }
    // Only send secrets when the admin typed a new value; blank keeps the old.
    if (form.anthropic_api_key.trim()) payload.anthropic_api_key = form.anthropic_api_key.trim()
    if (form.ocr_api_key.trim()) payload.ocr_api_key = form.ocr_api_key.trim()

    const resp = await adminApi.updateModelSettings(payload)
    if (!resp?.success || !resp.data) {
      throw new Error(resp?.message || t('admin.modelSettings.saveFail'))
    }
    populateForm(resp.data)
    appStore.showNotification({ title: t('admin.modelSettings.saved'), type: 'success' })
  } catch (err: any) {
    appStore.showNotification({
      title: t('admin.modelSettings.saveFail'),
      message: parseErrorMessage(err),
      type: 'error',
    })
  } finally {
    savingSettings.value = false
  }
}

const handleResetSettings = async () => {
  if (!window.confirm(t('admin.modelSettings.resetConfirm'))) return
  resettingSettings.value = true
  try {
    const resp = await adminApi.resetModelSettings()
    if (!resp?.success || !resp.data) {
      throw new Error(resp?.message || t('admin.modelSettings.resetFail'))
    }
    populateForm(resp.data)
    appStore.showNotification({ title: t('admin.modelSettings.resetDone'), type: 'success' })
  } catch (err: any) {
    appStore.showNotification({
      title: t('admin.modelSettings.resetFail'),
      message: parseErrorMessage(err),
      type: 'error',
    })
  } finally {
    resettingSettings.value = false
  }
}

const navVisible = computed(() => appStore.adminSidebarVisible)
const activeNavKey = computed(() => resolveAdminNavKey(route.path))

const parseErrorMessage = (err: any) => {
  if (err?.response?.data?.detail) return err.response.data.detail
  if (err?.response?.data?.message) return err.response.data.message
  if (err?.message) return err.message
  return t('admin.parseError')
}

const persistToken = (token: string) => {
  adminToken.set(token)
}

const clearAuth = () => {
  adminToken.clear()
  isAuthenticated.value = false
  authForm.password = ''
}

const handleNavClick = (item: AdminNavItem) => {
  if (item.path && route.path !== item.path) router.push(item.path)
}

const toggleNavVisibility = () => {
  appStore.toggleAdminSidebar()
}

const handleLogin = async () => {
  if (!authForm.username || !authForm.password) {
    appStore.showNotification({ title: t('admin.loginWarning'), type: 'warning' })
    return
  }
  isLoggingIn.value = true
  try {
    const resp = await adminApi.login(authForm.username.trim(), authForm.password)
    if (!resp?.success || !resp.data) throw new Error(resp?.message || t('admin.loginFailFallback'))
    persistToken(resp.data.token)
    isAuthenticated.value = true
    appStore.showNotification({ title: t('admin.loginSuccessTitle'), message: t('admin.loginSuccessMsg', { username: resp.data.username }), type: 'success' })
    fetchModelSettings()
  } catch (err: any) {
    appStore.showNotification({ title: t('admin.loginFailFallback'), message: parseErrorMessage(err), type: 'error' })
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
    appStore.showNotification({ title: t('admin.logoutSuccessTitle'), type: 'info' })
  }
}

const bootstrap = async () => {
  const token = adminToken.get()
  if (!token) return
  try {
    const resp = await adminApi.me()
    if (resp?.success) {
      isAuthenticated.value = true
      fetchModelSettings()
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
            :title="navVisible ? t('admin.toggleSidebarHide') : t('admin.toggleSidebarShow')"
            :aria-label="t('admin.toggleSidebarAriaLabel')"
          >
            <PanelLeftClose v-if="navVisible" :size="18" />
            <Menu v-else :size="18" />
          </button>
          <div>
            <h1 class="admin-title">{{ t('admin.title') }}</h1>
            <p class="admin-subtitle">{{ t('admin.modelSettings.subtitle') }}</p>
          </div>
        </div>
        <div class="admin-topbar-right">
          <ThemeToggle class="admin-theme-toggle" />
          <span class="px-3 py-1 text-xs font-semibold rounded-full bg-slate-700 text-slate-100">
            {{ isAuthenticated ? t('admin.modelSettings.badge') : t('admin.badgeNotLoggedIn') }}
          </span>
          <button v-if="isAuthenticated" class="admin-logout-btn" @click="handleLogout">
            <LogOut :size="14" />
            <span>{{ t('admin.logoutBtn') }}</span>
          </button>
        </div>
      </div>
    </header>

    <button
      v-if="isAuthenticated && navVisible"
      class="admin-sidebar-backdrop"
      @click="toggleNavVisibility"
      :aria-label="t('admin.closeSidebarAriaLabel')"
    ></button>

    <aside v-if="isAuthenticated" class="admin-sidebar" :class="{ 'is-hidden': !navVisible }">
      <div class="space-y-2">
        <button
          v-for="item in visibleNavItems"
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
              <h2 class="text-lg font-semibold text-slate-900">{{ t('admin.loginCardTitle') }}</h2>
              <p class="text-sm text-slate-500">{{ t('admin.loginCardDesc') }}</p>
            </div>
          </div>
          <form class="space-y-4 max-w-md" @submit.prevent="handleLogin">
            <label class="block">
              <span class="text-sm text-slate-700">{{ t('admin.usernameLabel') }}</span>
              <input
                v-model="authForm.username"
                type="text"
                class="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm focus:border-cyan-500 focus:ring-2 focus:ring-cyan-100 outline-none"
                placeholder="admin"
                autocomplete="username"
              />
            </label>
            <label class="block">
              <span class="text-sm text-slate-700">{{ t('admin.passwordLabel') }}</span>
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
              {{ isLoggingIn ? t('admin.loginBtnLoading') : t('admin.loginBtn') }}
            </button>
          </form>
        </div>
      </section>

      <section v-else class="space-y-4 admin-model-form">
        <div v-if="loadingSettings" class="bg-white rounded-2xl shadow-sm border border-slate-200 p-6 text-sm text-slate-500">
          {{ t('admin.modelSettings.loading') }}
        </div>

        <form v-else class="space-y-4" @submit.prevent="handleSaveSettings">
          <!-- Anthropic 主力模型 -->
          <div class="bg-white rounded-2xl shadow-sm border border-slate-200 p-5">
            <div class="mb-4">
              <h2 class="text-lg font-semibold text-slate-900">{{ t('admin.modelSettings.anthropicSectionTitle') }}</h2>
              <p class="text-sm text-slate-500">{{ t('admin.modelSettings.anthropicSectionDesc') }}</p>
            </div>

            <div class="grid gap-4 lg:grid-cols-2">
              <label class="block text-sm text-slate-700">
                <span class="flex items-center gap-2">
                  {{ t('admin.modelSettings.providerLabel') }}
                  <span class="ms-badge" :class="`ms-badge--${sourceOf('anthropic_provider')}`">{{ sourceLabel('anthropic_provider') }}</span>
                </span>
                <select
                  v-model="form.anthropic_provider"
                  class="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm focus:border-cyan-500 focus:ring-2 focus:ring-cyan-100 outline-none bg-white"
                >
                  <option v-for="opt in providerOptions" :key="opt" :value="opt">{{ opt }}</option>
                </select>
                <p v-if="selectedProfile" class="text-xs text-slate-500 mt-1">
                  {{ t('admin.modelSettings.capabilities') }}:
                  <span :class="selectedProfile.supports_image_input ? 'text-emerald-600' : 'text-slate-400'">
                    {{ selectedProfile.supports_image_input ? t('admin.modelSettings.capImageYes') : t('admin.modelSettings.capImageNo') }}
                  </span>
                  ·
                  <span :class="selectedProfile.supports_mcp_server_tools ? 'text-emerald-600' : 'text-slate-400'">
                    {{ selectedProfile.supports_mcp_server_tools ? t('admin.modelSettings.capMcpYes') : t('admin.modelSettings.capMcpNo') }}
                  </span>
                </p>
              </label>

              <label class="block text-sm text-slate-700">
                <span class="flex items-center gap-2">
                  {{ t('admin.modelSettings.apiKeyLabel') }}
                  <span class="ms-badge" :class="`ms-badge--${sourceOf('anthropic_api_key')}`">{{ sourceLabel('anthropic_api_key') }}</span>
                </span>
                <input
                  v-model="form.anthropic_api_key"
                  type="password"
                  autocomplete="off"
                  class="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm focus:border-cyan-500 focus:ring-2 focus:ring-cyan-100 outline-none"
                  :placeholder="anthropicKeySet ? t('admin.modelSettings.apiKeySetPlaceholder') : t('admin.modelSettings.apiKeyUnsetPlaceholder')"
                />
                <p class="text-xs text-slate-500 mt-1">{{ t('admin.modelSettings.apiKeyHint') }}</p>
              </label>

              <label class="block text-sm text-slate-700">
                <span class="flex items-center gap-2">
                  {{ t('admin.modelSettings.baseUrlLabel') }}
                  <span class="ms-badge" :class="`ms-badge--${sourceOf('anthropic_base_url')}`">{{ sourceLabel('anthropic_base_url') }}</span>
                </span>
                <input
                  v-model="form.anthropic_base_url"
                  type="text"
                  spellcheck="false"
                  class="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 font-mono text-sm focus:border-cyan-500 focus:ring-2 focus:ring-cyan-100 outline-none"
                  :placeholder="selectedProfile?.default_base_url || t('admin.modelSettings.customRequiredPlaceholder')"
                />
                <p class="text-xs text-slate-500 mt-1">
                  {{ isCustomProvider ? t('admin.modelSettings.baseUrlCustomHint') : t('admin.modelSettings.baseUrlHint') }}
                </p>
              </label>

              <label class="block text-sm text-slate-700">
                <span class="flex items-center gap-2">
                  {{ t('admin.modelSettings.modelLabel') }}
                  <span class="ms-badge" :class="`ms-badge--${sourceOf('anthropic_model')}`">{{ sourceLabel('anthropic_model') }}</span>
                </span>
                <input
                  v-model="form.anthropic_model"
                  type="text"
                  spellcheck="false"
                  class="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 font-mono text-sm focus:border-cyan-500 focus:ring-2 focus:ring-cyan-100 outline-none"
                  :placeholder="selectedProfile?.default_model || t('admin.modelSettings.customRequiredPlaceholder')"
                />
                <p class="text-xs text-slate-500 mt-1">
                  {{ isCustomProvider ? t('admin.modelSettings.modelCustomHint') : t('admin.modelSettings.modelHint') }}
                </p>
              </label>

              <label class="block text-sm text-slate-700">
                <span class="flex items-center gap-2">
                  {{ t('admin.modelSettings.smallFastModelLabel') }}
                  <span class="ms-badge" :class="`ms-badge--${sourceOf('anthropic_small_fast_model')}`">{{ sourceLabel('anthropic_small_fast_model') }}</span>
                </span>
                <input
                  v-model="form.anthropic_small_fast_model"
                  type="text"
                  spellcheck="false"
                  class="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 font-mono text-sm focus:border-cyan-500 focus:ring-2 focus:ring-cyan-100 outline-none"
                  :placeholder="selectedProfile?.default_small_fast_model || t('admin.modelSettings.customRequiredPlaceholder')"
                />
                <p class="text-xs text-slate-500 mt-1">{{ t('admin.modelSettings.smallFastModelHint') }}</p>
              </label>

              <label class="block text-sm text-slate-700">
                <span class="flex items-center gap-2">
                  {{ t('admin.modelSettings.maxTokensLabel') }}
                  <span class="ms-badge" :class="`ms-badge--${sourceOf('anthropic_max_tokens')}`">{{ sourceLabel('anthropic_max_tokens') }}</span>
                </span>
                <input
                  v-model.number="form.anthropic_max_tokens"
                  type="number"
                  min="1"
                  max="200000"
                  class="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm focus:border-cyan-500 focus:ring-2 focus:ring-cyan-100 outline-none"
                />
                <p class="text-xs text-slate-500 mt-1">{{ t('admin.modelSettings.maxTokensHint') }}</p>
              </label>
            </div>
          </div>

          <!-- OCR / 视觉模型 -->
          <div class="bg-white rounded-2xl shadow-sm border border-slate-200 p-5">
            <div class="mb-4">
              <h2 class="text-lg font-semibold text-slate-900">{{ t('admin.modelSettings.ocrSectionTitle') }}</h2>
              <p class="text-sm text-slate-500">{{ t('admin.modelSettings.ocrSectionDesc') }}</p>
            </div>

            <label class="flex items-center gap-2 text-sm text-slate-700 mb-4">
              <input v-model="form.ocr_enabled" type="checkbox" class="h-4 w-4 rounded border-slate-300 text-cyan-600 focus:ring-cyan-500" />
              <span>{{ t('admin.modelSettings.ocrEnabledLabel') }}</span>
              <span class="ms-badge" :class="`ms-badge--${sourceOf('ocr_enabled')}`">{{ sourceLabel('ocr_enabled') }}</span>
            </label>

            <div class="grid gap-4 lg:grid-cols-2" :class="{ 'opacity-50 pointer-events-none': !form.ocr_enabled }">
              <label class="block text-sm text-slate-700">
                <span class="flex items-center gap-2">
                  {{ t('admin.modelSettings.ocrApiKeyLabel') }}
                  <span class="ms-badge" :class="`ms-badge--${sourceOf('ocr_api_key')}`">{{ sourceLabel('ocr_api_key') }}</span>
                </span>
                <input
                  v-model="form.ocr_api_key"
                  type="password"
                  autocomplete="off"
                  class="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm focus:border-cyan-500 focus:ring-2 focus:ring-cyan-100 outline-none"
                  :placeholder="ocrKeySet ? t('admin.modelSettings.apiKeySetPlaceholder') : t('admin.modelSettings.apiKeyUnsetPlaceholder')"
                />
                <p class="text-xs text-slate-500 mt-1">{{ t('admin.modelSettings.ocrApiKeyHint') }}</p>
              </label>

              <label class="block text-sm text-slate-700">
                <span class="flex items-center gap-2">
                  {{ t('admin.modelSettings.ocrModelLabel') }}
                  <span class="ms-badge" :class="`ms-badge--${sourceOf('ocr_model')}`">{{ sourceLabel('ocr_model') }}</span>
                </span>
                <input
                  v-model="form.ocr_model"
                  type="text"
                  spellcheck="false"
                  class="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 font-mono text-sm focus:border-cyan-500 focus:ring-2 focus:ring-cyan-100 outline-none"
                  :placeholder="t('admin.modelSettings.ocrModelPlaceholder')"
                />
                <p class="text-xs text-slate-500 mt-1">{{ t('admin.modelSettings.ocrModelHint') }}</p>
              </label>

              <label class="block text-sm text-slate-700">
                <span class="flex items-center gap-2">
                  {{ t('admin.modelSettings.ocrBaseUrlLabel') }}
                  <span class="ms-badge" :class="`ms-badge--${sourceOf('ocr_base_url')}`">{{ sourceLabel('ocr_base_url') }}</span>
                </span>
                <input
                  v-model="form.ocr_base_url"
                  type="text"
                  spellcheck="false"
                  class="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 font-mono text-sm focus:border-cyan-500 focus:ring-2 focus:ring-cyan-100 outline-none"
                  :placeholder="t('admin.modelSettings.ocrBaseUrlPlaceholder')"
                />
                <p class="text-xs text-slate-500 mt-1">{{ t('admin.modelSettings.ocrBaseUrlHint') }}</p>
              </label>

              <label class="block text-sm text-slate-700">
                <span class="flex items-center gap-2">
                  {{ t('admin.modelSettings.ocrProviderLabel') }}
                  <span class="ms-badge" :class="`ms-badge--${sourceOf('ocr_provider')}`">{{ sourceLabel('ocr_provider') }}</span>
                </span>
                <input
                  v-model="form.ocr_provider"
                  type="text"
                  spellcheck="false"
                  class="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm focus:border-cyan-500 focus:ring-2 focus:ring-cyan-100 outline-none"
                  :placeholder="t('admin.modelSettings.ocrProviderPlaceholder')"
                />
                <p class="text-xs text-slate-500 mt-1">{{ t('admin.modelSettings.ocrProviderHint') }}</p>
              </label>
            </div>

            <p class="text-xs text-slate-500 mt-3">{{ t('admin.modelSettings.ocrComplianceNote') }}</p>
          </div>

          <!-- Notes + Actions -->
          <div class="bg-white rounded-2xl shadow-sm border border-slate-200 p-5">
            <div class="text-sm text-slate-500 space-y-1 mb-4">
              <p>{{ t('admin.modelSettings.effectiveNote') }}</p>
              <p>{{ t('admin.modelSettings.envFallbackNote') }}</p>
              <p>{{ t('admin.modelSettings.deepseekNote') }}</p>
            </div>
            <div class="flex flex-wrap items-center gap-3">
              <button
                type="submit"
                class="inline-flex items-center gap-2 px-4 py-2 bg-cyan-600 text-white rounded-lg text-sm font-semibold hover:bg-cyan-700 transition disabled:opacity-60"
                :disabled="savingSettings || resettingSettings"
              >
                <Save :size="15" />
                {{ savingSettings ? t('admin.modelSettings.savingBtn') : t('admin.modelSettings.saveBtn') }}
              </button>
              <button
                type="button"
                class="inline-flex items-center gap-2 px-4 py-2 border border-slate-300 text-slate-700 rounded-lg text-sm font-semibold hover:bg-slate-50 transition disabled:opacity-60"
                :disabled="savingSettings || resettingSettings"
                @click="handleResetSettings"
              >
                <RotateCcw :size="15" />
                {{ resettingSettings ? t('admin.modelSettings.resettingBtn') : t('admin.modelSettings.resetBtn') }}
              </button>
            </div>
          </div>
        </form>
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

.admin-model-form :deep(code) {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}

.ms-badge {
  display: inline-flex;
  align-items: center;
  padding: 0.05rem 0.4rem;
  border-radius: 9999px;
  font-size: 0.65rem;
  font-weight: 600;
  line-height: 1.4;
  border: 1px solid transparent;
}

.ms-badge--override {
  color: #0e7490;
  background: #cffafe;
  border-color: #a5f3fc;
}

.ms-badge--env {
  color: #475569;
  background: #f1f5f9;
  border-color: #e2e8f0;
}

.ms-badge--unset {
  color: #b45309;
  background: #fef3c7;
  border-color: #fde68a;
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

<template>
  <div class="rw-page">
    <WorkbenchTopbar :title="pageTitle" meta="404" />

    <div class="rw-page-scroll">
      <section class="not-found-panel">
        <div class="not-found-mark" aria-hidden="true">
          <span>404</span>
        </div>
        <p class="not-found-kicker">ROUTE NOT AVAILABLE</p>
        <h1>{{ t('notFound.title') }}</h1>
        <p class="not-found-copy">{{ t('notFound.copy') }}</p>
        <div class="not-found-actions">
          <button type="button" class="rw-btn-secondary" @click="$router.back()">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">
              <path d="m15 18-6-6 6-6" />
            </svg>
            <span>{{ t('notFound.back') }}</span>
          </button>
          <button type="button" class="rw-btn-primary" @click="goHome">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">
              <path d="M3 11.5 12 4l9 7.5" />
              <path d="M5 10.5V20h14v-9.5" />
              <path d="M9 20v-6h6v6" />
            </svg>
            <span>{{ t('notFound.home') }}</span>
          </button>
        </div>
      </section>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import WorkbenchTopbar from '@/layouts/WorkbenchTopbar.vue'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()

const pageTitle = computed(() => (route.meta?.title as string) || t('notFound.pageTitle'))

const goHome = () => {
  router.push('/workbench')
}
</script>

<style scoped>
.rw-page {
  min-height: 0;
  height: 100%;
  display: flex;
  flex-direction: column;
  background: var(--rw-canvas, #ffffff);
}

.rw-page-scroll {
  flex: 1;
  min-height: 0;
  overflow: auto;
  display: grid;
  place-items: center;
  padding: 28px;
}

.not-found-panel {
  width: min(100%, 640px);
  border: 1px solid var(--rw-hairline, #f0f0f3);
  background:
    linear-gradient(135deg, rgba(250, 250, 250, 0.92), rgba(255, 255, 255, 0.98)),
    var(--rw-canvas, #ffffff);
  border-radius: 8px;
  padding: 42px;
  box-shadow: 0 20px 70px rgba(23, 23, 23, 0.08);
}

.not-found-mark {
  width: 74px;
  height: 74px;
  border-radius: 8px;
  display: grid;
  place-items: center;
  background: var(--rw-ink, #171717);
  color: var(--rw-on-primary, #ffffff);
  font-family: var(--rw-mono, monospace);
  font-size: 16px;
  font-weight: 700;
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.14);
}

.not-found-kicker {
  margin: 28px 0 8px;
  color: var(--rw-muted, #999999);
  font-family: var(--rw-mono, monospace);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.08em;
}

.not-found-panel h1 {
  margin: 0;
  color: var(--rw-ink, #171717);
  font-size: 26px;
  line-height: 1.2;
  font-weight: 650;
}

.not-found-copy {
  margin: 12px 0 0;
  max-width: 520px;
  color: var(--rw-body, #60646c);
  font-size: 14px;
  line-height: 1.8;
}

.not-found-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 28px;
  flex-wrap: wrap;
}

.rw-btn-primary,
.rw-btn-secondary {
  height: 36px;
  border-radius: 8px;
  padding: 0 14px;
  display: inline-flex;
  align-items: center;
  gap: 7px;
  font-size: 13.5px;
  font-weight: 600;
  transition: background 0.15s, color 0.15s, border-color 0.15s;
}

.rw-btn-primary {
  border: 1px solid var(--rw-primary, #171717);
  background: var(--rw-primary, #171717);
  color: var(--rw-on-primary, #ffffff);
}

.rw-btn-primary:hover {
  background: var(--rw-primary-hover, #2e2e2e);
  color: var(--rw-on-primary, #ffffff);
}

.rw-btn-secondary {
  border: 1px solid var(--rw-hairline-strong, #dcdee0);
  background: var(--rw-canvas, #ffffff);
  color: var(--rw-ink, #171717);
}

.rw-btn-secondary:hover {
  background: var(--rw-surface-strong, #f0f0f3);
}

@media (max-width: 640px) {
  .rw-page-scroll {
    padding: 18px;
  }

  .not-found-panel {
    padding: 28px;
  }

  .not-found-panel h1 {
    font-size: 22px;
  }
}
</style>

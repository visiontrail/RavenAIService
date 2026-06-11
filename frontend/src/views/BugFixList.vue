<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { GitPullRequest, RefreshCw } from 'lucide-vue-next'
import WorkbenchTopbar from '@/layouts/WorkbenchTopbar.vue'
import { useBugFixStore } from '@/stores/bugFixes'
import { useUserStore } from '@/stores/user'
import type { BugFixTaskStatus, BugFixTaskSummary } from '@/types'

const router = useRouter()
const bugFixStore = useBugFixStore()
const { t } = useI18n()
const userStore = useUserStore()

const totalMeta = computed(() => t('bugFix.totalTasks', { count: bugFixStore.pagination.total }))

const statusMeta: Record<string, { text: string; className: string }> = {
  pending: { text: t('bugFix.statusText.pending'), className: 'rw-pill-neutral' },
  running: { text: t('bugFix.statusText.running'), className: 'rw-pill-info' },
  succeeded: { text: t('bugFix.statusText.succeeded'), className: 'rw-pill-success' },
  partial: { text: t('bugFix.statusText.partial'), className: 'rw-pill-warning' },
  failed: { text: t('bugFix.statusText.failed'), className: 'rw-pill-danger' },
  cancelled: { text: t('bugFix.statusText.cancelled'), className: 'rw-pill-neutral' },
}

const statusText = (status: BugFixTaskStatus) =>
  statusMeta[String(status)]?.text || String(status || t('bugFix.statusText.unknown'))

const statusClass = (status: BugFixTaskStatus) =>
  statusMeta[String(status)]?.className || 'rw-pill-neutral'

const formatDateTime = (value?: string | null) => {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString('zh-CN', {
    hour12: false,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

const projectText = (task: BugFixTaskSummary) => {
  if (task.project_name && task.project_code) return `${task.project_name} · ${task.project_code}`
  return task.project_name || task.project_code || t('bugFix.noProject')
}

const sourceLogText = (task: BugFixTaskSummary) =>
  task.source_log_id ? task.source_log_id.slice(0, 8) : '-'

const openDetail = (task: BugFixTaskSummary) => {
  router.push(`/bug-fixes/${task.id}`)
}

const refreshData = async () => {
  if (!userStore.isAuthenticated) return
  try {
    await bugFixStore.fetchTasks()
  } catch (error: any) {
    ElMessage.error(bugFixStore.error || error?.message || t('bugFix.fetchListFail'))
  }
}

const handlePageChange = async (page: number) => {
  try {
    await bugFixStore.fetchTasks({ page })
  } catch {
    ElMessage.error(bugFixStore.error || t('bugFix.fetchListFail'))
  }
}

const handleSizeChange = async (pageSize: number) => {
  try {
    await bugFixStore.fetchTasks({ page: 1, page_size: pageSize })
  } catch {
    ElMessage.error(bugFixStore.error || t('bugFix.fetchListFail'))
  }
}

onMounted(() => {
  refreshData()
})
</script>

<template>
  <div class="rw-page bug-fix-list-page">
    <WorkbenchTopbar :title="$t('bugFix.listTitle')" :meta="totalMeta">
      <template #actions>
        <button class="rw-btn-secondary" :disabled="bugFixStore.loading || !userStore.isAuthenticated" @click="refreshData">
          <RefreshCw :size="14" :class="{ spin: bugFixStore.loading }" />
          <span>{{ $t('bugFix.refresh') }}</span>
        </button>
      </template>
    </WorkbenchTopbar>

    <div class="rw-page-scroll">
      <section v-if="!userStore.isAuthenticated" class="rw-card empty-card">
        <div class="empty-icon">
          <GitPullRequest :size="22" />
        </div>
        <h2>{{ $t('bugFix.loginRequired') }}</h2>
        <p>{{ $t('bugFix.loginRequiredDesc') }}</p>
      </section>

      <template v-else>
        <section v-if="bugFixStore.loading || bugFixStore.tasks.length" class="rw-card table-card desktop-only">
          <el-table
            v-loading="bugFixStore.loading"
            :data="bugFixStore.tasks"
            class="bug-fix-table"
            :border="false"
            @row-click="openDetail"
          >
            <el-table-column prop="title" :label="$t('bugFix.taskTitle')" min-width="280" :show-overflow-tooltip="true">
              <template #default="{ row }">
                <div class="task-title-cell">
                  <span class="task-title">{{ row.title }}</span>
                  <span class="task-id">#{{ row.id.slice(0, 8) }}</span>
                </div>
              </template>
            </el-table-column>
            <el-table-column :label="$t('bugFix.project')" min-width="190" :show-overflow-tooltip="true">
              <template #default="{ row }">
                <div class="project-cell">
                  <span>{{ row.project_name || row.project_code || '-' }}</span>
                  <code v-if="row.project_code">{{ row.project_code }}</code>
                </div>
              </template>
            </el-table-column>
            <el-table-column :label="$t('bugFix.status')" width="120">
              <template #default="{ row }">
                <span :class="['rw-pill', statusClass(row.status)]">{{ statusText(row.status) }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="merge_request_count" :label="$t('bugFix.mrCount')" width="110" align="center">
              <template #default="{ row }">
                <span class="mono-cell">{{ row.merge_request_count }}</span>
              </template>
            </el-table-column>
            <el-table-column :label="$t('bugFix.sourceLog')" width="130">
              <template #default="{ row }">
                <router-link
                  v-if="row.source_log_id"
                  class="source-link"
                  :to="`/log/${row.source_log_id}`"
                  @click.stop
                >
                  {{ sourceLogText(row) }}
                </router-link>
                <span v-else class="muted-cell">-</span>
              </template>
            </el-table-column>
            <el-table-column :label="$t('bugFix.createdAt')" width="180">
              <template #default="{ row }">
                <span class="mono-cell">{{ formatDateTime(row.created_at) }}</span>
              </template>
            </el-table-column>
          </el-table>

          <div class="pagination-wrapper">
            <el-pagination
              :current-page="bugFixStore.pagination.page"
              :page-size="bugFixStore.pagination.page_size"
              :total="bugFixStore.pagination.total"
              :page-sizes="[10, 20, 50, 100]"
              layout="total, sizes, prev, pager, next, jumper"
              @current-change="handlePageChange"
              @size-change="handleSizeChange"
            />
          </div>
        </section>

        <div class="mobile-only mobile-list-wrap" v-loading="bugFixStore.loading">
          <article
            v-for="task in bugFixStore.tasks"
            :key="task.id"
            class="mobile-task-card"
            @click="openDetail(task)"
          >
            <div class="mobile-card-head">
              <h2>{{ task.title }}</h2>
              <span :class="['rw-pill', statusClass(task.status)]">{{ statusText(task.status) }}</span>
            </div>
            <div class="mobile-meta-row">
              <span>{{ projectText(task) }}</span>
              <span>{{ task.merge_request_count }} MR</span>
            </div>
            <div class="mobile-meta-row">
              <router-link
                v-if="task.source_log_id"
                class="source-link"
                :to="`/log/${task.source_log_id}`"
                @click.stop
              >
                {{ $t('bugFix.sourceText', { text: sourceLogText(task) }) }}
              </router-link>
              <span v-else>{{ $t('bugFix.noSourceLog') }}</span>
              <span>{{ formatDateTime(task.created_at) }}</span>
            </div>
          </article>

          <div v-if="!bugFixStore.loading && !bugFixStore.tasks.length" class="rw-card empty-card">
            <div class="empty-icon">
              <GitPullRequest :size="22" />
            </div>
            <h2>{{ $t('bugFix.emptyListTitle') }}</h2>
            <p>{{ $t('bugFix.emptyListDesc') }}</p>
          </div>
        </div>

        <section v-if="!bugFixStore.loading && !bugFixStore.tasks.length" class="rw-card empty-card desktop-empty">
          <div class="empty-icon">
            <GitPullRequest :size="22" />
          </div>
          <h2>{{ $t('bugFix.emptyListTitle') }}</h2>
          <p>{{ $t('bugFix.emptyListDesc') }}</p>
        </section>
      </template>
    </div>
  </div>
</template>

<style scoped>
.rw-page {
  --rw-canvas: #ffffff;
  --rw-canvas-soft: #fafafa;
  --rw-surface-card: #ffffff;
  --rw-surface-strong: #f0f0f3;
  --rw-ink: #171717;
  --rw-body: #60646c;
  --rw-muted: #999999;
  --rw-hairline: #f0f0f3;
  --rw-hairline-strong: #dcdee0;
  --rw-primary: #171717;
  --rw-primary-active: #404040;
  --rw-on-primary: #ffffff;
  --rw-success: #16a34a;
  --rw-danger: #c0382b;
  --rw-mono: 'JetBrains Mono', 'Fira Code', ui-monospace, monospace;
  height: 100%;
  display: flex;
  flex-direction: column;
  min-width: 0;
  background: var(--rw-canvas);
  color: var(--rw-ink);
}

.rw-page-scroll {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: 24px 28px 36px;
}

.rw-page-scroll > * + * {
  margin-top: 16px;
}

.rw-card {
  background: var(--rw-surface-card);
  border: 1px solid var(--rw-hairline);
  border-radius: 8px;
}

.desktop-only { display: block; }
.mobile-only { display: none; }

.rw-btn-secondary {
  min-height: 32px;
  padding: 0 12px;
  border: 1px solid var(--rw-hairline-strong);
  border-radius: 8px;
  background: var(--rw-canvas);
  color: var(--rw-ink);
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  font-weight: 600;
}

.rw-btn-secondary:hover:not(:disabled) {
  background: var(--rw-surface-strong);
}

.rw-btn-secondary:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.spin {
  animation: spin 0.9s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.table-card {
  padding: 16px 18px 18px;
}

.bug-fix-table :deep(.el-table__row) {
  cursor: pointer;
}

.bug-fix-table :deep(.el-table__row:hover > td.el-table__cell) {
  background: var(--rw-canvas-soft);
}

.task-title-cell {
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 8px;
}

.task-title {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-weight: 650;
  color: var(--rw-ink);
}

.task-id,
.mono-cell {
  font-family: var(--rw-mono);
  color: var(--rw-muted);
  font-size: 12px;
}

.project-cell {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.project-cell span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--rw-ink);
  font-weight: 550;
}

.project-cell code {
  width: fit-content;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  border-radius: 6px;
  padding: 2px 6px;
  background: var(--rw-surface-strong);
  color: var(--rw-body);
  font-family: var(--rw-mono);
  font-size: 11px;
}

.source-link {
  color: var(--rw-ink);
  font-family: var(--rw-mono);
  font-size: 12px;
  text-decoration: underline;
  text-underline-offset: 3px;
}

.muted-cell {
  color: var(--rw-muted);
}

.rw-pill {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 24px;
  padding: 0 9px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 650;
  white-space: nowrap;
}

.rw-pill-success { background: rgba(22, 163, 74, 0.12); color: #15803d; }
.rw-pill-info { background: var(--rw-surface-strong); color: var(--rw-ink); }
.rw-pill-warning { background: rgba(171, 100, 0, 0.10); color: #ab6400; }
.rw-pill-danger { background: rgba(192, 56, 43, 0.10); color: #c0382b; }
.rw-pill-neutral { background: var(--rw-surface-strong); color: var(--rw-body); }

.pagination-wrapper {
  display: flex;
  justify-content: flex-end;
  padding-top: 16px;
}

.empty-card {
  min-height: 260px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 32px;
  color: var(--rw-body);
  text-align: center;
}

.empty-icon {
  width: 44px;
  height: 44px;
  border-radius: 8px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: var(--rw-surface-strong);
  color: var(--rw-ink);
}

.empty-card h2 {
  margin: 6px 0 0;
  font-size: 17px;
  font-weight: 650;
  color: var(--rw-ink);
}

.empty-card p {
  margin: 0;
  font-size: 13px;
  color: var(--rw-muted);
}

.desktop-empty {
  display: flex;
}

.mobile-task-card {
  border: 1px solid var(--rw-hairline);
  border-radius: 8px;
  padding: 14px;
  background: var(--rw-surface-card);
}

.mobile-task-card + .mobile-task-card {
  margin-top: 12px;
}

.mobile-card-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.mobile-card-head h2 {
  margin: 0;
  min-width: 0;
  font-size: 15px;
  line-height: 1.35;
  font-weight: 650;
  color: var(--rw-ink);
}

.mobile-meta-row {
  margin-top: 10px;
  display: flex;
  justify-content: space-between;
  gap: 12px;
  color: var(--rw-body);
  font-size: 12px;
}

.mobile-meta-row span {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

@media (max-width: 900px) {
  .rw-page-scroll {
    padding: 16px 16px 28px;
  }

  .desktop-only,
  .desktop-empty {
    display: none;
  }

  .mobile-only {
    display: block;
  }
}
</style>

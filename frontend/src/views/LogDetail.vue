<template>
  <div class="rw-page log-detail-page">
    <header class="rw-topbar">
      <div class="rw-topbar-left">
        <button class="back-btn" @click="$router.back()" :title="t('common.back')">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
            <path d="M15 18l-6-6 6-6" />
          </svg>
        </button>
        <span class="rw-crumb">{{ t('logDetail.crumb') }}</span>
        <span v-if="logStore.currentLog" class="rw-crumb-meta">· {{ logStore.currentLog.filename }}</span>
      </div>
      <div class="rw-topbar-right">
        <button class="rw-btn-secondary" @click="handleCopyLink">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
            <rect x="9" y="9" width="13" height="13" rx="2" ry="2"/>
            <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>
          </svg>
          <span>{{ t('common.copyLink') }}</span>
        </button>
        <button class="rw-btn-secondary" :disabled="exportPdfLoading || !logStore.currentLog" @click="handleExportPDF">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
            <polyline points="14 2 14 8 20 8"/>
            <line x1="9" y1="15" x2="15" y2="15"/>
            <line x1="9" y1="11" x2="15" y2="11"/>
          </svg>
          <span>{{ exportPdfLoading ? t('logDetail.exportPdfLoading') : t('logDetail.exportPdf') }}</span>
        </button>
        <button class="rw-btn-primary" :disabled="downloadLoading || !logStore.currentLog" @click="handleDownload">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
            <polyline points="7 10 12 15 17 10" />
            <line x1="12" y1="15" x2="12" y2="3" />
          </svg>
          <span>{{ downloadLoading ? t('logDetail.downloadLoading') : t('common.download') }}</span>
        </button>
      </div>
    </header>

    <div class="rw-page-scroll">
      <div v-if="logStore.loading" class="rw-card">
        <el-skeleton :rows="8" animated />
      </div>

      <template v-else-if="logStore.currentLog">
        <!-- 标题卡 -->
        <section class="rw-card title-card">
          <div class="title-row">
            <div class="title-left">
              <h1 class="title-name">{{ logStore.currentLog.filename }}</h1>
              <div class="title-meta">
                <span class="title-id">ID: {{ logStore.currentLog.id }}</span>
              </div>
            </div>
            <div class="title-tags">
              <span :class="['rw-pill', projectPill(logStore.currentLog)]">
                {{ getProjectLabel(logStore.currentLog) }}
              </span>
              <span :class="['rw-pill', statusPill(logStore.currentLog.status)]">
                <span v-if="logStore.currentLog.status === 'processing'" class="rw-pill-dot"></span>
                {{ getStatusLabel(logStore.currentLog.status) }}
              </span>
            </div>
          </div>
        </section>

        <!-- 基本信息 -->
        <section class="rw-card">
          <div class="card-head">
            <h2 class="card-title">{{ t('logDetail.basicInfo') }}</h2>
          </div>
          <div class="info-grid">
            <div class="info-item">
              <label>{{ t('logDetail.filename') }}</label>
              <div class="info-value mono">{{ logStore.currentLog.filename }}</div>
            </div>
            <div class="info-item" v-if="logStore.currentLog.original_filename">
              <label>{{ t('logDetail.originalFilename') }}</label>
              <div class="info-value">{{ logStore.currentLog.original_filename }}</div>
            </div>
            <div
              class="info-item col-span-all"
              v-if="(logStore.currentLog.attachment_count ?? 1) > 1"
            >
              <label>
                {{ t('logDetail.attachments', { count: logStore.currentLog.attachment_count }) }}
              </label>
              <div class="code-box">
                <div
                  v-for="attachment in logStore.currentLog.attachments"
                  :key="attachment.id"
                >
                  {{ attachment.filename }} · {{ formatFileSize(attachment.file_size) }}
                </div>
              </div>
            </div>
            <div class="info-item">
              <label>{{ t('logDetail.fileSize') }}</label>
              <div class="info-value strong">{{ formatFileSize(logStore.currentLog.file_size) }}</div>
            </div>
            <div class="info-item">
              <label>{{ t('logDetail.createdAt') }}</label>
              <div class="info-value mono">{{ formatDateTime(logStore.currentLog.created_at) }}</div>
            </div>
            <div class="info-item">
              <label>{{ t('logDetail.processStatus') }}</label>
              <div>
                <span :class="['rw-pill', statusPill(logStore.currentLog.status)]">
                  {{ getStatusLabel(logStore.currentLog.status) }}
                </span>
              </div>
            </div>
            <div class="info-item">
              <label>{{ t('logDetail.downloadCount') }}</label>
              <div class="info-value strong">{{ logStore.currentLog.download_count }}</div>
            </div>

            <div
              class="info-item col-span-all"
              v-if="logStore.currentLog.status === 'processing'"
            >
              <label>{{ t('logDetail.processProgress') }}</label>
              <el-progress
                :percentage="logStore.currentLog.progress || 0"
                :status="logStore.currentLog.progress === 100 ? 'success' : undefined"
                :stroke-width="8"
              />
              <div class="info-hint">{{ t('logDetail.percentComplete', { percent: logStore.currentLog.progress || 0 }) }}</div>
            </div>

            <div class="info-item col-span-all" v-if="logStore.currentLog.checksum">
              <label>{{ t('logDetail.checksum') }}</label>
              <div class="code-box">{{ logStore.currentLog.checksum }}</div>
            </div>

            <div class="info-item" v-if="logStore.currentLog.task_id">
              <label>{{ t('logDetail.taskId') }}</label>
              <div class="code-box">{{ logStore.currentLog.task_id }}</div>
            </div>

            <div class="info-item" v-if="logStore.currentLog.retry_count !== undefined && logStore.currentLog.retry_count > 0">
              <label>{{ t('logDetail.retryCount') }}</label>
              <div class="info-value strong">{{ logStore.currentLog.retry_count }}</div>
            </div>

            <!-- 问题描述 -->
            <div class="info-item col-span-all">
              <div class="info-item-head">
                <label>{{ t('logDetail.issueDescription') }}</label>
                <div class="info-item-actions">
                  <button v-if="issueDescriptionEditing" class="rw-btn-secondary rw-btn-xs" @click="cancelIssueDescriptionEdit">{{ t('common.cancel') }}</button>
                  <button
                    class="rw-btn-primary rw-btn-xs"
                    :disabled="issueDescriptionSaving"
                    @click="issueDescriptionEditing ? handleSaveIssueDescription() : startEditIssueDescription()"
                  >
                    {{ issueDescriptionEditing ? t('common.save') : (logStore.currentLog?.issue_description ? t('common.edit') : t('common.add')) }}
                  </button>
                </div>
              </div>
              <div v-if="issueDescriptionEditing" class="issue-edit">
                <el-input
                  v-model="issueDescriptionDraft"
                  type="textarea"
                  :autosize="{ minRows: 3, maxRows: 6 }"
                  maxlength="5000"
                  show-word-limit
                  :placeholder="t('logDetail.issuePlaceholder')"
                />
                <div class="info-hint">{{ t('logDetail.issueClearHint') }}</div>
              </div>
              <div v-else>
                <div v-if="logStore.currentLog.issue_description" class="info-block highlight">{{ logStore.currentLog.issue_description }}</div>
                <div v-else class="info-block dashed">{{ t('logDetail.noIssueDescription') }}</div>
              </div>
            </div>

            <!-- 错误信息 -->
            <div class="info-item col-span-all" v-if="logStore.currentLog.error_message">
              <label>{{ t('logDetail.errorMessage') }}</label>
              <div class="info-block error">{{ logStore.currentLog.error_message }}</div>
            </div>

            <!-- 元数据 -->
            <div class="info-item col-span-all" v-if="logStore.currentLog.metadata && hasMetadata(logStore.currentLog.metadata)">
              <label>{{ t('logDetail.metadata') }}</label>
              <div class="meta-block">
                <div class="meta-grid">
                  <div v-if="logStore.currentLog.metadata.source" class="meta-item">
                    <span class="meta-label">{{ t('logDetail.metaSource') }}</span>
                    <span class="meta-value">{{ logStore.currentLog.metadata.source }}</span>
                  </div>
                  <div v-if="triggerDisplayName" class="meta-item">
                    <span class="meta-label">{{ t('logDetail.metaUsername') }}</span>
                    <span class="meta-value">{{ triggerDisplayName }}</span>
                  </div>
                  <div v-if="logStore.currentLog.metadata.environment" class="meta-item">
                    <span class="meta-label">{{ t('logDetail.metaEnvironment') }}</span>
                    <span class="meta-value">{{ logStore.currentLog.metadata.environment }}</span>
                  </div>
                  <div v-if="logStore.currentLog.metadata.service_name" class="meta-item">
                    <span class="meta-label">{{ t('logDetail.metaServiceName') }}</span>
                    <span class="meta-value">{{ logStore.currentLog.metadata.service_name }}</span>
                  </div>
                  <div
                    v-if="logStore.currentLog.metadata.version_info || logStore.currentLog.metadata.version"
                    class="meta-item col-span-2"
                  >
                    <span class="meta-label">{{ t('logDetail.versionInfo') }}</span>
                    <div
                      v-if="logStore.currentLog.metadata.version_info && logStore.currentLog.metadata.version_info.raw_content"
                      class="version-info"
                    >
                      <el-collapse v-model="activeVersionCollapse" class="version-collapse">
                        <el-collapse-item name="version-details">
                          <template #title>
                            <div class="version-title">
                              <span class="version-title-text">{{ t('logDetail.versionBoardTitle') }}</span>
                              <span class="rw-pill rw-pill-info">{{ t('logDetail.boardCount', { count: getVersionBoardCount(logStore.currentLog.metadata.version_info.raw_content) }) }}</span>
                            </div>
                          </template>
                          <div class="version-content">
                            <div
                              v-for="(board, index) in parseVersionInfo(logStore.currentLog.metadata.version_info.raw_content)"
                              :key="index"
                              class="board-info"
                            >
                              <div class="board-header">
                                <div class="board-header-left">
                                  <h4>{{ board.title }}</h4>
                                  <p>Slot ID: {{ board.slotId }} · CPU ID: {{ board.cpuId }}</p>
                                </div>
                                <span :class="['rw-pill', board.type === 'main' ? 'rw-pill-success' : 'rw-pill-info']">
                                  {{ board.type === 'main' ? t('logDetail.mainBoard') : t('logDetail.subBoard') }}
                                </span>
                              </div>
                              <div class="board-details">
                                <div v-if="board.oamVersion" class="version-section">
                                  <h5>{{ t('logDetail.oamVersion') }}</h5>
                                  <div class="kv-list">
                                    <div class="kv"><span>{{ t('logDetail.versionNumber') }}</span><span class="mono">{{ board.oamVersion.version }}</span></div>
                                    <div class="kv"><span>{{ t('logDetail.gitVersion') }}</span><span class="mono">{{ board.oamVersion.gitVersion }}</span></div>
                                    <div class="kv"><span>{{ t('logDetail.branch') }}</span><span class="mono">{{ board.oamVersion.branch }}</span></div>
                                    <div class="kv"><span>{{ t('logDetail.buildTime') }}</span><span class="mono">{{ board.oamVersion.buildTime }}</span></div>
                                  </div>
                                </div>
                                <div v-if="board.protocolVersion" class="version-section">
                                  <h5>{{ t('logDetail.protocolStackVersion') }}</h5>
                                  <div class="kv-list">
                                    <div v-if="board.protocolVersion.cucp" class="kv"><span>{{ t('logDetail.cucpVersion') }}</span><span class="mono">{{ board.protocolVersion.cucp }}</span></div>
                                    <div v-if="board.protocolVersion.cuup" class="kv"><span>{{ t('logDetail.cuupVersion') }}</span><span class="mono">{{ board.protocolVersion.cuup }}</span></div>
                                    <div v-if="board.protocolVersion.du" class="kv"><span>{{ t('logDetail.duVersion') }}</span><span class="mono">{{ board.protocolVersion.du }}</span></div>
                                    <template v-if="board.protocolVersion.extra && board.protocolVersion.extra.length">
                                      <div v-for="(item, idx) in board.protocolVersion.extra" :key="idx" class="kv">
                                        <span>{{ item.key }}</span><span class="mono">{{ item.value }}</span>
                                      </div>
                                    </template>
                                    <div v-if="board.protocolVersion.status" class="kv">
                                      <span>{{ t('logDetail.boardStatus') }}</span>
                                      <span :class="['rw-pill', board.protocolVersion.status === 'Not applicable for this SOM type' ? 'rw-pill-info' : 'rw-pill-success']">
                                        {{ board.protocolVersion.status }}
                                      </span>
                                    </div>
                                  </div>
                                </div>
                                <div v-if="board.fpgaVersion" class="version-section">
                                  <h5>{{ t('logDetail.fpgaVersion') }}</h5>
                                  <span class="rw-pill rw-pill-warning">{{ board.fpgaVersion }}</span>
                                </div>
                                <div v-if="board.componentCount" class="version-section">
                                  <h5>{{ t('logDetail.componentInfo') }}</h5>
                                  <div class="kv"><span>{{ t('logDetail.componentCount') }}</span><span class="mono strong">{{ board.componentCount }}</span></div>
                                </div>
                              </div>
                            </div>
                          </div>
                        </el-collapse-item>
                      </el-collapse>
                    </div>
                    <div v-else-if="logStore.currentLog.metadata.version" class="code-box">{{ logStore.currentLog.metadata.version }}</div>
                  </div>
                </div>
                <div v-if="logStore.currentLog.metadata.tags && logStore.currentLog.metadata.tags.length > 0" class="meta-tags">
                  <span class="meta-label">{{ t('logDetail.tags') }}</span>
                  <div class="tag-list">
                    <span class="rw-pill rw-pill-info" v-for="tag in logStore.currentLog.metadata.tags" :key="tag">{{ tag }}</span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </section>

        <!-- AI 分析 -->
        <section class="rw-card">
          <div class="card-head">
            <h2 class="card-title">{{ t('logDetail.aiAnalysisTitle') }}</h2>
            <span class="card-subtitle">{{ t('logDetail.aiAutoSaveHint') }}</span>
            <span
              v-if="aiAnalysisResult"
              :class="['rw-pill', aiAnalysisResult.status === 'completed' ? 'rw-pill-success' : 'rw-pill-warning']"
            >
              {{ aiAnalysisResult.status === 'completed' ? t('logDetail.completed') : t('logDetail.partialComplete') }}
            </span>
          </div>

          <div v-if="!aiAnalysisLoading && !aiAnalysisResult" class="analysis-input">
            <p class="analysis-hint">
              {{ logStore.currentLog.issue_description
                ? t('logDetail.aiQueryFilledHint')
                : t('logDetail.aiQueryEmptyHint') }}
            </p>
            <el-input
              v-model="aiAnalysisQuery"
              type="textarea"
              :rows="3"
              :placeholder="logStore.currentLog.issue_description
                ? t('logDetail.aiQueryFilledPlaceholder')
                : t('logDetail.aiQueryEmptyPlaceholder')"
            />
            <div class="analysis-project-row">
              <label class="analysis-project-label">{{ t('logDetail.relatedProject') }}</label>
              <el-select
                v-model="selectedProjectRepoId"
                :loading="projectReposLoading"
                :placeholder="t('logDetail.projectSelectPlaceholder')"
                clearable
                filterable
                class="analysis-project-select"
              >
                <el-option
                  v-for="repo in projectRepos"
                  :key="repo.id"
                  :label="`${repo.project_name}（${repo.project_code}）`"
                  :value="repo.id"
                />
              </el-select>
              <span class="analysis-project-hint">
                {{ t('logDetail.projectSelectHint') }}
              </span>
            </div>
            <div class="analysis-actions">
              <button class="rw-btn-primary" @click="handleAIAnalysisSubmit">{{ t('logDetail.startAnalysis') }}</button>
              <button class="rw-btn-secondary" @click="aiAnalysisQuery = ''">{{ t('logDetail.clear') }}</button>
            </div>
          </div>

          <div v-if="aiAnalysisLoading" class="analysis-loading">
            <div class="loading-row">
              <span class="loader-dot"></span>
              <span>{{ t('logDetail.aiAnalyzing') }}</span>
            </div>
            <el-progress :percentage="aiAnalysisProgress" :stroke-width="8" />
            <div class="loading-meta">
              {{ t('logDetail.currentStatus', { status: aiAnalysisStatus || t('logDetail.running') }) }}
              <span v-if="aiAnalysisTaskId" class="loading-task">{{ t('logDetail.taskIdLabel', { taskId: aiAnalysisTaskId }) }}</span>
            </div>
          </div>

          <AgentTraceStream
            v-if="aiTraceEvents.length > 0 || aiTraceRunning"
            class="analysis-trace"
            :events="aiTraceEvents"
            :running="aiTraceRunning"
          />

          <AIAnalysisResult
            v-for="(turn, idx) in aiAnalysisConversation"
            :key="idx"
            class="analysis-turn"
            :result="turn"
            :readonly="idx < aiAnalysisConversation.length - 1"
            @restart="resetAIAnalysis"
            @copy="copyAnalysisResult"
            @download="downloadAnalysisResult"
            @share="shareAnalysisResult"
          />
        </section>

        <!-- 人工分析 -->
        <section class="rw-card">
          <div class="card-head">
            <h2 class="card-title">{{ t('logDetail.manualAnalysisTitle') }}</h2>
            <div class="card-head-right">
              <span v-if="manualAnalysisAuthorLabel" class="card-subtitle">
                {{ t('logDetail.manualAnalysisAuthor', { name: manualAnalysisAuthorLabel }) }}
              </span>
              <span v-if="logStore.currentLog?.manual_analysis_updated_at" class="card-subtitle">
                {{ t('logDetail.lastUpdated', { time: formatDateTime(logStore.currentLog.manual_analysis_updated_at) }) }}
              </span>
              <button class="rw-btn-secondary rw-btn-xs" @click="openManualAnalysisDialog">
                {{ logStore.currentLog?.manual_analysis ? t('logDetail.editManualAnalysis') : t('logDetail.addManualAnalysis') }}
              </button>
            </div>
          </div>
          <div
            v-if="logStore.currentLog?.manual_analysis"
            ref="manualAnalysisBodyRef"
            class="manual-analysis-body"
            v-html="renderedManualAnalysis"
          />
          <div v-else class="manual-empty">
            <p>{{ t('logDetail.noManualAnalysis') }}</p>
            <button class="rw-btn-primary rw-btn-xs" @click="openManualAnalysisDialog">{{ t('logDetail.addManualAnalysis') }}</button>
          </div>
        </section>

        <!-- 操作 -->
        <section class="rw-card">
          <div class="card-head">
            <h2 class="card-title">{{ t('logDetail.operations') }}</h2>
          </div>
          <div class="actions-grid">
            <button class="rw-btn-primary" :disabled="downloadLoading" @click="handleDownload">
              {{ downloadLoading ? t('logDetail.downloadLoading') : t('logDetail.downloadFile') }}
            </button>
            <button class="rw-btn-secondary" @click="openManualAnalysisDialog">{{ t('logDetail.manualAnalysisTitle') }}</button>
            <button class="rw-btn-secondary" @click="handleCopyLink">{{ t('common.copyLink') }}</button>
            <button class="rw-btn-danger" :disabled="deleteLoading" @click="handleDelete">
              {{ deleteLoading ? t('logDetail.deleteLoading') : t('logDetail.deleteFile') }}
            </button>
          </div>
        </section>
      </template>

      <div v-else class="not-found">
        <el-result icon="warning" :title="t('logDetail.notFoundTitle')" :sub-title="t('logDetail.notFoundSubtitle')">
          <template #extra>
            <button class="rw-btn-primary" @click="$router.push('/logs')">{{ t('logDetail.backToList') }}</button>
          </template>
        </el-result>
      </div>
    </div>

    <!-- 人工分析录入弹窗 -->
    <el-dialog
      v-model="manualAnalysisDialogVisible"
      :title="t('logDetail.manualDialogTitle')"
      width="720px"
      :close-on-click-modal="false"
      destroy-on-close
    >
      <el-form
        ref="manualAnalysisFormRef"
        :model="manualAnalysisForm"
        :rules="manualAnalysisRules"
        label-position="top"
      >
        <el-form-item :label="t('logDetail.manualLabel')" prop="content">
          <el-input
            v-model="manualAnalysisForm.content"
            type="textarea"
            :autosize="{ minRows: 6, maxRows: 14 }"
            maxlength="5000"
            show-word-limit
            :placeholder="t('logDetail.manualPlaceholder')"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <span class="dialog-footer">
          <button class="rw-btn-secondary" @click="manualAnalysisDialogVisible = false">{{ t('common.cancel') }}</button>
          <button class="rw-btn-primary" :disabled="manualAnalysisSaving" @click="handleSaveManualAnalysis">{{ t('common.save') }}</button>
        </span>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, onUnmounted, ref, computed, watch, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ElMessageBox, ElMessage } from 'element-plus'
import type { FormInstance } from 'element-plus'
import { useLogStore } from '../stores/logs'
import {
  formatFileSize,
  formatDateTime,
  downloadFile,
  copyToClipboard
} from '../utils'
import { logApi, projectRepoApi } from '../api'
import type { ProjectRepoOption } from '../api'
import type { LogRecord } from '../types'
import { API_BASE_URL } from '../api'
import AIAnalysisResult from '../components/AIAnalysisResult.vue'
import AgentTraceStream from '../components/AgentTraceStream.vue'
import type { AgentTraceEvent } from '../types/agentTrace'
import { useUserStore } from '../stores/user'
import { renderMarkdown, processMermaidBlocks } from '../utils/markdownRenderer'
import { jsPDF } from 'jspdf'
import html2canvas from 'html2canvas-pro'

interface Props {
  id: string
}

const props = defineProps<Props>()
const route = useRoute()
const router = useRouter()
const logStore = useLogStore()
const userStore = useUserStore()
const { t } = useI18n()

// 响应式变量
const downloadLoading = ref(false)
const deleteLoading = ref(false)
const exportPdfLoading = ref(false)
const activeVersionCollapse = ref(['version-details'])
const issueDescriptionEditing = ref(false)
const issueDescriptionSaving = ref(false)
const issueDescriptionDraft = ref('')
const manualAnalysisDialogVisible = ref(false)
const manualAnalysisSaving = ref(false)
const manualAnalysisFormRef = ref<FormInstance>()
const manualAnalysisBodyRef = ref<HTMLElement | null>(null)
const manualAnalysisForm = ref({
  content: ''
})
const manualAnalysisRules = {
  content: [
    { required: true, message: t('logDetail.manualRequired'), trigger: 'blur' },
    {
      validator: (_rule: any, value: string, callback: (error?: Error) => void) => {
        if (!value || !value.trim()) {
          callback(new Error(t('logDetail.manualRequired')))
        } else {
          callback()
        }
      },
      trigger: 'blur'
    },
    { min: 5, message: t('logDetail.manualMinLength'), trigger: 'blur' }
  ]
}

// AI分析相关状态
const aiAnalysisQuery = ref('')
const aiAnalysisLoading = ref(false)
const aiAnalysisProgress = ref(0)
const aiAnalysisResult = ref<any>(null)
const aiAnalysisTaskId = ref<string | null>(null)
const aiAnalysisStatus = ref<string | null>(null)
const aiAnalysisError = ref<string | null>(null)
const aiAnalysisPollTimer = ref<number | null>(null)
const aiAnalysisProgressTimer = ref<number | null>(null)
const showReasoningProcess = ref(false)
const showDetailedOutput = ref(false)

// AgentTrace stream state. Sourced from either the live SSE endpoint
// (`/logs/{log_id}/ai-analysis/trace/stream`) while a task is running, or
// from `ai_analysis_result.trace_events` once a task has finished.
const aiTraceEvents = ref<AgentTraceEvent[]>([])
const aiTraceRunning = ref(false)
const aiTraceAbort = ref<AbortController | null>(null)
const aiTraceLogId = ref<string | null>(null)

// 项目仓库选项（用于在 AI 分析时显式指定项目身份，
// 当上传的归档中不含 metadata.json 时尤为关键）
const projectRepos = ref<ProjectRepoOption[]>([])
const selectedProjectRepoId = ref<number | null>(null)
const projectReposLoading = ref(false)
const projectReposLoaded = ref(false)

const fetchProjectRepos = async () => {
  if (projectReposLoading.value || projectReposLoaded.value) return
  projectReposLoading.value = true
  try {
    const response = await projectRepoApi.listEnabled({ agent_key: 'log_analysis' })
    if (response.success && Array.isArray(response.data)) {
      projectRepos.value = response.data
    } else {
      projectRepos.value = []
    }
    projectReposLoaded.value = true
  } catch (err) {
    console.warn('Failed to load project repo list:', err)
    projectRepos.value = []
  } finally {
    projectReposLoading.value = false
  }
}

// 渲染已保存结果时的提问来源：优先用结果自带的 query（后端已持久化本轮提问），
// 再回退到当前日志的分析查询 / 问题描述。绝不使用临时输入框 aiAnalysisQuery，
// 否则在前端切换日志时会显示上一条日志残留的提问。
const resolveSavedQuery = (raw: any): string =>
  raw?.query ||
  logStore.currentLog?.ai_analysis_query ||
  logStore.currentLog?.issue_description ||
  ''

const normalizeAIAnalysisResult = (raw: any) => {
  if (!raw) return null

  if (typeof raw === 'string') {
    return {
      id: `analysis_${Date.now()}`,
      query: resolveSavedQuery(raw),
      status: 'completed',
      timestamp: new Date().toISOString(),
      final_result: {
        content: raw,
        summary: '',
        recommendations: []
      },
      metadata: {
        execution_time: 0,
        model_used: 'unknown'
      }
    }
  }

  // 兼容 V2/V3 扁平 schema（claude-agent-sdk 返回）与旧嵌套 schema
  const isV2Flat =
    raw && typeof raw === 'object' &&
    (raw.schema_version === 2 ||
     raw.schema_version === 3 ||
     'duration_seconds' in raw ||
     ('raw' in raw && !('final_result' in raw)))

  const QUESTION_TYPE_LABEL: Record<string, string> = {
    root_cause: t('logDetail.report.questionType.root_cause'),
    qa: t('logDetail.report.questionType.qa'),
    search: t('logDetail.report.questionType.search'),
    stats: t('logDetail.report.questionType.stats'),
    meta: t('logDetail.report.questionType.meta'),
    other: t('logDetail.report.questionType.other'),
  }

  const extractJsonStringField = (text: string, field: string): string => {
    const source = text || ''
    const key = `"${field}"`
    const keyIndex = source.indexOf(key)
    if (keyIndex < 0) return ''
    const colonIndex = source.indexOf(':', keyIndex + key.length)
    if (colonIndex < 0) return ''
    let quoteIndex = colonIndex + 1
    while (quoteIndex < source.length && /\s/.test(source[quoteIndex])) quoteIndex += 1
    if (source[quoteIndex] !== '"') return ''

    let escaped = false
    for (let i = quoteIndex + 1; i < source.length; i += 1) {
      const char = source[i]
      if (escaped) {
        escaped = false
        continue
      }
      if (char === '\\') {
        escaped = true
        continue
      }
      if (char === '"') {
        try {
          return JSON.parse(source.slice(quoteIndex, i + 1))
        } catch {
          return source.slice(quoteIndex + 1, i)
        }
      }
    }
    return ''
  }

  const extractAnswerFromRaw = (rawText: unknown): string => {
    if (typeof rawText !== 'string' || !rawText.trim()) return ''
    return extractJsonStringField(rawText, 'answer') || extractJsonStringField(rawText, 'summary')
  }

  const buildV2Markdown = (r: any): string => {
    const parts: string[] = []
    const qType: string = typeof r?.question_type === 'string' ? r.question_type : ''
    const isRootCause = qType === 'root_cause'

    // 主回答优先 —— V3 新增 answer 字段直接回应用户问题
    const answer: string = (typeof r?.answer === 'string' ? r.answer.trim() : '')
      || (r?.status === 'schema_mismatch' ? extractAnswerFromRaw(r?.raw).trim() : '')
    if (answer) {
      const label = QUESTION_TYPE_LABEL[qType] || t('logDetail.report.answer')
      parts.push(`## ${t('logDetail.report.answerHeadingLabel', { label })}\n\n${answer}`)
    }

    // summary 与 answer 不重复时再展示
    const summary: string = typeof r?.summary === 'string' ? r.summary.trim() : ''
    if (summary && summary !== answer) {
      parts.push(`## ${t('logDetail.report.summaryHeading')}\n\n${summary}`)
    }

    // 根因假设：只在 root_cause 且数组非空时显示
    if (isRootCause && Array.isArray(r?.root_cause_hypotheses) && r.root_cause_hypotheses.length) {
      const items = r.root_cause_hypotheses
        .map((h: any) => (typeof h === 'string' ? h : (h?.hypothesis || h?.description || JSON.stringify(h))))
        .map((s: string) => `- ${s}`).join('\n')
      parts.push(`## ${t('logDetail.report.rootCauseHypotheses')}\n\n${items}`)
    }
    // 旧 schema 兼容：没有 question_type 字段时按老行为渲染
    if (!qType && Array.isArray(r?.root_cause_hypotheses) && r.root_cause_hypotheses.length) {
      const items = r.root_cause_hypotheses
        .map((h: any) => (typeof h === 'string' ? h : (h?.hypothesis || h?.description || JSON.stringify(h))))
        .map((s: string) => `- ${s}`).join('\n')
      parts.push(`## ${t('logDetail.report.rootCauseHypotheses')}\n\n${items}`)
    }

    if (Array.isArray(r?.recommended_actions) && r.recommended_actions.length) {
      const items = r.recommended_actions
        .map((a: any) => (typeof a === 'string' ? a : (a?.action || a?.description || JSON.stringify(a))))
        .map((s: string) => `- ${s}`).join('\n')
      parts.push(`## ${t('logDetail.report.suggestions')}\n\n${items}`)
    }
    if (Array.isArray(r?.related_keywords) && r.related_keywords.length) {
      parts.push(`## ${t('logDetail.report.keywords')}\n\n${r.related_keywords.map((k: string) => `\`${k}\``).join(' ')}`)
    }
    // 兜底：schema_mismatch 不直接展示半截原始 JSON，避免把模型契约失败暴露给用户。
    if (parts.length === 0 && r?.status === 'schema_mismatch') {
      return t('logDetail.report.incompleteResult')
    }
    // 兜底：仅在没有任何结构化内容时保留原始文本，兼容旧数据。
    if (parts.length === 0 && typeof r?.raw === 'string' && r.raw.trim()) {
      return r.raw
    }
    return parts.join('\n\n')
  }

  let content: string
  let summary: string
  let executionTime: number
  let modelUsed: string
  let recommendations: string[]

  if (isV2Flat) {
    content = buildV2Markdown(raw)
    const recoveredAnswer = raw?.status === 'schema_mismatch' ? extractAnswerFromRaw(raw?.raw).trim() : ''
    // V3：优先使用直接回答用户问题的 answer 字段作为概览
    summary = (raw?.answer && String(raw.answer).trim())
      || raw?.summary
      || recoveredAnswer
      || ''
    executionTime = Number(raw?.duration_seconds ?? 0)
    modelUsed = raw?.model || 'unknown'
    recommendations = Array.isArray(raw?.recommended_actions)
      ? raw.recommended_actions.map((a: any) =>
          typeof a === 'string' ? a : (a?.action || a?.description || JSON.stringify(a)))
      : []
  } else {
    const rawContent = raw?.final_result?.content ?? raw?.final_report ?? raw?.content ?? ''
    content = typeof rawContent === 'string' ? rawContent : JSON.stringify(rawContent, null, 2)
    const firstNonEmptyLine = content
      .split('\n')
      .map((line: string) => line.trim())
      .find((line: string) => line.length > 0)
    summary =
      raw?.final_result?.summary ||
      (firstNonEmptyLine ? firstNonEmptyLine.replace(/^#+\s*/, '').slice(0, 200) : t('logDetail.report.analysisDone'))
    executionTime = Number(raw?.metadata?.execution_time ?? 0)
    modelUsed = raw?.metadata?.model_used || 'unknown'
    recommendations = Array.isArray(raw?.final_result?.recommendations) ? raw.final_result.recommendations : []
  }

  // 状态归一化：V2 的 "ok" 应映射为前端的 "completed"
  const rawStatus = raw?.status
  const schemaMismatchHasAnswer = rawStatus === 'schema_mismatch' && (
    (typeof raw?.answer === 'string' && raw.answer.trim()) ||
    (typeof raw?.summary === 'string' && raw.summary.trim()) ||
    extractAnswerFromRaw(raw?.raw).trim()
  )
  const normalizedStatus =
    rawStatus === 'ok' ? 'completed' :
    schemaMismatchHasAnswer ? 'completed' :
    rawStatus === 'error' ? 'failed' :
    (rawStatus || 'completed')

  return {
    ...raw,
    id: raw?.id || `analysis_${Date.now()}`,
    query: resolveSavedQuery(raw),
    status: normalizedStatus,
    timestamp: raw?.timestamp || new Date().toISOString(),
    final_result: {
      ...(raw?.final_result || {}),
      content,
      summary,
      recommendations,
    },
    metadata: {
      execution_time: executionTime,
      model_used: modelUsed,
      tokens_used: raw?.metadata?.tokens_used ?? raw?.token_usage?.output_tokens,
    }
  }
}

// 计算属性
const pageTitle = computed(() => {
  if (logStore.currentLog) {
    return t('logDetail.pageTitle', { filename: logStore.currentLog.filename })
  }
  return t('logDetail.crumb')
})

// 完整的 AI 分析多轮对话：后端按时间顺序持久化每一轮问答。
// 后端 conversation 列表已包含最近一轮，因此直接整段渲染；
// 仅当历史列表缺失（旧数据）时回退到单条 aiAnalysisResult。
const aiAnalysisConversation = computed(() => {
  const conversation = logStore.currentLog?.ai_analysis_conversation
  if (Array.isArray(conversation) && conversation.length) {
    return conversation
      .map((turn) => normalizeAIAnalysisResult(turn))
      .filter((turn): turn is NonNullable<typeof turn> => !!turn)
  }
  return aiAnalysisResult.value ? [aiAnalysisResult.value] : []
})

// 人工分析添加人展示：显示名称（或用户名），有邮箱时附加邮箱
const manualAnalysisAuthorLabel = computed(() => {
  const author = logStore.currentLog?.manual_analysis_author
  if (!author) return ''
  const name = author.display_name || author.username || ''
  if (name && author.email) return `${name} (${author.email})`
  return name || author.email || ''
})

const renderedManualAnalysis = computed(() => {
  const content = logStore.currentLog?.manual_analysis
  if (!content) return ''
  return renderMarkdown(content, { wrapperClass: 'markdown-content', cleanXml: true })
})

let manualAnalysisMermaidRenderScheduled = false

const scheduleManualAnalysisMermaidRender = () => {
  if (!renderedManualAnalysis.value || manualAnalysisMermaidRenderScheduled) return

  manualAnalysisMermaidRenderScheduled = true
  nextTick(() => {
    manualAnalysisMermaidRenderScheduled = false
    void processMermaidBlocks(manualAnalysisBodyRef.value)
  })
}

const triggerInfo = computed(() => {
  const value = logStore.currentLog?.ai_analysis_triggered_by
    || aiAnalysisResult.value?.triggered_by
    || logStore.currentLog?.ai_analysis_result?.triggered_by
  return value && typeof value === 'object' ? value : null
})

const triggerDisplayName = computed(() => {
  const user = triggerInfo.value?.user
  if (!user || typeof user !== 'object') return ''
  return String(user.display_name || user.username || user.email || user.id || '')
})

const logSource = computed(() => logStore.currentLog?.metadata?.source || '')

// 项目对应的 pill 样式
const projectPill = (log?: LogRecord | null) => {
  return log?.project_id ? 'rw-pill-success' : 'rw-pill-neutral'
}

// 获取项目标签文本
const getProjectLabel = (log?: LogRecord | null) => {
  return log?.project_name || t('logDetail.uncategorized')
}

// 状态对应的 pill 样式
const statusPill = (status?: string) => {
  switch (status) {
    case 'completed':
      return 'rw-pill-success'
    case 'processing':
      return 'rw-pill-warning'
    case 'failed':
      return 'rw-pill-danger'
    case 'pending':
      return 'rw-pill-info'
    default:
      return 'rw-pill-neutral'
  }
}

// 获取状态标签文本
const getStatusLabel = (status: string) => {
  switch (status) {
    case 'completed':
      return t('logDetail.statusLabel.completed')
    case 'processing':
      return t('logDetail.statusLabel.processing')
    case 'failed':
      return t('logDetail.statusLabel.failed')
    case 'pending':
      return t('logDetail.statusLabel.pending')
    default:
      return t('logDetail.statusLabel.unknown')
  }
}


// 检查是否有元数据内容
const hasMetadata = (metadata: any) => {
  if (!metadata || typeof metadata !== 'object') return false
  
  return !!(
    metadata.source ||
    triggerDisplayName.value ||
    metadata.environment ||
    metadata.service_name ||
    metadata.version ||
    (metadata.tags && metadata.tags.length > 0) ||
    (metadata.extra_fields && Object.keys(metadata.extra_fields).length > 0)
  )
}

// 解析版本信息
const parseVersionInfo = (rawContent: string) => {
  const boards = []
  const sections = rawContent.split('-----------------------------------------------------------------')
  const extractAfterColon = (text: string) => {
    const parts = text.split(':')
    if (parts.length <= 1) return text.trim()
    const value = parts.slice(1).join(':').trim()
    return value || text.trim()
  }
  
  for (const section of sections) {
    if (!section.trim()) continue
    
    const lines = section.split('\n').map(line => line.trim()).filter(line => line)
    
    let board: any = {
      title: '',
      slotId: '',
      cpuId: '',
      type: 'sub',
      oamVersion: null,
      protocolVersion: null,
      fpgaVersion: null,
      componentCount: null
    }
    
    // 解析板卡信息
    for (let i = 0; i < lines.length; i++) {
      const line = lines[i]
      
      if (line.includes('[Main Control Board Information]')) {
        board.title = 'Main Control Board Information'
        board.type = 'main'
      } else if (line.includes('[Sub Board Information]')) {
        board.title = 'Sub Board Information'
        board.type = 'sub'
      } else if (line.startsWith('Slot ID:')) {
        board.slotId = extractAfterColon(line)
      } else if (line.startsWith('CPU ID:')) {
        board.cpuId = extractAfterColon(line)
      } else if (line.startsWith('Component Count:')) {
        board.componentCount = extractAfterColon(line)
      } else if (line.includes('[OAM Version]')) {
        // 解析OAM版本信息
        board.oamVersion = {}
        for (let j = i + 1; j < lines.length && !lines[j].startsWith('['); j++) {
          const versionLine = lines[j]
          if (versionLine.startsWith('version:')) {
            board.oamVersion.version = extractAfterColon(versionLine)
          } else if (versionLine.startsWith('git version:')) {
            board.oamVersion.gitVersion = extractAfterColon(versionLine)
          } else if (versionLine.startsWith('branch:')) {
            board.oamVersion.branch = extractAfterColon(versionLine)
          } else if (versionLine.startsWith('build time:')) {
            board.oamVersion.buildTime = extractAfterColon(versionLine)
          }
        }
      } else if (/\[.*Protocol Stack Version.*\]/.test(line)) {
        // 解析协议栈版本信息
        board.protocolVersion = {}
        for (let j = i + 1; j < lines.length && !lines[j].startsWith('['); j++) {
          const protocolLine = lines[j]
          if (protocolLine.startsWith('cucp_version=')) {
            board.protocolVersion.cucp = protocolLine.split('=')[1]?.trim()
          } else if (protocolLine.startsWith('cuup_version=')) {
            board.protocolVersion.cuup = protocolLine.split('=')[1]?.trim()
          } else if (protocolLine.startsWith('du_version=')) {
            board.protocolVersion.du = protocolLine.split('=')[1]?.trim()
          } else if (protocolLine.includes('Not applicable for this SOM type')) {
            board.protocolVersion.status = 'Not applicable for this SOM type'
          } else if (protocolLine.includes('=')) {
            const [key, value] = protocolLine.split('=')
            if (key && value) {
              if (!board.protocolVersion.extra) board.protocolVersion.extra = []
              board.protocolVersion.extra.push({
                key: key.trim(),
                value: value.trim()
              })
            }
          }
        }
      } else if (/\[.*FPGA Version.*\]/.test(line)) {
        // 解析FPGA版本信息
        for (let j = i + 1; j < lines.length && !lines[j].startsWith('['); j++) {
          const fpgaLine = lines[j]
          if (fpgaLine.trim() && !fpgaLine.includes('Unavailable')) {
            board.fpgaVersion = extractAfterColon(fpgaLine)
          } else if (fpgaLine.includes('Unavailable')) {
            board.fpgaVersion = 'Unavailable'
          }
        }
      }
    }
    
    // 只添加有效的板卡信息
    if (board.slotId && board.cpuId) {
      boards.push(board)
    }
  }
  
  return boards
}

// 获取版本信息中的板卡数量
const getVersionBoardCount = (rawContent: string) => {
  const boards = parseVersionInfo(rawContent)
  return boards.length
}

// 下载文件 - 使用直接URL下载，立即触发
const handleDownload = async () => {
  if (!logStore.currentLog) return

  try {
    downloadLoading.value = true
    
    // 直接使用URL下载，立即触发浏览器下载
    const downloadUrl = logApi.getDownloadUrl(logStore.currentLog.id)
    const filename = logStore.currentLog.download_filename || logStore.currentLog.filename
    downloadFile(downloadUrl, filename)
    ElMessage.success(t('logDetail.downloadStarted', { filename }))
  } catch (error) {
    ElMessage.error(t('logDetail.downloadFail'))
  } finally {
    downloadLoading.value = false
  }
}

// 删除文件
const handleDelete = async () => {
  if (!logStore.currentLog) return

  try {
    await ElMessageBox.confirm(
      t('logDetail.deleteConfirm', { filename: logStore.currentLog.filename }),
      t('logDetail.deleteConfirmTitle'),
      {
        confirmButtonText: t('logDetail.confirmDelete'),
        cancelButtonText: t('common.cancel'),
        type: 'warning',
        dangerouslyUseHTMLString: false,
      }
    )

    deleteLoading.value = true
    await logStore.deleteLog(logStore.currentLog.id)
    ElMessage.success(t('logDetail.deleteSuccess', { filename: logStore.currentLog.filename }))
    router.push('/logs')
  } catch (error) {
    if (error !== 'cancel') {
      ElMessage.error(t('logDetail.deleteFail'))
    }
  } finally {
    deleteLoading.value = false
  }
}

// 问题描述编辑
const startEditIssueDescription = () => {
  issueDescriptionDraft.value = logStore.currentLog?.issue_description || ''
  issueDescriptionEditing.value = true
}

const cancelIssueDescriptionEdit = () => {
  issueDescriptionDraft.value = logStore.currentLog?.issue_description || ''
  issueDescriptionEditing.value = false
}

const handleSaveIssueDescription = async () => {
  if (!logStore.currentLog) return

  const value = issueDescriptionDraft.value.trim()
  const payload = value || null

  issueDescriptionSaving.value = true
  try {
    const response = await logApi.updateIssueDescription(logStore.currentLog.id, payload)
    if (response.success) {
      const updatedDescription = response.data?.issue_description || ''
      logStore.currentLog.issue_description = updatedDescription
      if (response.data?.updated_at) {
        logStore.currentLog.updated_at = response.data.updated_at
      }
      issueDescriptionDraft.value = updatedDescription
      issueDescriptionEditing.value = false
      ElMessage.success(updatedDescription ? t('logDetail.issueUpdated') : t('logDetail.issueCleared'))
    } else {
      throw new Error(response.message || t('logDetail.issueUpdateFail'))
    }
  } catch (error: any) {
    console.error('Failed to update issue description:', error)
    ElMessage.error(error.response?.data?.detail || error.message || t('logDetail.issueUpdateFail'))
  } finally {
    issueDescriptionSaving.value = false
  }
}

// 打开人工分析弹窗
const openManualAnalysisDialog = () => {
  manualAnalysisForm.value.content = logStore.currentLog?.manual_analysis || ''
  manualAnalysisDialogVisible.value = true
}

// 保存人工分析
const handleSaveManualAnalysis = async () => {
  if (!logStore.currentLog) return

  const form = manualAnalysisFormRef.value
  if (form) {
    try {
      await form.validate()
    } catch {
      return
    }
  }

  manualAnalysisSaving.value = true
  try {
    const content = manualAnalysisForm.value.content.trim()
    const response = await logApi.saveManualAnalysis(logStore.currentLog.id, content)
    if (response.success) {
      logStore.currentLog.manual_analysis = content
      logStore.currentLog.manual_analysis_updated_at =
        response.data?.manual_analysis_updated_at || new Date().toISOString()
      logStore.currentLog.manual_analysis_author = response.data?.manual_analysis_author || undefined
      ElMessage.success(t('logDetail.manualSaved'))
      manualAnalysisDialogVisible.value = false
    } else {
      throw new Error(response.message || t('logDetail.saveFail'))
    }
  } catch (error: any) {
    console.error('Failed to save manual analysis:', error)
    ElMessage.error(error.response?.data?.detail || error.message || t('logDetail.manualSaveFail'))
  } finally {
    manualAnalysisSaving.value = false
  }
}

// 复制链接
const handleCopyLink = async () => {
  const success = await copyToClipboard(window.location.href)
  if (success) {
    ElMessage.success(t('logDetail.copyLinkSuccess'))
  } else {
    ElMessage.error(t('logDetail.copyLinkFail'))
  }
}

// 导出 PDF 报告：使用内置渲染（html2canvas-pro 光栅化 + jsPDF 直接生成），
// 不走浏览器系统打印对话框，点击即直接下载 PDF 文件。
// 由于内容被光栅化为图片，可彻底规避 macOS 系统打印导出时中文字体缺失（空白）
// 以及原生分页重复页的问题；分页由我们自行按页高切片并对齐到元素边界完成。
// 报告内容中刻意剔除 "模型原文" 段落，避免冗余 raw 文本进入正式报告。
const escapeHtml = (text: string) =>
  text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')

const stripModelRawSection = (markdown: string): string => {
  if (!markdown) return ''
  // 匹配 "## 模型原文" 段落，直到下一个二级标题或文末。
  // 标题以 Unicode 转义写出（模型原文 = 模型原文），
  // 以便 CJK-literal 扫描通过，同时保持匹配行为不变。
  return markdown.replace(new RegExp('##\\s*\\u6a21\\u578b\\u539f\\u6587[\\s\\S]*?(?=\\n##\\s|\\n#\\s|$)', 'g'), '').trimEnd()
}

// 报告容器的样式。所有规则都用 `.pdf-export-root` 作为前缀作用域，
// 因此即便以全局 <style> 注入也不会污染当前页面（光栅化离屏容器使用）。
const PDF_EXPORT_STYLES = `
.pdf-export-root, .pdf-export-root * { box-sizing: border-box; }
.pdf-export-root {
  width: auto;
  max-width: none;
  padding: 0;
  font-family: 'PingFang SC', 'Microsoft YaHei', -apple-system, system-ui, sans-serif;
  color: #171717;
  background: #ffffff;
  line-height: 1.6;
  font-size: 13px;
  -webkit-print-color-adjust: exact;
  print-color-adjust: exact;
}
.pdf-export-root .report-title {
  font-size: 22px;
  margin: 0 0 4px;
  letter-spacing: -0.3px;
  font-weight: 600;
}
.pdf-export-root .report-meta {
  color: #777;
  font-size: 12px;
  margin-bottom: 24px;
  border-bottom: 1px solid #e5e5e5;
  padding-bottom: 12px;
}
.pdf-export-root section {
  margin-bottom: 24px;
  break-inside: avoid-page;
  page-break-inside: avoid;
}
.pdf-export-root h2 {
  font-size: 15px;
  margin: 0 0 10px;
  padding-bottom: 6px;
  border-bottom: 1px solid #e5e5e5;
  letter-spacing: -0.1px;
  font-weight: 600;
  break-after: avoid-page;
  page-break-after: avoid;
}
.pdf-export-root h3 {
  font-size: 13.5px;
  margin: 14px 0 6px;
  font-weight: 600;
  break-after: avoid-page;
  page-break-after: avoid;
}
.pdf-export-root table.info {
  width: 100%;
  border-collapse: collapse;
  break-inside: avoid-page;
  page-break-inside: avoid;
}
.pdf-export-root table.info th,
.pdf-export-root table.info td {
  text-align: left;
  padding: 6px 10px;
  border-bottom: 1px solid #f0f0f0;
  vertical-align: top;
  font-size: 12.5px;
}
.pdf-export-root table.info th {
  width: 130px;
  color: #666;
  font-weight: 500;
  background: #fafafa;
}
.pdf-export-root .issue-box,
.pdf-export-root .empty-box {
  padding: 10px 12px;
  border: 1px solid #eee;
  border-radius: 6px;
  background: #fafafa;
  break-inside: avoid-page;
  page-break-inside: avoid;
}
.pdf-export-root .empty-box { color: #999; font-style: italic; }
.pdf-export-root .ai-meta { font-size: 12px; color: #666; margin-bottom: 8px; }
.pdf-export-root .ai-meta span { margin-right: 16px; }
.pdf-export-root ul.recommendations { padding-left: 22px; margin: 8px 0; }
.pdf-export-root ul.recommendations li { margin-bottom: 4px; }
.pdf-export-root .md h1,
.pdf-export-root .md h2,
.pdf-export-root .md h3,
.pdf-export-root .md h4 {
  margin: 1em 0 0.4em;
  line-height: 1.3;
  font-weight: 600;
  break-after: avoid-page;
  page-break-after: avoid;
}
.pdf-export-root .md h1 { font-size: 16px; }
.pdf-export-root .md h2 { font-size: 14.5px; border: none; padding: 0; }
.pdf-export-root .md h3 { font-size: 13.5px; }
.pdf-export-root .md p {
  margin: 0.5em 0;
  break-inside: avoid-page;
  page-break-inside: avoid;
  orphans: 3;
  widows: 3;
}
.pdf-export-root .md code {
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  background: #f5f5f7;
  border: 1px solid #ececec;
  border-radius: 4px;
  padding: 1px 5px;
  font-size: 12px;
}
.pdf-export-root .md pre {
  background: #1a1a1a;
  color: #f5f5f5;
  padding: 10px 12px;
  border-radius: 6px;
  overflow: hidden;
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 12px;
  line-height: 1.5;
  break-inside: avoid-page;
  page-break-inside: avoid;
}
.pdf-export-root .md pre code {
  background: transparent;
  border: none;
  padding: 0;
  color: inherit;
}
.pdf-export-root .md table {
  width: 100%;
  border-collapse: collapse;
  margin: 0.8em 0;
  break-inside: avoid-page;
  page-break-inside: avoid;
}
.pdf-export-root .md th,
.pdf-export-root .md td { border: 1px solid #ddd; padding: 4px 8px; font-size: 12.5px; }
.pdf-export-root .md th { background: #f5f5f7; }
.pdf-export-root .md ul,
.pdf-export-root .md ol { padding-left: 1.6em; }
.pdf-export-root .md ul { list-style-type: disc; }
.pdf-export-root .md ol { list-style-type: decimal; }
.pdf-export-root .md ul ul { list-style-type: circle; }
.pdf-export-root .md ul ul ul { list-style-type: square; }
.pdf-export-root .md li {
  break-inside: avoid-page;
  page-break-inside: avoid;
  orphans: 3;
  widows: 3;
}
.pdf-export-root .md blockquote {
  border-left: 3px solid #d4d4d4;
  padding-left: 12px;
  color: #555;
  margin: 0.6em 0;
  break-inside: avoid-page;
  page-break-inside: avoid;
}
.pdf-export-root tr {
  break-inside: avoid-page;
  page-break-inside: avoid;
}
`

const buildPdfFilename = (filename: string, id: string | number): string => {
  const base = (filename || String(id) || 'report').replace(/\.(zip|tar|gz|log|txt)$/i, '')
  const date = new Date().toISOString().slice(0, 10)
  return t('logDetail.report.pdfFilename', { base, date })
}

// A4 纸张与内容区尺寸（mm），以及离屏渲染宽度（px）。
const PDF_PAGE = {
  marginMm: 10,
  widthMm: 210,
  heightMm: 297,
  get contentWidthMm() { return this.widthMm - this.marginMm * 2 },
  get contentHeightMm() { return this.heightMm - this.marginMm * 2 },
  renderWidthPx: 760,
  scale: 2,
}

const handleExportPDF = async () => {
  if (!logStore.currentLog) return
  const log = logStore.currentLog

  // 离屏容器：渲染完整报告 DOM，供 html2canvas 光栅化后切片成 PDF。
  let container: HTMLDivElement | null = null
  const cleanupContainer = () => {
    if (container && container.parentNode) {
      container.parentNode.removeChild(container)
    }
    container = null
  }

  try {
    exportPdfLoading.value = true

    const aiContent = aiAnalysisResult.value?.final_result?.content || ''
    const aiContentNoRaw = stripModelRawSection(aiContent)
    const aiSummary = aiAnalysisResult.value?.final_result?.summary || ''
    const aiRecommendations: string[] = Array.isArray(aiAnalysisResult.value?.final_result?.recommendations)
      ? aiAnalysisResult.value.final_result.recommendations
      : []
    const aiModel = aiAnalysisResult.value?.metadata?.model_used || ''
    const aiExecTime = aiAnalysisResult.value?.metadata?.execution_time || 0

    const aiSummaryHtml = aiSummary ? renderMarkdown(aiSummary, { wrapperClass: 'md', cleanXml: true }) : ''
    const aiContentHtml = aiContentNoRaw ? renderMarkdown(aiContentNoRaw, { wrapperClass: 'md', cleanXml: true }) : ''
    const manualHtml = log.manual_analysis
      ? renderMarkdown(log.manual_analysis, { wrapperClass: 'md', cleanXml: true })
      : ''

    const infoRows: Array<[string, string]> = [
      [t('logDetail.originalFilename'), log.original_filename || ''],
      [t('logDetail.fileSize'), formatFileSize(log.file_size)],
      [t('logDetail.report.project'), getProjectLabel(log)],
      [t('logDetail.metaSource'), logSource.value],
      [t('logDetail.metaUsername'), triggerDisplayName.value],
      [t('logDetail.processStatus'), getStatusLabel(log.status)],
      [t('logDetail.createdAt'), formatDateTime(log.created_at)],
      [t('logDetail.downloadCount'), String(log.download_count ?? 0)],
    ]

    const infoRowsHtml = infoRows
      .filter(([, v]) => v !== '' && v !== undefined && v !== null)
      .map(([k, v]) => `<tr><th>${escapeHtml(k)}</th><td>${escapeHtml(v)}</td></tr>`)
      .join('')

    const title = t('logDetail.report.pdfTitle', { filename: log.filename })
    const generatedAt = formatDateTime(new Date().toISOString())

    const innerHtml = `
<h1 class="report-title">${escapeHtml(title)}</h1>
<div class="report-meta">${escapeHtml(t('logDetail.report.generatedAt', { time: generatedAt }))}</div>

<section>
  <h2>${escapeHtml(t('logDetail.basicInfo'))}</h2>
  <table class="info"><tbody>${infoRowsHtml}</tbody></table>
</section>

<section>
  <h2>${escapeHtml(t('logDetail.issueDescription'))}</h2>
  ${log.issue_description
    ? `<div class="issue-box">${escapeHtml(log.issue_description)}</div>`
    : `<div class="empty-box">${escapeHtml(t('logDetail.noIssueDescription'))}</div>`}
</section>

${log.error_message ? `
<section>
  <h2>${escapeHtml(t('logDetail.errorMessage'))}</h2>
  <div class="issue-box" style="color:#c0382b;border-color:rgba(192,56,43,0.25);background:rgba(192,56,43,0.04);">${escapeHtml(log.error_message)}</div>
</section>` : ''}

<section>
  <h2>${escapeHtml(t('logDetail.aiAnalysisTitle'))}</h2>
  ${aiAnalysisResult.value ? `
    <div class="ai-meta">
      ${aiModel ? `<span>${escapeHtml(t('logDetail.report.model', { model: aiModel }))}</span>` : ''}
      ${aiExecTime ? `<span>${escapeHtml(t('logDetail.report.execTime', { time: String(aiExecTime) }))}</span>` : ''}
    </div>
    ${aiSummaryHtml ? `<h3>${escapeHtml(t('logDetail.report.summaryHeading'))}</h3>${aiSummaryHtml}` : ''}
    ${aiContentHtml ? `<h3>${escapeHtml(t('logDetail.report.mdDetailedAnalysis'))}</h3>${aiContentHtml}` : ''}
    ${aiRecommendations.length ? `<h3>${escapeHtml(t('logDetail.report.suggestions'))}</h3><ul class="recommendations">${
      aiRecommendations.map((r) => `<li>${escapeHtml(r)}</li>`).join('')
    }</ul>` : ''}
  ` : `<div class="empty-box">${escapeHtml(t('logDetail.report.noAiResult'))}</div>`}
</section>

<section>
  <h2>${escapeHtml(t('logDetail.manualAnalysisTitle'))}</h2>
  ${manualHtml || `<div class="empty-box">${escapeHtml(t('logDetail.noManualAnalysis'))}</div>`}
</section>
`

    // 离屏渲染容器：固定到视口外，宽度固定以保证排版/换行稳定。
    container = document.createElement('div')
    container.setAttribute('aria-hidden', 'true')
    container.style.cssText = [
      'position: fixed',
      'left: -10000px',
      'top: 0',
      `width: ${PDF_PAGE.renderWidthPx}px`,
      'background: #ffffff',
      'pointer-events: none',
      'z-index: -1',
    ].join('; ')
    // 样式全部以 `.pdf-export-root` 作用域，随容器一起注入即可，不污染主页面。
    container.innerHTML = `<style>${PDF_EXPORT_STYLES}</style>` +
      `<div class="pdf-export-root" id="pdf-root">${innerHtml}</div>`
    document.body.appendChild(container)

    const root = container.querySelector('#pdf-root') as HTMLElement | null
    if (!root) throw new Error(t('logDetail.exportContainerFail'))

    // 等待 web 字体就绪，避免中文回退字体导致的度量偏差。
    if ((document as any).fonts?.ready) {
      try { await (document as any).fonts.ready } catch { /* noop */ }
    }
    // 给浏览器一次回流时间，确保子元素尺寸已计算完成。
    await new Promise((r) => setTimeout(r, 50))

    const scale = PDF_PAGE.scale
    const canvas = await html2canvas(root, {
      scale,
      backgroundColor: '#ffffff',
      useCORS: true,
      logging: false,
      windowWidth: PDF_PAGE.renderWidthPx,
    })
    if (!canvas.width || !canvas.height) {
      throw new Error(t('logDetail.exportFail'))
    }

    // 采集"安全分页点"：块级元素底部的 Y 坐标（画布像素），
    // 分页时把页底对齐到这些边界，避免把一行文字从中间切断。
    const rootTop = root.getBoundingClientRect().top
    const breakYs: number[] = []
    root
      .querySelectorAll('section, h1, h2, h3, h4, p, li, tr, pre, blockquote, table, ul, ol, .issue-box, .empty-box')
      .forEach((el) => {
        const bottom = (el.getBoundingClientRect().bottom - rootTop) * scale
        if (bottom > 0 && bottom <= canvas.height) breakYs.push(bottom)
      })
    breakYs.sort((a, b) => a - b)

    const pxPerMm = canvas.width / PDF_PAGE.contentWidthMm
    const pageHeightPx = PDF_PAGE.contentHeightMm * pxPerMm

    const pdf = new jsPDF({ unit: 'mm', format: 'a4', compress: true })

    let startY = 0
    let firstPage = true
    while (startY < canvas.height - 1) {
      let endY = Math.min(startY + pageHeightPx, canvas.height)
      // 若不是最后一页，尽量把页底对齐到一个安全分页点（至少填满半页，
      // 否则遇到超高元素会退化为硬切，避免出现大量空白页）。
      if (endY < canvas.height) {
        let snapped = -1
        for (const y of breakYs) {
          if (y > endY) break
          if (y > startY + pageHeightPx * 0.5) snapped = y
        }
        if (snapped > 0) endY = snapped
      }

      const sliceHeightPx = Math.max(1, Math.round(endY - startY))
      const pageCanvas = document.createElement('canvas')
      pageCanvas.width = canvas.width
      pageCanvas.height = sliceHeightPx
      const ctx = pageCanvas.getContext('2d')
      if (!ctx) throw new Error(t('logDetail.canvasCtxFail'))
      ctx.fillStyle = '#ffffff'
      ctx.fillRect(0, 0, pageCanvas.width, pageCanvas.height)
      ctx.drawImage(
        canvas,
        0, startY, canvas.width, sliceHeightPx,
        0, 0, canvas.width, sliceHeightPx,
      )

      const imgData = pageCanvas.toDataURL('image/png')
      const sliceHeightMm = sliceHeightPx / pxPerMm
      if (!firstPage) pdf.addPage()
      pdf.addImage(
        imgData, 'PNG',
        PDF_PAGE.marginMm, PDF_PAGE.marginMm,
        PDF_PAGE.contentWidthMm, sliceHeightMm,
        undefined, 'FAST',
      )

      firstPage = false
      startY = endY
    }

    pdf.save(buildPdfFilename(log.filename, log.id))
    ElMessage.success(t('logDetail.pdfDownloadStarted'))
  } catch (error: any) {
    console.error('Failed to export report:', error)
    ElMessage.error(error?.message || t('logDetail.exportFail'))
  } finally {
    cleanupContainer()
    exportPdfLoading.value = false
  }
}

const stopAIAnalysisPolling = () => {
  if (aiAnalysisPollTimer.value) {
    window.clearInterval(aiAnalysisPollTimer.value)
    aiAnalysisPollTimer.value = null
  }
}

const closeTraceStream = () => {
  if (aiTraceAbort.value) {
    try { aiTraceAbort.value.abort() } catch { /* noop */ }
    aiTraceAbort.value = null
  }
  aiTraceRunning.value = false
}

const seedTraceFromResult = (result: any) => {
  // Backend persists the full event list to ai_analysis_result.trace_events
  // on task completion. Hydrating here lets a refresh restore the trace as
  // the terminal collapsed summary (component does that automatically once
  // it sees run_complete/cancelled/error in the events array).
  const events = Array.isArray(result?.trace_events) ? result.trace_events : []
  if (events.length > 0) {
    aiTraceEvents.value = events as AgentTraceEvent[]
    aiTraceRunning.value = false
  } else {
    aiTraceEvents.value = []
  }
}

const openTraceStream = async (logId: string) => {
  if (aiTraceLogId.value === logId && aiTraceAbort.value) return
  closeTraceStream()

  aiTraceLogId.value = logId
  aiTraceRunning.value = true
  // Don't clobber any already-seeded events — backend replays from seq=1
  // and the composable de-dupes, so an existing buffer is harmless.
  if (aiTraceEvents.value.length === 0) aiTraceEvents.value = []

  const controller = new AbortController()
  aiTraceAbort.value = controller

  const headers: Record<string, string> = { Accept: 'text/event-stream' }
  const token = userStore.token as unknown as string
  if (token) headers.Authorization = `Bearer ${token}`

  try {
    const resp = await fetch(
      `${API_BASE_URL}/api/v1/logs/${encodeURIComponent(logId)}/ai-analysis/trace/stream`,
      { method: 'GET', headers, signal: controller.signal },
    )
    if (!resp.ok || !resp.body) {
      if (resp.status === 404) {
        // No task exists yet — nothing to stream.
        aiTraceRunning.value = false
        return
      }
      throw new Error(`HTTP ${resp.status}`)
    }

    const textStream = typeof TextDecoderStream !== 'undefined'
      ? resp.body.pipeThrough(new TextDecoderStream())
      : null
    const reader = textStream ? textStream.getReader() : null
    const binaryReader = !textStream ? resp.body.getReader() : null
    const decoder = !textStream ? new TextDecoder('utf-8') : null

    let buffer = ''
    const processChunk = (chunk: string) => {
      buffer += chunk
      let remaining = buffer.replace(/\r\n/g, '\n')
      while (true) {
        const idx = remaining.indexOf('\n\n')
        if (idx === -1) break
        const raw = remaining.slice(0, idx)
        remaining = remaining.slice(idx + 2)
        const trimmed = raw.trim()
        if (!trimmed.startsWith('data:')) continue
        const jsonStr = trimmed.replace(/^data:\s*/, '')
        if (!jsonStr) continue
        try {
          const event = JSON.parse(jsonStr)
          if (event && typeof event.seq === 'number' && typeof event.type === 'string') {
            aiTraceEvents.value.push(event as AgentTraceEvent)
          }
        } catch (err) {
          console.warn('Failed to parse trace stream data', err, jsonStr)
        }
      }
      buffer = remaining
    }

    if (reader) {
      while (true) {
        const { value, done } = await reader.read()
        if (value) processChunk(value)
        if (done) break
      }
    } else if (binaryReader && decoder) {
      while (true) {
        const { value, done } = await binaryReader.read()
        if (value) processChunk(decoder.decode(value, { stream: !done }))
        if (done) break
      }
    }
    if (buffer.trim()) processChunk('\n\n')
  } catch (err: any) {
    if (err?.name !== 'AbortError') {
      console.warn('Failed to read trace stream', err)
    }
  } finally {
    aiTraceRunning.value = false
    if (aiTraceAbort.value === controller) aiTraceAbort.value = null
  }
}

const stopFakeProgress = () => {
  if (aiAnalysisProgressTimer.value) {
    window.clearInterval(aiAnalysisProgressTimer.value)
    aiAnalysisProgressTimer.value = null
  }
}

const startFakeProgress = () => {
  stopFakeProgress()
  aiAnalysisProgressTimer.value = window.setInterval(() => {
    if (!aiAnalysisLoading.value) return
    if (aiAnalysisProgress.value < 90) {
      aiAnalysisProgress.value = Math.min(aiAnalysisProgress.value + 5, 90)
    }
  }, 1200)
}

const fetchAIAnalysisStatus = async () => {
  if (!logStore.currentLog) return

  try {
    const response = await logApi.getAIAnalysisStatus(logStore.currentLog.id)
    if (response.success && response.data) {
      const previousStatus = aiAnalysisStatus.value
      const { status, progress, task_id, result, error, query, started_at, finished_at } = response.data
      aiAnalysisTaskId.value = task_id || null
      aiAnalysisStatus.value = status || null
      aiAnalysisError.value = error || null

      if (typeof progress === 'number') {
        aiAnalysisProgress.value = Math.max(aiAnalysisProgress.value, progress)
      }

      if (logStore.currentLog) {
        logStore.currentLog.ai_analysis_task_id = task_id
        logStore.currentLog.ai_analysis_status = status
        logStore.currentLog.ai_analysis_progress = progress
        logStore.currentLog.ai_analysis_error = error
        logStore.currentLog.ai_analysis_query = query
        logStore.currentLog.ai_analysis_started_at = started_at
        logStore.currentLog.ai_analysis_finished_at = finished_at
      }

      if (status === 'completed') {
        if (result) {
          aiAnalysisResult.value = normalizeAIAnalysisResult(result)
          if (logStore.currentLog) {
            logStore.currentLog.ai_analysis_result = result
            // 本轮分析刚完成：把新结果追加到本地对话历史，
            // 使详情页立即展示新一轮问答（后端也已持久化该轮）。
            // 仅在 completed 状态首次出现时追加，避免轮询重复入列。
            if (previousStatus !== 'completed') {
              const conv = Array.isArray(logStore.currentLog.ai_analysis_conversation)
                ? logStore.currentLog.ai_analysis_conversation
                : []
              logStore.currentLog.ai_analysis_conversation = [...conv, result]
            }
          }
          if (previousStatus !== 'completed') {
            ElMessage.success(t('logDetail.aiCompleted'))
          }
        } else {
          ElMessage.warning(t('logDetail.aiNoResult'))
        }
        aiAnalysisLoading.value = false
        aiAnalysisProgress.value = 100
        stopAIAnalysisPolling()
        stopFakeProgress()
      } else if (status === 'failed') {
        aiAnalysisLoading.value = false
        stopAIAnalysisPolling()
        stopFakeProgress()
        if (error) {
          ElMessage.error(t('logDetail.aiFailedWithError', { error }))
        } else {
          ElMessage.error(t('logDetail.aiFailed'))
        }
      } else if (status) {
        aiAnalysisLoading.value = true
      } else if (!task_id) {
        aiAnalysisLoading.value = false
        stopFakeProgress()
        stopAIAnalysisPolling()
      }
    }
  } catch (error) {
    console.error('Failed to fetch AI analysis status:', error)
  }
}

const startAIAnalysisPolling = () => {
  stopAIAnalysisPolling()
  aiAnalysisPollTimer.value = window.setInterval(fetchAIAnalysisStatus, 2000)
  fetchAIAnalysisStatus()
  startFakeProgress()
}

// AI分析提交
const handleAIAnalysisSubmit = async () => {
  if (!logStore.currentLog) return

  // 使用用户输入的查询，如果为空则使用问题描述
  const query = aiAnalysisQuery.value.trim() || logStore.currentLog.issue_description || ''
  
  if (!query) {
    ElMessage.warning(t('logDetail.aiQueryRequired'))
    return
  }

  try {
    aiAnalysisResult.value = null
    aiAnalysisLoading.value = true
    aiAnalysisProgress.value = 5
    aiAnalysisStatus.value = 'queued'
    aiAnalysisError.value = null
    aiTraceEvents.value = []
    closeTraceStream()

    const response = await logApi.analyzeLog(
      logStore.currentLog.id,
      query,
      selectedProjectRepoId.value,
    )

    if (response.success) {
      const taskId = response.data?.task_id || response.data?.taskId || null
      const status = response.data?.status || 'queued'
      aiAnalysisTaskId.value = taskId
      aiAnalysisStatus.value = status

      if (logStore.currentLog) {
        logStore.currentLog.ai_analysis_task_id = taskId
        logStore.currentLog.ai_analysis_status = status
        logStore.currentLog.ai_analysis_progress = 5
        logStore.currentLog.ai_analysis_query = query
      }

      startAIAnalysisPolling()
      ElMessage.success(t('logDetail.aiTaskStarted'))
    } else {
      throw new Error(response.message || t('logDetail.aiTaskStartFailFallback'))
    }
  } catch (error: any) {
    console.error('AI analysis failed:', error)
    stopAIAnalysisPolling()
    stopFakeProgress()
    aiAnalysisLoading.value = false
    aiAnalysisStatus.value = null
    aiAnalysisTaskId.value = null
    ElMessage.error(error.response?.data?.detail || error.message || t('logDetail.aiStartFail'))
  } finally {
    // 加载状态将在轮询或错误时关闭
  }
}

// 重置AI分析
const resetAIAnalysis = () => {
  aiAnalysisResult.value = null
  aiAnalysisQuery.value = ''
  aiAnalysisProgress.value = 0
  aiAnalysisStatus.value = null
  aiAnalysisTaskId.value = null
  aiAnalysisError.value = null
  aiAnalysisLoading.value = false
  selectedProjectRepoId.value = null
  showReasoningProcess.value = false
  showDetailedOutput.value = false
  stopAIAnalysisPolling()
  stopFakeProgress()
  closeTraceStream()
  aiTraceEvents.value = []
}

// 复制分析结果
const copyAnalysisResult = async (event?: ClipboardEvent) => {
  if (!aiAnalysisResult.value) return

  // 如果用户选中了部分内容（原生 Ctrl+C / 右键复制），放行浏览器默认行为，
  // 仅复制选中的内容，不再用完整结果覆盖剪贴板
  const selection = window.getSelection()
  if (selection && !selection.isCollapsed && selection.toString().trim()) {
    return
  }

  // 没有选区时才主动复制完整分析结果
  if (event) {
    event.preventDefault()
  }

  try {
    const resultText = `
${t('logDetail.report.query')}: ${aiAnalysisResult.value.query}

${t('logDetail.report.summary')}: ${aiAnalysisResult.value.final_result.summary}

${t('logDetail.report.details')}:
${aiAnalysisResult.value.final_result.content}

${t('logDetail.report.recommendations')}:
${aiAnalysisResult.value.final_result.recommendations.join('\n')}
    `.trim()

    const success = await copyToClipboard(resultText)
    if (success) {
      ElMessage.success(t('logDetail.reportCopied'))
    } else {
      ElMessage.error(t('logDetail.copyFail'))
    }
  } catch (error) {
    console.error('Copy failed:', error)
    ElMessage.error(t('logDetail.copyFail'))
  }
}

// 下载分析结果
const downloadAnalysisResult = () => {
  if (!aiAnalysisResult.value) return
  
  try {
    const content = `# ${t('logDetail.report.mdTitle')}

## ${t('logDetail.basicInfo')}
- ${t('logDetail.report.query')}: ${aiAnalysisResult.value.query}
- ${t('logDetail.report.mdAnalysisTime')}: ${aiAnalysisResult.value.timestamp}
- ${t('logDetail.report.mdExecTime')}: ${aiAnalysisResult.value.metadata.execution_time}${t('logDetail.report.mdSecondsSuffix')}
- ${t('logDetail.report.mdModel')}: ${aiAnalysisResult.value.metadata.model_used}

## ${t('logDetail.report.mdPlan')}
${aiAnalysisResult.value.plan.content}

## ${t('logDetail.report.mdProcess')}
${aiAnalysisResult.value.acts.map((act: any, index: number) => `
### ${t('logDetail.report.mdStep', { index: index + 1, title: act.title })}
**${t('logDetail.report.mdThought')}**
${act.thought.reasoning}

**${t('logDetail.report.mdResult')}**
${act.summary}
`).join('\n')}

## ${t('logDetail.report.mdAnalysisResult')}
### ${t('logDetail.report.summaryHeading')}
${aiAnalysisResult.value.final_result.summary}

### ${t('logDetail.report.mdDetailedAnalysis')}
${aiAnalysisResult.value.final_result.content}

### ${t('logDetail.report.recommendations')}
${aiAnalysisResult.value.final_result.recommendations.map((rec: string) => `- ${rec}`).join('\n')}
`

    const blob = new Blob([content], { type: 'text/markdown' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = t('logDetail.report.mdFilename', {
      filename: logStore.currentLog?.filename || 'unknown',
      date: new Date().toISOString().slice(0, 10),
    })
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)

    ElMessage.success(t('logDetail.reportDownloaded'))
  } catch (error) {
    console.error('Download failed:', error)
    ElMessage.error(t('logDetail.reportDownloadFail'))
  }
}

// 分享分析结果
const shareAnalysisResult = async () => {
  if (!aiAnalysisResult.value) return
  
  const shareData = {
    title: t('logDetail.report.shareTitle', { filename: logStore.currentLog?.filename }),
    text: t('logDetail.report.shareText', { summary: aiAnalysisResult.value.final_result.summary }),
    url: window.location.href
  }

  try {
    if (navigator.share && navigator.canShare && navigator.canShare(shareData)) {
      await navigator.share(shareData)
      ElMessage.success(t('logDetail.shareSuccess'))
    } else {
      // 降级到复制链接
      const copied = await copyToClipboard(window.location.href)
      if (copied) {
        ElMessage.success(t('logDetail.copyLinkSuccess'))
      } else {
        ElMessage.error(t('logDetail.copyLinkFail'))
      }
    }
  } catch (error: any) {
    if (error?.name !== 'AbortError') {
      ElMessage.error(t('logDetail.shareFail'))
    }
  }
}



// SEO优化和页面标题设置
const updatePageMeta = () => {
  if (logStore.currentLog) {
    // 设置页面标题
    document.title = pageTitle.value
    
    // 设置meta描述
    const metaDescription = document.querySelector('meta[name="description"]')
    const metaDescriptionText = t('logDetail.metaDescription', {
      filename: logStore.currentLog.filename,
      size: formatFileSize(logStore.currentLog.file_size),
      status: getStatusLabel(logStore.currentLog.status),
    })
    if (metaDescription) {
      metaDescription.setAttribute('content', metaDescriptionText)
    } else {
      const meta = document.createElement('meta')
      meta.name = 'description'
      meta.content = metaDescriptionText
      document.head.appendChild(meta)
    }

    // 设置Open Graph标签
    const setOGMeta = (property: string, content: string) => {
      let meta = document.querySelector(`meta[property="${property}"]`)
      if (meta) {
        meta.setAttribute('content', content)
      } else {
        meta = document.createElement('meta')
        meta.setAttribute('property', property)
        meta.setAttribute('content', content)
        document.head.appendChild(meta)
      }
    }

    setOGMeta('og:title', pageTitle.value)
    setOGMeta('og:description', t('logDetail.ogDescription', { filename: logStore.currentLog.filename }))
    setOGMeta('og:url', window.location.href)
    setOGMeta('og:type', 'website')
  }
}

// 监听当前日志变化，自动填入问题描述
watch(
  () => logStore.currentLog?.issue_description,
  (newIssueDescription) => {
    if (!issueDescriptionEditing.value) {
      issueDescriptionDraft.value = newIssueDescription || ''
    }
    // 只有当输入框为空且存在问题描述时才自动填入
    if (newIssueDescription && !aiAnalysisQuery.value) {
      aiAnalysisQuery.value = newIssueDescription
    }
  },
  { immediate: true }
)

watch(
  renderedManualAnalysis,
  scheduleManualAnalysisMermaidRender,
  { immediate: true, flush: 'post' }
)

// 监听AI分析结果的持久化数据，进入页面时优先展示最近一次结果
watch(
  () => logStore.currentLog?.ai_analysis_result,
  (savedResult) => {
    if (savedResult) {
      aiAnalysisResult.value = normalizeAIAnalysisResult(savedResult)
      seedTraceFromResult(savedResult)
    } else {
      aiAnalysisResult.value = null
      aiTraceEvents.value = []
    }
  },
  { immediate: true }
)

watch(
  () => ({
    status: logStore.currentLog?.ai_analysis_status,
    progress: logStore.currentLog?.ai_analysis_progress,
    taskId: logStore.currentLog?.ai_analysis_task_id,
    error: logStore.currentLog?.ai_analysis_error,
  }),
  ({ status, progress, taskId, error }) => {
    aiAnalysisStatus.value = status || null
    aiAnalysisTaskId.value = taskId || null
    aiAnalysisError.value = error || null

    if (typeof progress === 'number') {
      aiAnalysisProgress.value = progress
    } else if (!status) {
      aiAnalysisProgress.value = 0
    }

    if (status === 'queued' || status === 'running') {
      aiAnalysisLoading.value = true
      startAIAnalysisPolling()
      if (logStore.currentLog?.id) {
        // Fire-and-forget: SSE consumer runs until terminal or unmount.
        openTraceStream(logStore.currentLog.id)
      }
    } else if (status === 'completed') {
      aiAnalysisLoading.value = false
      stopAIAnalysisPolling()
      stopFakeProgress()
      aiAnalysisProgress.value = 100
      closeTraceStream()
    } else if (status === 'failed') {
      closeTraceStream()
    } else if (!status) {
      aiAnalysisLoading.value = false
      stopAIAnalysisPolling()
      stopFakeProgress()
      closeTraceStream()
    }
  },
  { immediate: true }
)

// 切换日志时，重置临时状态，等待新日志的AI分析结果填充
watch(
  () => logStore.currentLog?.id,
  () => {
    if (!logStore.currentLog?.ai_analysis_result) {
      aiAnalysisResult.value = null
    }
    aiAnalysisProgress.value = logStore.currentLog?.ai_analysis_progress || 0
    aiAnalysisStatus.value = logStore.currentLog?.ai_analysis_status || null
    aiAnalysisTaskId.value = logStore.currentLog?.ai_analysis_task_id || null
    aiAnalysisError.value = logStore.currentLog?.ai_analysis_error || null
    aiAnalysisLoading.value = false
    // 切换日志时同步重置分析输入框，避免残留上一条日志的提问
    aiAnalysisQuery.value = logStore.currentLog?.issue_description || ''
    issueDescriptionEditing.value = false
    issueDescriptionSaving.value = false
    issueDescriptionDraft.value = logStore.currentLog?.issue_description || ''
    manualAnalysisDialogVisible.value = false
    manualAnalysisForm.value.content = logStore.currentLog?.manual_analysis || ''
    manualAnalysisSaving.value = false
    stopAIAnalysisPolling()
    stopFakeProgress()
    closeTraceStream()
    aiTraceEvents.value = []
    aiTraceLogId.value = null
  }
)

onMounted(async () => {
  const id = props.id || route.params.id as string
  if (id) {
    await logStore.fetchLogDetail(id)
    updatePageMeta()
  }
  // 并行加载项目仓库下拉项，不阻塞主流程
  fetchProjectRepos()
})

onUnmounted(() => {
  stopAIAnalysisPolling()
  stopFakeProgress()
  closeTraceStream()
})
</script>

<style scoped>
.rw-page {
  /* --rw-* tokens come from src/styles/theme.css (light + dark). */
  display: flex;
  flex-direction: column;
  min-height: 100vh;
  background: var(--rw-canvas);
  color: var(--rw-ink);
  font-family: var(--rw-sans);
  font-size: 14px;
  line-height: 1.5;
  -webkit-font-smoothing: antialiased;
  text-rendering: optimizeLegibility;
}

.rw-page *,
.rw-page *::before,
.rw-page *::after { box-sizing: border-box; }

.rw-page button {
  font-family: inherit;
  cursor: pointer;
  border: none;
  background: none;
  padding: 0;
  color: inherit;
}

/* Topbar */
.rw-topbar {
  height: 56px;
  flex-shrink: 0;
  border-bottom: 1px solid var(--rw-hairline);
  display: flex;
  align-items: center;
  padding: 0 28px;
  gap: 14px;
  background: var(--rw-canvas);
  position: sticky;
  top: 0;
  z-index: 10;
}
.rw-topbar-left {
  display: flex;
  align-items: center;
  gap: 10px;
  flex: 1;
  min-width: 0;
}
.rw-topbar-right {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}
.rw-crumb {
  font-size: 14.5px;
  font-weight: 600;
  color: var(--rw-ink);
  letter-spacing: -0.1px;
  flex-shrink: 0;
}
.rw-crumb-meta {
  font-size: 12px;
  color: var(--rw-muted);
  font-family: var(--rw-mono);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  min-width: 0;
}

.back-btn {
  width: 32px;
  height: 32px;
  border-radius: 6px;
  border: 1px solid var(--rw-hairline-strong);
  background: var(--rw-canvas);
  color: var(--rw-ink);
  display: inline-grid;
  place-items: center;
  cursor: pointer;
  transition: background-color .15s ease, border-color .15s ease;
}
.back-btn:hover { background: var(--rw-surface-strong); }

/* Buttons */
.rw-page .rw-btn-primary,
.rw-page .rw-btn-secondary,
.rw-page .rw-btn-danger {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  height: 32px;
  padding: 0 14px;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 500;
  font-family: var(--rw-sans);
  cursor: pointer;
  transition: background-color .15s ease, border-color .15s ease, color .15s ease;
  white-space: nowrap;
  border: none;
  line-height: 1;
}
.rw-page .rw-btn-primary { background: var(--rw-primary); color: var(--rw-on-primary); }
.rw-page .rw-btn-primary:hover:not(:disabled) { background: var(--rw-primary-active); }
.rw-page .rw-btn-secondary {
  background: var(--rw-canvas);
  color: var(--rw-ink);
  border: 1px solid var(--rw-hairline-strong);
}
.rw-page .rw-btn-secondary:hover:not(:disabled) { background: var(--rw-surface-strong); }
.rw-page .rw-btn-danger { background: var(--rw-danger); color: #fff; }
.rw-page .rw-btn-danger:hover:not(:disabled) { background: #a02f24; }
.rw-page .rw-btn-primary:disabled,
.rw-page .rw-btn-secondary:disabled,
.rw-page .rw-btn-danger:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.rw-page .rw-btn-xs {
  height: 28px;
  padding: 0 10px;
  font-size: 12px;
  border-radius: 6px;
}

/* Pills */
.rw-pill {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  height: 22px;
  padding: 0 9px;
  border-radius: 999px;
  font-size: 11.5px;
  font-weight: 600;
  letter-spacing: 0.2px;
  white-space: nowrap;
  line-height: 1;
}
.rw-pill-success { background: rgba(22, 163, 74, 0.12); color: #15803d; }
.rw-pill-info { background: var(--rw-surface-strong); color: var(--rw-ink); }
.rw-pill-warning { background: rgba(171, 100, 0, 0.10); color: #ab6400; }
.rw-pill-danger { background: rgba(192, 56, 43, 0.10); color: #c0382b; }
.rw-pill-neutral { background: var(--rw-surface-strong); color: var(--rw-body); }
.rw-pill-preview { background: rgba(129, 69, 181, 0.10); color: #8145b5; }
.rw-pill-dot {
  width: 6px;
  height: 6px;
  border-radius: 999px;
  background: currentColor;
  animation: rw-pulse 1.2s ease-in-out infinite;
}
@keyframes rw-pulse {
  0%, 100% { opacity: 0.35; }
  50% { opacity: 1; }
}

/* Page scroll */
.rw-page-scroll {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: 24px 28px 48px;
  display: flex;
  flex-direction: column;
  gap: 20px;
  max-width: 1200px;
  margin: 0 auto;
  width: 100%;
}

.rw-card {
  background: var(--rw-surface-card);
  border: 1px solid var(--rw-hairline-strong);
  border-radius: 12px;
  padding: 24px;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.02);
}

/* Title card */
.title-card { padding: 20px 24px; }
.title-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
}
.title-left { flex: 1; min-width: 0; }
.title-name {
  font-size: 22px;
  font-weight: 600;
  letter-spacing: -0.5px;
  color: var(--rw-ink);
  margin: 0;
  word-break: break-all;
  line-height: 1.3;
}
.title-meta { margin-top: 6px; }
.title-id {
  font-family: var(--rw-mono);
  font-size: 12px;
  color: var(--rw-muted);
}
.title-tags { display: flex; gap: 8px; flex-wrap: wrap; }

/* Card head */
.card-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}
.card-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--rw-ink);
  letter-spacing: -0.1px;
  margin: 0;
}
.card-subtitle {
  font-size: 12px;
  color: var(--rw-muted);
}
.card-head-right {
  margin-left: auto;
  display: flex;
  gap: 10px;
  align-items: center;
  flex-wrap: wrap;
}

/* Info grid */
.info-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 18px 22px;
}
.info-item { display: flex; flex-direction: column; gap: 6px; min-width: 0; }
.info-item > label {
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.6px;
  color: var(--rw-muted);
  text-transform: uppercase;
}
.info-value { font-size: 13.5px; color: var(--rw-ink); word-break: break-word; }
.info-value.strong { font-weight: 600; }
.info-value.mono {
  font-family: var(--rw-mono);
  font-size: 12.5px;
  color: var(--rw-body);
}
.info-hint { font-size: 11.5px; color: var(--rw-muted); }
.info-item.col-span-all { grid-column: 1 / -1; }
.info-item-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.info-item-actions { display: flex; gap: 6px; }

.code-box {
  background: var(--rw-canvas-soft);
  border: 1px solid var(--rw-hairline);
  border-radius: 6px;
  padding: 8px 10px;
  font-family: var(--rw-mono);
  font-size: 12px;
  color: var(--rw-body);
  word-break: break-all;
  line-height: 1.5;
}

.info-block {
  padding: 12px 14px;
  border-radius: 8px;
  font-size: 13.5px;
  line-height: 1.55;
  color: var(--rw-ink);
}
.info-block.highlight {
  background: var(--rw-canvas-soft);
  border: 1px solid var(--rw-hairline);
}
.info-block.dashed {
  background: var(--rw-canvas-soft);
  border: 1px dashed var(--rw-hairline-strong);
  color: var(--rw-muted);
}
.info-block.error {
  background: rgba(192, 56, 43, 0.06);
  border: 1px solid rgba(192, 56, 43, 0.20);
  color: #c0382b;
}

.issue-edit { display: flex; flex-direction: column; gap: 6px; }

/* Meta block */
.meta-block {
  border: 1px solid var(--rw-hairline);
  background: var(--rw-canvas-soft);
  border-radius: 10px;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.meta-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px 22px;
}
.meta-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}
.meta-item.col-span-2 { grid-column: 1 / -1; }
.meta-label {
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.5px;
  color: var(--rw-muted);
  text-transform: uppercase;
}
.meta-value { font-size: 13px; color: var(--rw-ink); }
.meta-tags {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.meta-tags .tag-list { display: flex; flex-wrap: wrap; gap: 6px; }

/* Version collapse */
.version-info { margin-top: 4px; }
.version-collapse {
  border: 1px solid var(--rw-hairline-strong);
  border-radius: 10px;
  background: var(--rw-canvas);
  overflow: hidden;
}
.version-collapse :deep(.el-collapse) { border: none; }
.version-collapse :deep(.el-collapse-item__header) {
  padding: 0 14px;
  background: var(--rw-canvas);
  border-bottom: 1px solid var(--rw-hairline);
  font-weight: 600;
  color: var(--rw-ink);
  font-size: 13.5px;
  height: 44px;
}
.version-collapse :deep(.el-collapse-item__wrap) {
  background: var(--rw-canvas-soft);
  border-bottom: none;
}
.version-collapse :deep(.el-collapse-item__content) {
  padding: 16px;
  color: var(--rw-ink);
}
.version-collapse :deep(.el-collapse-item:last-child .el-collapse-item__header.is-active) {
  border-bottom: 1px solid var(--rw-hairline);
}
.version-title { display: flex; align-items: center; gap: 8px; }
.version-title-text { font-size: 13.5px; }

.version-content {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.board-info {
  background: var(--rw-canvas);
  border: 1px solid var(--rw-hairline);
  border-radius: 10px;
  padding: 14px;
}
.board-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
  gap: 10px;
  flex-wrap: wrap;
}
.board-header-left h4 {
  font-size: 14px;
  font-weight: 600;
  color: var(--rw-ink);
  margin: 0 0 2px;
  letter-spacing: -0.1px;
}
.board-header-left p {
  font-size: 12px;
  color: var(--rw-body);
  margin: 0;
  font-family: var(--rw-mono);
}
.board-details {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}
.version-section {
  padding: 12px;
  border: 1px solid var(--rw-hairline);
  border-radius: 8px;
  background: var(--rw-canvas-soft);
}
.version-section h5 {
  font-size: 12.5px;
  font-weight: 600;
  color: var(--rw-ink);
  margin: 0 0 8px;
  letter-spacing: 0.1px;
}
.kv-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.kv {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  font-size: 12.5px;
  align-items: center;
}
.kv > span:first-child { color: var(--rw-body); }
.kv > span:last-child { color: var(--rw-ink); }
.kv .mono {
  font-family: var(--rw-mono);
  font-size: 12px;
}
.kv .mono.strong { font-weight: 600; }

/* AI analysis card */
.analysis-input { display: flex; flex-direction: column; gap: 12px; }
.analysis-hint { font-size: 13px; color: var(--rw-body); margin: 0; }
.analysis-actions { display: flex; gap: 8px; }
.analysis-project-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px 12px;
  padding: 8px 0 0;
}
.analysis-project-label {
  font-size: 13px;
  font-weight: 500;
  color: var(--rw-ink);
  flex-shrink: 0;
}
.analysis-project-select { min-width: 280px; flex: 0 0 auto; }
.analysis-project-hint {
  font-size: 12px;
  color: var(--rw-muted);
  flex: 1 1 100%;
}

.analysis-trace { margin: 12px 0; }

/* 多轮分析历史：相邻轮次之间留出间距 */
.analysis-turn + .analysis-turn { margin-top: 16px; }

.analysis-loading {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 12px 0;
}
.loading-row {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 14px;
  color: var(--rw-body);
}
.loader-dot {
  width: 10px;
  height: 10px;
  border-radius: 999px;
  background: var(--rw-ink);
  animation: rw-pulse 1.1s ease-in-out infinite;
}
.loading-meta {
  font-size: 12px;
  color: var(--rw-muted);
  font-family: var(--rw-mono);
}
.loading-task { margin-left: 12px; }

/* Manual analysis */
.manual-analysis-body {
  font-size: 14px;
  color: var(--rw-ink);
  line-height: 1.65;
}
.manual-analysis-body :deep(h1),
.manual-analysis-body :deep(h2),
.manual-analysis-body :deep(h3),
.manual-analysis-body :deep(h4) {
  color: var(--rw-ink);
  font-weight: 600;
  letter-spacing: -0.2px;
  margin-top: 1.2em;
  margin-bottom: 0.6em;
}
.manual-analysis-body :deep(p) { margin: 0.6em 0; }
.manual-analysis-body :deep(code) {
  font-family: var(--rw-mono);
  background: var(--rw-canvas-soft);
  border: 1px solid var(--rw-hairline);
  border-radius: 4px;
  padding: 1px 6px;
  font-size: 12.5px;
}
.manual-analysis-body :deep(pre) {
  background: var(--rw-surface-dark);
  color: var(--rw-on-primary);
  padding: 14px 16px;
  border-radius: 10px;
  overflow-x: auto;
  font-family: var(--rw-mono);
  font-size: 12.5px;
  line-height: 1.55;
}
.manual-analysis-body :deep(pre code) {
  background: transparent;
  border: none;
  padding: 0;
  color: inherit;
  font-size: inherit;
}
.manual-analysis-body :deep(a) { color: var(--rw-link); }
.manual-analysis-body :deep(ul),
.manual-analysis-body :deep(ol) { padding-left: 1.4em; }

.manual-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  padding: 28px 0;
}
.manual-empty p {
  font-size: 13px;
  color: var(--rw-muted);
  margin: 0;
}

/* Actions grid */
.actions-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
}
.actions-grid > button {
  width: 100%;
  height: 40px;
}

.not-found {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 60vh;
}
.not-found :deep(.el-result__title) { color: var(--rw-ink); }
.not-found :deep(.el-result__subtitle) { color: var(--rw-muted); }

.dialog-footer {
  display: flex;
  gap: 8px;
  justify-content: flex-end;
}

/* Element Plus overrides */
.rw-page :deep(.el-input__wrapper),
.rw-page :deep(.el-textarea__inner) {
  background: var(--rw-canvas) !important;
  border: 1px solid var(--rw-hairline-strong) !important;
  border-radius: 8px !important;
  box-shadow: none !important;
}
.rw-page :deep(.el-textarea__inner) {
  padding: 10px 12px;
  font-family: var(--rw-sans);
  font-size: 13.5px;
  color: var(--rw-ink);
  line-height: 1.55;
}
.rw-page :deep(.el-textarea__inner:focus),
.rw-page :deep(.el-input__wrapper.is-focus) {
  border-color: var(--rw-ink) !important;
  box-shadow: none !important;
}
.rw-page :deep(.el-input__inner) {
  color: var(--rw-ink);
  font-family: var(--rw-sans);
  font-size: 13.5px;
}
.rw-page :deep(.el-input__inner::placeholder),
.rw-page :deep(.el-textarea__inner::placeholder) { color: var(--rw-muted); }

.rw-page :deep(.el-progress-bar__outer) { background: var(--rw-hairline) !important; }
.rw-page :deep(.el-progress-bar__inner) { background: var(--rw-ink) !important; }
.rw-page :deep(.el-progress--success .el-progress-bar__inner) { background: var(--rw-success) !important; }
.rw-page :deep(.el-progress__text) { color: var(--rw-body) !important; font-size: 12px !important; }

.rw-page :deep(.el-skeleton__item) { background: var(--rw-surface-strong); }

/* Dialog */
:deep(.el-dialog) {
  border-radius: 12px;
  overflow: hidden;
  border: 1px solid var(--rw-hairline-strong);
  box-shadow: 0 8px 28px rgba(0, 0, 0, 0.12);
}
:deep(.el-dialog__header) {
  padding: 16px 20px;
  margin: 0;
  border-bottom: 1px solid var(--rw-hairline);
}
:deep(.el-dialog__title) {
  color: #171717;
  font-weight: 600;
  font-size: 15px;
}
:deep(.el-dialog__body) {
  padding: 20px;
  color: #171717;
}
:deep(.el-dialog__footer) {
  padding: 12px 20px;
  border-top: 1px solid #f0f0f3;
}
:deep(.el-form-item__label) {
  color: #60646c;
  font-size: 12.5px;
  font-weight: 500;
}

/* Responsive */
@media (max-width: 1024px) {
  .info-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .meta-grid { grid-template-columns: 1fr; }
  .actions-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (max-width: 768px) {
  .rw-topbar { padding: 0 16px; }
  .rw-page-scroll { padding: 16px 16px 32px; gap: 14px; }
  .rw-card { padding: 18px; }
  .info-grid { grid-template-columns: 1fr; gap: 14px; }
  .board-details { grid-template-columns: 1fr; }
  .actions-grid { grid-template-columns: 1fr; }
  .title-name { font-size: 18px; }
  .card-head-right { width: 100%; }
}
</style>

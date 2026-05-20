<template>
  <div class="rw-page log-detail-page">
    <header class="rw-topbar">
      <div class="rw-topbar-left">
        <button class="back-btn" @click="$router.back()" title="返回">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
            <path d="M15 18l-6-6 6-6" />
          </svg>
        </button>
        <span class="rw-crumb">日志详情</span>
        <span v-if="logStore.currentLog" class="rw-crumb-meta">· {{ logStore.currentLog.filename }}</span>
      </div>
      <div class="rw-topbar-right">
        <button class="rw-btn-secondary" @click="handleCopyLink">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
            <rect x="9" y="9" width="13" height="13" rx="2" ry="2"/>
            <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>
          </svg>
          <span>复制链接</span>
        </button>
        <button class="rw-btn-primary" :disabled="downloadLoading || !logStore.currentLog" @click="handleDownload">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
            <polyline points="7 10 12 15 17 10" />
            <line x1="12" y1="15" x2="12" y2="3" />
          </svg>
          <span>{{ downloadLoading ? '下载中…' : '下载' }}</span>
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
              <span :class="['rw-pill', logTypePill(logStore.currentLog.log_type)]">
                {{ getLogTypeLabel(logStore.currentLog.log_type) }}
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
            <h2 class="card-title">基本信息</h2>
          </div>
          <div class="info-grid">
            <div class="info-item">
              <label>文件名</label>
              <div class="info-value mono">{{ logStore.currentLog.filename }}</div>
            </div>
            <div class="info-item" v-if="logStore.currentLog.original_filename">
              <label>原始文件名</label>
              <div class="info-value">{{ logStore.currentLog.original_filename }}</div>
            </div>
            <div class="info-item">
              <label>文件大小</label>
              <div class="info-value strong">{{ formatFileSize(logStore.currentLog.file_size) }}</div>
            </div>
            <div class="info-item">
              <label>创建时间</label>
              <div class="info-value mono">{{ formatDateTime(logStore.currentLog.created_at) }}</div>
            </div>
            <div class="info-item">
              <label>处理状态</label>
              <div>
                <span :class="['rw-pill', statusPill(logStore.currentLog.status)]">
                  {{ getStatusLabel(logStore.currentLog.status) }}
                </span>
              </div>
            </div>
            <div class="info-item">
              <label>下载次数</label>
              <div class="info-value strong">{{ logStore.currentLog.download_count }}</div>
            </div>

            <div
              class="info-item col-span-all"
              v-if="(logStore.currentLog.log_type === 'stack' || logStore.currentLog.log_type === 'full') && logStore.currentLog.status === 'processing'"
            >
              <label>处理进度</label>
              <el-progress
                :percentage="logStore.currentLog.progress || 0"
                :status="logStore.currentLog.progress === 100 ? 'success' : undefined"
                :stroke-width="8"
              />
              <div class="info-hint">{{ logStore.currentLog.progress || 0 }}% 完成</div>
            </div>

            <div class="info-item col-span-all" v-if="logStore.currentLog.checksum">
              <label>文件校验和 (SHA256)</label>
              <div class="code-box">{{ logStore.currentLog.checksum }}</div>
            </div>

            <div class="info-item" v-if="logStore.currentLog.task_id">
              <label>任务 ID</label>
              <div class="code-box">{{ logStore.currentLog.task_id }}</div>
            </div>

            <div class="info-item" v-if="logStore.currentLog.retry_count !== undefined && logStore.currentLog.retry_count > 0">
              <label>重试次数</label>
              <div class="info-value strong">{{ logStore.currentLog.retry_count }}</div>
            </div>

            <!-- 问题描述 -->
            <div class="info-item col-span-all">
              <div class="info-item-head">
                <label>问题描述</label>
                <div class="info-item-actions">
                  <button v-if="issueDescriptionEditing" class="rw-btn-secondary rw-btn-xs" @click="cancelIssueDescriptionEdit">取消</button>
                  <button
                    class="rw-btn-primary rw-btn-xs"
                    :disabled="issueDescriptionSaving"
                    @click="issueDescriptionEditing ? handleSaveIssueDescription() : startEditIssueDescription()"
                  >
                    {{ issueDescriptionEditing ? '保存' : (logStore.currentLog?.issue_description ? '编辑' : '添加') }}
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
                  placeholder="描述日志涉及的问题，便于AI分析和人工排查"
                />
                <div class="info-hint">留空后保存可清除问题描述</div>
              </div>
              <div v-else>
                <div v-if="logStore.currentLog.issue_description" class="info-block highlight">{{ logStore.currentLog.issue_description }}</div>
                <div v-else class="info-block dashed">暂无问题描述</div>
              </div>
            </div>

            <!-- 错误信息 -->
            <div class="info-item col-span-all" v-if="logStore.currentLog.error_message">
              <label>错误信息</label>
              <div class="info-block error">{{ logStore.currentLog.error_message }}</div>
            </div>

            <!-- 元数据 -->
            <div class="info-item col-span-all" v-if="logStore.currentLog.metadata && hasMetadata(logStore.currentLog.metadata)">
              <label>元数据信息</label>
              <div class="meta-block">
                <div class="meta-grid">
                  <div v-if="logStore.currentLog.metadata.source" class="meta-item">
                    <span class="meta-label">日志来源</span>
                    <span class="meta-value">{{ logStore.currentLog.metadata.source }}</span>
                  </div>
                  <div v-if="logStore.currentLog.metadata.environment" class="meta-item">
                    <span class="meta-label">环境信息</span>
                    <span class="meta-value">{{ logStore.currentLog.metadata.environment }}</span>
                  </div>
                  <div v-if="logStore.currentLog.metadata.service_name" class="meta-item">
                    <span class="meta-label">研发分析</span>
                    <span class="meta-value">{{ logStore.currentLog.metadata.service_name }}</span>
                  </div>
                  <div
                    v-if="logStore.currentLog.metadata.version_info || logStore.currentLog.metadata.version"
                    class="meta-item col-span-2"
                  >
                    <span class="meta-label">版本信息</span>
                    <div
                      v-if="logStore.currentLog.metadata.version_info && logStore.currentLog.metadata.version_info.raw_content"
                      class="version-info"
                    >
                      <el-collapse v-model="activeVersionCollapse" class="version-collapse">
                        <el-collapse-item name="version-details">
                          <template #title>
                            <div class="version-title">
                              <span class="version-title-text">GNB 系统组件版本详情</span>
                              <span class="rw-pill rw-pill-info">{{ getVersionBoardCount(logStore.currentLog.metadata.version_info.raw_content) }} 个板卡</span>
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
                                  {{ board.type === 'main' ? '主控板' : '子板' }}
                                </span>
                              </div>
                              <div class="board-details">
                                <div v-if="board.oamVersion" class="version-section">
                                  <h5>OAM 版本</h5>
                                  <div class="kv-list">
                                    <div class="kv"><span>版本号</span><span class="mono">{{ board.oamVersion.version }}</span></div>
                                    <div class="kv"><span>Git 版本</span><span class="mono">{{ board.oamVersion.gitVersion }}</span></div>
                                    <div class="kv"><span>分支</span><span class="mono">{{ board.oamVersion.branch }}</span></div>
                                    <div class="kv"><span>构建时间</span><span class="mono">{{ board.oamVersion.buildTime }}</span></div>
                                  </div>
                                </div>
                                <div v-if="board.protocolVersion" class="version-section">
                                  <h5>协议栈版本</h5>
                                  <div class="kv-list">
                                    <div v-if="board.protocolVersion.cucp" class="kv"><span>CUCP 版本</span><span class="mono">{{ board.protocolVersion.cucp }}</span></div>
                                    <div v-if="board.protocolVersion.cuup" class="kv"><span>CUUP 版本</span><span class="mono">{{ board.protocolVersion.cuup }}</span></div>
                                    <div v-if="board.protocolVersion.du" class="kv"><span>DU 版本</span><span class="mono">{{ board.protocolVersion.du }}</span></div>
                                    <template v-if="board.protocolVersion.extra && board.protocolVersion.extra.length">
                                      <div v-for="(item, idx) in board.protocolVersion.extra" :key="idx" class="kv">
                                        <span>{{ item.key }}</span><span class="mono">{{ item.value }}</span>
                                      </div>
                                    </template>
                                    <div v-if="board.protocolVersion.status" class="kv">
                                      <span>状态</span>
                                      <span :class="['rw-pill', board.protocolVersion.status === 'Not applicable for this SOM type' ? 'rw-pill-info' : 'rw-pill-success']">
                                        {{ board.protocolVersion.status }}
                                      </span>
                                    </div>
                                  </div>
                                </div>
                                <div v-if="board.fpgaVersion" class="version-section">
                                  <h5>FPGA 版本</h5>
                                  <span class="rw-pill rw-pill-warning">{{ board.fpgaVersion }}</span>
                                </div>
                                <div v-if="board.componentCount" class="version-section">
                                  <h5>组件信息</h5>
                                  <div class="kv"><span>组件数量</span><span class="mono strong">{{ board.componentCount }}</span></div>
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
                  <span class="meta-label">标签</span>
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
            <h2 class="card-title">AI 分析</h2>
            <span class="card-subtitle">结果将自动保存，刷新或再次访问时可直接查看</span>
            <span
              v-if="aiAnalysisResult"
              :class="['rw-pill', aiAnalysisResult.status === 'completed' ? 'rw-pill-success' : 'rw-pill-warning']"
            >
              {{ aiAnalysisResult.status === 'completed' ? '已完成' : '部分完成' }}
            </span>
          </div>

          <div v-if="!aiAnalysisLoading && !aiAnalysisResult" class="analysis-input">
            <p class="analysis-hint">
              {{ logStore.currentLog.issue_description
                ? '已自动填入问题描述，您可以直接分析或修改查询内容'
                : '请输入您想要分析的问题，AI 将为您提供详细的分析结果' }}
            </p>
            <el-input
              v-model="aiAnalysisQuery"
              type="textarea"
              :rows="3"
              :placeholder="logStore.currentLog.issue_description
                ? '已自动填入问题描述，您可以修改或直接开始分析...'
                : '例如：分析所有错误日志、查找天线异常、统计告警信息等...'"
            />
            <div class="analysis-actions">
              <button class="rw-btn-primary" @click="handleAIAnalysisSubmit">开始分析</button>
              <button class="rw-btn-secondary" @click="aiAnalysisQuery = ''">清空</button>
            </div>
          </div>

          <div v-if="aiAnalysisLoading" class="analysis-loading">
            <div class="loading-row">
              <span class="loader-dot"></span>
              <span>AI 正在分析日志，请稍候…</span>
            </div>
            <el-progress :percentage="aiAnalysisProgress" :stroke-width="8" />
            <div class="loading-meta">
              当前状态：{{ aiAnalysisStatus || '运行中' }}
              <span v-if="aiAnalysisTaskId" class="loading-task">任务ID: {{ aiAnalysisTaskId }}</span>
            </div>
          </div>

          <AgentTraceStream
            v-if="aiTraceEvents.length > 0 || aiTraceRunning"
            class="analysis-trace"
            :events="aiTraceEvents"
            :running="aiTraceRunning"
          />

          <AIAnalysisResult
            v-if="aiAnalysisResult"
            :result="aiAnalysisResult"
            @restart="resetAIAnalysis"
            @copy="copyAnalysisResult"
            @download="downloadAnalysisResult"
            @share="shareAnalysisResult"
          />
        </section>

        <!-- 人工分析 -->
        <section class="rw-card">
          <div class="card-head">
            <h2 class="card-title">人工分析</h2>
            <div class="card-head-right">
              <span v-if="logStore.currentLog?.manual_analysis_updated_at" class="card-subtitle">
                最近更新：{{ formatDateTime(logStore.currentLog.manual_analysis_updated_at) }}
              </span>
              <button class="rw-btn-secondary rw-btn-xs" @click="openManualAnalysisDialog">
                {{ logStore.currentLog?.manual_analysis ? '编辑' : '添加' }}人工分析
              </button>
            </div>
          </div>
          <div
            v-if="logStore.currentLog?.manual_analysis"
            class="manual-analysis-body"
            v-html="renderedManualAnalysis"
          />
          <div v-else class="manual-empty">
            <p>暂无人工分析内容</p>
            <button class="rw-btn-primary rw-btn-xs" @click="openManualAnalysisDialog">添加人工分析</button>
          </div>
        </section>

        <!-- 操作 -->
        <section class="rw-card">
          <div class="card-head">
            <h2 class="card-title">操作</h2>
          </div>
          <div class="actions-grid">
            <button class="rw-btn-primary" :disabled="downloadLoading" @click="handleDownload">
              {{ downloadLoading ? '下载中…' : '下载文件' }}
            </button>
            <button class="rw-btn-secondary" @click="openManualAnalysisDialog">人工分析</button>
            <button class="rw-btn-secondary" @click="handleCopyLink">复制链接</button>
            <button class="rw-btn-danger" :disabled="deleteLoading" @click="handleDelete">
              {{ deleteLoading ? '删除中…' : '删除文件' }}
            </button>
          </div>
        </section>
      </template>

      <div v-else class="not-found">
        <el-result icon="warning" title="文件不存在" sub-title="请检查文件ID是否正确，或文件可能已被删除">
          <template #extra>
            <button class="rw-btn-primary" @click="$router.push('/logs')">返回列表</button>
          </template>
        </el-result>
      </div>
    </div>

    <!-- 人工分析录入弹窗 -->
    <el-dialog
      v-model="manualAnalysisDialogVisible"
      title="录入人工分析"
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
        <el-form-item label="分析结果（支持 Markdown）" prop="content">
          <el-input
            v-model="manualAnalysisForm.content"
            type="textarea"
            :autosize="{ minRows: 6, maxRows: 14 }"
            maxlength="5000"
            show-word-limit
            placeholder="记录对日志的人工分析结论、影响范围与处理建议，支持 Markdown 格式。"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <span class="dialog-footer">
          <button class="rw-btn-secondary" @click="manualAnalysisDialogVisible = false">取消</button>
          <button class="rw-btn-primary" :disabled="manualAnalysisSaving" @click="handleSaveManualAnalysis">保存</button>
        </span>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, onUnmounted, ref, computed, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessageBox, ElMessage } from 'element-plus'
import type { FormInstance } from 'element-plus'
import { useLogStore } from '../stores/logs'
import { 
  formatFileSize, 
  formatDateTime,
  downloadFile 
} from '../utils'
import { logApi } from '../api'
import { API_BASE_URL } from '../api'
import AIAnalysisResult from '../components/AIAnalysisResult.vue'
import AgentTraceStream from '../components/AgentTraceStream.vue'
import type { AgentTraceEvent } from '../types/agentTrace'
import { useUserStore } from '../stores/user'
import { renderMarkdown } from '../utils/markdownRenderer'

interface Props {
  id: string
}

const props = defineProps<Props>()
const route = useRoute()
const router = useRouter()
const logStore = useLogStore()
const userStore = useUserStore()

// 响应式变量
const downloadLoading = ref(false)
const deleteLoading = ref(false)
const activeVersionCollapse = ref(['version-details'])
const issueDescriptionEditing = ref(false)
const issueDescriptionSaving = ref(false)
const issueDescriptionDraft = ref('')
const manualAnalysisDialogVisible = ref(false)
const manualAnalysisSaving = ref(false)
const manualAnalysisFormRef = ref<FormInstance>()
const manualAnalysisForm = ref({
  content: ''
})
const manualAnalysisRules = {
  content: [
    { required: true, message: '请输入人工分析内容', trigger: 'blur' },
    {
      validator: (_rule: any, value: string, callback: (error?: Error) => void) => {
        if (!value || !value.trim()) {
          callback(new Error('请输入人工分析内容'))
        } else {
          callback()
        }
      },
      trigger: 'blur'
    },
    { min: 5, message: '请至少输入5个字符', trigger: 'blur' }
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

const normalizeAIAnalysisResult = (raw: any) => {
  // 临时调试：打印后端返回的原始 ai_analysis_result 结构
  // 用于核对 V2 扁平 schema 字段（model / duration_seconds / summary / raw / ...）
  // 是否被前端正确读取。验证完后可删除。
  try {
    console.log('[AI-Analysis] normalizeAIAnalysisResult input:', {
      type: typeof raw,
      isObject: raw && typeof raw === 'object',
      keys: raw && typeof raw === 'object' ? Object.keys(raw) : null,
      schema_version: raw?.schema_version,
      status: raw?.status,
      model: raw?.model,
      duration_seconds: raw?.duration_seconds,
      has_raw_field: typeof raw?.raw === 'string',
      raw_length: typeof raw?.raw === 'string' ? raw.raw.length : -1,
      has_summary: !!raw?.summary,
      has_final_result: !!raw?.final_result,
      sample: raw,
    })
  } catch (e) {
    console.warn('[AI-Analysis] debug log failed:', e)
  }

  if (!raw) return null

  if (typeof raw === 'string') {
    return {
      id: `analysis_${Date.now()}`,
      query: aiAnalysisQuery.value || logStore.currentLog?.issue_description || '',
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
    root_cause: '根因分析',
    qa: '问答',
    search: '检索',
    stats: '统计',
    meta: '元信息',
    other: '其他',
  }

  const buildV2Markdown = (r: any): string => {
    const parts: string[] = []
    const qType: string = typeof r?.question_type === 'string' ? r.question_type : ''
    const isRootCause = qType === 'root_cause'

    // 主回答优先 —— V3 新增 answer 字段直接回应用户问题
    const answer: string = typeof r?.answer === 'string' ? r.answer.trim() : ''
    if (answer) {
      const label = QUESTION_TYPE_LABEL[qType] || '回答'
      parts.push(`## 回答（${label}）\n\n${answer}`)
    }

    // summary 与 answer 不重复时再展示
    const summary: string = typeof r?.summary === 'string' ? r.summary.trim() : ''
    if (summary && summary !== answer) {
      parts.push(`## 摘要\n\n${summary}`)
    }

    // 根因假设：只在 root_cause 且数组非空时显示
    if (isRootCause && Array.isArray(r?.root_cause_hypotheses) && r.root_cause_hypotheses.length) {
      const items = r.root_cause_hypotheses
        .map((h: any) => (typeof h === 'string' ? h : (h?.hypothesis || h?.description || JSON.stringify(h))))
        .map((s: string) => `- ${s}`).join('\n')
      parts.push(`## 根因假设\n\n${items}`)
    }
    // 旧 schema 兼容：没有 question_type 字段时按老行为渲染
    if (!qType && Array.isArray(r?.root_cause_hypotheses) && r.root_cause_hypotheses.length) {
      const items = r.root_cause_hypotheses
        .map((h: any) => (typeof h === 'string' ? h : (h?.hypothesis || h?.description || JSON.stringify(h))))
        .map((s: string) => `- ${s}`).join('\n')
      parts.push(`## 根因假设\n\n${items}`)
    }

    if (Array.isArray(r?.recommended_actions) && r.recommended_actions.length) {
      const items = r.recommended_actions
        .map((a: any) => (typeof a === 'string' ? a : (a?.action || a?.description || JSON.stringify(a))))
        .map((s: string) => `- ${s}`).join('\n')
      parts.push(`## 建议\n\n${items}`)
    }
    if (Array.isArray(r?.related_keywords) && r.related_keywords.length) {
      parts.push(`## 关键词\n\n${r.related_keywords.map((k: string) => `\`${k}\``).join(' ')}`)
    }
    // 兜底：模型原始文本（含 fenced JSON 之外的解释性内容）
    if (parts.length === 0 && typeof r?.raw === 'string' && r.raw.trim()) {
      return r.raw
    }
    if (typeof r?.raw === 'string' && r.raw.trim()) {
      parts.push(`## 模型原文\n\n${r.raw}`)
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
    // V3：优先使用直接回答用户问题的 answer 字段作为概览
    summary = (raw?.answer && String(raw.answer).trim())
      || raw?.summary
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
      (firstNonEmptyLine ? firstNonEmptyLine.replace(/^#+\s*/, '').slice(0, 200) : '分析完成')
    executionTime = Number(raw?.metadata?.execution_time ?? 0)
    modelUsed = raw?.metadata?.model_used || 'unknown'
    recommendations = Array.isArray(raw?.final_result?.recommendations) ? raw.final_result.recommendations : []
  }

  // 状态归一化：V2 的 "ok" 应映射为前端的 "completed"
  const rawStatus = raw?.status
  const normalizedStatus =
    rawStatus === 'ok' ? 'completed' :
    rawStatus === 'error' ? 'failed' :
    (rawStatus || 'completed')

  return {
    ...raw,
    id: raw?.id || `analysis_${Date.now()}`,
    query: raw?.query || aiAnalysisQuery.value || logStore.currentLog?.issue_description || '',
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

// 示例查询
const exampleQueries = [
  '分析所有错误日志',
  '查找天线异常',
  '统计告警信息',
  '分析系统性能问题',
  '查找连接失败原因'
]

// 计算属性
const pageTitle = computed(() => {
  if (logStore.currentLog) {
    return `${logStore.currentLog.filename} - 日志详情`
  }
  return '日志详情'
})

const renderedManualAnalysis = computed(() => {
  const content = logStore.currentLog?.manual_analysis
  if (!content) return ''
  return renderMarkdown(content, { wrapperClass: 'markdown-content', cleanXml: true })
})

// 日志类型对应的 pill 样式
const logTypePill = (logType?: string) => {
  switch (logType) {
    case 'stack':
      return 'rw-pill-success'
    case 'oam_antenna':
      return 'rw-pill-info'
    case 'full':
      return 'rw-pill-warning'
    default:
      return 'rw-pill-neutral'
  }
}

// 获取日志类型标签文本
const getLogTypeLabel = (logType?: string) => {
  switch (logType) {
    case 'stack':
      return '协议栈日志'
    case 'oam_antenna':
      return 'OAM天线日志'
    case 'full':
      return '全量日志'
    default:
      return '未知类型'
  }
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
      return '处理完成'
    case 'processing':
      return '处理中'
    case 'failed':
      return '处理失败'
    case 'pending':
      return '等待处理'
    default:
      return '未知状态'
  }
}


// 检查是否有元数据内容
const hasMetadata = (metadata: any) => {
  if (!metadata || typeof metadata !== 'object') return false
  
  return !!(
    metadata.source ||
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
    downloadFile(downloadUrl, logStore.currentLog.filename)
    ElMessage.success(`文件 ${logStore.currentLog.filename} 已开始下载`)
    
    // 异步更新下载次数，不影响下载体验
    try {
      const response = await logApi.incrementDownloadCount(logStore.currentLog.id)
      // 更新本地下载次数
      if (logStore.currentLog && response.data?.data?.download_count) {
        logStore.currentLog.download_count = response.data.data.download_count
      }
    } catch (error) {
      // 忽略计数更新失败，不影响用户体验
      console.warn('下载计数更新失败:', error)
    }
  } catch (error) {
    ElMessage.error('文件下载失败，请稍后重试')
  } finally {
    downloadLoading.value = false
  }
}

// 删除文件
const handleDelete = async () => {
  if (!logStore.currentLog) return

  try {
    await ElMessageBox.confirm(
      `确定要删除文件 "${logStore.currentLog.filename}" 吗？此操作不可恢复。`,
      '确认删除',
      {
        confirmButtonText: '确定删除',
        cancelButtonText: '取消',
        type: 'warning',
        dangerouslyUseHTMLString: false,
      }
    )

    deleteLoading.value = true
    await logStore.deleteLog(logStore.currentLog.id)
    ElMessage.success(`文件 ${logStore.currentLog.filename} 已删除`)
    router.push('/logs')
  } catch (error) {
    if (error !== 'cancel') {
      ElMessage.error('文件删除失败，请稍后重试')
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
      ElMessage.success(updatedDescription ? '问题描述已更新' : '问题描述已清除')
    } else {
      throw new Error(response.message || '问题描述更新失败')
    }
  } catch (error: any) {
    console.error('更新问题描述失败:', error)
    ElMessage.error(error.response?.data?.detail || error.message || '问题描述更新失败')
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
      ElMessage.success('人工分析已保存')
      manualAnalysisDialogVisible.value = false
    } else {
      throw new Error(response.message || '保存失败')
    }
  } catch (error: any) {
    console.error('保存人工分析失败:', error)
    ElMessage.error(error.response?.data?.detail || error.message || '保存人工分析失败')
  } finally {
    manualAnalysisSaving.value = false
  }
}

// 复制链接
const handleCopyLink = async () => {
  try {
    await navigator.clipboard.writeText(window.location.href)
    ElMessage.success('链接已复制到剪贴板')
  } catch (error) {
    // 降级方案
    const textArea = document.createElement('textarea')
    textArea.value = window.location.href
    document.body.appendChild(textArea)
    textArea.select()
    try {
      document.execCommand('copy')
      ElMessage.success('链接已复制到剪贴板')
    } catch (err) {
      ElMessage.error('复制失败，请手动复制链接')
    }
    document.body.removeChild(textArea)
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
          console.warn('解析 trace 流数据失败', err, jsonStr)
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
      console.warn('trace 流读取失败', err)
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
          }
          if (previousStatus !== 'completed') {
            ElMessage.success('AI分析完成')
          }
        } else {
          ElMessage.warning('AI分析已结束，但未返回结果')
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
          ElMessage.error(`AI分析失败: ${error}`)
        } else {
          ElMessage.error('AI分析失败，请稍后重试')
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
    console.error('获取AI分析状态失败:', error)
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
    ElMessage.warning('请输入分析查询内容或在上传时提供问题描述')
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

    const response = await logApi.analyzeLog(logStore.currentLog.id, query)

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
      ElMessage.success('AI分析任务已启动，完成后结果会自动保存')
    } else {
      throw new Error(response.message || 'AI分析任务启动失败')
    }
  } catch (error: any) {
    console.error('AI分析失败:', error)
    stopAIAnalysisPolling()
    stopFakeProgress()
    aiAnalysisLoading.value = false
    aiAnalysisStatus.value = null
    aiAnalysisTaskId.value = null
    ElMessage.error(error.response?.data?.detail || error.message || 'AI分析启动失败，请稍后重试')
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
  showReasoningProcess.value = false
  showDetailedOutput.value = false
  stopAIAnalysisPolling()
  stopFakeProgress()
  closeTraceStream()
  aiTraceEvents.value = []
}

// 复制分析结果
const copyAnalysisResult = async () => {
  if (!aiAnalysisResult.value) return
  
  try {
    const resultText = `
查询: ${aiAnalysisResult.value.query}

摘要: ${aiAnalysisResult.value.final_result.summary}

详细结果:
${aiAnalysisResult.value.final_result.content}

推荐建议:
${aiAnalysisResult.value.final_result.recommendations.join('\n')}
    `.trim()
    
    await navigator.clipboard.writeText(resultText)
    ElMessage.success('分析结果已复制到剪贴板')
  } catch (error) {
    console.error('复制失败:', error)
    ElMessage.error('复制失败，请手动复制')
  }
}

// 下载分析结果
const downloadAnalysisResult = () => {
  if (!aiAnalysisResult.value) return
  
  try {
    const content = `# AI日志分析报告

## 基本信息
- 查询: ${aiAnalysisResult.value.query}
- 分析时间: ${aiAnalysisResult.value.timestamp}
- 执行时长: ${aiAnalysisResult.value.metadata.execution_time}秒
- 使用模型: ${aiAnalysisResult.value.metadata.model_used}

## 执行计划
${aiAnalysisResult.value.plan.content}

## 执行过程
${aiAnalysisResult.value.acts.map((act, index) => `
### 步骤 ${index + 1}: ${act.title}
**思考过程:**
${act.thought.reasoning}

**执行结果:**
${act.summary}
`).join('\n')}

## 分析结果
### 摘要
${aiAnalysisResult.value.final_result.summary}

### 详细分析
${aiAnalysisResult.value.final_result.content}

### 推荐建议
${aiAnalysisResult.value.final_result.recommendations.map(rec => `- ${rec}`).join('\n')}
`
    
    const blob = new Blob([content], { type: 'text/markdown' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `AI分析报告_${logStore.currentLog?.filename || 'unknown'}_${new Date().toISOString().slice(0, 10)}.md`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
    
    ElMessage.success('分析报告已下载')
  } catch (error) {
    console.error('下载失败:', error)
    ElMessage.error('下载失败，请稍后重试')
  }
}

// 分享分析结果
const shareAnalysisResult = async () => {
  if (!aiAnalysisResult.value) return
  
  const shareData = {
    title: `AI日志分析结果 - ${logStore.currentLog?.filename}`,
    text: `查看AI分析结果：${aiAnalysisResult.value.final_result.summary}`,
    url: window.location.href
  }
  
  try {
    if (navigator.share && navigator.canShare && navigator.canShare(shareData)) {
      await navigator.share(shareData)
      ElMessage.success('分享成功')
    } else {
      // 降级到复制链接
      await navigator.clipboard.writeText(window.location.href)
      ElMessage.success('链接已复制到剪贴板')
    }
  } catch (error: any) {
    if (error?.name !== 'AbortError') {
      ElMessage.error('分享失败，请稍后重试')
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
    if (metaDescription) {
      metaDescription.setAttribute('content', 
        `查看日志文件 ${logStore.currentLog.filename} 的详细信息，文件大小 ${formatFileSize(logStore.currentLog.file_size)}，状态 ${getStatusLabel(logStore.currentLog.status)}`
      )
    } else {
      const meta = document.createElement('meta')
      meta.name = 'description'
      meta.content = `查看日志文件 ${logStore.currentLog.filename} 的详细信息，文件大小 ${formatFileSize(logStore.currentLog.file_size)}，状态 ${getStatusLabel(logStore.currentLog.status)}`
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
    setOGMeta('og:description', `查看日志文件详情 - ${logStore.currentLog.filename}`)
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
})

onUnmounted(() => {
  stopAIAnalysisPolling()
  stopFakeProgress()
  closeTraceStream()
})
</script>

<style scoped>
.rw-page {
  --rw-canvas: #ffffff;
  --rw-canvas-soft: #fafafa;
  --rw-surface-card: #ffffff;
  --rw-surface-strong: #f0f0f3;
  --rw-surface-dark: #171717;
  --rw-ink: #171717;
  --rw-body: #60646c;
  --rw-muted: #999999;
  --rw-muted-soft: #cccccc;
  --rw-hairline: #f0f0f3;
  --rw-hairline-soft: #f5f5f7;
  --rw-hairline-strong: #dcdee0;
  --rw-primary: #000000;
  --rw-primary-active: #1a1a1a;
  --rw-on-primary: #ffffff;
  --rw-success: #16a34a;
  --rw-danger: #c0382b;
  --rw-link: #0d74ce;
  --rw-sans: 'Inter', -apple-system, system-ui, 'PingFang SC', 'Microsoft YaHei', sans-serif;
  --rw-mono: 'JetBrains Mono', 'Fira Code', ui-monospace, monospace;

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

.analysis-trace { margin: 12px 0; }

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

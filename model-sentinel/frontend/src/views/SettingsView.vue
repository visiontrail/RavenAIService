<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import {
  ArrowLeft,
  CheckCircle2,
  CircleHelp,
  Clock,
  Eye,
  EyeOff,
  KeyRound,
  LoaderCircle,
  LockKeyhole,
  Play,
  RotateCcw,
  Save,
  Server,
  ShieldCheck,
  SlidersHorizontal,
  TerminalSquare,
  XCircle,
} from 'lucide-vue-next'
import { api } from '@/api'
import type { MonitorSettings, ProbeRun } from '@/types'

const emit = defineEmits<{ backDashboard: [] }>()

const loading = ref(true)
const saving = ref(false)
const testing = ref(false)
const showKey = ref(false)
const error = ref('')
const saved = ref(false)
const keySet = ref(false)
const testResult = ref<ProbeRun | null>(null)

const form = reactive({
  target_name: '',
  protocol: 'anthropic' as 'anthropic' | 'openai',
  base_url: '',
  model: '',
  api_key: '',
  enabled: true,
  interval_seconds: 300,
  timeout_seconds: 1800,
  max_tokens: 1024,
  alert_latency_ms: 30000,
  retention_days: 365,
  timezone: 'Asia/Singapore',
  agent_prompt: '',
})

const endpointPreview = computed(() => {
  const base = form.base_url.replace(/\/$/, '')
  if (!base) return '等待 Base URL'
  if (form.protocol === 'openai') {
    return base.endsWith('/v1') ? `${base}/chat/completions` : `${base}/v1/chat/completions`
  }
  return base.endsWith('/v1') ? `${base}/messages` : `${base}/v1/messages`
})

function populate(data: MonitorSettings) {
  form.target_name = data.target_name
  form.protocol = data.protocol
  form.base_url = data.base_url
  form.model = data.model
  form.api_key = ''
  form.enabled = data.enabled
  form.interval_seconds = data.interval_seconds
  form.timeout_seconds = data.timeout_seconds
  form.max_tokens = data.max_tokens
  form.alert_latency_ms = data.alert_latency_ms
  form.retention_days = data.retention_days
  form.timezone = data.timezone
  form.agent_prompt = data.agent_prompt
  keySet.value = data.api_key_set
}

async function load() {
  loading.value = true
  try {
    const response = await api.settings()
    populate(response.data)
    error.value = ''
  } catch (err: any) {
    error.value = err.message || '读取设置失败'
  } finally {
    loading.value = false
  }
}

async function save() {
  saving.value = true
  saved.value = false
  error.value = ''
  try {
    const response = await api.saveSettings({
      ...form,
      api_key: form.api_key.trim() || undefined,
    })
    populate(response.data)
    saved.value = true
    window.setTimeout(() => (saved.value = false), 3500)
  } catch (err: any) {
    error.value = err.message || '保存设置失败'
  } finally {
    saving.value = false
  }
}

async function test() {
  testing.value = true
  testResult.value = null
  error.value = ''
  try {
    const response = await api.testSettings({
      target_name: form.target_name || '临时测试',
      protocol: form.protocol,
      base_url: form.base_url,
      model: form.model,
      api_key: form.api_key.trim() || undefined,
      timeout_seconds: form.timeout_seconds,
      max_tokens: Math.min(form.max_tokens, 128),
      alert_latency_ms: form.alert_latency_ms,
      agent_prompt: form.agent_prompt,
    })
    testResult.value = response.data
  } catch (err: any) {
    error.value = err.message || '连接测试失败'
  } finally {
    testing.value = false
  }
}

function resetPrompt() {
  form.agent_prompt = `你是公司内部的生产级运维分析 Agent。请阅读下面这组模拟告警，完成一次中等强度的推理：

- 10:02，API 网关 P95 延迟由 2.1s 升至 8.6s
- 10:04，模型节点 GPU 利用率 94%，队列深度 37
- 10:06，5 分钟窗口内出现 3 次 429，未出现 5xx
- 10:09，队列深度回落至 12，GPU 利用率仍为 89%

请用中文输出：①最可能根因；②两个验证动作；③是否需要扩容。总计不超过 180 字。`
}

function duration(value: number | null) {
  if (value == null) return '—'
  return value >= 1000 ? `${(value / 1000).toFixed(1)} 秒` : `${value} 毫秒`
}

onMounted(load)
</script>

<template>
  <div class="page settings-page">
    <div class="page-heading settings-heading">
      <div>
        <button class="back-link" @click="emit('backDashboard')"><ArrowLeft :size="15" />返回运行态势</button>
        <span class="eyebrow"><i></i>MONITOR CONTROL</span>
        <h1>被测模型与 Agent 工况</h1>
        <p>设置会热更新到独立调度器，无需重启容器；API Key 永不返回前端。</p>
      </div>
      <div class="heading-actions">
        <span class="secure-label"><LockKeyhole :size="14" />凭据加密保存</span>
        <label class="monitor-switch">
          <span><strong>{{ form.enabled ? '监控运行中' : '监控已暂停' }}</strong><small>7×24 定时调度</small></span>
          <input v-model="form.enabled" type="checkbox" />
          <i></i>
        </label>
      </div>
    </div>

    <div v-if="error" class="settings-alert settings-alert--error">
      <XCircle :size="17" /><span>{{ error }}</span><button @click="error = ''"><XCircle :size="14" /></button>
    </div>
    <div v-if="saved" class="settings-alert settings-alert--success">
      <CheckCircle2 :size="17" /><span>设置已保存，常驻调度器已热更新。</span>
    </div>

    <div v-if="loading" class="settings-loading">
      <div class="skeleton skeleton--settings"></div>
      <div class="skeleton skeleton--settings"></div>
    </div>

    <form v-else @submit.prevent="save">
      <section class="settings-layout">
        <div class="settings-main">
          <article class="settings-card reveal-card">
            <header class="settings-card__head">
              <span class="settings-card__icon"><Server :size="18" /></span>
              <div><h2>被测模型</h2><p>沿用 Raven 主力模型的 Anthropic 兼容端点，也支持 OpenAI 协议。</p></div>
              <span class="source-badge">独立配置</span>
            </header>
            <div class="form-grid">
              <label class="field">
                <span>显示名称</span>
                <input v-model="form.target_name" required maxlength="80" placeholder="例如：银河私有模型集群" />
                <small>用于结果页和数据导出的目标标识。</small>
              </label>
              <label class="field">
                <span>接口协议</span>
                <select v-model="form.protocol">
                  <option value="anthropic">Anthropic Messages API</option>
                  <option value="openai">OpenAI Chat Completions</option>
                </select>
                <small>Raven 当前主力模型使用 Anthropic 兼容协议。</small>
              </label>
              <label class="field field--wide">
                <span>Base URL</span>
                <input v-model="form.base_url" class="mono" required spellcheck="false" placeholder="https://model-gateway.example.com" />
                <small>只填写网关根地址；服务会自动追加版本与接口路径。</small>
              </label>
              <label class="field">
                <span>模型 ID</span>
                <input v-model="form.model" class="mono" required spellcheck="false" placeholder="model-name" />
                <small>必须与网关中可调用的模型标识一致。</small>
              </label>
              <label class="field">
                <span class="field-label-row">API Key <em :class="{ set: keySet }">{{ keySet ? '已保存' : '未设置' }}</em></span>
                <span class="secret-input">
                  <KeyRound :size="15" />
                  <input v-model="form.api_key" :type="showKey ? 'text' : 'password'" autocomplete="new-password"
                    :placeholder="keySet ? '••••••••  留空则保持原 Key' : '请输入被测模型 API Key'" />
                  <button type="button" :aria-label="showKey ? '隐藏 Key' : '显示 Key'" @click="showKey = !showKey">
                    <EyeOff v-if="showKey" :size="16" /><Eye v-else :size="16" />
                  </button>
                </span>
                <small>通过独立密钥加密写入数据卷，读取接口只返回“是否已设置”。</small>
              </label>
            </div>
            <div class="endpoint-preview">
              <TerminalSquare :size="15" />
              <span>实际探测地址</span>
              <code>{{ endpointPreview }}</code>
            </div>
          </article>

          <article class="settings-card reveal-card">
            <header class="settings-card__head">
              <span class="settings-card__icon"><SlidersHorizontal :size="18" /></span>
              <div><h2>探测策略</h2><p>在监控成本与问题发现速度之间取得平衡。</p></div>
            </header>
            <div class="form-grid form-grid--three">
              <label class="field">
                <span>调用间隔</span>
                <div class="unit-input"><input v-model.number="form.interval_seconds" type="number" min="30" max="86400" required /><i>秒</i></div>
                <small>建议生产环境 300 秒。</small>
              </label>
              <label class="field">
                <span>单次超时</span>
                <div class="unit-input"><input v-model.number="form.timeout_seconds" type="number" min="5" max="3600" required /><i>秒</i></div>
                <small>覆盖模型完整推理时间。</small>
              </label>
              <label class="field">
                <span>最大输出</span>
                <div class="unit-input"><input v-model.number="form.max_tokens" type="number" min="16" max="200000" required /><i>Token</i></div>
                <small>用于模拟 Agent 输出配额。</small>
              </label>
              <label class="field">
                <span>可用延迟阈值</span>
                <div class="unit-input"><input v-model.number="form.alert_latency_ms" type="number" min="1000" max="3600000" step="1000" required /><i>毫秒</i></div>
                <small>成功但超阈值会标记“缓慢”。</small>
              </label>
              <label class="field">
                <span>数据保留</span>
                <div class="unit-input"><input v-model.number="form.retention_days" type="number" min="7" max="3650" required /><i>天</i></div>
                <small>到期数据由调度器自动清理。</small>
              </label>
              <label class="field">
                <span>IANA 时区</span>
                <input v-model="form.timezone" class="mono" required placeholder="Asia/Singapore" />
                <small>小时/每日聚合均按此时区。</small>
              </label>
            </div>
          </article>

          <article class="settings-card reveal-card">
            <header class="settings-card__head">
              <span class="settings-card__icon"><TerminalSquare :size="18" /></span>
              <div><h2>Agent 模拟工况</h2><p>每轮定时调用都会发送此任务，确保测到的是推理能力与真实排队延迟。</p></div>
              <button type="button" class="text-button" @click="resetPrompt"><RotateCcw :size="13" />恢复默认</button>
            </header>
            <label class="field prompt-field">
              <span>测试任务 Prompt</span>
              <textarea v-model="form.agent_prompt" required rows="11" maxlength="10000" spellcheck="false"></textarea>
              <small>{{ form.agent_prompt.length }} / 10000 字符。请勿放入公司秘密或个人数据。</small>
            </label>
          </article>
        </div>

        <aside class="settings-aside">
          <article class="settings-card connection-card">
            <span class="panel-eyebrow">CONNECTION TEST</span>
            <h2>保存前验证</h2>
            <p>执行一次缩短输出的真实流式请求，不会写入正式探测历史。</p>
            <button type="button" class="button button--secondary button--full"
              :disabled="testing || (!form.api_key.trim() && !keySet)" @click="test">
              <LoaderCircle v-if="testing" :size="16" class="spin" />
              <Play v-else :size="15" />{{ testing ? '正在调用模型' : '测试模型连接' }}
            </button>
            <div v-if="testResult" class="test-result" :class="{ ok: testResult.success, fail: !testResult.success }">
              <CheckCircle2 v-if="testResult.success" :size="18" />
              <XCircle v-else :size="18" />
              <div>
                <strong>{{ testResult.success ? '连接与推理成功' : '连接测试失败' }}</strong>
                <p v-if="testResult.success">总耗时 {{ duration(testResult.latency_ms) }} · 首 Token {{ duration(testResult.ttft_ms) }}</p>
                <p v-else>{{ testResult.error_message || testResult.error_kind }}</p>
              </div>
            </div>
            <dl class="connection-facts">
              <div><dt><Clock :size="14" />调度周期</dt><dd>{{ form.interval_seconds }}s</dd></div>
              <div><dt><ShieldCheck :size="14" />延迟阈值</dt><dd>{{ (form.alert_latency_ms / 1000).toFixed(0) }}s</dd></div>
              <div><dt><KeyRound :size="14" />凭据状态</dt><dd>{{ form.api_key.trim() ? '待保存新 Key' : keySet ? '已加密保存' : '未设置' }}</dd></div>
            </dl>
          </article>

          <article class="settings-card info-card">
            <CircleHelp :size="18" />
            <div><strong>为什么使用真实 Prompt？</strong><p>简单 ping 无法反映 GPU 排队、首 Token 与长尾推理。中等任务更接近 Raven Agent 的生产调用。</p></div>
          </article>
        </aside>
      </section>

      <footer class="settings-actions">
        <div><Server :size="15" /><span>设置保存后立即热更新，不重启容器。</span></div>
        <div>
          <button type="button" class="button button--secondary" @click="emit('backDashboard')">取消</button>
          <button type="submit" class="button button--primary" :disabled="saving">
            <LoaderCircle v-if="saving" :size="16" class="spin" /><Save v-else :size="15" />
            {{ saving ? '正在保存' : '保存设置' }}
          </button>
        </div>
      </footer>
    </form>
  </div>
</template>

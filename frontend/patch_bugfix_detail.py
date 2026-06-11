import re

with open('src/views/BugFixDetail.vue', 'r') as f:
    content = f.read()

content = content.replace("if (!task.value) return '加载中'", "if (!task.value) return t('bugFix.loading')")
content = content.replace("const project = task.value.project_name || task.value.project_code || '未关联项目'", "const project = task.value.project_name || task.value.project_code || t('bugFix.noProject')")

content = content.replace("pending: { text: '等待执行', className: 'rw-pill-neutral' },", "pending: { text: t('bugFix.statusText.pending'), className: 'rw-pill-neutral' },")
content = content.replace("running: { text: '修复中', className: 'rw-pill-info' },", "running: { text: t('bugFix.statusText.running'), className: 'rw-pill-info' },")
content = content.replace("succeeded: { text: '已完成', className: 'rw-pill-success' },", "succeeded: { text: t('bugFix.statusText.succeeded'), className: 'rw-pill-success' },")
content = content.replace("partial: { text: '部分完成', className: 'rw-pill-warning' },", "partial: { text: t('bugFix.statusText.partial'), className: 'rw-pill-warning' },")
content = content.replace("failed: { text: '失败', className: 'rw-pill-danger' },", "failed: { text: t('bugFix.statusText.failed'), className: 'rw-pill-danger' },")
content = content.replace("cancelled: { text: '已取消', className: 'rw-pill-neutral' },", "cancelled: { text: t('bugFix.statusText.cancelled'), className: 'rw-pill-neutral' },")

content = content.replace("created: { text: '已创建', className: 'rw-pill-success' },", "created: { text: t('bugFix.statusText.created'), className: 'rw-pill-success' },")
content = content.replace("open: { text: '已打开', className: 'rw-pill-success' },", "open: { text: t('bugFix.statusText.open'), className: 'rw-pill-success' },")
content = content.replace("push_failed: { text: '推送失败', className: 'rw-pill-danger' },", "push_failed: { text: t('bugFix.statusText.push_failed'), className: 'rw-pill-danger' },")
content = content.replace("mr_failed: { text: '创建失败', className: 'rw-pill-danger' },", "mr_failed: { text: t('bugFix.statusText.mr_failed'), className: 'rw-pill-danger' },")

content = content.replace("statusMeta[String(status)]?.text || String(status || '未知')", "statusMeta[String(status)]?.text || String(status || t('bugFix.statusText.unknown'))")
content = content.replace("mrStatusMeta[String(status)]?.text || String(status || '未知')", "mrStatusMeta[String(status)]?.text || String(status || t('bugFix.statusText.unknown'))")

content = content.replace("file.path || file.file_path || file.filename || file.name || '未知文件'", "file.path || file.file_path || file.filename || file.name || t('bugFix.unknownFile')")
content = content.replace("return `${fileCount} 文件 · +${added} / -${removed}`", "return t('bugFix.fileStats', { count: fileCount, added, removed })")

content = content.replace("ElMessage.error(bugFixStore.error || error?.message || '加载 Bug 修复详情失败')", "ElMessage.error(bugFixStore.error || error?.message || t('bugFix.fetchDetailFail'))")

content = content.replace(":title=\"task?.title || 'Bug 修复详情'\"", ":title=\"task?.title || $t('bugFix.detailTitle')\"")
content = content.replace("<span>返回列表</span>", "<span>{{ $t('bugFix.backToList') }}</span>")
content = content.replace("<span>刷新</span>", "<span>{{ $t('bugFix.refresh') }}</span>")

content = content.replace("<h2>未找到 Bug 修复任务</h2>", "<h2>{{ $t('bugFix.notFound') }}</h2>")
content = content.replace("<p>该任务不存在，或你没有所属项目的查看权限。</p>", "<p>{{ $t('bugFix.notFoundDesc') }}</p>")

content = content.replace("<span>所属项目</span>", "<span>{{ $t('bugFix.project') }}</span>")
content = content.replace("<span>来源日志</span>", "<span>{{ $t('bugFix.sourceLog') }}</span>")
content = content.replace("<span>MR 数量</span>", "<span>{{ $t('bugFix.mrCount') }}</span>")
content = content.replace("<span>创建时间</span>", "<span>{{ $t('bugFix.createdAt') }}</span>")

content = content.replace("<h2>拟修复项</h2>", "<h2>{{ $t('bugFix.fixItems') }}</h2>")
content = content.replace("<h3>{{ fix.title || `修复项 ${index + 1}` }}</h3>", "<h3>{{ fix.title || $t('bugFix.fixItemTitle', { index: index + 1 }) }}</h3>")
content = content.replace("<p v-else class=\"muted-text\">暂无结构化拟修复项。</p>", "<p v-else class=\"muted-text\">{{ $t('bugFix.noFixItems') }}</p>")

content = content.replace("<h2>执行信息</h2>", "<h2>{{ $t('bugFix.executionInfo') }}</h2>")
content = content.replace("<dt>开始时间</dt>", "<dt>{{ $t('bugFix.startTime') }}</dt>")
content = content.replace("<dt>完成时间</dt>", "<dt>{{ $t('bugFix.finishTime') }}</dt>")
content = content.replace("<dt>分析任务</dt>", "<dt>{{ $t('bugFix.analysisTask') }}</dt>")
content = content.replace("<dt>错误</dt>", "<dt>{{ $t('bugFix.error') }}</dt>")

content = content.replace("<h2>暂无 MR</h2>", "<h2>{{ $t('bugFix.noMr') }}</h2>")
content = content.replace("<p>Agent 还没有产出可展示的 Merge Request。</p>", "<p>{{ $t('bugFix.noMrDesc') }}</p>")

content = content.replace("打开 MR", "{{ $t('bugFix.openMr') }}")
content = content.replace("暂无改动文件统计。", "{{ $t('bugFix.noStats') }}")

if "import { useI18n } from 'vue-i18n'" not in content:
    content = content.replace("import { ref, computed, onMounted, onUnmounted } from 'vue'", "import { ref, computed, onMounted, onUnmounted } from 'vue'\nimport { useI18n } from 'vue-i18n'")
    content = content.replace("const bugFixStore = useBugFixStore()", "const bugFixStore = useBugFixStore()\nconst { t } = useI18n()")

with open('src/views/BugFixDetail.vue', 'w') as f:
    f.write(content)

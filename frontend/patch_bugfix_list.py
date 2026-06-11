import re

with open('src/views/BugFixList.vue', 'r') as f:
    content = f.read()

# Script section replacements
content = content.replace("`共 ${bugFixStore.pagination.total} 个任务`", "t('bugFix.totalTasks', { count: bugFixStore.pagination.total })")
content = content.replace("pending: { text: '等待执行', className: 'rw-pill-neutral' },", "pending: { text: t('bugFix.statusText.pending'), className: 'rw-pill-neutral' },")
content = content.replace("running: { text: '修复中', className: 'rw-pill-info' },", "running: { text: t('bugFix.statusText.running'), className: 'rw-pill-info' },")
content = content.replace("succeeded: { text: '已完成', className: 'rw-pill-success' },", "succeeded: { text: t('bugFix.statusText.succeeded'), className: 'rw-pill-success' },")
content = content.replace("partial: { text: '部分完成', className: 'rw-pill-warning' },", "partial: { text: t('bugFix.statusText.partial'), className: 'rw-pill-warning' },")
content = content.replace("failed: { text: '失败', className: 'rw-pill-danger' },", "failed: { text: t('bugFix.statusText.failed'), className: 'rw-pill-danger' },")
content = content.replace("cancelled: { text: '已取消', className: 'rw-pill-neutral' },", "cancelled: { text: t('bugFix.statusText.cancelled'), className: 'rw-pill-neutral' },")
content = content.replace("statusMeta[String(status)]?.text || String(status || '未知')", "statusMeta[String(status)]?.text || String(status || t('bugFix.statusText.unknown'))")

content = content.replace("return task.project_name || task.project_code || '未关联项目'", "return task.project_name || task.project_code || t('bugFix.noProject')")
content = content.replace("ElMessage.error(bugFixStore.error || error?.message || '加载 Bug 修复任务失败')", "ElMessage.error(bugFixStore.error || error?.message || t('bugFix.fetchListFail'))")
content = content.replace("ElMessage.error(bugFixStore.error || '加载 Bug 修复任务失败')", "ElMessage.error(bugFixStore.error || t('bugFix.fetchListFail'))")

# Template replacements
content = content.replace('title="Bug 修复"', ':title="$t(\'bugFix.listTitle\')"')
content = content.replace('<span>刷新</span>', '<span>{{ $t(\'bugFix.refresh\') }}</span>')
content = content.replace('<h2>请先登录</h2>', '<h2>{{ $t(\'bugFix.loginRequired\') }}</h2>')
content = content.replace('<p>登录后可查看你所属项目的 Bug 修复任务。</p>', '<p>{{ $t(\'bugFix.loginRequiredDesc\') }}</p>')

content = content.replace('label="任务标题"', ':label="$t(\'bugFix.taskTitle\')"')
content = content.replace('label="所属项目"', ':label="$t(\'bugFix.project\')"')
content = content.replace('label="状态"', ':label="$t(\'bugFix.status\')"')
content = content.replace('label="MR 数量"', ':label="$t(\'bugFix.mrCount\')"')
content = content.replace('label="来源日志"', ':label="$t(\'bugFix.sourceLog\')"')
content = content.replace('label="创建时间"', ':label="$t(\'bugFix.createdAt\')"')

content = content.replace('来源 {{ sourceLogText(task) }}', '{{ $t(\'bugFix.sourceText\', { text: sourceLogText(task) }) }}')
content = content.replace('<span v-else>无来源日志</span>', '<span v-else>{{ $t(\'bugFix.noSourceLog\') }}</span>')

content = content.replace('<h2>暂无 Bug 修复任务</h2>', '<h2>{{ $t(\'bugFix.emptyListTitle\') }}</h2>')
content = content.replace('<p>当日志分析确认需要代码修复后，任务会出现在这里。</p>', '<p>{{ $t(\'bugFix.emptyListDesc\') }}</p>')

if "import { useI18n } from 'vue-i18n'" not in content:
    content = content.replace("import { ref, computed, onMounted } from 'vue'", "import { ref, computed, onMounted } from 'vue'\nimport { useI18n } from 'vue-i18n'")
    content = content.replace("const bugFixStore = useBugFixStore()", "const bugFixStore = useBugFixStore()\nconst { t } = useI18n()")

with open('src/views/BugFixList.vue', 'w') as f:
    f.write(content)

import re

def add_to_ts(filepath, new_content):
    with open(filepath, 'r') as f:
        content = f.read()
    
    # Insert right before the last closing brace
    last_brace_idx = content.rfind('}')
    if last_brace_idx != -1:
        updated = content[:last_brace_idx] + new_content + "\n" + content[last_brace_idx:]
        with open(filepath, 'w') as f:
            f.write(updated)
            
zh_content = """
  bugFix: {
    listTitle: 'Bug 修复',
    detailTitle: 'Bug 修复详情',
    totalTasks: '共 {count} 个任务',
    fetchListFail: '加载 Bug 修复任务失败',
    fetchDetailFail: '加载 Bug 修复详情失败',
    taskTitle: '任务标题',
    project: '所属项目',
    status: '状态',
    mrCount: 'MR 数量',
    sourceLog: '来源日志',
    createdAt: '创建时间',
    noProject: '未关联项目',
    sourceText: '来源 {text}',
    noSourceLog: '无来源日志',
    emptyListTitle: '暂无 Bug 修复任务',
    emptyListDesc: '当日志分析确认需要代码修复后，任务会出现在这里。',
    loginRequired: '请先登录',
    loginRequiredDesc: '登录后可查看你所属项目的 Bug 修复任务。',
    loading: '加载中',
    refresh: '刷新',
    backToList: '返回列表',
    notFound: '未找到 Bug 修复任务',
    notFoundDesc: '该任务不存在，或你没有所属项目的查看权限。',
    fixItems: '拟修复项',
    fixItemTitle: '修复项 {index}',
    noFixItems: '暂无结构化拟修复项。',
    executionInfo: '执行信息',
    startTime: '开始时间',
    finishTime: '完成时间',
    analysisTask: '分析任务',
    error: '错误',
    noMr: '暂无 MR',
    noMrDesc: 'Agent 还没有产出可展示的 Merge Request。',
    openMr: '打开 MR',
    noStats: '暂无改动文件统计。',
    unknownFile: '未知文件',
    fileStats: '{count} 文件 · +{added} / -{removed}',
    statusText: {
      pending: '等待执行',
      running: '修复中',
      succeeded: '已完成',
      partial: '部分完成',
      failed: '失败',
      cancelled: '已取消',
      created: '已创建',
      open: '已打开',
      push_failed: '推送失败',
      mr_failed: '创建失败',
      unknown: '未知',
    }
  },
"""

en_content = """
  bugFix: {
    listTitle: 'Bug Fixes',
    detailTitle: 'Bug Fix Detail',
    totalTasks: '{count} total tasks',
    fetchListFail: 'Failed to load bug fix tasks',
    fetchDetailFail: 'Failed to load bug fix detail',
    taskTitle: 'Task title',
    project: 'Project',
    status: 'Status',
    mrCount: 'MRs',
    sourceLog: 'Source log',
    createdAt: 'Created at',
    noProject: 'No project linked',
    sourceText: 'Source {text}',
    noSourceLog: 'No source log',
    emptyListTitle: 'No bug fix tasks',
    emptyListDesc: 'Tasks will appear here when log analysis confirms a code fix is needed.',
    loginRequired: 'Please log in',
    loginRequiredDesc: 'Log in to view bug fix tasks for your projects.',
    loading: 'Loading',
    refresh: 'Refresh',
    backToList: 'Back to list',
    notFound: 'Bug fix task not found',
    notFoundDesc: 'The task does not exist, or you do not have permission to view it.',
    fixItems: 'Proposed fixes',
    fixItemTitle: 'Fix item {index}',
    noFixItems: 'No structured fix items.',
    executionInfo: 'Execution info',
    startTime: 'Start time',
    finishTime: 'Finish time',
    analysisTask: 'Analysis task',
    error: 'Error',
    noMr: 'No MRs',
    noMrDesc: 'The Agent has not produced a displayable Merge Request yet.',
    openMr: 'Open MR',
    noStats: 'No changed files stats.',
    unknownFile: 'Unknown file',
    fileStats: '{count} files · +{added} / -{removed}',
    statusText: {
      pending: 'Pending',
      running: 'Running',
      succeeded: 'Succeeded',
      partial: 'Partial',
      failed: 'Failed',
      cancelled: 'Cancelled',
      created: 'Created',
      open: 'Open',
      push_failed: 'Push failed',
      mr_failed: 'MR failed',
      unknown: 'Unknown',
    }
  },
"""

add_to_ts('src/i18n/zh.ts', zh_content)
add_to_ts('src/i18n/en.ts', en_content)

import re

def add_to_ts(filepath, new_content):
    with open(filepath, 'r') as f:
        content = f.read()
    
    last_brace_idx = content.rfind('}')
    if last_brace_idx != -1:
        updated = content[:last_brace_idx] + new_content + "\n" + content[last_brace_idx:]
        with open(filepath, 'w') as f:
            f.write(updated)

zh_content = """
  router: {
    workbench: 'RavenAI 工作台',
    logList: '日志列表',
    logDetail: '日志详情',
    devices: '设备机柜',
    deviceDetail: '设备详情',
    raven: '重构包仓库',
    ravenDetail: '包详情',
    bugFix: 'Bug 修复',
    bugFixDetail: 'Bug 修复详情',
    upload: '上传日志',
    download: '下载客户端',
    about: '关于 Raven',
    changelog: '更新日志',
    privacy: '隐私政策',
    terms: '服务条款',
    admin: '后台管理',
    adminUsers: '用户管理',
    adminRelease: 'App Release 管理',
    adminRepos: '项目仓库管理',
    adminAgentSkills: 'Agent Skill 管理',
    adminProjectSkills: '项目 Skill 管理',
    adminModelSettings: '模型设置',
    adminMetrics: '数据指标',
    notFound: '页面未找到',
    docTitleSuffix: ' - Raven智能测试平台'
  },
  adminNav: {
    promptConfig: 'Prompt 配置',
    promptConfigDesc: '按功能和 Agent 编辑系统提示词',
    users: '用户管理',
    usersDesc: '管理对话用户、重置密码',
    releaseDesc: '上传 Linux / macOS / Windows 发布包',
    repos: '项目仓库管理',
    reposDesc: '维护 project_code 到 Git 仓库的映射',
    agentSkills: 'Agent Skill 管理',
    agentSkillsDesc: '为 Claude Agent 上传/启用用户自定义 Skill 包',
    modelSettings: '模型设置',
    modelSettingsDesc: '配置轻量级模型（会话摘要、标题生成等）',
    metrics: '数据指标',
    metricsDesc: '查看 Token 用量、调用统计与业务活动'
  },
  tools: {
    Bash: '终端',
    Read: '读文件',
    Write: '写文件',
    Edit: '编辑文件',
    Grep: '代码搜索',
    Glob: '文件查找',
    Skill: '调用技能',
    Task: '子任务',
    WebFetch: '网页抓取',
    WebSearch: '联网搜索',
    ProjectRepo: '项目仓库查询',
    LogSearch: '日志搜索'
  },
"""

en_content = """
  router: {
    workbench: 'RavenAI Workbench',
    logList: 'Log List',
    logDetail: 'Log Detail',
    devices: 'Devices',
    deviceDetail: 'Device Detail',
    raven: 'Package Repository',
    ravenDetail: 'Package Detail',
    bugFix: 'Bug Fix',
    bugFixDetail: 'Bug Fix Detail',
    upload: 'Upload Log',
    download: 'Download Client',
    about: 'About Raven',
    changelog: 'Changelog',
    privacy: 'Privacy Policy',
    terms: 'Terms of Service',
    admin: 'Admin Console',
    adminUsers: 'User Management',
    adminRelease: 'App Release Management',
    adminRepos: 'Project Repositories',
    adminAgentSkills: 'Agent Skills',
    adminProjectSkills: 'Project Skills',
    adminModelSettings: 'Model Settings',
    adminMetrics: 'Metrics',
    notFound: 'Page Not Found',
    docTitleSuffix: ' - Raven AI Test Platform'
  },
  adminNav: {
    promptConfig: 'Prompt Config',
    promptConfigDesc: 'Edit system prompts by function and Agent',
    users: 'User Management',
    usersDesc: 'Manage conversation users, reset passwords',
    releaseDesc: 'Upload Linux / macOS / Windows release packages',
    repos: 'Project Repositories',
    reposDesc: 'Maintain project_code to Git repository mappings',
    agentSkills: 'Agent Skills',
    agentSkillsDesc: 'Upload/enable custom Skill packages for Claude Agent',
    modelSettings: 'Model Settings',
    modelSettingsDesc: 'Configure lightweight models (session summary, title generation, etc.)',
    metrics: 'Metrics',
    metricsDesc: 'View Token usage, call statistics, and business activity'
  },
  tools: {
    Bash: 'Terminal',
    Read: 'Read File',
    Write: 'Write File',
    Edit: 'Edit File',
    Grep: 'Code Search',
    Glob: 'File Search',
    Skill: 'Call Skill',
    Task: 'Subtask',
    WebFetch: 'Web Fetch',
    WebSearch: 'Web Search',
    ProjectRepo: 'Project Repo Query',
    LogSearch: 'Log Search'
  },
"""

add_to_ts('src/i18n/zh.ts', zh_content)
add_to_ts('src/i18n/en.ts', en_content)

# Update AdminMetrics.vue
with open('src/views/AdminMetrics.vue', 'r') as f:
    admin_metrics = f.read()
admin_metrics = admin_metrics.replace('Agent 调用趋势 (按时间序列)', '{{ $t(\'admin.metrics.agentTrendTitle\') }}')
with open('src/views/AdminMetrics.vue', 'w') as f:
    f.write(admin_metrics)

# Update utils/adminNav.ts
with open('src/utils/adminNav.ts', 'r') as f:
    admin_nav = f.read()
if "import { i18n } from '@/i18n'" not in admin_nav:
    admin_nav = "import { i18n } from '@/i18n'\n\n" + admin_nav

admin_nav = admin_nav.replace("'Prompt 配置'", "i18n.global.t('adminNav.promptConfig')")
admin_nav = admin_nav.replace("'按功能和 Agent 编辑系统提示词'", "i18n.global.t('adminNav.promptConfigDesc')")
admin_nav = admin_nav.replace("'用户管理'", "i18n.global.t('adminNav.users')")
admin_nav = admin_nav.replace("'管理对话用户、重置密码'", "i18n.global.t('adminNav.usersDesc')")
admin_nav = admin_nav.replace("'上传 Linux / macOS / Windows 发布包'", "i18n.global.t('adminNav.releaseDesc')")
admin_nav = admin_nav.replace("'项目仓库管理'", "i18n.global.t('adminNav.repos')")
admin_nav = admin_nav.replace("'维护 project_code 到 Git 仓库的映射'", "i18n.global.t('adminNav.reposDesc')")
admin_nav = admin_nav.replace("'Agent Skill 管理'", "i18n.global.t('adminNav.agentSkills')")
admin_nav = admin_nav.replace("'为 Claude Agent 上传/启用用户自定义 Skill 包'", "i18n.global.t('adminNav.agentSkillsDesc')")
admin_nav = admin_nav.replace("'模型设置'", "i18n.global.t('adminNav.modelSettings')")
admin_nav = admin_nav.replace("'配置轻量级模型（会话摘要、标题生成等）'", "i18n.global.t('adminNav.modelSettingsDesc')")
admin_nav = admin_nav.replace("'数据指标'", "i18n.global.t('adminNav.metrics')")
admin_nav = admin_nav.replace("'查看 Token 用量、调用统计与业务活动'", "i18n.global.t('adminNav.metricsDesc')")

with open('src/utils/adminNav.ts', 'w') as f:
    f.write(admin_nav)

# Update composables/useToolDisplayName.ts
with open('src/composables/useToolDisplayName.ts', 'r') as f:
    tool_names = f.read()

if "import { i18n } from '@/i18n'" not in tool_names:
    tool_names = "import { i18n } from '@/i18n'\n" + tool_names

tool_names = tool_names.replace("'终端'", "i18n.global.t('tools.Bash')")
tool_names = tool_names.replace("'读文件'", "i18n.global.t('tools.Read')")
tool_names = tool_names.replace("'写文件'", "i18n.global.t('tools.Write')")
tool_names = tool_names.replace("'编辑文件'", "i18n.global.t('tools.Edit')")
tool_names = tool_names.replace("'代码搜索'", "i18n.global.t('tools.Grep')")
tool_names = tool_names.replace("'文件查找'", "i18n.global.t('tools.Glob')")
tool_names = tool_names.replace("'调用技能'", "i18n.global.t('tools.Skill')")
tool_names = tool_names.replace("'子任务'", "i18n.global.t('tools.Task')")
tool_names = tool_names.replace("'网页抓取'", "i18n.global.t('tools.WebFetch')")
tool_names = tool_names.replace("'联网搜索'", "i18n.global.t('tools.WebSearch')")
tool_names = tool_names.replace("'项目仓库查询'", "i18n.global.t('tools.ProjectRepo')")
tool_names = tool_names.replace("'日志搜索'", "i18n.global.t('tools.LogSearch')")

with open('src/composables/useToolDisplayName.ts', 'w') as f:
    f.write(tool_names)

# Update router/index.ts
with open('src/router/index.ts', 'r') as f:
    router_ts = f.read()

if "import { i18n } from '@/i18n'" not in router_ts:
    router_ts = router_ts.replace("import { createRouter, createWebHistory } from 'vue-router'", "import { createRouter, createWebHistory } from 'vue-router'\nimport { i18n } from '@/i18n'")

router_ts = router_ts.replace("'RavenAI 工作台'", "i18n.global.t('router.workbench')")
router_ts = router_ts.replace("'日志列表'", "i18n.global.t('router.logList')")
router_ts = router_ts.replace("'日志详情'", "i18n.global.t('router.logDetail')")
router_ts = router_ts.replace("'设备机柜'", "i18n.global.t('router.devices')")
router_ts = router_ts.replace("'设备详情'", "i18n.global.t('router.deviceDetail')")
router_ts = router_ts.replace("'重构包仓库'", "i18n.global.t('router.raven')")
router_ts = router_ts.replace("'包详情'", "i18n.global.t('router.ravenDetail')")
router_ts = router_ts.replace("'Bug 修复'", "i18n.global.t('router.bugFix')")
router_ts = router_ts.replace("'Bug 修复详情'", "i18n.global.t('router.bugFixDetail')")
router_ts = router_ts.replace("'上传日志'", "i18n.global.t('router.upload')")
router_ts = router_ts.replace("'下载客户端'", "i18n.global.t('router.download')")
router_ts = router_ts.replace("'关于 Raven'", "i18n.global.t('router.about')")
router_ts = router_ts.replace("'更新日志'", "i18n.global.t('router.changelog')")
router_ts = router_ts.replace("'隐私政策'", "i18n.global.t('router.privacy')")
router_ts = router_ts.replace("'服务条款'", "i18n.global.t('router.terms')")
router_ts = router_ts.replace("'后台管理'", "i18n.global.t('router.admin')")
router_ts = router_ts.replace("'用户管理'", "i18n.global.t('router.adminUsers')")
router_ts = router_ts.replace("'App Release 管理'", "i18n.global.t('router.adminRelease')")
router_ts = router_ts.replace("'项目仓库管理'", "i18n.global.t('router.adminRepos')")
router_ts = router_ts.replace("'Agent Skill 管理'", "i18n.global.t('router.adminAgentSkills')")
router_ts = router_ts.replace("'项目 Skill 管理'", "i18n.global.t('router.adminProjectSkills')")
router_ts = router_ts.replace("'模型设置'", "i18n.global.t('router.adminModelSettings')")
router_ts = router_ts.replace("'数据指标'", "i18n.global.t('router.adminMetrics')")
router_ts = router_ts.replace("'页面未找到'", "i18n.global.t('router.notFound')")
router_ts = router_ts.replace("' - Raven智能测试平台'", "i18n.global.t('router.docTitleSuffix')")

with open('src/router/index.ts', 'w') as f:
    f.write(router_ts)


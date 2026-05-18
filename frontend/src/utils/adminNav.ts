export const adminNavItems = [
  {
    key: 'prompts',
    label: 'Prompt 配置',
    path: '/admin/prompts',
    description: '按功能和 Agent 编辑系统提示词',
  },
  {
    key: 'users',
    label: '用户管理',
    path: '/admin/users',
    description: '管理对话用户、重置密码',
  },
  {
    key: 'releases',
    label: 'App Release',
    path: '/admin/releases',
    description: '上传 Linux / macOS / Windows 发布包',
  },
  {
    key: 'project-repos',
    label: '项目仓库管理',
    path: '/admin/project-repos',
    description: '维护 project_code 到 Git 仓库的映射',
  },
  {
    key: 'agent-skills',
    label: 'Agent Skill 管理',
    path: '/admin/agent-skills',
    description: '为 Claude Agent 上传/启用用户自定义 Skill 包',
  },
] as const

export type AdminNavItem = (typeof adminNavItems)[number]

export const resolveAdminNavKey = (path: string) => {
  if (path.startsWith('/admin/users')) return 'users'
  if (path.startsWith('/admin/releases')) return 'releases'
  if (path.startsWith('/admin/project-repos')) return 'project-repos'
  if (path.startsWith('/admin/agent-skills')) return 'agent-skills'
  if (path.startsWith('/admin')) return 'prompts'
  return ''
}

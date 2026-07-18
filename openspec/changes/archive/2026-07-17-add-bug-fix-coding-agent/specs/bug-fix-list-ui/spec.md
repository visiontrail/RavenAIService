## ADDED Requirements

### Requirement: Bug fix entry lives in the bottom-left user menu

The frontend SHALL add a "Bug 修复" entry inside the bottom-left user-info expandable menu (the `showUserMenu` block in `WorkbenchLayout.vue`). Activating it SHALL navigate to `/bug-fixes` and render the list in the right-hand main area, consistent with how the "日志列表" and "设备机柜" navigation items behave. The entry SHALL be visible only to authenticated users.

#### Scenario: User opens bug fix list from the menu

- **WHEN** an authenticated user opens the bottom-left user menu and clicks "Bug 修复"
- **THEN** the app navigates to `/bug-fixes` and the bug fix list renders in the right-hand main area

#### Scenario: Entry hidden when logged out

- **WHEN** no user is authenticated
- **THEN** the "Bug 修复" entry is not shown in the user menu

### Requirement: Bug fix list view shows summary columns and links to detail

The frontend SHALL provide `/bug-fixes` (`BugFixList.vue`) rendering a table whose columns include at minimum: 任务标题, 所属项目, 状态 (rendered as a colored badge), MR 数量, 来源日志, 创建时间. Each row SHALL be clickable to open the corresponding detail at `/bug-fixes/:id`. The list SHALL be populated from `GET /api/v1/bug-fixes`.

#### Scenario: List renders task rows

- **WHEN** the bug fix list loads for a user with visible tasks
- **THEN** each row shows the task title, project, status badge, MR count, source log, and creation time

#### Scenario: Row click opens detail

- **WHEN** the user clicks a task row
- **THEN** the app navigates to `/bug-fixes/:id` and shows that task's detail

### Requirement: Bug fix detail view shows task summary and per-MR change information

The frontend SHALL provide `/bug-fixes/:id` (`BugFixDetail.vue`) showing the task summary and `proposed_fixes`, and for each Merge Request a card with its title, status, branch name, list of changed files with diff statistics, and a clickable link to the Merge Request (`mr_url`). Data SHALL come from `GET /api/v1/bug-fixes/{id}`.

#### Scenario: Detail shows MR cards

- **WHEN** a task detail with two Merge Requests loads
- **THEN** two MR cards are shown, each with branch name, changed files, diff stats, and a clickable MR link

### Requirement: Admin project repo page manages project members

`AdminProjectRepos.vue` SHALL provide a way to view, add, and remove the registered users who are members of a project repository, by searching registered users by username or email. This SHALL call the admin member-management endpoints.

#### Scenario: Admin adds a member

- **WHEN** an admin searches a registered user and adds them to a project repository
- **THEN** the user appears in that project's member list and gains visibility of the project's bug fixes

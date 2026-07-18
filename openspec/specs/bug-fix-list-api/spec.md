# bug-fix-list-api Specification

## Purpose

Expose authenticated, membership-scoped APIs for listing and reading bug fix tasks and their merge requests, without ever leaking git credentials.

## Requirements

### Requirement: Authenticated users list bug fixes scoped to their project membership

The system SHALL expose `GET /api/v1/bug-fixes` (paginated) returning `bug_fix_task` summaries. The endpoint SHALL require an authenticated user. The returned set SHALL be limited to tasks whose `project_repo` the requesting user is a member of, EXCEPT that a user with `role == "admin"` SHALL see tasks across all projects. Each summary SHALL include at minimum `id`, `title`, `project_code`, `project_name`, `status`, `merge_request_count`, `source_log_id`, `created_at`, and `finished_at`. No git token SHALL appear in any field.

#### Scenario: Member sees only their projects' tasks

- **WHEN** a non-admin user who is a member of project A (but not project B) calls `GET /api/v1/bug-fixes`
- **THEN** the response contains tasks for project A and excludes tasks for project B

#### Scenario: Admin sees all tasks

- **WHEN** a user with `role == "admin"` calls `GET /api/v1/bug-fixes`
- **THEN** the response contains tasks across all projects

#### Scenario: Unauthenticated request is rejected

- **WHEN** a request without valid authentication calls `GET /api/v1/bug-fixes`
- **THEN** the response is `401`

### Requirement: Authenticated users read a bug fix task detail with its merge requests

The system SHALL expose `GET /api/v1/bug-fixes/{id}` returning the task detail and its associated `bug_fix_merge_request` rows. The task summary, `proposed_fixes`, and per–Merge Request fields (`title`, `status`, `branch_name`, `base_branch`, `mr_url`, `mr_iid`, `commit_sha`, `changed_files`, `diff_stat`) SHALL be included. If the requesting user is neither a member of the task's project nor an admin, the endpoint SHALL return `404` (not `403`) so it does not disclose existence.

#### Scenario: Member reads task detail with MRs

- **WHEN** a member of the task's project calls `GET /api/v1/bug-fixes/{id}`
- **THEN** the response includes the task summary, `proposed_fixes`, and each Merge Request's `mr_url`, `branch_name`, `changed_files`, and `diff_stat`

#### Scenario: Non-member detail access returns 404

- **WHEN** a non-admin, non-member user requests a task detail by id
- **THEN** the response is `404`

## ADDED Requirements

### Requirement: Project-bound Agents can clone registered projects into the current workspace
The system SHALL provide a workspace-bound in-process MCP tool named `mcp__project_repo__clone_project_repo` to Project Expert and Log Analysis. The tool SHALL accept only a `project_code`, resolve an enabled repository that is bound to the calling Agent, clone it beneath the bound workspace, and return its sanitized project identity/card, relative and absolute workspace paths, checked-out branch, commit SHA, and reuse status. The tool response MUST NOT contain a repository URL, clone URL, token, SSH identity, or authentication state.

#### Scenario: Additional project is cloned without credential exposure
- **WHEN** Project Expert calls `clone_project_repo` for a different enabled project with an SSH or token-authenticated repository
- **THEN** the repository is cloned into `<workspace>/related_repos/<project-code>`
- **AND** the tool response and persisted trace contain the resulting path and commit but no clone credential or repository URL

#### Scenario: Primary project uses the compatible repo path
- **WHEN** the tool is called with the current session's primary project code
- **THEN** it clones or reuses `<workspace>/repo`
- **AND** existing single-project evidence paths remain valid

#### Scenario: Project is not available to the calling Agent
- **WHEN** the requested project is disabled, has no repository, does not exist, or is not bound to the calling Agent
- **THEN** the tool returns a typed non-sensitive error
- **AND** no filesystem path is created for that project

### Requirement: Related repository paths are contained, bounded, and idempotent
The clone tool SHALL choose deterministic repository paths derived from registry-owned project codes, SHALL verify that every target and partial path remains under the bound workspace, and SHALL enforce a configured maximum number of related repositories. Repeated calls for an existing valid checkout SHALL reuse it instead of cloning again.

#### Scenario: Repeated clone call reuses the checkout
- **WHEN** the same project code is cloned twice in one persistent workspace
- **THEN** the second call returns `reused: true` with the existing branch and commit
- **AND** no second `git clone` is executed

#### Scenario: Related repository limit is reached
- **WHEN** a run attempts to clone another additional project after the configured workspace limit is reached
- **THEN** the tool returns a typed limit error
- **AND** existing repositories remain unchanged

#### Scenario: Unsafe or conflicting destination is detected
- **WHEN** a derived target would escape the workspace or an expected target contains non-Git user data
- **THEN** the tool refuses the operation with a typed error
- **AND** it does not delete or overwrite the conflicting data

### Requirement: Clone failures are cleaned and sanitized
The clone tool SHALL execute Git without a shell, SHALL impose a finite timeout, SHALL clone into a unique validated partial directory, and SHALL atomically publish the checkout only after success. On failure it SHALL remove only the partial directory created by that call and return a sanitized error that does not reveal credentials.

#### Scenario: SSH authentication fails
- **WHEN** an SSH repository clone fails because the runtime identity is unavailable or rejected
- **THEN** the partial clone directory is removed and the final target remains absent or unchanged
- **AND** the returned error contains a useful category/summary but no private key, token, or credential-bearing URL

#### Scenario: Clone succeeds through the SSH-agent overlay
- **WHEN** the Agent container has the documented `SSH_AUTH_SOCK`, strict known-host configuration, and a valid sidecar identity
- **THEN** the tool inherits that environment and completes the clone without reading or mounting the private key itself

### Requirement: Workspace manifest records related repository provenance
After a successful clone or reuse, the system SHALL atomically upsert a non-sensitive entry in `task.json.related_repos` containing project identity/card, workspace-relative path, branch, commit SHA, and reuse state. It MUST NOT persist repository URLs, clone URLs, tokens, SSH identity details, or raw Git errors.

#### Scenario: Joint analysis persists two project sources
- **WHEN** an Agent uses the primary repository and clones one additional project
- **THEN** `task.json` retains the original `repo_info` and adds one `related_repos` entry for the additional checkout
- **AND** a follow-up turn can reuse both checkouts and identify their exact commits

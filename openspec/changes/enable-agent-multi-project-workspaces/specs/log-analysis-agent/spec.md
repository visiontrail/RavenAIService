## MODIFIED Requirements

### Requirement: Log Analysis validates project context before project-grounded analysis
Log Analysis workspaces resolved from a registered project SHALL include its `project_card` in `task.json.repo_info`. LogAnalysisAgent SHALL compare the log identity and user question with the selected/resolved project card and the discovered catalog before project-grounded conclusions. On a clear mismatch it SHALL clone and inspect the matching registered project in the same workspace instead of analyzing the unrelated selected repository. When the log crosses project boundaries, it SHALL use the primary repository plus only the additional repositories materially required to explain the evidence.

#### Scenario: Explicit user selection conflicts with log identity
- **WHEN** a user-selected project's card clearly conflicts with the log metadata/question and another discovered project clearly matches
- **THEN** LogAnalysisAgent clones the matching project in `related_repos/<project-code>` and analyzes that checkout
- **AND** it does not produce a repository-grounded diagnosis from the unrelated selected project

#### Scenario: Log requires cross-project correlation
- **WHEN** a log line is emitted in one project but its message schema or behavior is implemented in another matching registered project
- **THEN** LogAnalysisAgent clones the additional project and correlates the log with both relevant source trees
- **AND** its evidence identifies the originating project and repository-relative path for each source citation

#### Scenario: No project can analyze the log
- **WHEN** the complete catalog contains no project card suitable for the log/question
- **THEN** LogAnalysisAgent explicitly states that no suitable project is currently registered
- **AND** it does not force the analysis into an unrelated project

#### Scenario: Resolved project remains sufficient
- **WHEN** the selected or metadata-resolved project card fully matches the log identity/question
- **THEN** LogAnalysisAgent continues the existing log and source-code analysis workflow
- **AND** it does not clone unrelated projects

## ADDED Requirements

### Requirement: Log Analysis validates project context before project-grounded analysis
Log Analysis workspaces resolved from a registered project SHALL include its `project_card` in `task.json.repo_info`. LogAnalysisAgent SHALL compare the log identity and user question with the selected/resolved project card and the discovered catalog. On a clear mismatch it MUST NOT attribute findings to or clone/analyze the unrelated project's repository.

#### Scenario: Explicit user selection conflicts with log identity
- **WHEN** a user-selected project's card clearly conflicts with the log metadata/question and another discovered project clearly matches
- **THEN** LogAnalysisAgent explains that the selected project is unsuitable and recommends the matching project by name/code
- **AND** it does not produce a repository-grounded diagnosis from the wrong project

#### Scenario: No project can analyze the log
- **WHEN** the complete catalog contains no project card suitable for the log/question
- **THEN** LogAnalysisAgent explicitly states that no suitable project is currently registered
- **AND** it does not force the analysis into an unrelated project

#### Scenario: Resolved project is suitable
- **WHEN** the selected or metadata-resolved project card matches the log identity/question
- **THEN** LogAnalysisAgent continues the existing log and source-code analysis workflow

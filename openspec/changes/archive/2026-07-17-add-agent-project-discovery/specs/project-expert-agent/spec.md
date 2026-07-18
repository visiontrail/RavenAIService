## ADDED Requirements

### Requirement: Project Expert validates the selected project before domain answering
The Project Expert workspace SHALL persist the selected project's non-sensitive `project_card` in `task.json.repo_info`. ProjectExpertAgent SHALL compare the user's question with that card and the discovered enabled catalog. When the selected project is clearly unrelated, it MUST NOT answer from the selected repository, project prompt, or project skills as though they were relevant.

#### Scenario: Selected project is clearly wrong and another project matches
- **WHEN** the selected project's card is unrelated to the question and another discovered card clearly matches
- **THEN** the final answer identifies the mismatch and recommends the matching project by name/code
- **AND** it instructs the user to start a new project-expert session because the current session remains bound

#### Scenario: Selected project is wrong and no project matches
- **WHEN** the selected project's card is unrelated and no discovered project card fits
- **THEN** the final answer states that no suitable project is currently registered
- **AND** no source-grounded answer is fabricated from the selected repository

#### Scenario: Selected project remains suitable
- **WHEN** the question is within the selected project card's scope
- **THEN** ProjectExpertAgent continues the existing source/project-context workflow
- **AND** the answer remains grounded in the selected project

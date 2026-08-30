## MODIFIED Requirements

### Requirement: Project Expert validates the selected project before domain answering
The Project Expert workspace SHALL persist the selected project's non-sensitive `project_card` in `task.json.repo_info`. ProjectExpertAgent SHALL compare the user's question with that card and the discovered enabled catalog before project-grounded conclusions. When the selected project is clearly unrelated and another registered project matches, it SHALL clone and inspect the matching project in the same workspace; when multiple project cards are materially required, it SHALL analyze the selected repository and the necessary additional repositories together. It MUST NOT use an unrelated selected repository, project prompt, or project Skill as evidence for the matching project.

#### Scenario: Selected project is clearly wrong and another project matches
- **WHEN** the selected project's card is unrelated to the question and another discovered card clearly matches
- **THEN** ProjectExpertAgent clones the matching project into `related_repos/<project-code>` and answers from that checkout
- **AND** the final answer identifies the recovered mismatch and does not require the user to start a new session

#### Scenario: Question spans the selected and another project
- **WHEN** the selected project's card covers one responsibility and another discovered card covers a second responsibility required by the same question
- **THEN** ProjectExpertAgent clones the additional project and investigates both checkouts
- **AND** the final answer labels evidence by project and path

#### Scenario: Selected project is wrong and no project matches
- **WHEN** the selected project's card is unrelated and no discovered project card fits
- **THEN** the final answer states that no suitable project is currently registered
- **AND** no source-grounded answer is fabricated from the selected repository

#### Scenario: Selected project remains sufficient
- **WHEN** the question is fully within the selected project card's scope
- **THEN** ProjectExpertAgent continues the existing single-repository workflow
- **AND** it does not clone unrelated projects merely because they are present in the catalog

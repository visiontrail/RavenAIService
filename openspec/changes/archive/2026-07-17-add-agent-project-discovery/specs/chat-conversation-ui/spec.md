## ADDED Requirements

### Requirement: Project selection surfaces project-card guidance
The chat project's selector SHALL expose a bounded project-card summary together with each project name/code, and SHALL make the complete card available as accessible/title guidance. The admin project create/edit UI SHALL label the field “Project Card”, mark it required, explain that Agents use it for matching, and prevent submission while it is blank.

#### Scenario: User compares project cards before selection
- **WHEN** the project selector is open for a project-bound Agent
- **THEN** each option shows the project name/code and a project-card summary
- **AND** the full project card is available as option guidance

#### Scenario: Admin cannot save a blank card
- **WHEN** an administrator leaves Project Card blank in the create/edit dialog
- **THEN** the Save action reports that the project card is required
- **AND** no create/update request is sent

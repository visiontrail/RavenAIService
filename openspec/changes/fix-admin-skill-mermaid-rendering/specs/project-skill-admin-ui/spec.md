## MODIFIED Requirements

### Requirement: Skill file preview from project detail page

The system SHALL allow admins to browse a project skill's file tree and preview file contents, reusing the same UI pattern as the agent skill file browser. Clicking a skill SHALL expand to show its file tree; clicking a file SHALL display its content. Markdown previews containing Mermaid fences SHALL asynchronously replace each loading placeholder with either a rendered SVG or the shared visible error fallback.

#### Scenario: View SKILL.md content

- **WHEN** admin clicks on a project skill and selects `SKILL.md`
- **THEN** the file content is displayed in a code/markdown viewer

#### Scenario: View Mermaid diagram in project SKILL.md

- **WHEN** admin selects a project `SKILL.md` containing a valid Mermaid fence
- **THEN** the preview renders an SVG diagram after the Markdown DOM is inserted
- **AND** the Mermaid container does not remain in the pending or rendering state

#### Scenario: Invalid Mermaid in project SKILL.md degrades visibly

- **WHEN** admin selects a project `SKILL.md` containing invalid Mermaid syntax
- **THEN** the preview displays the shared Mermaid error and source fallback
- **AND** the loading indicator is removed

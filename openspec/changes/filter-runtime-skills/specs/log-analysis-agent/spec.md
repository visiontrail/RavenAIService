## ADDED Requirements

### Requirement: Log analysis skill selection uses request and attachment evidence

Before materializing Skills, `LogAnalysisAgent` SHALL build relevance evidence from the current question, hints, issue description/service/environment metadata, and original log/archive filenames. It SHALL pass this evidence and the resolved `project_code` to the shared relevant-Skill materializer.

#### Scenario: Ka antenna archive excludes unrelated skills

- **WHEN** the question concerns a Ka receive-antenna beam conversion status anomaly
- **AND** the input is a `.tar.gz` log archive
- **THEN** `ka-phased-array-antenna` is eligible for selection
- **AND** unrelated `payload-management-unit`, `tcpt027-db-modify`, `xlsx`, and `docx` Skills are not selected without independent positive evidence

#### Scenario: Spreadsheet attachment selects spreadsheet support

- **WHEN** the question asks to analyze an attached `.xlsx` workbook
- **THEN** the `xlsx` Skill is eligible for selection using the filename/type evidence


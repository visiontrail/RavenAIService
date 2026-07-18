## ADDED Requirements

### Requirement: Analysis result carries a structured code-fix signal

The log analysis result schema SHALL be extended with two fields that drive downstream bug-fix dispatch:

- `requires_code_fix` (boolean): whether the analysis concludes that source code must be changed to resolve the issue;
- `proposed_fixes` (array): each element describing one independent proposed fix with at minimum `title`, `description`, and `rationale`, and optionally `suspected_files` and `suspected_symbols`.

The agent's prompt SHALL instruct the model to set `requires_code_fix: true` and populate `proposed_fixes` only when the evidence points to a concrete code defect, and to set `requires_code_fix: false` otherwise (configuration issues, operational guidance, pure Q&A, etc.). When the model omits these fields (legacy/older responses), the system SHALL default `requires_code_fix` to `false` and `proposed_fixes` to an empty list so existing behavior is unaffected.

#### Scenario: Code defect populates the signal

- **WHEN** the agent concludes a null-pointer bug in the source code is the root cause
- **THEN** the result includes `requires_code_fix: true` and a `proposed_fixes` entry describing the fix with a `rationale` tied to the root cause

#### Scenario: Non-code issue clears the signal

- **WHEN** the agent concludes the issue is a misconfiguration, not a code defect
- **THEN** the result includes `requires_code_fix: false` and an empty `proposed_fixes`

#### Scenario: Legacy response defaults safely

- **WHEN** a model response omits `requires_code_fix` and `proposed_fixes`
- **THEN** the persisted result defaults `requires_code_fix` to `false` and `proposed_fixes` to `[]`
- **AND** no bug fix task is dispatched

## 1. Relevant Skill Selection

- [x] 1.1 Implement deterministic Agent/project candidate scoring with bounded body reads, attachment-aware evidence, no-match-empty behavior, project precedence, and a default maximum of three.
- [x] 1.2 Add unit tests for Ka-domain selection, unrelated Skill exclusion, document suffix gating, no-match behavior, ranking, and same-name project override.

## 2. Agent Integration

- [x] 2.1 Build request evidence and use relevant-Skill materialization in log analysis and project expert runs.
- [x] 2.2 Apply the shared relevant-Skill materializer to general, device, and configuration-manager runs without weakening mandatory packaging safety gates.
- [x] 2.3 Add/update agent tests proving only selected candidates are materialized and advertised.

## 3. Trace Semantics and UI

- [x] 3.1 Extend Python/TypeScript trace schemas with `available_skills` and emit `skills_available` lifecycle metadata while retaining a temporary legacy alias.
- [x] 3.2 Split frontend aggregation and rendering into available versus actually loaded Skill rows, including historical trace compatibility and bilingual labels.
- [x] 3.3 Add frontend tests proving lifecycle candidates are not counted as loaded and `Skill` tool steps are.

## 4. Documentation and Verification

- [x] 4.1 Update the trace/log-analysis documentation for candidate selection and availability/invocation semantics.
- [x] 4.2 Run focused backend tests, frontend unit/type checks, formatting/diff checks, and the relevant full suites.
- [ ] 4.3 Commit the scoped RavenAIService change, deploy the exact commit to nr-test, and verify health plus a Browser-visible production task trace that excludes unrelated Skills.

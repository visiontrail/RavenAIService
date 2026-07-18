## 1. Project card data contract

- [x] 1.1 Rename the ProjectRepo model field from optional description to required project_card and add normalization/validation in the service layer
- [x] 1.2 Add an Alembic migration that preserves descriptions, backfills incomplete legacy cards, enforces NOT NULL, and supports downgrade
- [x] 1.3 Replace description with required project_card in admin/public API schemas and responses
- [x] 1.4 Add/update backend tests for create, update, response, and migration-compatible project-card behavior

## 2. Safe Agent project discovery

- [x] 2.1 Add a bounded service-layer catalog query/serializer that returns enabled projects and Agent bindings only
- [x] 2.2 Add the credential-free mcp__project_repo__discover_projects tool to the shared project_repo MCP server
- [x] 2.3 Add tests proving discovery returns complete project cards while excluding disabled and sensitive fields

## 3. Agent project-fit behavior

- [x] 3.1 Enable discovery-only MCP access for GeneralAgent and add recommendation/no-match/fallback prompt rules
- [x] 3.2 Enable discovery alongside lookup for ProjectExpertAgent and persist the selected project card in its workspace
- [x] 3.3 Enable discovery alongside lookup for LogAnalysisAgent and persist project cards in resolved/selected repo_info
- [x] 3.4 Add/update Agent tests for tool allowlists, safe provider fallback, selected-card context, and mismatch response instructions

## 4. Project-card user experience

- [x] 4.1 Replace description with required project_card in frontend types and project-management form/list UI
- [x] 4.2 Add Chinese and English Project Card labels, guidance, and required validation messages
- [x] 4.3 Show bounded project-card summaries and full-card guidance in the chat project selector
- [x] 4.4 Update frontend tool display naming and tests/build coverage for project discovery

## 5. Verification

- [x] 5.1 Run focused backend tests for project registry, Agents, workspace metadata, and MCP discovery
- [x] 5.2 Run frontend type-check/tests/build and resolve regressions
- [x] 5.3 Run OpenSpec validation and mark all implementation tasks complete

## 6. Custom-provider discovery regression

- [x] 6.1 Treat Anthropic-compatible custom endpoints as supporting SDK in-process MCP tools so project discovery is not removed before an Agent run
- [x] 6.2 Add regression coverage for custom-provider option passthrough and ProjectExpertAgent project discovery, then run focused validation

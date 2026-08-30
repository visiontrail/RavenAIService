## 1. Workspace-bound project clone tool

- [x] 1.1 Add the `clone_project_repo` tool constant, per-workspace full MCP server factory, Agent-binding checks, and credential-free response contract
- [x] 1.2 Implement deterministic primary/related paths, containment checks, repository limits, idempotent reuse, shallow partial clone, timeout, and sanitized failure cleanup
- [x] 1.3 Atomically persist non-sensitive `task.json.related_repos` provenance after clone or reuse

## 2. Project-bound Agent integration

- [x] 2.1 Bind the full project-repository MCP server to Project Expert workspaces and allow the clone tool while preserving GeneralAgent discovery-only isolation
- [x] 2.2 Bind the full project-repository MCP server to Log Analysis workspaces and allow the clone tool
- [x] 2.3 Replace redirect-only project-fit prompts with wrong-project recovery and joint multi-project analysis instructions in Chinese and English paths

## 3. Tests and documentation

- [x] 3.1 Add MCP/tool tests for registration isolation, safe clone responses, SSH-compatible environment inheritance, reuse, limits, containment, conflicts, failure cleanup, and manifest persistence
- [x] 3.2 Add Project Expert and Log Analysis regressions for workspace binding, tool allowlists, provider fallback, and multi-project prompt behavior
- [x] 3.3 Update Agent documentation and run focused backend tests plus OpenSpec validation

## 4. Commit, production deployment, and end-to-end verification

- [x] 4.1 Review the scoped diff, verify no credential or unrelated change is included, and commit the RavenAIService implementation
- [x] 4.2 Inspect `nr-test` production Git/Docker state, deploy the exact commit with the SSH overlay, and verify scoped container/image/health/API state
- [x] 4.3 Verify the new tool clones `LX07A-协议栈` through the production container and persists the expected multi-repository workspace provenance
- [ ] 4.4 In Browser/Computer, select `灵犀07A操作维护`, run the specified Project Expert ephemeris-log request, and confirm discovery, additional protocol-stack clone, source-grounded answer, persisted trace/result, and browser-visible completion

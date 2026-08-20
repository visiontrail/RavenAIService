## 1. Error Classification

- [x] 1.1 Add a typed, sanitized upstream API error and structured/legacy frame extraction helpers in `routed_query.py`
- [x] 1.2 Quarantine candidate error frames until confirmation while preserving TTFT, ordering, failover, and committed-attempt safety

## 2. Verification Coverage

- [x] 2.1 Add regression fixtures and tests for structured errors, the production 402 sequence, fallback success, all-endpoint failure, false positives, sanitization, and no retry after commit
- [x] 2.2 Update routed model operational documentation and validate the OpenSpec change
- [x] 2.3 Run targeted router tests and the proportionate backend test suite

## 3. Runtime Acceptance

- [x] 3.1 Review the scoped diff, create the required git commit, and rebuild/start the local Docker Compose stack
- [x] 3.2 Verify container health plus deterministic routed-error behavior inside the running backend image
- [x] 3.3 Use the in-app Browser to verify the local RavenAI UI and its user-visible terminal behavior

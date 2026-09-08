## Why

BugFix currently shares the analysis endpoint and does not expose its model override in Admin. Its asynchronous workspace loses questions, grouped uploads and screenshot context, while incomplete outcomes can incorrectly count as success.

## What Changes

- Add an independent BugFix endpoint, model and execution limits to runtime Admin settings.
- Require independent evidence review; explicitly reject incorrect repair proposals with reasons.
- Preserve the source analysis context and original attachments across dispatch and retries.
- Preserve actionable SDK failures and enforce complete outcome accounting.
- Replay existing production failure scenarios in local Docker.

## Capabilities

### New Capabilities

- `independent-bug-fix-review`: Dedicated model configuration, evidence handoff and independent review outcomes.

### Modified Capabilities

## Impact

BugFix agent/workspace/task/service, log-analysis dispatch paths, nullable task context fields, Admin model settings, BugFix details, regression tests and agent documentation. Production inspection is read-only; verification uses local Docker.

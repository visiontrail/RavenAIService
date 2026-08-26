## 1. Backend Attribution

- [x] 1.1 Add the normalized `ai_analysis_triggered_by` response field and resolve result, active-task, and legacy AI Chat attribution with the specified precedence.
- [x] 1.2 Capture the optional current-user snapshot when standalone analysis is enqueued and preserve it in terminal Celery results.
- [x] 1.3 Add backend regression tests for completed, active, anonymous, unavailable, grouped, and historical attribution cases.

## 2. Responsive Log List

- [x] 2.1 Extend the frontend log type and add deterministic trigger-user display formatting.
- [x] 2.2 Add the bilingual desktop column and mobile metadata item, including anonymous and unavailable states.
- [x] 2.3 Add frontend regression tests for formatter behavior and catalog parity.

## 3. Verification

- [x] 3.1 Run targeted backend tests, frontend tests, and frontend type checking.
- [x] 3.2 Build and restart the local Docker service, then verify the list API and rendered log-list UI end to end.
- [x] 3.3 Review the final diff, confirm only scoped files are staged, and commit the completed change.

## 1. Configuration

- [x] 1.1 Add independently validated BugFix endpoint and execution settings with Admin UI/probe.
- [x] 1.2 Pin BugFix runs to the independent endpoint and preserve model/error provenance.

## 2. Evidence and decisions

- [x] 2.1 Preserve exact analysis context, grouped logs and screenshot originals across dispatch/retry.
- [x] 2.2 Add explicit rejected outcomes, complete accounting and actionable SDK failure details.
- [x] 2.3 Update bilingual UI and agent documentation.

## 3. Verification

- [x] 3.1 Add and run focused behavioral regressions and frontend checks.
- [x] 3.2 Replay both existing production scenarios with the advanced model in local Docker; verify the enum repair, independent model settings and evidence-based rejection in the browser.
- [x] 3.3 Review scoped diff and commit implementation on main without pushing.
- [ ] 3.4 Verify the completed SMC replay detail and final container health after Docker Desktop recovers from its internal API outage.

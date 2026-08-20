## 1. Shared Preview Lifecycle

- [x] 1.1 Add a focused Vue composable that waits for rendered Markdown DOM updates and invokes the shared Mermaid processor for the current preview root.
- [x] 1.2 Add unit coverage for the composable's initial, content-change, and preview-root behavior.

## 2. Admin Skill Surfaces

- [x] 2.1 Wire the Agent Skill Markdown preview root and rendered content into the Mermaid preview lifecycle.
- [x] 2.2 Wire the Project Skill Markdown preview root and rendered content into the Mermaid preview lifecycle.

## 3. Verification

- [x] 3.1 Run focused frontend tests, the full frontend test suite, type checking, and the production build.
- [x] 3.2 Validate in the running admin UI that a Skill Markdown Mermaid block reaches rendered SVG state and no longer displays the loading placeholder.
- [x] 3.3 Review the final diff, confirm unrelated worktree changes remain untouched, and commit the scoped change.

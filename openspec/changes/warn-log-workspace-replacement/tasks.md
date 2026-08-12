## 1. Session-scoped attachment context

- [x] 1.1 Add tested helpers for detecting persisted log-attachment history, deciding when replacement confirmation is required, and normalizing confirmation outcomes
- [x] 1.2 Track existing log workspace context per conversation from `log_analysis_context` events and persisted history without leaking state across sessions

## 2. Replacement confirmation UX

- [x] 2.1 Add localized zh/en title, explanation, workflow guidance, and action labels for the replacement confirmation
- [x] 2.2 Gate `AIChat.vue` log-analysis sends on the confirmation and preserve the current composer when the prompt is closed
- [x] 2.3 Implement the new-conversation action so pending log attachments and project selection survive reset without automatically sending

## 3. Verification

- [x] 3.1 Add Vitest coverage for first upload, replacement upload, confirm, close, new-conversation, non-log/image-only requests, history restoration, and session isolation
- [x] 3.2 Run focused Vitest, the frontend i18n checks, and `npm run type-check`
- [x] 3.3 Review the final diff and OpenSpec task status for scope and consistency

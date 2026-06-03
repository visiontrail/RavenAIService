## Why

The system is currently Chinese-only: every frontend label, every prompt sent to the AI agents, and every AI-generated result (analysis reports, chat replies, session titles) is hardcoded in Chinese. To serve English-speaking users we need a single language preference that switches **the entire experience** — UI chrome, server-generated text, the prompts we send to the model, and the language the model answers in. Adding this now, while only two languages (`zh`, `en`) are in scope, lets us establish the locale plumbing before more languages or surface area accrue.

## What Changes

- Introduce a system-wide locale concept with two supported languages: Simplified Chinese (`zh`) and English (`en`), `zh` as the default.
- Add a language preference that is **persisted per authenticated user** and remembered for anonymous visitors (browser storage), with sensible detection from `Accept-Language` on first visit.
- Add a frontend i18n layer (vue-i18n) and extract all hardcoded UI strings into `zh` / `en` message catalogs, including Element Plus component locale and date/number formatting.
- Propagate the active locale to the backend on every request (header) and persist it via the user profile API.
- Localize all **server-generated, user-facing** text (API messages, validation errors, notifications, status labels).
- Make **AI interaction** language-aware: prompt templates (system + user) gain `zh` / `en` variants, the active locale is passed into every agent run, and prompts instruct the model to **respond in the active language** so analysis reports, chat answers, and generated session titles come back in the selected language.
- Update the admin prompt editor so prompts can be authored/edited per language.
- **BREAKING**: `prompts_config.yaml` structure changes from single-language prompt bodies to per-language variants; existing agent prompt-loading code must select by locale.

## Capabilities

### New Capabilities
- `localization`: Defines supported languages, default/fallback rules, language detection, per-user and anonymous persistence, the request-to-backend locale propagation contract, frontend UI string localization, and localization of server-generated user-facing text.
- `localized-ai-interaction`: Defines how the active locale drives AI behavior — per-language prompt templates, passing locale into every agent run, instructing the model to answer in the active language, and localization of agent-produced artifacts (analysis output, chat replies, session titles).

### Modified Capabilities
<!-- No existing spec's requirements change; AI language behavior is captured as a new cross-cutting capability rather than amending each agent spec. -->

## Impact

- **Frontend**: add `vue-i18n` dependency; new `i18n/` message catalogs and locale composable; `app.ts`/`user.ts` stores gain locale state; all `views/`, `components/`, `layouts/` strings extracted; Element Plus `locale` wired; API client (`api/index.ts`) sends an `Accept-Language`/locale header.
- **Backend**: `app/models/user.py` (+ Alembic migration) gains a `language` column; user profile read/update API exposes it; a request-scoped locale resolver (header → user pref → default); localized message catalog for API/validation/notification text.
- **AI / prompts**: `app/prompts/prompts_config.yaml` restructured to per-language variants; agent `prompts.py` modules (`log_analysis`, `device_agent`, `project_expert`, `package_search`, `general_agent`) and the chat title prompt select templates by locale and inject a "respond in <language>" directive; `prompts_config_service.py` and `AdminPrompts.vue` updated for per-language editing.
- **Tests**: existing prompt/agent tests updated for the new prompt structure; new tests for locale resolution, persistence, and AI language directive.

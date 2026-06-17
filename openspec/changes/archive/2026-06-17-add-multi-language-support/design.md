## Context

The product is Chinese-only end to end. The frontend (Vue 3 + Element Plus + Pinia) has **no i18n library** and hardcodes Chinese literals throughout `views/`, `components/`, and `layouts/`. The backend (FastAPI + Celery) returns Chinese user-facing messages inline. All AI prompts live in a single `app/prompts/prompts_config.yaml` with Chinese-only bodies, loaded per agent by small `prompts.py` modules (`get_prompts()` / `render_user_prompt()` doing plain `{placeholder}` replacement) and editable through `prompts_config_service.py` + `AdminPrompts.vue`. The `User` model has no language column.

The defining constraint from the request: **everything** switches with the language — UI, server-generated text, the prompts we send the model, and the language the model answers in. This is cross-cutting (frontend, API, models, async tasks, prompts) and changes the `prompts_config.yaml` data shape, so a design doc is warranted.

## Goals / Non-Goals

**Goals:**
- One language preference that drives the whole stack, with `zh` (default) and `en`.
- A single locale-resolution chain: request header → authenticated user preference → default.
- Per-user server-side persistence and anonymous browser persistence.
- AI prompts available per language; AI instructed to answer in the active language even when input data is in another language.
- Keep admin prompt editing working, now per language.

**Non-Goals:**
- More than two languages (the structure must not preclude it, but no third locale is built).
- Translating user-generated content or stored historical data (old AI reports stay in whatever language they were produced).
- Localizing internal logs / developer diagnostics.
- Machine-translating existing prompts perfectly — initial `en` prompt bodies are authored deliberately, not auto-translated.
- RTL layouts.

## Decisions

### 1. Frontend: vue-i18n with two flat catalogs
Use `vue-i18n` (Composition API mode). Message catalogs live in `frontend/src/i18n/{zh,en}.ts` with a shared key structure; an `index.ts` exports the supported-locale list (single source of truth) and the configured `i18n` instance. Wire Element Plus via its `el` locale packs keyed off the active locale, and use vue-i18n's date/number formats.
- *Why not hand-rolled?* vue-i18n is the de-facto Vue standard, handles reactivity, pluralization, Element Plus integration, and lazy formatting for free.
- *Trade-off:* a large one-time string-extraction effort. Mitigated by doing it view-by-view and adding a catalog-parity check (every key in both catalogs).

### 2. Locale state: app store + persistence layering
`app.ts` (Pinia) holds the reactive `locale`. Resolution on boot: if authenticated, use profile `language`; else use `localStorage`; else detect from `navigator.language` (`en*` → `en`, else `zh`). Switching updates the store + `localStorage`, sets vue-i18n + Element Plus locale, and — if authenticated — PATCHes the profile.
- *Why store, not route/query?* Language is a cross-app preference, not navigation state; no reload needed.

### 3. Backend locale resolution: request-scoped dependency
A FastAPI dependency resolves locale per request: `Accept-Language`-style custom header (frontend always sends it) → `current_user.language` → default `zh`. User-facing backend strings move into a small message catalog (`app/i18n/` dict keyed by locale + message id) accessed through a `t(key, locale)` helper. For async/Celery tasks there is no request; the task receives the owner's `language` (resolved when the task is enqueued) and passes it down.
- *Why a custom header vs. `Accept-Language`?* The app's explicit choice can diverge from the browser's `Accept-Language`; an app-controlled header avoids ambiguity. (Implementation may reuse `Accept-Language` if simpler — the contract only requires the active locale to travel on every request.)

### 4. User model: add `language` column
Add `language VARCHAR(8) NOT NULL DEFAULT 'zh'` to `users` via a new Alembic migration, validated against supported codes on update. Surface it in the profile read/update API and `UserProfile` type.

### 5. Prompts: per-language variants in YAML
Restructure each prompt body to a per-language map. Two shapes are viable:
```yaml
claude_agent_log_analysis:
  generic:
    system_prompt:
      zh: |
        ...
      en: |
        ...
    user_prompt_template:
      zh: |
        ...
      en: |
        ...
```
`get_prompts()` gains a `locale` argument and selects the body, falling back to `zh` when a variant is missing. `render_user_prompt()` placeholder logic is unchanged. `prompts_config_service.py` reads/writes the nested per-language bodies; `AdminPrompts.vue` shows a language tab/selector per prompt.
- *Why nest by language inside each field (vs. a top-level `zh:`/`en:` tree)?* Keeps each prompt's variants adjacent for editing and diffing, and makes "missing variant → fallback" a local lookup.
- *Migration of existing content:* current Chinese bodies become the `zh` variant verbatim; `en` variants are authored alongside.

### 6. Response-language directive
Rather than relying on prompt prose alone, each agent run appends a short, explicit directive ("Respond entirely in English / 请全程使用中文回答") derived from the active locale, injected near the end of the system prompt. This guarantees the answer language is decoupled from the (possibly mixed-language) input data such as logs or source code.
- *Why a separate directive in addition to language-specific bodies?* Defense in depth — even a translated prompt body can drift; an explicit final instruction is the most reliable lever on output language.

## Risks / Trade-offs

- **Incomplete string extraction** → leftover hardcoded Chinese in the UI. Mitigation: catalog-parity check + a grep/lint pass for CJK literals in `.vue`/`.ts` outside the catalogs during implementation.
- **Model ignores the language directive on mixed-language input** → answer leaks the input's language. Mitigation: put the directive last and make it imperative; verify with the "English answer over Chinese log" scenario.
- **Prompt YAML restructure breaks existing agents/tests (BREAKING)** → runtime errors. Mitigation: loader fallback to `zh`; update all `prompts.py` callers and prompt tests in the same change; keep placeholder semantics identical.
- **Background tasks lack a request locale** → reports come back in the wrong language. Mitigation: resolve owner `language` at enqueue time and thread it through the task signature.
- **Stale prompt cache after admin edit** → edits don't take effect. Mitigation: keep existing cache-clear-on-save behavior and cover it with the cache-invalidation scenario.
- **Anonymous→authenticated precedence confusion** → user's saved choice gets overwritten by browser value. Mitigation: profile preference wins on login; only persist to profile when the user explicitly switches while authenticated.

## Migration Plan

1. Backend: add `language` column + migration; add locale resolver + backend message catalog; extend profile API/type. Deploy is backward compatible (default `zh`).
2. Prompts: restructure `prompts_config.yaml` to per-language, populate `zh` from current bodies, author `en`; update all `prompts.py` loaders + `prompts_config_service` + tests.
3. Frontend: add vue-i18n, build catalogs, extract strings view-by-view, add language switcher, send locale header, wire Element Plus + formatting.
4. Rollback: revert frontend independently (backend tolerates absent header). Backend column can remain (nullable-safe default) even if frontend rolled back. Prompt YAML revert requires reverting loader changes together — ship them as one unit.

## Open Questions

- Header name: reuse standard `Accept-Language` or a custom `X-App-Locale`? (Leaning custom to separate explicit choice from browser hints; either satisfies the spec.)
- Should historical AI artifacts (existing session titles, stored reports) be left as-is? (Assumed yes — non-goal.)
- Where does the language switcher live in the layout — top bar vs. user menu? (UX detail, decided during implementation.)

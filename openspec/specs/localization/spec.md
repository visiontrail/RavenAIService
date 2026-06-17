## ADDED Requirements

### Requirement: Supported languages and default

The system SHALL support exactly two languages — Simplified Chinese (`zh`) and English (`en`) — identified by these locale codes. `zh` SHALL be the default and the fallback when a requested or stored locale is unknown or unsupported.

#### Scenario: Unknown locale falls back to default

- **WHEN** any layer (frontend, backend, AI) is asked to operate with a locale code that is not `zh` or `en`
- **THEN** it SHALL behave as if the locale were `zh` and SHALL NOT raise an error to the user

#### Scenario: Adding a language is localized data, not code

- **WHEN** a maintainer reviews the supported-language list
- **THEN** the set of codes SHALL be defined in one shared place per layer (frontend catalog index, backend locale constant) so the system has a single source of truth for "what languages exist"

### Requirement: First-visit language detection

For a visitor with no stored preference, the system SHALL detect an initial language from the browser's `Accept-Language` / `navigator.language`, choosing `en` when the primary language tag starts with `en` and `zh` otherwise.

#### Scenario: English browser, no stored preference

- **WHEN** an anonymous visitor whose browser primary language is `en-US` loads the app for the first time
- **THEN** the UI SHALL render in English

#### Scenario: Other-language browser, no stored preference

- **WHEN** an anonymous visitor whose browser primary language is neither English nor Chinese (e.g. `ja`) loads the app
- **THEN** the UI SHALL render in `zh` (the default)

### Requirement: User can switch language

The system SHALL provide a visible UI control to switch between supported languages. Switching SHALL take effect immediately across the running UI without a full page reload.

#### Scenario: Switching updates the live UI

- **WHEN** the user selects a different language from the language control
- **THEN** all visible UI text, Element Plus component text, and date/number formatting SHALL re-render in the selected language without losing the user's current view or unsaved input

### Requirement: Language preference persistence

The selected language SHALL persist across sessions. For an authenticated user it SHALL be stored on the user profile server-side; for an anonymous visitor it SHALL be stored in browser storage. On login, the user's server-side preference SHALL take precedence over any anonymous browser value.

#### Scenario: Anonymous preference persists across reloads

- **WHEN** an anonymous visitor switches to English and later reloads the app
- **THEN** the UI SHALL render in English without re-detecting from the browser

#### Scenario: Authenticated preference persists across devices

- **WHEN** a user sets their language to English and later signs in on a different device
- **THEN** the UI SHALL render in English because the preference is loaded from their profile

#### Scenario: Logged-in switch is saved to the profile

- **WHEN** an authenticated user switches language
- **THEN** the system SHALL persist the new value to the user profile via the profile-update API

### Requirement: Locale propagation to the backend

Every request the frontend makes to the backend SHALL carry the active locale (via an HTTP header). The backend SHALL resolve the request locale in priority order: explicit request header, then the authenticated user's stored preference, then the default.

#### Scenario: Header drives server-generated text

- **WHEN** the frontend is in English and calls any backend endpoint that returns user-facing text
- **THEN** the request SHALL include the locale header and the backend SHALL produce that text in English

#### Scenario: Missing header falls back to user preference then default

- **WHEN** a backend request arrives without a locale header
- **THEN** the backend SHALL use the authenticated user's stored language if present, otherwise the default `zh`

### Requirement: User profile exposes language

The user profile read and update APIs SHALL include the user's `language` field, and the persisted user record SHALL store it.

#### Scenario: Profile read returns language

- **WHEN** the frontend fetches the current user profile
- **THEN** the response SHALL include the user's `language` value

#### Scenario: Profile update validates language

- **WHEN** a profile-update request sets `language` to an unsupported code
- **THEN** the update SHALL be rejected or coerced to a supported code, never stored as-is

### Requirement: Localized frontend UI strings

All user-facing UI strings SHALL be sourced from `zh` and `en` message catalogs rather than hardcoded literals. There SHALL be no untranslated hardcoded user-facing string left in views, components, or layouts.

#### Scenario: Every catalog key exists in both languages

- **WHEN** the message catalogs are validated
- **THEN** every key present in one language catalog SHALL also exist in the other, so no key renders as a raw key or empty string

#### Scenario: Element Plus and formatting follow the locale

- **WHEN** the UI is in a given language
- **THEN** Element Plus built-in component text (pagination, date pickers, table empty-text, etc.) and date/number formatting SHALL match that language

### Requirement: Localized server-generated user-facing text

Server-generated text intended for end users — API success/error messages, validation errors, notifications, and status labels returned to the client — SHALL be produced in the resolved request locale. Internal logs and developer-facing diagnostics are out of scope.

#### Scenario: Error message language matches request locale

- **WHEN** an English-locale request triggers a validation error (e.g. unsupported upload file type)
- **THEN** the error message returned to the client SHALL be in English

#### Scenario: Default locale for unattributed text

- **WHEN** the backend produces user-facing text outside any request context (e.g. a background task with no caller locale available)
- **THEN** it SHALL use the relevant owner's stored language if known, otherwise the default `zh`

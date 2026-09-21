## ADDED Requirements

### Requirement: Private persisted conversation retrieval
The system SHALL search the authenticated user's non-deleted conversation titles and visible message content by a literal case-insensitive substring, return each session once with a bounded matching excerpt, and paginate in stable most-recent order. Empty queries SHALL return recent sessions. Queries SHALL be bounded to 200 characters and pages to 50 results.

#### Scenario: Match inside an old assistant message
- **WHEN** a user searches text present only in an assistant message
- **THEN** its conversation is returned once with an excerpt containing that text

#### Scenario: Ownership and deletion isolation
- **WHEN** other users' sessions or deleted sessions contain the query
- **THEN** those sessions are not returned and unauthenticated search is rejected

#### Scenario: Literal special characters and pagination
- **WHEN** the query contains percent, underscore or backslash characters
- **THEN** those characters are matched literally and subsequent result pages do not repeat sessions for unchanged data

### Requirement: Familiar accessible search dialog
The sidebar magnifier and Cmd/Ctrl+K SHALL open a centered modal with a focused search input. It SHALL show recent conversations on opening, a new-chat action, matched titles and excerpts, time grouping, and keyboard selection with Up/Down and Enter. Escape and backdrop clicks SHALL close it and restore focus. Tab SHALL remain inside the modal. Selecting a result SHALL reopen its conversation through the existing session flow.

#### Scenario: Keyboard-only retrieval
- **WHEN** a user opens search with Cmd/Ctrl+K, types, moves with arrow keys and presses Enter
- **THEN** the selected conversation opens and the dialog closes

#### Scenario: Guest and account changes
- **WHEN** a guest invokes search or a logged-in user signs out
- **THEN** the guest sees login and previous search results do not remain accessible after logout

### Requirement: Responsive predictable search state
The UI SHALL debounce queries, suppress stale responses, respect IME composition, render highlight text safely, and provide loading, empty, retryable error and pagination states. It SHALL support Chinese/English, light/dark themes and narrow viewports.

#### Scenario: Out-of-order results
- **WHEN** a slow earlier search finishes after the user changes the query or closes the dialog
- **THEN** it cannot overwrite the current search state

#### Scenario: Search fails
- **WHEN** the request fails
- **THEN** an error with a retry action is shown without falsely reporting no matches

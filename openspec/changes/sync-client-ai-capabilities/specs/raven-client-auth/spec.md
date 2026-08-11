## ADDED Requirements

### Requirement: RavenClient is globally gated by RavenAIService authentication

RavenClient SHALL validate a shared RavenAIService user session before rendering its application shell, routes, sidebar, embedded webviews, or Assistant UI. A missing, expired, or invalid bearer token MUST show the global authentication view and MUST NOT fall back to a local-only model session.

#### Scenario: Stored session restores at startup

- **WHEN** RavenClient starts with a stored valid RavenAIService bearer token
- **THEN** it MUST validate the token through the user profile endpoint
- **AND** it MUST load the client AI capability snapshot before rendering the application shell

#### Scenario: Invalid session returns to authentication

- **WHEN** startup profile validation returns HTTP 401 or 403
- **THEN** RavenClient MUST clear the stored bearer token and all in-memory AI capabilities
- **AND** it MUST render the global authentication view

#### Scenario: Service is unreachable at startup

- **WHEN** RavenClient cannot reach RavenAIService while validating authentication or loading capabilities
- **THEN** it MUST keep the application shell gated
- **AND** it MUST display the service endpoint, a connection error, and a retry action

### Requirement: Users can register and log in from the global authentication view

The global authentication view SHALL support login with username/password and registration with username, password, confirmation, display name, and email using the existing RavenAIService user APIs. A successful response MUST store the returned shared bearer token and initialize the same application session used by the Agents tab.

#### Scenario: User registers from RavenClient

- **WHEN** a user submits valid registration fields from the global view
- **THEN** RavenClient MUST call `/api/v1/users/auth/register`
- **AND** it MUST store the returned token, load capabilities, and enter the application as the returned user

#### Scenario: Registration validation is visible

- **WHEN** passwords do not match or RavenAIService rejects a registration field
- **THEN** RavenClient MUST remain on the registration view
- **AND** it MUST show a field or form error without storing a token

#### Scenario: User logs in from RavenClient

- **WHEN** a user submits valid login credentials
- **THEN** RavenClient MUST call `/api/v1/users/auth/login`
- **AND** the resulting profile and token MUST be shared by Assistant and Agents

### Requirement: Logout clears shared user and AI state

RavenClient SHALL expose logout from the authenticated application chrome. Logout MUST clear the stored RavenAIService token, raw in-memory provider credentials, synchronized service model metadata, and the active user attachment in the Agents conversation store.

#### Scenario: User logs out

- **WHEN** an authenticated user selects logout
- **THEN** RavenClient MUST clear all shared auth and AI runtime state
- **AND** it MUST return to the global authentication view without rendering the prior user's content

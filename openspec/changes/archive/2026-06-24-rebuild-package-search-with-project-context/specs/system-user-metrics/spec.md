## MODIFIED Requirements

### Requirement: Business-domain metrics summarize current system activity

The system SHALL include non-Token business metrics in admin system overview responses using existing domain data and newly recorded business events. At minimum, the overview MUST include user/chat activity, log upload and AI analysis activity, package inventory and package activity, and device connection summary. Package activity events (`package_activity`) MUST record the associated `project_code` (or `unassociated`) in event metadata instead of the removed package type; the Prometheus `raven_package_activity_total` counter MUST drop its `package_type` label and keep only low-cardinality `action` and `status` labels (project identifiers MUST NOT appear as Prometheus labels).

#### Scenario: Overview includes chat and user activity

- **WHEN** an admin reads the system overview
- **THEN** the response MUST include total users, active users in range, chat session count, chat message count, and chat Agent run counts by status

#### Scenario: Overview includes log activity

- **WHEN** an admin reads the system overview
- **THEN** the response MUST include log upload count, uploaded bytes, counts by `log_type`, counts by processing status, and AI analysis terminal counts when available

#### Scenario: Overview includes package activity

- **WHEN** an admin reads the system overview
- **THEN** the response MUST include Raven package count, package total bytes, package distribution by project (with an `unassociated` bucket), package upload/download activity when recorded, and package search AI usage counts

#### Scenario: Package activity event carries project dimension

- **WHEN** a package is uploaded or downloaded after this change
- **THEN** the persisted `package_activity` event metadata MUST contain `project_code` (or `unassociated`) and MUST NOT introduce new `package_type` values

#### Scenario: Prometheus package activity counter stays low-cardinality

- **WHEN** `GET /metrics` is scraped after a package upload
- **THEN** `raven_package_activity_total` series MUST only carry `action` and `status` labels, with no package type or project identifier label

#### Scenario: Overview includes device activity

- **WHEN** an admin reads the system overview
- **THEN** the response MUST include current device connection counts by state when available
- **AND** DeviceAgent invocation and Token usage MUST be included in AI metrics groups

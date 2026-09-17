## ADDED Requirements

### Requirement: Standard image file transport
The log-analysis, project-expert and package-search multipart endpoints SHALL accept repeated `image_files` uploads and preserve image bytes and order for the existing OCR workflow. Existing image size and count settings SHALL remain authoritative.

#### Scenario: Images exceed one MiB in aggregate
- **WHEN** valid images total more than one MiB and remain within configured image limits
- **THEN** each endpoint accepts them and forwards their unchanged bytes to its service

#### Scenario: Legacy image JSON
- **WHEN** an older client sends an `images` JSON form field larger than one MiB within configured image limits
- **THEN** the endpoint accepts it without requiring a client upgrade

### Requirement: Actionable upload rejection
The service SHALL reject oversized images with HTTP 413 and a localized message identifying the image, size, configured limit and corrective action. Malformed images and excessive image counts SHALL return explicit HTTP 400 errors before starting any agent run. Multipart field overflow SHALL return an actionable HTTP 413 with the applicable field limit.

#### Scenario: Image exceeds the configured size
- **WHEN** one binary or legacy image is above the configured per-image limit
- **THEN** the response states its index, actual size, limit and a compression or split-upload suggestion

#### Scenario: Invalid or excessive attachments
- **WHEN** image format or total count violates configured rules, including mixed legacy and binary inputs
- **THEN** the request is rejected with a specific localized reason and no analysis starts

### Requirement: Visible HTTP failure details
The conversation UI SHALL preserve readable API errors and distinguish HTTP rejections from transport failures. Non-JSON proxy errors SHALL use localized status-specific messages without displaying proxy HTML.

#### Scenario: Structured rejection and proxy rejection
- **WHEN** an upload receives a JSON validation error or an HTML HTTP 413
- **THEN** the user sees the validation detail or an explicit upload-too-large message with corrective action

#### Scenario: Connection failure
- **WHEN** the browser cannot obtain an HTTP response
- **THEN** the user sees the connection failure message and the pending run exits its sending state

#### Scenario: First upload in a new conversation fails
- **WHEN** the first request in a newly created conversation receives an asynchronous rejection
- **THEN** the visible answer immediately changes from the thinking placeholder to the rejection without navigation or reload

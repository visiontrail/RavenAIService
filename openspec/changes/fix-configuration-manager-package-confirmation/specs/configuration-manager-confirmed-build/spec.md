## ADDED Requirements

### Requirement: Confirmation constraints survive transport
The system SHALL preserve explicit custom-answer constraints in mandatory confirmation and SHALL reject custom answers to questions with `allow_custom=false`. The webpage SHALL hide custom input for such questions. Explicit cancellation SHALL terminate without publication or a catalog-missing error.

#### Scenario: Unsupported project text
- **WHEN** a caller supplies custom text for the closed project question
- **THEN** confirmation fails before catalog selection or construction

#### Scenario: Cancelled project selection
- **WHEN** the user selects the cancellation option
- **THEN** the run ends as cancelled and no package is published

### Requirement: Supported LX07A builds
The built-in catalog SHALL include LX07A rules backed by its existing upgrade protocol and SHALL generate project-correct OAM/CUCP/CUUP/DU payloads from confirmed inputs. The system SHALL bind catalog rules to registered projects using only exact project codes or explicit catalog registry mappings, and SHALL preserve the selected registry identity when publishing.

#### Scenario: LX07A OAM and protocol package
- **WHEN** the user confirms the supplied LX07A OAM patch and protocol ZIP for a full package
- **THEN** the artifact contains four payloads with project-correct names, attributes and source component versions

#### Scenario: Catalog and registered project codes differ
- **WHEN** the catalog explicitly binds LX07A to registered project `oam_lx07a`
- **THEN** the confirmation and package metadata use `oam_lx07a` while the LX07A component rules remain authoritative

### Requirement: Verified prebuilt component extraction
The system SHALL allow prebuilt component extraction only with catalog opt-in and a validated package manifest matching the selected project and component. It MUST retain rejection of malformed, mismatched, unsafe or unsupported packages and MUST revalidate before building.

#### Scenario: Valid OAM patch
- **WHEN** a supported OAM patch has a matching manifest and payload
- **THEN** the component payload is extracted, its version is retained, and the new package receives a new manifest

#### Scenario: Mismatched manifest
- **WHEN** source manifest attributes, filenames, sizes or integrity fields disagree with the allowed component or actual payload
- **THEN** no artifact is published

### Requirement: Repeated browser acceptance
Acceptance SHALL include webpage attachment selection, submission, complete confirmation and download verification for LX07A 1.1.0.0, LX10 V1.0.0.3 and LX10 V1.0.0.2.

#### Scenario: Three independent release requests
- **WHEN** the three supplied release combinations are submitted in the browser
- **THEN** each produces a downloadable package whose contents, manifest and source hashes agree

## Why

Configuration Manager can accept a custom project answer that has no effective packaging catalog and then fail after confirmation. The shipped catalog lacks LX07A, and existing OAM patch packages cannot contribute their verified component payload to a new upgrade package.

## What Changes

- Preserve and enforce whether confirmation questions allow custom answers, and handle explicit cancellation before catalog resolution.
- Add LX07A packaging rules grounded in the existing client, upgrade protocol, and supplied release packages.
- Permit explicitly configured components to be extracted from a prebuilt package only after validating its manifest and matching project/component attributes.
- Verify repeated browser requests with the supplied LX07A and LX10 release files, including artifact downloads.

## Capabilities

### New Capabilities

- `configuration-manager-confirmed-build`: enforce valid project selection and support verified prebuilt component inputs.

### Modified Capabilities

None.

## Impact

Shared clarification normalization, the Vue confirmation card and trace types, Configuration Manager preflight, full-package catalog and builder, focused regression tests, and the package-search runbook. No database migration or device upgrade is required.

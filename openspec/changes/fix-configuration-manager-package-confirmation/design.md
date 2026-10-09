## Context

Packaging uses an immutable catalog snapshot, mandatory shared clarification, signed plans, bounded archive extraction, and atomic publication. The project question disables custom input at its source but loses this constraint in the shared trace/UI. LX07A has existing client and upgrade-protocol definitions but no built-in service catalog.

## Goals / Non-Goals

**Goals:** Accept supported project options, terminate cancellation clearly, combine validated OAM patch payloads with raw protocol archives, and prove actual browser delivery for three supplied release directories.

**Non-Goals:** Upgrade devices, guess unsupported FPGA attributes, migrate data, replace uploaded project rules, or change provider routing.

## Decisions

1. Preserve optional `allow_custom` and `required` through normalization and trace types. Mandatory validation rejects disallowed custom answers; the card hides that input. Legacy ordinary clarification retains its current custom-input default. Resolve cancellation before selecting a catalog.
2. Add a minimal `lingxi-07a` definition using OAM 301, CUCP 302, CUUP 307, DU 308, total 1001 and patch 1002. These values are established by RavenClient, LX07A upgrade headers, and the supplied patch manifest. Catalog `registry_project_codes` explicitly maps LX10 to `oam_lx10` and LX07A to `oam_lx07a`, the verified production registry codes. Resolve only exact codes or these declared bindings, retaining the registry code in confirmation and publication; never infer identity from labels or loose aliases. Project overrides continue to fail closed.
3. Use catalog opt-in for prebuilt component extraction. Parse a bounded, unambiguous `si.ini`, require a supported project packet attribute and exact component filename/FileAttr, and verify declared file count, sizes and integrity fields when present. Take component versions from the validated manifest. Unknown, malformed, mismatched or non-opted-in prebuilt packages remain blocked. Recheck at build time before materialization; never embed the source package as a payload.
4. Keep source/input/catalog hashes, complete confirmation, signed plans, override precedence and final verification unchanged.
5. Resolve the configured workspace base and restored context paths to absolute paths before staging uploads. Production uses the relative `temp/code_repos` default; storing that full cwd-relative prefix as a manifest pointer causes the builder to append the workspace twice. Keep the builder's existing absolute-or-workspace-relative contract and containment checks; do not add a cwd fallback or guess legacy path prefixes. A fresh attachment turn in an existing failed conversation must also regenerate valid paths and confirmation.

## Risks / Trade-offs

- Project Skill overrides can lack the new rules → preserve explicit override precedence and show actionable failure.
- Prebuilt packages differ in manifest fields → validate the documented format without inventing missing fields; test mismatches and bounded parsing.
- Production restart can interrupt chat runs → check active runs, preserve state, deploy only scoped services, and retain rollback image/source.

## Migration Plan

Run focused backend/frontend checks, commit only this task, synchronize the exact change to nr-test while preserving its untracked files, update scoped images, verify source parity and health, and perform three browser builds/download checks. Retain the prior image for rollback.

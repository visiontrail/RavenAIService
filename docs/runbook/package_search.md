# Configuration Manager (`package_search`) Runbook

The user-facing Agent name is **Configuration Manager** (Chinese:
**配置管理员**). The internal key remains `package_search` so existing project
bindings, conversations, metrics, and API clients remain compatible.

It supports two paths:

1. project-scoped package search, retained for compatibility; and
2. Skill-driven full upgrade package creation from uploaded component files.

## Skills

Configuration Manager loads Skills through the same host used by Project
Expert and Log Analysis. Runtime precedence is deterministic:

```text
built-in Skill -> uploaded Agent Skill -> project Skill
```

Later layers override an earlier Skill with the same name. The source tree
ships a built-in `full-package-build` Skill so packaging works out of the box;
administrators can extend or replace its rules without changing the Agent.
For an unbound upload, each visible project's catalog is evaluated in an
isolated preflight workspace so project-level rules can participate in the
initial inference. The selected project's Skill becomes the live workspace
layer only after confirmation; if that effective catalog changes the draft,
Raven reclassifies and asks the complete confirmation card again.

The component/project rule catalog is JSON-driven. A component entry contains
its stable key, display name, package/file attributes, matching evidence, build
strategy, and whether it is publishable. Recognition-only entries are useful
for preliminary classification but cannot be silently put into a release.

## Chat endpoint

Use the interactive endpoint for packaging:

`POST /api/v1/ai-chat/package-search/stream`

It accepts `multipart/form-data`:

| Field | Required | Notes |
| --- | --- | --- |
| `message` | no | Defaults to a full-package request when files are attached. |
| `session_id` | no | Server creates one when absent. |
| `project_repo_id` | search only | Required for a new pure-search session. Optional evidence for a packaging turn; it is not authoritative until confirmed. |
| `files` | packaging only | Repeat the same field for every component input. Any extension is accepted; type is detected independently. |
| `remember` | no | Persist the exchange when true. |
| `images` | no | Existing image/OCR JSON contract. |

The endpoint streams the normal `AgentTraceEvent` protocol. A terminal `done`
frame includes `artifacts`, and the rendered answer contains a relative Markdown
link such as `[下载整包](/raven/api/download/<package-id>)`.

Projects without a Git repository are valid Configuration Manager projects.
Git is optional project context, not a prerequisite for package configuration.

## Mandatory packaging workflow

An attachment-bearing turn always follows this server-enforced sequence:

1. Each upload is chunk-copied into an isolated turn directory. Raven records a
   stable upload ID, original name, detected type, byte size, SHA-256, and safe
   relative path in `input-manifest.json`.
2. The JSON catalog and built-in Skill inspect names and bounded archive content
   to propose a project, version/mode, and candidate component mapping with
   confidence and evidence. This is a draft only.
3. Raven emits one existing `clarification_request` card containing project
   confirmation and a question for **every uploaded file**. Multi-component
   sources use a multi-select question. Unknown, prebuilt-patch, and
   recognition-only files still receive a question and must be explicitly
   excluded or mapped by valid configuration.
4. The gate requires every answer, builds an immutable confirmed plan, binds it
   to the session/user/catalog/input hashes, and signs the complete plan with a
   short-lived server HMAC. User preferences that disable ordinary Agent
   clarification do not disable this packaging confirmation.
5. The dedicated builder validates the signature and plan again, safely
   materializes selected archives, writes `si.ini`, creates the TGZ, reopens it,
   and verifies its manifest, members, attributes, sizes, and hashes.
6. Only the service layer may publish. It copies the artifact atomically into
   the Raven package repository, atomically updates package metadata, and rolls
   the file back if registration fails.

No model decision can skip steps 3–6. General shell/write/web tools are hard
disabled in packaging mode, and the builder never publishes directly.

### Cancellation and failure

- A timeout, cancellation, missing answer, stale/tampered plan, changed input,
  invalid archive, unsupported confirmed component, or validation mismatch
  stops the run before repository publication.
- ZIP/TAR/GZIP/7z are handled in the isolated workspace. RAR uses the available
  `rarfile`, `unar`/`lsar`, or `bsdtar` backend. Traversal, links escaping the
  destination, entry-count/size limits, and decompression bombs are rejected.
- Duplicate original filenames remain distinct because upload IDs, not names,
  are the identity key.

## Search-only compatibility endpoint

`POST /raven/api/packages/agent-search` remains a project-bound one-shot search
API. Its JSON body requires `project_repo_id`; it does not accept component
uploads and must not be used to build a package because it has no interactive
clarification loop.

Package metadata is scoped by `projectCode`, sourced from
`project_repo.project_code`, instead of the legacy `packageType` enum. Legacy
records are lazily normalized while preserving their original key for rollback
compatibility.

## Configuration

| Variable | Default | Notes |
| --- | --- | --- |
| `MAX_FILE_SIZE` | `1 GiB` | HTTP request and staged-turn total limit. |
| `UPLOAD_MAX_SIZE_MB` | `500` | Maximum finished artifact accepted by the package repository. |
| `AI_ANALYSIS_MAX_EXTRACT_BYTES` | `2 GiB` | Upper bound available to safe archive materialization. |
| `AGENT_CLARIFICATION_TIMEOUT_SECONDS` | `300` | Mandatory confirmation timeout; packaging always cancels on timeout. |
| `PACKAGE_SEARCH_MAX_TURNS` | `8` | SDK Agent loop cap. |
| `PACKAGE_SEARCH_DEFAULT_LIMIT` | `5` | Search tool default page size. |
| `PACKAGE_SEARCH_MAX_LIMIT` | `50` | Search tool hard page-size cap. |

## Verification fixture

The repository fixture `Temp/LX10-V1.0.0.3` contains 13 component inputs after
excluding `.DS_Store`. A full acceptance run must show the project question and
all 13 exact basenames in the confirmation card, explicitly exclude or configure
non-publishable inputs, download the terminal artifact, verify its contents and
SHA-256, and confirm that the package appears in the Raven repository list.

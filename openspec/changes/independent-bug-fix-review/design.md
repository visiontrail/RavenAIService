## Context

Analysis dispatches asynchronous coding work to a separate Celery queue. Runtime endpoint slots and nullable schema synchronization already exist. Analysis workspaces and chat screenshots have independent lifecycles.

## Goals / Non-Goals

Goals: independent advanced endpoint, evidence-based rejection, complete original context, actionable errors, local Docker replay.
Non-goals: production deployment or changes to the general model router's failover behavior.

## Decisions

- Add a dedicated always-independent BugFix slot using existing slot validation/probes; missing credentials fail explicitly instead of silently falling back to the analysis model. Keep the existing model environment variable and default the dedicated model to an advanced model.
- Snapshot the exact analysis task data, logs and original screenshots into shared persistent storage at dispatch. Store a nullable context reference on each task; rebuild legacy context from persisted source records with explicit availability reporting.
- Represent rejected proposals as per-item `rejected` outcomes with evidence reasons. Validate one outcome per proposed item and derive success/partial/failure from all outcomes. Incomplete output cannot silently become a successful rejection.
- Preserve SDK terminal errors and human-readable redacted detail. Do not replay write-capable SDK runs after side effects.

## Risks / Trade-offs

- Snapshot storage costs → copy only task evidence, never cloned repositories or Git credentials.
- Legacy records cannot recover deleted screenshots → expose missing context; never invent evidence.
- Higher model cost → independent credentials, model, limits and explicit Admin connectivity test.

## Migration Plan

Add nullable context/model fields through existing startup schema sync. Configure the dedicated endpoint before enabling BugFix work. Validate in local Docker with copied existing scenarios and isolated Git hosting. Production deployment is outside this task.

# Orchestration Manifest

## Contents

- Canonical path
- Desired-state schema
- Validation rules
- Minimal example
- Live-state limits

## Canonical Path

Store approved desired state at `.codex/orchestration.json`. This tracked file contains aliases and policy, never native Codex task IDs or automation IDs. `scripts/bootstrap_project.py` is the executable validator and renderer for schema version 1.

## Progressive Specification Boundary

Do not write or select a manifest for an abstract request. First run the Progressive Specification Loop and obtain explicit user freeze approval for the goal, first usable artifact, scope boundaries, constraints, success evidence, durable domains, and material unknowns. A manifest records approved operating state; it is not evidence that discovery or approval occurred.

Separate invocations are independent projects unless the user explicitly establishes a relationship. Do not infer shared IP, canon, repository, Wiki, roadmap, or roles. When a relationship is explicit, each independent project retains its own manifest and authority; only the approved shared contract crosses the boundary.

The operational-control repository need not be the deliverable authority. An external artifact authority belongs in an approved durable source and requires a credential-free stable locator or local alias, accountable owner, immutable revision or export digest, `verified-at` value, freshness policy, and proof limits. Schema version 1 does not add a connector or embed credentials, native identities, registry values, or workstation-specific absolute paths.

## Desired-State Schema

Required top-level fields:

- `schema_version`: integer `1`.
- `tooling`: exact `plugin: project-orchestration` and the installed contract `version`.
- `project`: non-empty `name`, `goal`, and `risk` (`low`, `standard`, `high`, or `critical`).
- `governance`: exact repository-relative paths for `project_plan`, `requirement_brief`, and `bootstrap_work_item`.
- `knowledge`: `provider: llm-wiki`, `location: local`, `session_mode`, `raw_transcripts: false`, and `privacy: redacted`.
- `sessions`: the approved persistent-session desired state.
- `domains`: durable domains; it may be empty for a small project.
- `assurance`: timezone plus daily, weekly, and milestone profiles.
- `loop_breaker`: integer `warn_after` and `block_after`.

Each persistent session requires:

- `ref`: lowercase Session Ref alias.
- `title`: stable task title used with project root and Session Ref for recovery lookup.
- `role`, `purpose`, and `retirement_condition`.
- `persistent: true`.
- `environment`: `local` or `worktree`.
- `branch`: expected branch.
- `model` and `reasoning`: exact user-approved profile.
- `read_scope`: repository-relative prefixes; `.` means the repository root.
- `write_scope`: repository-relative prefixes without globs.
- `durable_sources`: exact plans, briefs, contracts, indexes, or evidence inputs needed to rehydrate the role.
- `evidence_outputs`: outputs owned by the role and contained by its write scope.

Each domain requires `id`, `purpose`, `steward_ref`, and `write_scope`. Its steward must exist, and each domain scope must be contained by that steward's write scope.

Every enabled assurance cadence requires `model`, `reasoning`, `prompt`, non-empty `checks`, `cost_profile`, and `fresh_context`. Daily also requires `local_time`; weekly requires `day` and `local_time`. Weekly and milestone profiles require `fresh_context: true`. The stable automation lookup key is `<project>:<cadence>:<timezone>` and is derived rather than storing a native automation ID.

## Validation Rules

- `tooling.plugin` and `tooling.version` must match the executing helper; a mismatch blocks rather than silently migrating policy.
- Exactly one session has role `program-orchestrator`, and it uses the local checkout.
- Session refs and stable titles are unique under case folding.
- Persistent write scopes do not overlap.
- Evidence outputs stay within the owning session's write scope.
- Paths are repository-relative, use `/`, contain no `..`, and contain no glob syntax.
- `warn_after` is at least 2 and `block_after` is greater than `warn_after`.
- Native task IDs must be UUIDv7 and are valid only in ignored `.codex/session-registry.local.json`.
- `check --ready` requires the manifest, governance sources, generated baseline, and Wiki config/schema to be committed in a clean worktree.
- Model support, live task reachability, stale mappings, Wiki semantic truth, and automation existence require live tool or Wiki audit evidence.

## Minimal Example

The example deliberately uses only a Program Orchestrator. Add a persistent Domain or Assurance Steward only when measured responsibility justifies retained context.

```json
{
  "schema_version": 1,
  "tooling": {
    "plugin": "project-orchestration",
    "version": "0.2.1"
  },
  "project": {
    "name": "example-project",
    "goal": "Deliver the approved project outcome reproducibly.",
    "risk": "standard"
  },
  "governance": {
    "project_plan": ".codex/docs/projects/P001-example.md",
    "requirement_brief": ".codex/docs/requirements/P001-G001-bootstrap.md",
    "bootstrap_work_item": ".codex/work/items/WI-001-bootstrap.md"
  },
  "knowledge": {
    "provider": "llm-wiki",
    "location": "local",
    "session_mode": "balanced",
    "raw_transcripts": false,
    "privacy": "redacted"
  },
  "sessions": [
    {
      "ref": "program-orchestrator",
      "title": "example-project - program orchestrator",
      "role": "program-orchestrator",
      "purpose": "Own goals, dependencies, and user decision routing.",
      "persistent": true,
      "environment": "local",
      "branch": "main",
      "model": "user-approved-model",
      "reasoning": "medium",
      "read_scope": ["."],
      "write_scope": [".codex/docs", ".codex/work", ".codex/coordination", ".wiki"],
      "durable_sources": [
        ".codex/docs/projects/P001-example.md",
        ".codex/docs/requirements/P001-G001-bootstrap.md"
      ],
      "evidence_outputs": [".codex/work/items/WI-001-bootstrap.md"],
      "retirement_condition": "The project closes or an approved successor takes ownership."
    }
  ],
  "domains": [],
  "assurance": {
    "timezone": "Asia/Seoul",
    "daily": {
      "enabled": true,
      "local_time": "18:00",
      "model": "user-approved-model",
      "reasoning": "low",
      "prompt": "Report deterministic exceptions only.",
      "checks": ["handoff", "scope", "wiki-lint", "loop-threshold"],
      "cost_profile": "low",
      "fresh_context": false
    },
    "weekly": {
      "enabled": true,
      "day": "FRI",
      "local_time": "18:30",
      "model": "user-approved-model",
      "reasoning": "high",
      "prompt": "Perform a fresh independent system audit.",
      "checks": ["goal-progress", "adoption-lag", "wiki-audit", "rework", "overinvestment"],
      "cost_profile": "standard",
      "fresh_context": true
    },
    "milestone": {
      "enabled": true,
      "model": "user-approved-model",
      "reasoning": "high",
      "prompt": "Perform a fresh milestone acceptance audit.",
      "checks": ["acceptance", "consumer-evidence", "independent-review"],
      "cost_profile": "standard",
      "fresh_context": true
    }
  },
  "loop_breaker": {
    "warn_after": 2,
    "block_after": 3
  }
}
```

## Live-State Limits

The manifest is desired state. The ignored registry is local identity state. Codex tasks, hook trust, hook enablement, worktrees, and automations are live state. Report them separately. Recovery must find a unique existing task by project root, Session Ref, stable title, role, and branch before creating another. A valid manifest and filesystem-ready PASS do not prove live reachability, hook execution, automation execution, Wiki truth, Work Item semantic correctness, or independent audit closure. Record the effective runtime fingerprint with material evidence and invalidate affected PASS results after a relevant model, reasoning, tooling, instruction, acceptance, source, or input change.

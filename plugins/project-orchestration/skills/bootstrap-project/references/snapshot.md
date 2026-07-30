# Operations Snapshot Contract

## Contents

- Command and authority
- Version 1 envelope
- Record kinds and links
- Determinism and privacy
- Failure rules

## Command and Authority

Run:

```text
python <skill>/scripts/bootstrap_project.py snapshot --root <project-root> --json
```

The command is read-only. It requires a Git repository with a committed HEAD and a completely clean worktree. Git, Project Plans, Requirement Briefs, Work Items, and audit evidence remain authoritative; the JSON is a rebuildable projection.

Version 1 reads:

- `.codex/docs/projects/P???-*.md` as `project-plan`;
- `.codex/docs/requirements/P???-G???-*.md` as `requirement-brief`;
- `.codex/work/items/WI-*.md` as `work-item`.

`.codex/audits/index.md` is navigation metadata only. Version 1 reports audit state as unknown and does not emit the index as an authoritative record. It never reads the ignored local session registry.

## Version 1 Envelope

```json
{
  "schema_version": 1,
  "source_revision": "<full Git object ID>",
  "records": [
    {
      "kind": "project-plan",
      "ref": "P001",
      "title": "Example",
      "status": "active",
      "authority_path": ".codex/docs/projects/P001-example.md",
      "source_revision": "<same full Git object ID>",
      "content_sha256": "<lowercase SHA-256 of committed bytes>",
      "origin": "durable",
      "proof_level": "declared",
      "freshness": "current-at-source-revision",
      "links": [],
      "unknowns": [
        "automation-state=UNKNOWN",
        "consumer-adoption=UNKNOWN",
        "independent-audit=UNKNOWN",
        "live-task-state=UNKNOWN",
        "live-worktree-state=UNKNOWN",
        "semantic-verification=UNKNOWN",
        "wiki-truth=UNKNOWN"
      ],
      "limitations": [
        "live-state-not-queried",
        "semantic-state-not-evaluated"
      ]
    }
  ],
  "live_overlay": {
    "status": "UNKNOWN",
    "observed_at": null,
    "limitations": [
      "automation-state-not-queried",
      "consumer-adoption-not-evaluated",
      "independent-audit-not-evaluated",
      "live-task-state-not-queried",
      "live-worktree-state-not-queried",
      "semantic-verification-not-evaluated",
      "wiki-truth-not-evaluated"
    ]
  },
  "limitations": [
    "audit-record-schema-not-defined",
    "domain-registers-not-normalized",
    "structural-projection-only"
  ]
}
```

Every record has exactly the keys shown above. Top-level keys and record keys are emitted with `sort_keys=True`; arrays use the ordering rules below.

Every version 1 record has exactly the seven `unknowns` strings shown above. The suffix `=UNKNOWN` is the state value, not free text. Every record also has exactly the two record limitations shown above. `live_overlay.limitations` has exactly the seven field-specific limitations shown above. Version 1 performs no aggregation: one unavailable field cannot stand in for another, and the top-level `live_overlay.status` remains `UNKNOWN` while any listed field is not queried or evaluated.

## Record Kinds and Links

Required source syntax:

- Project: exactly one `# Project Plan <ref>: <title>` and one `Status: <status>`.
- Requirement: exactly one `# Requirement Brief <ref>: <title>`, one `Status: <status>`, and one `Project Plan: <path>`.
- Work Item: exactly one `# Work Item <ref>: <title>`, one `Status: <status>`, one `Project: <ref>`, and one `Requirement: <ref>`.

Refs must agree with canonical filenames. Status is preserved after trimming and must match `^[a-z][a-z0-9-]*$`.

Links have exactly `kind` and `target`:

- Requirement: `{"kind": "project", "target": "<P ref>"}`.
- Work Item: project and requirement links. Add `{"kind": "evidence", "target": "<repository-relative path>"}` only when exactly one valid `Evidence Path` exists.

Sort records by `(kind, ref, authority_path)`. Sort links by `(kind, target)`, unknowns and limitations lexicographically. Reject duplicate `(kind, ref)` pairs.

## Determinism and Privacy

Read committed bytes from HEAD, not mutable working-tree bytes. Require the worktree to be clean first. Compute `content_sha256` over the exact committed bytes.

The durable envelope contains no wall-clock time, absolute path, host name, native task ID, registry value, or inferred semantic state. `observed_at` exists only in `live_overlay` and is `null` because version 1 does not query live state.

Before emitting, reject a UUIDv7-shaped native identity anywhere in a projected source file or output string. Tests use a synthetic sentinel only; never place a real native identity in fixtures, output, or error details.

## Failure Rules

Use existing `BlockedError` handling and return non-zero with `BLOCKED <code>`. Error details may include only safe repository-relative paths or refs.

- `SNAPSHOT_HEAD_REQUIRED`: no committed HEAD.
- `WORKTREE_NOT_CLEAN`: tracked or untracked change exists.
- `SNAPSHOT_SOURCE_UNREADABLE`: committed authority path cannot be read as UTF-8 regular-file content.
- `SNAPSHOT_RECORD_MALFORMED`: heading, status, required link, filename agreement, status syntax, or safe path is invalid.
- `SNAPSHOT_DUPLICATE_REF`: duplicate `(kind, ref)`.
- `SNAPSHOT_LINK_UNRESOLVED`: required project or requirement target is absent.
- `SNAPSHOT_IDENTITY_EXPOSURE`: a UUIDv7-shaped value occurs; never echo the value.

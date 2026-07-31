# Assurance Record Contract

## Commands and Authority

Run the read-only checks against a clean Git checkout:

```text
python <skill>/scripts/bootstrap_project.py assurance-check --root <project-root> --record .codex/audits/<record-id>.md
python <skill>/scripts/bootstrap_project.py close-check --root <project-root> --work-item .codex/work/items/<work-item>.md --owner-record .codex/audits/<owner-record>.md --audit-record .codex/audits/<audit-record>.md
```

Git, the Work Item, its pinned acceptance revision, evidence blobs, and immutable Assurance Records remain authoritative. Both commands report only `structural-and-local-evidence-only`; they do not change lifecycle state or prove semantic correctness, live task state, auditor freshness, or actual closure.

## Version 1 Grammar

Store each record once at `.codex/audits/<record-id>.md`. `<record-id>` must match `AR-[A-Z0-9]+(?:-[A-Z0-9]+)*` and the heading and `Record Path` must name the same canonical path. Use UTF-8, LF line endings, one terminal newline, the exact field and section order below, sorted unique list entries, and no extra prose.

```text
# Assurance Record AR-WI-001-OWNER

Schema Version: 1
Record Type: owner-verification
Record Path: .codex/audits/AR-WI-001-OWNER.md
Subject Work Item: .codex/work/items/WI-001.md
Subject Commit: <full-40-or-64-character-lowercase-Git-commit>
Acceptance Path: .codex/docs/requirements/P001-G001-example.md
Acceptance Revision: <full-40-or-64-character-lowercase-Git-commit>
Actor Session Ref: program-orchestrator
Owner Session Ref: program-orchestrator
Remediator Session Ref: not-applicable
Fresh Context: false
Runtime Fingerprint: sha256:<64-character-lowercase-digest>
Verdict: passed
P0 Findings: 0
P1 Findings: 0
P2 Findings: 0
Blocking Findings: 0
Adoption: not-required
Freshness: current

## Evidence

- .codex/work/evidence/WI-001.md | <full-40-or-64-character-lowercase-Git-blob>

## Criteria

- acceptance | passed

## Limitations

- structural-and-local-evidence-only

## Stale Triggers

- acceptance-revision-changed
- actor-registry-unresolved
- adoption-state-changed
- evidence-blob-changed
- runtime-fingerprint-changed
- subject-commit-changed
```

`Record Type` is `owner-verification` or `independent-audit`. The owner record uses its accountable owner as actor, `not-applicable` as remediator, and `Fresh Context: false`. An independent audit uses `Fresh Context: true`; its actor must differ from both owner and any named remediator. Add `independence-invalidated` to its sorted stale triggers. Every named Session Ref must resolve in the ignored local registry.

`Runtime Fingerprint` is the SHA-256 of the effective source, dispatch, implementation, acceptance, model, reasoning, plugin, governing-instruction, and material-input fingerprint assembled by the evidence producer. The local checker validates its shape and invalidation trigger, not those external semantics.

Evidence entries are `repository-relative-path | Git-blob-id`, sorted by path, and must include the Work Item's declared `Evidence Path`. Each path must be a regular blob with that object ID at `Subject Commit` and the same blob at the clean current HEAD. The pinned acceptance file must likewise remain the same blob at HEAD. The Work Item uses one canonical `Project`, a matching Requirement prefix, and a lowercase full-hash `Source Commit` with complete non-shallow history. Exactly one canonical Brief path may define that Requirement at the source revision and HEAD. Its heading/path must agree, its `Project Plan` must name the same Project, and that canonical plan path must be unique, regular, and heading-consistent at both revisions; normal plan content updates remain allowed. Both the canonical Brief and Project Plan must contain exactly one `Status` whose trimmed value matches `^[a-z][a-z0-9-]*$` at the source revision and HEAD. The canonical Brief must remain byte-identical from source through subject and current HEAD. `Acceptance Revision` must equal the Work Item's `Source Commit`. The full reachable source-through-dispatch path set is limited to the exact Work Item, the one source-revision canonical Project Plan for its Project, `.codex/work/index.md`, and `.codex/work/current.md`; every other planning, coordination, or product change belongs in a separate pre-source commit. The subject must then pass the same Git-derived dispatch, immutable Work Item, scoped-delta, changed nonempty evidence, and diff checks as handoff. Scope containment covers every path touched by every reachable implementation commit, including merge-parent deltas; a later revert does not erase an out-of-scope touch. The immutable record must be introduced in exactly one later record-only commit whose entire changed-path set is that canonical Assurance Record path; full reachable path history makes a modification, deletion, or rename fail closed.

Provenance-sensitive checks disable Git replacement-object resolution, reject a configured replacement namespace, `refs/replace/*`, and nonempty grafts, and require complete non-shallow history before building one reachable commit graph for existence and ancestry decisions. These local checks do not prove remote object retention or repository-host policy.

The assurance and close checks optimistically recheck their initial HEAD, clean index/worktree/untracked state, complete-history state, and exact registry immediately before PASS. Work checks additionally recheck the initial symbolic branch. Any unreadable, malformed, deleted, remapped, or changed value returns code-only `BLOCKED EVALUATION_STATE_CHANGED`. This is not a lock or lease; a mutation after the final recheck invalidates the result, and the next action must run the gate again.

Criteria entries are `stable-ref | verdict`, sorted uniquely by ref, with at least one entry. Refs are lowercase hyphen tokens local to the record; this contract does not create a criterion registry. The aggregate `Verdict` is the worst criterion state in the fixed order `stale`, `blocked`, `failed`, `passed`.

## Verdict, Severity, Adoption, and Staleness

- P0: authority, security, safety, data-loss, or irreversible false-action risk.
- P1: acceptance, ownership, scope, provenance, or reproducibility breach.
- P2: bounded correctness or regression gap.

`Blocking Findings` must equal P0 plus P1 plus P2. `passed` requires zero findings and `Freshness: current`; `failed` or `blocked` requires at least one finding and current evidence; `stale` requires `Freshness: stale`. Audit verdict and adoption remain separate, so an Assurance Record may pass with adoption `required`, `pending`, `rejected`, `blocked`, or `stale`; those states cannot pass `close-check`.

`Adoption` is only the record author's structural assertion. The checker does not consult a consumer registry, approval authority, CCR, or adoption artifact, and it never proves that any consumer adopted a change. `close-check` accepts exact owner/audit agreement only on `not-required` or `adopted`; even those accepted literals remain assertions rather than consumer-adoption evidence. Defining durable consumer authority, breaking approval, or an executable adoption schema is separate work.

The required stale triggers are the six shown above. They make a prior result ineligible when its subject, acceptance, evidence, runtime, actor resolution, or adoption premise changes. An independent audit additionally requires `independence-invalidated`. The checks validate locally observable pins; freshness beyond those pins remains an explicit proof limitation.

Current registry resolution proves only current alias availability and current resolved-identity separation without disclosing registry values. Every same-subject, same-acceptance prior record must still resolve all named Session Refs and retain valid timeless actor roles. A selected independent auditor must differ from every prior audit actor and named remediator, and its named remediator must differ from every prior audit actor. A non-passed prior additionally requires the explicit re-audit remediator rule. Historical alias remapping cannot be reconstructed from the current local-only registry and remains an explicit proof limitation.

## Close Eligibility

`close-check` requires:

- the current committed Work Item is `handed-off`;
- exactly one post-subject Work Item commit changes only the `Status` value from `active` to `handed-off`, preserving any parser-permitted horizontal whitespace, followed by one passed owner verification by its accountable owner;
- one later passed independent audit by another registered Session Ref and, for a re-audit, not its remediator;
- the selected owner and audit records are each the unique latest chain tip for the same subject and acceptance; deleted or renamed record history invalidates the set, and a re-audit after a non-passed audit names a remediator who is neither the prior nor current auditor and uses a different auditor;
- identical Work Item, subject commit, acceptance path, and acceptance revision pins;
- zero P0, P1, P2, and blocking findings;
- evidence blob matches at the pinned subject commit;
- no Work Item-scoped implementation path changed after the subject, even if later reverted; the exact lifecycle Work Item path and immutable canonical Assurance Record additions are control-path exemptions;
- the same adoption premise in both records, with the identical value `not-required` or `adopted`.

PASS means structurally eligible for an owner-controlled close action. This contract does not provide that action.

There is no automatic pre-v1 grandfathering. A legacy Work Item or record that fails this grammar or its Git-derived eligibility checks is `BLOCKED` and ineligible for closure until a separately user-approved migration/revalidation Work Item or a new Work Item establishes a valid authority chain. Do not rewrite legacy planning or claim migration from this contract alone.

The frozen operations snapshot v1 limitation literal `audit-record-schema-not-defined` means snapshot v1 has no Assurance Record projection schema. Changing that literal is a separate snapshot revision; this assurance contract does not change snapshot v1 constants, code, or documentation.

This source reports plugin version `0.2.1`, succeeding the public `0.2.0` release. External installation and adoption remain `UNKNOWN`; publication, marketplace refresh, installation, and consumer verification require their own evidence.

## Fail-Closed Codes

Public command compatibility is limited to exit status `2` and the value-nondisclosing shape `BLOCKED <code>`. Exact suffix codes are internal diagnostics, are not a stable automation catalog, and must not be used for downstream branching. The commands fail closed for incomplete Git history; evaluation-state changes in HEAD, cleanliness, registry, or the work-check branch; invalid or non-canonical paths; untracked or mutable records; malformed grammar; native identity exposure; unresolved aliases; invalid commits or ancestry; invalid subject or acceptance records; evidence mismatch; impossible verdict/count combinations; missing proof limits or stale triggers; invalid ownership or independence; mismatched close pins; open findings; blocked adoption; and invalid record order.

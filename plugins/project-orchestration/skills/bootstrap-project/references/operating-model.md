# Operating Model

## Contents

- Authority and memory
- Progressive specification and artifact authority
- Session topology
- Ownership and worktrees
- Operational work gate
- Advisory lifecycle guards
- Knowledge lifecycle
- Runtime and evidence invalidation
- Independent assurance
- Loop prevention
- Better-goal loop
- Deliberate limits

## Authority and Memory

Keep four memory layers distinct:

1. Transactional truth: current user instruction, Git state, active Project Plan, Requirement Brief, Work Item, contract/adoption records, tests, and independent audit evidence.
2. Semantic memory: curated project-local llm-wiki articles with provenance, confidence, volatility, and verification dates.
3. Episodic memory: ignored, redacted `.wiki/.sessions/` digests used for rehydration but never treated as canonical knowledge.
4. Procedural memory: `AGENTS.md`, skills, role prompts, and the approved orchestration manifest.

Indexes and summaries are navigation caches. Resolve the authoritative source before making a material decision. Auto-compaction preserves continuity, not exact evidence.

## Progressive Specification and Artifact Authority

For an abstract request, use the Progressive Specification Loop before root selection or any Git, task, session, worktree, plugin, or automation mutation. Each turn updates current understanding, confirmed decisions, assumptions and `UNKNOWN` items, one recommendation, and the next highest-impact question. Only explicit user freeze approval of goal, first usable artifact, scope boundaries, constraints, success evidence, durable domains, and material unknowns authorizes apply.

Separate invocations are independent projects unless the user explicitly establishes a relationship; the system must not infer a shared project, IP, canon, repository, Wiki, roadmap, or persistent role.

Keep the operational-control repository separate from deliverable authority. An external artifact authority requires a credential-free stable locator or local alias, accountable owner, immutable revision or export digest, `verified-at` value, freshness policy, and proof limits. This contract supplies no connector.

For an explicit novel-to-game relationship, a bounded non-canon game experiment may consume a pinned canon revision. Promotion creates an independent game project; only a shared adaptation contract crosses the boundary. The game project must not directly modify the novel Wiki, canon, or manuscript.

## Session Topology

Use federated domain cells rather than a deep command hierarchy.

### Program Orchestrator

Always persistent. Own the portfolio goal, priority, dependency map, shared-decision routing, user questions, and cross-domain coordination. Do not own product implementation or audit verdicts.

### Domain Steward

Create only when all are true:

- the domain has independent decisions;
- knowledge will accumulate across multiple Work Items;
- the role repeatedly delegates and verifies work.

Own terminology, invariants, roadmap, current evidence, risks, interfaces, and improvement candidates for that domain. Do not infer facts owned by another domain; request a targeted handoff.

### Optional Persistent Roles

- Integration/Contract Owner: only for a shared contract with two or more real consumers.
- Knowledge Steward: only when Wiki promotion volume or freshness work exceeds Program Orchestrator capacity.
- Implementation Lead: only when a domain has sustained implementation and integration ownership.
- Assurance Steward: only when recurring standards and trend analysis justify persistent context.

### Ephemeral Roles

- Work Item worker: one bounded implementation or production task.
- Diagnostic worker: fresh context after a repeated-failure escalation.
- Auditor: fresh context for each actual audit and re-audit.
- General subagent: local bounded assistance, never a registered project session.

## Ownership and Worktrees

Write scope is a list of repository-relative directory or file prefixes without glob syntax. Reject equal scopes and ancestor/descendant overlaps across persistent sessions. Read scope may include root acceptance, declared interfaces, consumer state, and audit evidence outside the write scope.

Keep the Program Orchestrator in the main project checkout. Create a worktree only when a concrete Work Item needs isolated writes. Derive all concurrent product worktrees from the same verified baseline commit. A branch can be checked out in only one worktree.

Before a bounded worker starts, its immutable active Work Item records owner Session Ref, branch, full pre-dispatch Source Commit, exact Write Scope, Evidence Path, and Problem Key. The first later commit touching that Work Item is the Git-derived dispatch baseline. The worker never edits the Work Item. The Program Orchestrator compares active Work Items and live worktrees before delegation. Persistent stewards retain domain context but do not perform product writes in the shared local checkout.

## Operational Work Gate

Run `work-check --phase allocate` from the proposed worker slot before creating or reusing worker topology. It reuses the canonical Work Item, registry, Source/dispatch, scope-collision, clean-state, and Git worktree checks; requires exactly one clean symbolic target-branch slot under the default cap of one; and fails closed for stale, locked, prunable, dirty, detached, duplicate, or unmerged topology. It is read-only, never creates or repairs topology, and reports host live-task state as `UNKNOWN`. The Program Orchestrator separately confirms one matching idle task before dispatch.

Run `work-check --phase start` from the worker checkout before writes. It fails closed unless the active Work Item is tracked, the owner alias resolves locally, the branch and Git-derived dispatch match, the tree is clean, the Source Commit is an ancestor, and no active Write Scope overlaps.

Run `work-check --phase handoff` before owner readback. It additionally requires a committed delta after dispatch, an unchanged Work Item, all changed paths inside Write Scope, a changed tracked non-empty Evidence Path, clean checkout, and `git diff --check`. PASS proves only structural and local Git evidence. The owner still performs domain verification; a fresh auditor decides closure.

New work may opt in to Handoff Contract v1. The immutable Brief defines stable goal, non-goal, invariant, decision, and acceptance IDs (`G-###`, `NG-###`, `INV-###`, `D-###`, `AC-###`); the Work Item references the applicable IDs; committed Evidence maps each reference to an output, verification, and evidence pointer. Start validates the Brief-to-Work-Item link, and handoff requires exact complete traceability. Historical work without the section is unchanged. This reduces silent intent loss but does not replace owner semantic verification or fresh audit.

These Git-backed claims are intentionally not a lease service. Governance stays on the canonical branch; workers consume it read-only and commit only their exact scope. Reconcile terminal lifecycle and reusable Wiki knowledge before another dispatch, then promote only verified source into the independent release repository. Add a lease only after observed duplicate dispatch, and use Git common-directory state only for worktrees of one clone; cross-host execution would require an external coordinator.

## Advisory Lifecycle Guards

Plugin version `0.2.1` bundles one read-only `SessionStart` hook and one explicit-path `PreToolUse` guard for `apply_patch`. Session hydration reads only committed Git authority and reports Wiki tree drift from `main` as `SOURCE_DRIFT`; it does not repair Wiki state or claim semantic freshness. Write checks prefer one active committed Work Item for the current branch, fall back only to one matching persistent-session scope, and always require a Work Item for Wiki writes.

Git `pre-commit` installation is an explicit bootstrap option. It copies the same guard source byte-for-byte into `.codex/hooks`, preserves an identical `core.hooksPath`, blocks a conflicting path, checks staged scope and privacy, and runs Git's staged whitespace check. It is advisory: `--no-verify` can bypass it, hook trust and enablement are host-local, matching hooks may also run, and tools outside covered paths may bypass it. The committed start/handoff gates, owner verification, and fresh independent audit remain the authority chain.

## Knowledge Lifecycle

Use one project-local `.wiki/` by default. Use domain tags and indexes rather than separate per-domain Wikis. Promote cross-project lessons to a global hub only after explicit review.

All sessions may read curated Wiki content. One role owns compiled Wiki writes at a time. Domain Stewards submit evidence-backed promotion candidates. The Knowledge Steward, or Program Orchestrator in a small project, ingests immutable raw sources and compiles accepted knowledge.

Treat `SOURCE_DRIFT`, broken provenance, low confidence, or insufficient freshness as real gates for decisions that depend on the affected article. Record an immutable revision or content digest and verification date for promoted sources; modification time alone is not evidence. A healthy Wiki structure does not prove current truth.

Session capture remains redacted and ignored because llm-wiki digests can contain native runtime identity. Strip native IDs and transcript paths before explicit promotion; use Session Ref aliases in promoted notes.

## Runtime and Evidence Invalidation

For material work, record an effective runtime fingerprint beside the evidence: source/dispatch commit, acceptance or contract revision, model, reasoning effort, orchestration plugin version, governing instruction revision, and material input digests. A change to any relevant element invalidates the affected PASS until it is rerun. Probabilistic output need not be bit-identical, but the inputs, evaluator, budget, tolerance, and result must be reconstructable.

Codex reads governing instructions at the start of a run. After changing `AGENTS.md`, a skill, role prompt, or orchestration contract, use a fresh run for verification. Treat Wiki source drift, changed external data, or an expired assumption the same way: mark dependent evidence stale instead of silently carrying it forward.

Midstream project reconciliation preserves existing authority and protected work, applies only the approved delta, and proves a no-change rerun. Operations-ready completion additionally requires internally consistent ownership, domain-specific evidence, documented cadence and retirement conditions, accountable-owner semantic verification, and fresh independent audit.

## Independent Assurance

Separate automated health checks, recurring review, and independent audit:

- Handoff check: deterministic ownership, scope, manifest, commit, and evidence shape.
- Daily: low-cost exception scan; create durable findings only for exceptions.
- Weekly: fresh system audit of goal progress, dependency/adoption lag, knowledge freshness, rework, model/token use, idle roles, overinvestment, underinvestment, and improvement candidates.
- Milestone: fresh strict audit of acceptance and evidence before release or irreversible action.

Auditors have broad read scope and audit-only write scope. They do not implement, edit authoritative plans, promote Wiki knowledge, or approve their own remediation. A different fresh auditor verifies remediation. Structure-only checks always state their proof limits.

Recurring automations use one stable logical key per project, cadence, and timezone. Test prompts interactively first, use the narrowest access and an isolated worktree, inspect the first run, update the unique matching schedule, block on duplicates, and never treat a schedule definition as proof that a run occurred.

Cadence is domain-specific: investment may require daily data/risk review; a novel may use weekly and manuscript milestones; a webtoon may audit per episode; software may audit handoffs and releases.

## Loop Prevention

Use a stable Problem Key and `.codex/work/attempts.jsonl` as the single compact Attempt Log containing failure signature, hypothesis, change delta, evidence, outcome, and next decision. Work Items link the key and current decision rather than duplicate the ledger. Do not log every tool call.

Before work, search open Work Items, audit findings, affected paths, and Wiki constraints for the key. If two sessions target the same cause, the Program Orchestrator assigns one owner or declares a shared contract issue.

The default policy warns before the second matching attempt and blocks before the third without measurable progress. A retry must name a changed hypothesis, input, constraint, or evaluation method. On block, stop the current worker and give a fresh diagnostic worker raw evidence plus failed approaches, not the preferred answer.

Close only after reproducing the failure, isolating the cause, applying the smallest shared fix, adding regression evidence, verifying consumers, and obtaining independent review. Creative work may replace a programmatic regression with a versioned comparison and explicit editor acceptance.

## Better-Goal Loop

Domain Stewards record opportunity candidates in the Project Plan's minimal Opportunity Register with evidence, expected value, cost, risk, dependencies, and expiry. The Program Orchestrator deduplicates and ranks them. The user approves, rejects, or defers material goal changes. Auditors may identify opportunities but cannot start them. Do not add a separate opportunity subsystem until measured volume requires it.

## Deliberate Limits

Do not add permanent sessions per file, class, character, stock, or component. Do not create Planner, Architect, and Implementation Lead for every domain by default. Do not use coordination records for ordinary dependencies. Do not create separate Wikis, custom databases, vector search, dashboards, broader hook events, distributed leases, full telemetry stacks, or daily deep audits until measured failures justify them. Add coordination only for a real shared contract with two consumers; extend Hook v1 only after observed violations show its explicit-path boundary is insufficient; add dashboards only when weekly evidence collection repeatedly consumes material time.

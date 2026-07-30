---
name: bootstrap-project
description: Diagnose, establish, reconcile, or evolve sustainable operating state for a new, midstream, or mature project. Use when the user asks to set up or repair project operations, define durable artifact authority, create a PMO or justified persistent sessions, configure worktrees and assurance, prevent repeated failed approaches, or verify that the environment can be recreated without chat history.
---

# Project Operations Setup (`bootstrap-project`)

Establish the smallest approved operating system for a project, then hand control to its Program Orchestrator. Treat setup as a state transition, not initial-only scaffolding or a template dump.

## Read the References

Read [operating-model.md](references/operating-model.md) before deciding roles, ownership, knowledge, assurance, or escalation. Read [manifest.md](references/manifest.md) before writing or validating `.codex/orchestration.json`. Read [snapshot.md](references/snapshot.md) before producing or consuming an operations snapshot. Read [assurance.md](references/assurance.md) before creating, checking, or consuming an Assurance Record or deciding close eligibility.

## Progressive Specification Loop

For an abstract first message, do not select a root or mutate Git, tasks, sessions, worktrees, plugins, or automations. Each discovery turn updates current understanding, confirmed decisions, assumptions and `UNKNOWN` items, one recommendation, and the next highest-impact question. Ask one question by default and at most three only when independent.

Before apply, freeze the goal, first usable artifact, in-scope and out-of-scope boundaries, constraints, success evidence, durable domains, and material unknowns. Only explicit user freeze approval authorizes recording that summary in the Requirement Brief or manifest and applying operating state.

Separate invocations are independent projects unless the user explicitly establishes a relationship. The system must not infer a shared project, IP, canon, roadmap, repository, Wiki, or persistent role from a common user.

Keep the operational-control repository distinct from deliverable authority. An external artifact authority requires a credential-free stable locator or local alias, accountable owner, immutable revision or export digest, `verified-at` value, freshness policy, and proof limits. This skill defines the evidence contract but does not implement a connector.

## Scenario Contracts

Focused verification covers:

1. An abstract new-game request: discover player experience, first playable artifact, platform, tools, source and asset authority, build or executable evidence, and playtest evidence.
2. An abstract new-web-novel request: discover reader experience, first manuscript artifact, manuscript and canon authority, writing surface, editorial evidence, and an external artifact authority option.
3. Unrelated invocations: separate invocations are independent projects and must not infer a shared project or IP.
4. Existing novel IP: a bounded non-canon game experiment may consume a pinned canon revision only after the relationship is explicit and frozen.
5. Promotion: create an independent game project with its own Plan, Work Items, repository, Wiki, and Program Orchestrator; only a shared adaptation contract crosses the boundary.
6. Mutation rejection: the game project must not directly modify the novel Wiki, canon, or manuscript. Route proposed canon changes to the novel owner.
7. Midstream project reconciliation: inspect existing authority, preserve protected work, apply only the approved delta, and prove a no-change rerun.

Game acceptance uses playable, executable or build, platform, asset, and playtest evidence. Novel acceptance uses manuscript, canon, editorial, and reader-facing evidence. Neither domain inherits the other's acceptance shape.

For explicit novel-to-game work, freeze the relationship as `canonical-adaptation`, `spin-off`, `non-canon-experiment`, or `undecided`. The shared adaptation contract pins source revision, canon relationship, `allowed`, `must-preserve`, `may-adapt`, `forbidden`, rights and provenance, spoiler boundary, and change, approval, adoption, and audit flow. Do not add permanent organization for a small experiment; decide at its milestone whether to stop, repeat, or promote.

## Workflow

### 1. Inspect Without Writing

Resolve the target directory and inspect only bounded evidence first:

- Git root, branch, HEAD, worktree cleanliness, remotes, and existing worktrees
- `AGENTS.md`, `.codex/`, active plans, Work Items, role configs, and existing session registry ignore state
- project goal, artifact types, long-lived domains, shared contracts, risk, information volatility, and current verification commands
- existing `.wiki/` index/config and llm-wiki availability
- existing deliverable authorities, protected artifacts, immutable pins, freshness policies, and domain-specific success evidence

Do not initialize Git, edit files, create tasks, create worktrees, install plugins, or schedule jobs during inspection.

### 2. Propose the Smallest Topology

Always propose one Program Orchestrator. Add a persistent Domain Steward only when the responsibility has independent decisions, durable knowledge, and repeated delegation. Add Integration, Knowledge, Implementation Lead, or Assurance Steward roles only when evidence justifies them. Keep Work Item workers and actual auditors ephemeral.

For every proposed persistent session include:

- Session Ref, stable title, purpose, role, persistence reason, environment, expected branch, read boundary, and exact write-scope prefixes
- exact model and reasoning effort supported by the current host
- durable knowledge inputs, required handoffs, evidence outputs, and retirement condition

Reject overlapping write scopes. Read scope may cross domain boundaries; write scope may not.

### 3. Request One Material Approval

Present one compact desired-state proposal covering:

- goal, domains, sessions, models, reasoning, ownership, Git initialization or baseline commit
- local llm-wiki setup, knowledge owner, session-capture privacy
- daily/weekly/milestone assurance cadence, timezone, and cost profile
- Loop Breaker thresholds and actions
- files, tasks, worktrees, and automations that will be created

Do not create user-owned Codex tasks or scheduled automations until the user explicitly approves this proposal. A request such as "set up the project including the proposed sessions and schedules" is approval; a request for a preview is not.

For an existing project, present the current-state diagnosis and smallest approved delta. Preserve user-owned content and unrelated behavior. A same-input rerun must produce no tracked change; unresolved conflicts remain `UNKNOWN` or `BLOCKED`.

### 4. Write and Apply Desired State

Write the approved manifest to `.codex/orchestration.json` with `apply_patch`. Run:

```text
python <skill>/scripts/bootstrap_project.py apply --root <project-root>
```

The script uses only the Python standard library, preserves unrelated existing content, adds a managed `AGENTS.md` block, and is idempotent. Do not use `--init-git` unless Git initialization was included in the approval.

Lifecycle hooks are bundled but local Git-hook installation is opt-in. Install a private local guard copy only when that control was approved:

```text
python <skill>/scripts/bootstrap_project.py apply --root <project-root> --install-hooks
```

The option copies the bundled `hooks/scope_guard.py` byte-identically into the current worktree's private Git administrative directory, writes a small `pre-commit` wrapper there, enables Git's standard `extensions.worktreeConfig` only when its dormant worktree config (including includes) has no entries, and sets that worktree's `core.hooksPath` to the absolute private directory only when no shared value exists and the active value is absent or already exact. A false extension, any dormant setting, any shared hook path, or a different active worktree hook path is `BLOCKED`; do not overwrite, activate, migrate, or merge it automatically. Checked-out files cannot replace the installed guard, linked sibling worktrees do not inherit it, and re-running the option is idempotent.

If an existing repository has tracked changes outside the approved manifest, stop with `BLOCKED`; do not bootstrap over another worker's writes. The target directory must be the actual Git root, not a nested directory inside another repository.

llm-wiki is an optional external workflow dependency, not a bundled Python/runtime import. The manual integration is repository `https://github.com/nvk/llm-wiki`, ref `v0.16.0`, marketplace `nvk/llm-wiki`, and selector `wiki@llm-wiki`: add that marketplace at the pinned ref, add the selector, then start a fresh task. Never bundle, copy, or auto-install it. `apply` and ordinary structural `check` do not require `.wiki/`. `check --ready` requires tracked `.wiki/config.md` and `.wiki/schema.md`, fails `BLOCKED LOCAL_WIKI_REQUIRED` when they are absent, does not detect whether the Wiki plugin is installed, and does not prove Wiki semantic truth or freshness. End-to-end Wiki initialization, repair, lint, and fresh audit require the separately installed `wiki` skill. If that integration is unavailable, never hand-create `.wiki/`; report Wiki setup or freshness as `BLOCKED` or `UNKNOWN`. Plugin and skill validators are structural only and do not prove installation, security, Wiki truth, or readiness.

Use the installed `wiki` skill to initialize or repair a project-local `.wiki/`; do not recreate llm-wiki's structure. Configure redacted capture with raw transcripts disabled. Keep `.wiki/.sessions/` ignored and treat its contents as non-authoritative operational memory. Promotion into `raw/` and compilation into `wiki/` are explicit review actions. Every promoted source must retain provenance plus a content digest or immutable revision and a verification date; file modification time alone is not freshness evidence. Run the Wiki skill's lint and fresh audit workflows, and record their evidence pointer and proof limits in the bootstrap Work Item. A structure-only Wiki PASS is not semantic closure.

### 5. Establish the Baseline

Create or update the Project Plan, Requirement Brief, and bootstrap Work Item at the exact manifest paths. Put a minimal Opportunity Register in the Project Plan for evidence-backed better-goal candidates. Create a product Work Item only when approved product work exists. Run the project's native checks plus:

```text
python <skill>/scripts/bootstrap_project.py check --root <project-root>
```

Create a baseline commit only when it was approved. Record the plugin name and version in the manifest so a later tool or instruction change is visible. Create implementation worktrees from the same verified commit; do not create idle worktrees during bootstrap.

### 6. Create and Register Sessions

Use Codex project and task lookup before task creation. On every first run or recovery run, search existing tasks by the stable Session Ref, expected title, and project root. If exactly one candidate matches, verify its role and register it. If multiple candidates match, return `BLOCKED ORPHAN_SESSION_AMBIGUOUS`. Create a new task only when no candidate exists. Never duplicate a task merely because setup failed after task creation.

Create the Program Orchestrator in the project's local checkout. Create approved persistent Domain Stewards in the local checkout unless an explicitly owned implementation branch requires a worktree. Create Work Item workers later in isolated worktrees.

After each successful task creation, register its actual task ID without printing it:

```text
python <skill>/scripts/bootstrap_project.py registry-set --root <project-root> --alias <session-ref>
```

Pass the ID on stdin. Never put it in a command argument, tracked file, Wiki article, report, or user-facing response. The command returns only a count. Resolve and consume registry values only inside one orchestrated tool call; the helper deliberately provides no command that prints a stored value.

Send each session a targeted handoff containing its goal, durable sources, exact ownership, forbidden actions, first readback, and evidence requirements. Require the session to read back the same Session Ref, stable title, role, branch/environment, Work Item, and scope.

Before any implementation or production worker starts, commit one immutable active Work Item containing canonical `Project`, a matching `Requirement`, `Owner Session Ref`, `Branch`, a lowercase full-hash `Source Commit` from before dispatch, `Problem Key`, `Evidence Path`, and exact prefix-only `Write Scope`. `.codex/work/items/*.md` is reserved for canonical Work Item authorities; do not place README or other non-Work-Item Markdown there, and use `.codex/work/index.md` for navigation. The source must have complete non-shallow Git history. Provenance-sensitive gates disable replacement-object resolution and fail closed on replacement namespaces, `refs/replace/*`, or nonempty grafts. At both source and current HEAD, require one regular canonical Project Plan and one regular canonical Requirement Brief whose headings, paths, lowercase statuses, and Project linkage agree. The Brief must be byte-identical from source through closure. The complete source-to-dispatch changed-path set must include the Work Item and is limited to that Work Item, its Project Plan, `.codex/work/index.md`, and `.codex/work/current.md`; the Brief is not in the dispatch allowlist. If the Brief must change, mark the existing work stale or blocked and dispatch a new Work Item from a new Source Commit. The first commit after `Source Commit` that touches the Work Item is the Git-derived dispatch baseline; the worker never edits the Work Item. Check every committed Work Item authority and current worktrees for overlap, then run `work-check --phase start`. Persistent stewards do not implement product changes in the shared local checkout; concrete write work uses a bounded worker in an isolated worktree. The active Project Plan row's branch and Work Item identify delegated execution, not the persistent owner's own checkout.

Before creating or reusing worker topology, run the allocation phase from the proposed slot:

```text
python <skill>/scripts/bootstrap_project.py work-check --root <project-root> --phase allocate --work-item <work-item>
```

The allocation phase is read-only and does not replace `start`. It requires the active canonical Work Item, resolved owner alias, exact Source/dispatch and branch, non-overlapping scope, one clean symbolic target-branch worktree, default cap `1`, and no stale, locked, prunable, dirty, detached, or unmerged target slot. It never creates, resets, stashes, prunes, or deletes a branch or worktree. Its local PASS reports host live-task state as `UNKNOWN`; the Program Orchestrator must separately confirm exactly one matching idle task before dispatch. Reuse the matching slot. Creating another slot requires explicit user approval for concurrent independent work.

Before accepting a worker readback, require its committed evidence file and run `work-check --phase handoff`. This gate verifies the registered owner alias, branch, immutable dispatch, ancestry, clean tree, active-scope collision, full-history per-commit changed-path containment including merge-parent deltas, evidence update, and `git diff --check`. Its PASS is `structural-and-local-evidence-only`; the owner and a fresh auditor still read the evidence and verify semantics.

The bundled `SessionStart` hook provides bounded alias-safe committed context. The `PreToolUse` matcher receives `apply_patch`, `Edit`, and `Write`, but it path-scope checks only explicit paths in `apply_patch` edits; matching `Edit` and `Write` requests are intentionally denied fail-closed as `BLOCKED HOOK_INPUT_INVALID`. The optional Git hook checks staged paths, native-identity exposure, and whitespace against the same committed authority. Hooks never read the local registry, parse general shell commands, repair state, or replace `work-check`. Other matching hooks may run, specialized tools may bypass this guard, hook trust is host-local, and `git commit --no-verify` can bypass `pre-commit`; the start/handoff gates, owner verification, and fresh independent audit remain authoritative.

The start, handoff, assurance, and close checks use an optimistic final recheck: HEAD, clean index/worktree/untracked state, and the exact registry must still match their initial observations; work checks also require the same symbolic branch. A mismatch returns `BLOCKED EVALUATION_STATE_CHANGED` without values. This is not a lock or lease: mutation after the final recheck invalidates the PASS, and the next action must re-run the gate.

### 7. Configure Assurance

Use the Codex automation tool for approved recurring schedules; never write raw scheduling directives as a workaround. Test the prompt interactively first, use an isolated worktree and the narrowest required access, inspect the first run, and record actual-run evidence separately from the schedule definition. Before creating one, inspect existing automations using the stable logical key `<project>:<cadence>:<timezone>` and update the unique match. Multiple matches are `BLOCKED`; do not create duplicates. Daily work is an exception scan, weekly work is a fresh system audit, and milestone work is an explicitly triggered fresh audit. A persistent Assurance Steward may own standards and trends but must not implement findings or perform the final re-audit.

If an automation cannot be created or verified, report that item as `BLOCKED` and keep the filesystem baseline separate from live readiness.

Record owner verification and each fresh independent audit with the immutable Assurance Record contract. Run `assurance-check` on each record and `close-check` on the selected owner/audit pair. Treat either PASS as `structural-and-local-evidence-only`; only an owner-controlled lifecycle action may close work, and this skill does not provide one. Keep actual auditors and re-auditors ephemeral. Do not create a permanent Auditor; add a persistent Assurance Steward only after recurring standards and trend analysis justify it.

Treat `Adoption: not-required` and `Adoption: adopted` as structurally accepted owner/auditor assertions only, never as proof that a consumer adopted a shared change. Any real shared-surface adoption requires its own durable Source, authorized Work Item, consumer evidence, and independent review. Do not grandfather a legacy Work Item that fails the current gate; keep it `BLOCKED` until a separately user-approved migration/revalidation Work Item or a new authority chain exists.

Reconcile two separate chains. For a persistent task, compare manifest desired state to the Project Plan assignment, ignored registry alias, host-observed live task, and that task's own checkout. For delegated execution, compare the accountable owner Session Ref to the immutable active Work Item, the Work Item's worker execution branch/worktree, and its exact Write Scope. A worker branch need not equal the accountable owner's task checkout. Host tools alone provide observed task state. Report missing observation as `UNKNOWN`; report duplicate live tasks, unresolved required aliases, overlapping write scopes, or a mismatch inside either chain as `BLOCKED`. Do not infer a mismatch merely because the two chains use different checkouts. Never copy a native identity or registry value into durable text.

### 8. Verify Ready State

Run:

```text
python <skill>/scripts/bootstrap_project.py registry-check --root <project-root>
python <skill>/scripts/bootstrap_project.py check --root <project-root> --ready
```

Independently confirm live tasks, host-supported model/reasoning pairs, and automation state with Codex tools. Record the effective runtime fingerprint used for material evidence: model, reasoning, tool/plugin version, instruction revision, source commit, and material input digests. Re-run affected checks when any of those inputs or the acceptance contract changes; do not carry a prior PASS across an invalidated baseline. Codex instructions are loaded at run start, so instruction changes require a fresh task run. A filesystem PASS does not prove live task identity, automation execution, semantic correctness, consumer adoption, or audit closure.

Return a concise map of created roles, aliases, ownership, baseline commit, Wiki status, assurance status, Loop Breaker policy, verification evidence, and remaining `UNKNOWN` or `BLOCKED` items. Do not disclose registry values.

Operations-ready completion additionally requires the approved diagnosis and delta, consistent authority and non-overlapping ownership, protected artifact pins, domain-specific success evidence, documented cadence and retirement conditions, a no-change rerun, accountable-owner semantic verification, and fresh independent audit. Structural checks alone do not prove this state.

## Loop Breaker

Before a Work Item starts, search its Problem Key, failure signature, affected paths, existing findings, and Wiki constraints. `.codex/work/attempts.jsonl` is the authoritative compact Attempt Log; the Work Item links the Problem Key and current decision instead of duplicating the ledger. Do not log every command.

- First failure: diagnose normally.
- Before the second matching attempt: require a different hypothesis or input and warn about loop risk.
- Before the third matching attempt without measurable progress: mark `BLOCKED`, stop the worker, and create a fresh diagnostic task.
- Recurrence after closure: open a new recurrence Problem Key and inspect why the prior regression evidence failed.

A useful iteration changes evidence or improves an acceptance metric. Repeating the same inputs, assumptions, and action is a loop. Domain packs may change numeric thresholds, but must preserve the changed-hypothesis and escalation rules.

## Better-Goal Loop

Keep opportunity candidates in the Project Plan's minimal Opportunity Register with evidence, expected value, cost, risk, dependencies, expiry, and decision. The Program Orchestrator deduplicates and ranks them. Auditors may propose candidates but cannot start them; material goal changes require user approval. Do not create a separate opportunity service in v1.

## Fail Closed

Use `UNKNOWN` or `BLOCKED` when identity, authority, evidence, model support, schedule state, Wiki freshness, or scope is unresolved. Do not infer readiness from chat history, generated structure, or a structural checker alone. Do not let an auditor approve its own remediation or let a proposed improvement start without user approval.

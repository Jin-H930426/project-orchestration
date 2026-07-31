# Project Orchestration

`project-orchestration` is a Codex plugin for Project Operations Setup and bounded execution. It diagnoses, establishes, reconciles, and evolves approved operating state for new, midstream, and mature projects. It keeps desired state in Git, uses durable Project Plans, Requirement Briefs, and Work Items as authority, assigns persistent sessions by responsibility, sends implementation to isolated worktrees, and separates structural checks from owner verification and fresh audit.

The plugin bundles one public `bootstrap-project` skill and lifecycle hooks. It does not bundle a database, dashboard, release service, or llm-wiki.

## Project Operations Setup

The technical skill name remains `bootstrap-project`, but setup is not limited to initial project creation.

### Progressive Specification Loop

For an abstract request, update current understanding, confirmed decisions, assumptions and `UNKNOWN` items, one recommendation, and the next highest-impact question. Ask one question by default. Before selecting a root or mutating Git, tasks, sessions, worktrees, plugins, or automations, freeze the goal, first usable artifact, scope boundaries, constraints, success evidence, durable domains, and material unknowns. Only explicit user freeze approval authorizes apply.

Separate invocations are independent projects unless the user explicitly establishes a relationship; the system must not infer a shared project, IP, canon, repository, Wiki, roadmap, or persistent role.

An external artifact authority is distinct from the operational-control Git repository. Record a credential-free stable locator or local alias, accountable owner, immutable revision or export digest, verification time, freshness policy, and proof limits. This contract does not provide a connector.

### Seven scenario contracts

1. An abstract new-game request discovers intended player experience, first playable artifact, platform, tools, source and asset authority, build or executable evidence, and playtest evidence.
2. An abstract new-web-novel request discovers reader experience, first manuscript artifact, manuscript and canon authority, writing surface, editorial evidence, and an external artifact authority option.
3. Unrelated requests remain unrelated invocations and do not acquire shared IP implicitly.
4. Existing novel IP may produce a bounded non-canon game experiment consuming a pinned canon revision after the relationship is explicitly frozen.
5. Promotion creates an independent game project with its own authority and a shared adaptation contract as the only cross-project control surface.
6. The game project must not directly modify the novel Wiki, canon, or manuscript.
7. midstream project reconciliation preserves existing work, applies only the approved delta, and proves a no-change rerun.

Game acceptance uses playable, executable or build, platform, asset, and playtest evidence. Novel acceptance uses manuscript, canon, editorial, and reader-facing evidence; neither inherits the other's evidence shape.

operations-ready completion requires an approved diagnosis and delta, consistent ownership and scopes, protected artifact pins, domain-specific evidence, cadence and retirement conditions, a no-change rerun, owner semantic verification, and fresh independent audit. Structural validation alone is insufficient.

## Prerequisites

- A host that supports Codex plugins and the documented `codex plugin` CLI. No minimum Codex version is pinned here.
- Git, for repository identity, immutable revisions, worktrees, scope checks, and archives.
- Python. The source uses syntax inferred to be compatible with Python 3.10+, while the bounded verification authority covers only local Windows with Python 3.12.10. An official minimum and non-Windows support are `UNKNOWN`.
- A Git project root for the target project.

## Marketplace installation

A Git-installable marketplace must use the mapped release layout described below. A source checkout and the historical flat release repository are not installable marketplace evidence.

The locally verified generic command shapes are:

```text
codex plugin marketplace add <local path|owner/repo[@ref]|HTTPS|SSH> [--ref <ref>]
codex plugin add <plugin>@<marketplace>
codex plugin marketplace upgrade [marketplace-name]
codex plugin remove <plugin>@<marketplace>
codex plugin marketplace remove <marketplace-name>
```

Choose one marketplace selector:

- Local: replace `<local path>` with the mapped marketplace repository path.
- Git: use `owner/repo[@ref]`, HTTPS, or SSH; `--ref <ref>` may pin a revision where supported.

Then install:

```text
codex plugin marketplace add <local path|owner/repo[@ref]|HTTPS|SSH> [--ref <ref>]
codex plugin add project-orchestration@project-orchestration
```

Start a fresh Codex task or process after installation. These commands are instructions, not proof that this package has been registered or installed.

For a Git-backed marketplace update, upgrade that marketplace, reinstall the plugin, and then start a fresh Codex task or process:

```text
codex plugin marketplace upgrade project-orchestration
codex plugin add project-orchestration@project-orchestration
```

For a local-path development update, do not use marketplace upgrade as a source refresh. Update the plugin cachebuster with the installed `plugin-creator` helper, reinstall from the already configured marketplace, and then start a fresh Codex task or process:

```text
python <plugin-creator-skill-root>/scripts/update_plugin_cachebuster.py <local-plugin-path>
codex plugin add project-orchestration@project-orchestration
```

To remove it, remove the plugin first and the marketplace second:

```text
codex plugin remove project-orchestration@project-orchestration
codex plugin marketplace remove project-orchestration
```

## Quick start

`<installed-skill-root>` means the installed `bootstrap-project` skill directory containing `SKILL.md`, `references/`, and `scripts/`. It is not the marketplace root or a path relative to a fresh consumer repository.

After reviewing the skill and approving the desired `.codex/orchestration.json`:

```text
python <installed-skill-root>/scripts/bootstrap_project.py apply --root <project-root>
python <installed-skill-root>/scripts/bootstrap_project.py check --root <project-root>
```

Use `--init-git` or `--install-hooks` only when that mutation was explicitly approved. Do not assume `skills/bootstrap-project/...` exists under `<project-root>`.

The apply workflow generates or maintains the approved operating baseline, including:

- `AGENTS.md` managed instructions;
- `.codex/operating-model.md`;
- `.codex/session-registry.schema.json`;
- Project Plan, Requirement Brief, Work Item, work index, attempt ledger, and audit index paths;
- ignore and text-normalization rules.

Actual task identities belong only in ignored `.codex/session-registry.local.json`. Tracked text uses Session Ref aliases. Persistent sessions own durable responsibilities; bounded implementation workers use exact Write Scopes in isolated worktrees. A structural gate is not semantic verification or independent audit.

The `PreToolUse` matcher receives `apply_patch`, `Edit`, and `Write`, but only `apply_patch` requests are path-scope checked. Matching `Edit` and `Write` requests are intentionally denied fail-closed as `BLOCKED HOOK_INPUT_INVALID`.

## Conditional llm-wiki workflow

llm-wiki is an optional external workflow dependency. It is not bundled, copied, auto-installed, imported, or invoked by the public Python helper or hooks. Its pinned public repository is `https://github.com/nvk/llm-wiki` at ref `v0.16.0`; the marketplace locator is `nvk/llm-wiki` and the plugin selector is `wiki@llm-wiki`.

Enable it manually only when the project needs the Wiki lifecycle, then start a fresh Codex task or process:

```text
codex plugin marketplace add nvk/llm-wiki --ref v0.16.0
codex plugin add wiki@llm-wiki
```

- `apply` and ordinary structural `check` work without `.wiki/`.
- `check --ready` requires tracked `.wiki/config.md` and `.wiki/schema.md`; missing files fail `BLOCKED LOCAL_WIKI_REQUIRED`.
- `check --ready` does not detect whether the Wiki plugin is installed and does not prove Wiki semantic truth or freshness.
- End-to-end initialization, repair, lint, and fresh audit require the separately installed `wiki` skill.
- If that integration is unavailable, never hand-create `.wiki/`; report Wiki setup or freshness as `BLOCKED` or `UNKNOWN`.

Plugin, skill, and marketplace validators are structural only. They do not prove registration, installation, security, Wiki truth, semantic freshness, or operational readiness.

## Package and dependency matrix

| Surface | Classification | Package behavior |
| --- | --- | --- |
| Root `README.md` | Mapped marketplace file | Public documentation; outside plugin content |
| `.codex-plugin/**` | Bundled plugin content | Manifest and plugin identity |
| `skills/**` | Bundled plugin content | Public skill, references, agent metadata, and standard-library helper |
| `hooks/**` | Bundled plugin content | Codex lifecycle hooks and scope guard |
| Codex host and CLI | External prerequisite | Required for plugin discovery and lifecycle execution |
| Git | External prerequisite | Required for repository, revision, worktree, archive, and gate behavior |
| Python | External prerequisite | Runs the helper and guards; verified locally only as stated above |
| llm-wiki and installed `wiki` skill | Optional external dependency | Manual `nvk/llm-wiki` ref `v0.16.0`, selector `wiki@llm-wiki`; required only for end-to-end Wiki workflows |
| `.codex/session-registry.local.json` | Generated local-only state | Ignored alias-to-task mapping; never package or tracked output |
| `.wiki/**` | Generated project state | Created only through the external Wiki integration; session digests stay ignored |
| `tests/**` | Source-maintainer only | Excluded from the plugin and mapped release |
| Governance `.codex/**` | Repository-only | Excluded from the plugin and mapped release |
| External llm-wiki content | External | Never bundled or copied |
| `.codex/release/pre_push_guard.py` | Source-owned private release guard | Excluded from plugin content and mapped release |

## Delivery control and recurrence prevention

The delivery failure this release addresses was operational: blocked attempts accumulated new branches and worktrees, governance edits remained on worker branches, Wiki knowledge lagged behind the durable result, and verified source was not promoted into the independent release repository.

Before reusing a worker slot, run the read-only allocation gate from that slot:

```text
python <installed-skill-root>/scripts/bootstrap_project.py work-check --root <project-root> --phase allocate --work-item <work-item>
```

The gate reuses the canonical Work Item, registry, Source/dispatch, active-scope, clean-state, and Git worktree checks. It requires exactly one clean symbolic worktree for the target branch, enforces the default cap of one, and fails closed for a missing, duplicate, stale, locked, prunable, detached, dirty, or unmerged slot. It never creates, resets, stashes, prunes, or deletes topology. Local PASS reports host task state as `UNKNOWN`; the Program Orchestrator must still confirm one matching idle task before dispatch.

Governance changes belong on the canonical project branch. Worker branches consume the committed Brief and Work Item read-only and commit only their exact product/evidence scope. After a terminal result, reconcile lifecycle and Wiki knowledge on the canonical branch before another dispatch. After source verification, rebuild the independent release repository from the exact mapped ledger; documentation or tests on an unintegrated worker branch are not release output.

For new work, Handoff Contract v1 can carry intent across those boundaries without adding another file type. The immutable Brief defines stable `G-###`, `NG-###`, `INV-###`, `D-###`, and `AC-###` IDs; the Work Item references the applicable IDs; committed Evidence maps each ID to an output, verification, and evidence pointer. Start rejects invalid or Brief-unknown references, and handoff rejects missing, extra, duplicate, or incomplete traceability. Existing Work Items remain valid without opting in. Pseudocode or decision tables can clarify behavior, but the IDs and evidence table are the deterministic contract.

## Exact mapped release boundary

The release contains exactly thirteen files: root `README.md`, root `.agents/plugins/marketplace.json`, and these eleven byte-identical source mappings under `plugins/project-orchestration/`:

| Source path | Release path |
| --- | --- |
| `.codex-plugin/plugin.json` | `plugins/project-orchestration/.codex-plugin/plugin.json` |
| `hooks/hooks.json` | `plugins/project-orchestration/hooks/hooks.json` |
| `hooks/scope_guard.py` | `plugins/project-orchestration/hooks/scope_guard.py` |
| `skills/bootstrap-project/SKILL.md` | `plugins/project-orchestration/skills/bootstrap-project/SKILL.md` |
| `skills/bootstrap-project/agents/openai.yaml` | `plugins/project-orchestration/skills/bootstrap-project/agents/openai.yaml` |
| `skills/bootstrap-project/references/assurance.md` | `plugins/project-orchestration/skills/bootstrap-project/references/assurance.md` |
| `skills/bootstrap-project/references/manifest.md` | `plugins/project-orchestration/skills/bootstrap-project/references/manifest.md` |
| `skills/bootstrap-project/references/operating-model.md` | `plugins/project-orchestration/skills/bootstrap-project/references/operating-model.md` |
| `skills/bootstrap-project/references/snapshot.md` | `plugins/project-orchestration/skills/bootstrap-project/references/snapshot.md` |
| `skills/bootstrap-project/scripts/bootstrap_project.py` | `plugins/project-orchestration/skills/bootstrap-project/scripts/bootstrap_project.py` |
| `skills/bootstrap-project/scripts/capture_process.py` | `plugins/project-orchestration/skills/bootstrap-project/scripts/capture_process.py` |

The marketplace wrapper is canonical, separately digest-pinned, and not plugin content. The private guard is a validator, not a release materializer. It validates exact layout, source identity, privacy and credential rules, clean single-root history, public-safe Git metadata, source drift, and its byte-identical private pre-push installation. The installed pre-push copy remains untracked under the release repository's private Git hooks directory.

## Validation

### Source-maintainer validation

These commands require the source checkout and source-only `tests/**` or `.codex/release/**` paths:

```text
python -m unittest discover -s tests -v
python <plugin-creator-skill-root>/scripts/validate_plugin.py .
python <skill-creator-skill-root>/scripts/quick_validate.py skills/bootstrap-project
python -m py_compile skills/bootstrap-project/scripts/bootstrap_project.py hooks/scope_guard.py .codex/release/pre_push_guard.py
git archive --format=tar --worktree-attributes HEAD
```

### Installed-consumer validation

Installed consumers use the installed skill root and do not assume `tests/**` exists:

```text
python <installed-skill-root>/scripts/bootstrap_project.py check --root <project-root>
python <installed-skill-root>/scripts/bootstrap_project.py registry-check --root <project-root>
python <installed-skill-root>/scripts/bootstrap_project.py check --root <project-root> --ready
```

`registry-check` hides registry values. `check --ready` is still structural and local evidence only.

## Proof limits

Local validation can prove bounded source behavior, native source archives, mapped temporary fixtures, and the stated Windows/Python/Codex CLI observation. It cannot prove an official Python minimum, current flat-repository installability, registration, installation, security, remote publication, other-PC execution, non-Windows support, consumer adoption, external Wiki truth, semantic freshness, independent audit, adoption, or lifecycle closure.

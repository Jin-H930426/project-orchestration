#!/usr/bin/env python3
"""Deterministic filesystem and local-registry support for bootstrap-project."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any, NamedTuple

MANIFEST_PATH = Path(".codex/orchestration.json")
REGISTRY_PATH = Path(".codex/session-registry.local.json")
ATTEMPTS_PATH = Path(".codex/work/attempts.jsonl")
WORK_ITEMS_PATH = Path(".codex/work/items")
AUDITS_PATH = Path(".codex/audits")
PLUGIN_NAME = "project-orchestration"
PLUGIN_VERSION = "0.2.1"
HOOKS_PATH = Path("project-orchestration-hooks")
HOOK_GUARD_PATH = HOOKS_PATH / "scope_guard.py"
PRE_COMMIT_PATH = HOOKS_PATH / "pre-commit"
PRE_COMMIT_WRAPPER = b"""#!/bin/sh
# managed by project-orchestration
if command -v python3 >/dev/null 2>&1; then
  exec python3 "$(dirname "$0")/scope_guard.py" pre-commit
fi
exec python "$(dirname "$0")/scope_guard.py" pre-commit
"""
COMMIT_RE = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
SESSION_REF_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$")
HANDOFF_CONTRACT_ID_RE = re.compile(r"^(?:G|NG|INV|D|AC)-[0-9]{3}$")
TASK_ID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
TASK_ID_SEARCH_RE = re.compile(
    rb"(?i)(?<![0-9a-f])[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}(?![0-9a-f])"
)
SENSITIVE_TASK_ID_SEARCH_RE = re.compile(
    rb"(?i)[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"
)
ASSURANCE_COUNT_RE = re.compile(r"0|[1-9][0-9]{0,8}")
GIT_OBJECT_SIZE_RE = re.compile(r"0|[1-9][0-9]{0,19}")
TIME_RE = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")
DAYS = {"MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"}
RISKS = {"low", "standard", "high", "critical"}
SESSION_MODES = {"off", "capture-only", "balanced", "aggressive"}
REASONING = {"none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"}
OUTCOMES = {"failed", "resolved", "blocked"}
MANAGED_START = "<!-- project-orchestration:start -->"
MANAGED_END = "<!-- project-orchestration:end -->"
SENSITIVE_TEMP_PATTERN = ".codex/.session-registry.*.tmp"
BOOTSTRAP_MUTABLE_PATHS = {
    MANIFEST_PATH.as_posix(),
    ".gitignore",
    ".gitattributes",
    "AGENTS.md",
    ".codex/operating-model.md",
    ".codex/session-registry.schema.json",
}
TEXT_SUFFIXES = {
    ".adoc", ".cfg", ".conf", ".cs", ".csv", ".ini", ".java", ".js", ".json",
    ".md", ".mjs", ".py", ".rst", ".toml", ".ts", ".tsv", ".txt", ".xml", ".yaml", ".yml",
}
SNAPSHOT_PROJECT_PATH_RE = re.compile(r"^\.codex/docs/projects/(P\d{3})-[^/]+\.md$")
SNAPSHOT_REQUIREMENT_PATH_RE = re.compile(r"^\.codex/docs/requirements/((P\d{3})-G\d{3})-[^/]+\.md$")
SNAPSHOT_WORK_ITEM_DISCOVERY_RE = re.compile(r"^\.codex/work/items/WI-[^/]*\.md$")
SNAPSHOT_WORK_ITEM_PATH_RE = re.compile(r"^\.codex/work/items/(WI-[A-Za-z0-9][A-Za-z0-9._-]{0,126})\.md$")
SNAPSHOT_STATUS_RE = re.compile(r"^[a-z][a-z0-9-]*$")
SNAPSHOT_UNKNOWNS = [
    "automation-state=UNKNOWN",
    "consumer-adoption=UNKNOWN",
    "independent-audit=UNKNOWN",
    "live-task-state=UNKNOWN",
    "live-worktree-state=UNKNOWN",
    "semantic-verification=UNKNOWN",
    "wiki-truth=UNKNOWN",
]
SNAPSHOT_RECORD_LIMITATIONS = ["live-state-not-queried", "semantic-state-not-evaluated"]
SNAPSHOT_LIVE_LIMITATIONS = [
    "automation-state-not-queried",
    "consumer-adoption-not-evaluated",
    "independent-audit-not-evaluated",
    "live-task-state-not-queried",
    "live-worktree-state-not-queried",
    "semantic-verification-not-evaluated",
    "wiki-truth-not-evaluated",
]
SNAPSHOT_LIMITATIONS = [
    "audit-record-schema-not-defined",
    "domain-registers-not-normalized",
    "structural-projection-only",
]
ASSURANCE_ID_RE = re.compile(r"^AR-[A-Z0-9]+(?:-[A-Z0-9]+)*$")
ASSURANCE_RECORD_TYPES = {"owner-verification", "independent-audit"}
ASSURANCE_VERDICTS = {"passed", "failed", "blocked", "stale"}
ASSURANCE_ADOPTION_STATES = {"not-required", "required", "pending", "adopted", "rejected", "blocked", "stale"}
ASSURANCE_REQUIRED_STALE_TRIGGERS = {
    "acceptance-revision-changed",
    "actor-registry-unresolved",
    "adoption-state-changed",
    "evidence-blob-changed",
    "runtime-fingerprint-changed",
    "subject-commit-changed",
}
ASSURANCE_LIMITATION = "structural-and-local-evidence-only"
GIT_TIMEOUT_SECONDS = 15


class DeferredFileFailure(NamedTuple):
    code: str


CommittedFileValue = tuple[bytes, str] | DeferredFileFailure
CommittedFileCache = dict[tuple[str, str], CommittedFileValue]


class BlockedError(RuntimeError):
    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}{': ' + detail if detail else ''}")


def blocked(condition: bool, code: str, detail: str = "") -> None:
    if condition:
        raise BlockedError(code, detail)


def provenance_git_environment() -> dict[str, str]:
    environment = {
        name: value for name, value in os.environ.items() if not name.startswith("GIT_")
    }
    environment.update(
        {
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_NO_REPLACE_OBJECTS": "1",
            "GIT_TERMINAL_PROMPT": "0",
        }
    )
    return environment


def git_process(
    root: Path,
    *args: str | bytes,
    **kwargs: Any,
) -> subprocess.CompletedProcess[Any]:
    blocked("env" in kwargs, "GIT_ERROR")
    blocked("timeout" in kwargs, "GIT_ERROR")
    try:
        return subprocess.run(
            ["git", "-c", "core.fsmonitor=false", "-C", str(root), *args],
            env=provenance_git_environment(),
            timeout=GIT_TIMEOUT_SECONDS,
            **kwargs,
        )
    except subprocess.TimeoutExpired:
        raise BlockedError("GIT_TIMEOUT") from None
    except OSError:
        raise BlockedError("GIT_EXECUTION_FAILED") from None


class CommitGraph:
    def __init__(self, parents: dict[str, tuple[str, ...]]) -> None:
        self.parents = parents
        self.ancestor_cache: dict[tuple[str, str], bool] = {}

    def contains(self, commit: str) -> bool:
        return commit in self.parents

    def is_ancestor(self, ancestor: str, descendant: str) -> bool:
        key = (ancestor, descendant)
        if key not in self.ancestor_cache:
            pending = [descendant]
            seen: set[str] = set()
            while pending and ancestor not in seen:
                current = pending.pop()
                if current in seen or current not in self.parents:
                    continue
                seen.add(current)
                pending.extend(self.parents[current])
            self.ancestor_cache[key] = ancestor in seen
        return self.ancestor_cache[key]


def load_commit_graph(root: Path, head: str) -> CommitGraph:
    result = git_process(
        root,
        "rev-list",
        "--parents",
        head,
        text=True,
        capture_output=True,
    )
    blocked(result.returncode != 0 or bool(result.stderr), "GIT_HISTORY_INCOMPLETE")
    parents: dict[str, tuple[str, ...]] = {}
    for line in result.stdout.splitlines():
        values = line.split()
        blocked(
            not values
            or any(COMMIT_RE.fullmatch(value) is None for value in values)
            or values[0] in parents,
            "GIT_HISTORY_INCOMPLETE",
        )
        parents[values[0]] = tuple(values[1:])
    blocked(head not in parents or any(parent not in parents for values in parents.values() for parent in values), "GIT_HISTORY_INCOMPLETE")
    return CommitGraph(parents)


def commit_exists(root: Path, commit: str, graph: CommitGraph | None) -> bool:
    return graph.contains(commit) if graph is not None else (
        run_git(root, "cat-file", "-e", f"{commit}^{{commit}}").returncode == 0
    )


def commit_is_ancestor(
    root: Path,
    ancestor: str,
    descendant: str,
    graph: CommitGraph | None,
) -> bool:
    return graph.is_ancestor(ancestor, descendant) if graph is not None else (
        run_git(root, "merge-base", "--is-ancestor", ancestor, descendant).returncode == 0
    )


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise BlockedError("MISSING_FILE", str(path)) from exc
    except json.JSONDecodeError as exc:
        raise BlockedError("MALFORMED_JSON", f"{path}:{exc.lineno}:{exc.colno}") from exc


def nonempty(value: Any, field: str) -> str:
    blocked(not isinstance(value, str) or not value.strip(), "INVALID_FIELD", field)
    return value.strip()


def normalized_scope(value: Any, field: str) -> str:
    scope = nonempty(value, field)
    blocked("\\" in scope, "INVALID_SCOPE", f"{field}: use '/' separators")
    blocked(scope.startswith(("/", "~")) or re.match(r"^[A-Za-z]:", scope) is not None, "INVALID_SCOPE", field)
    blocked(any(char in scope for char in "*?[]{}"), "INVALID_SCOPE", f"{field}: globs are not allowed")
    path = PurePosixPath(scope)
    blocked(".." in path.parts, "INVALID_SCOPE", f"{field}: '..' is not allowed")
    result = str(path).removeprefix("./").rstrip("/")
    blocked(result in {"", "."}, "INVALID_SCOPE", field)
    return result


def normalized_read_scope(value: Any, field: str) -> str:
    if value == ".":
        return "."
    return normalized_scope(value, field)


def scopes_overlap(left: str, right: str) -> bool:
    a = left.casefold().rstrip("/")
    b = right.casefold().rstrip("/")
    return a == b or a.startswith(b + "/") or b.startswith(a + "/")


def validate_manifest(data: Any) -> dict[str, Any]:
    blocked(not isinstance(data, dict), "INVALID_MANIFEST", "root must be an object")
    blocked(data.get("schema_version") != 1, "UNSUPPORTED_SCHEMA", str(data.get("schema_version")))

    tooling = data.get("tooling")
    blocked(not isinstance(tooling, dict) or set(tooling) != {"plugin", "version"}, "INVALID_FIELD", "tooling")
    blocked(tooling.get("plugin") != PLUGIN_NAME, "INVALID_FIELD", "tooling.plugin")
    blocked(tooling.get("version") != PLUGIN_VERSION, "TOOLING_VERSION_MISMATCH", str(tooling.get("version")))

    project = data.get("project")
    blocked(not isinstance(project, dict), "INVALID_FIELD", "project")
    nonempty(project.get("name"), "project.name")
    nonempty(project.get("goal"), "project.goal")
    blocked(project.get("risk") not in RISKS, "INVALID_FIELD", "project.risk")

    governance = data.get("governance")
    blocked(not isinstance(governance, dict), "INVALID_FIELD", "governance")
    blocked(set(governance) != {"project_plan", "requirement_brief", "bootstrap_work_item"}, "INVALID_FIELD", "governance")
    for field in ("project_plan", "requirement_brief", "bootstrap_work_item"):
        governance[field] = normalized_scope(governance.get(field), f"governance.{field}")

    knowledge = data.get("knowledge")
    blocked(not isinstance(knowledge, dict), "INVALID_FIELD", "knowledge")
    blocked(knowledge.get("provider") != "llm-wiki", "INVALID_FIELD", "knowledge.provider")
    blocked(knowledge.get("location") != "local", "INVALID_FIELD", "knowledge.location")
    blocked(knowledge.get("session_mode") not in SESSION_MODES, "INVALID_FIELD", "knowledge.session_mode")
    blocked(knowledge.get("raw_transcripts") is not False, "PRIVACY_REQUIRED", "knowledge.raw_transcripts must be false")
    blocked(knowledge.get("privacy") != "redacted", "PRIVACY_REQUIRED", "knowledge.privacy must be redacted")

    sessions = data.get("sessions")
    blocked(not isinstance(sessions, list) or not sessions, "INVALID_FIELD", "sessions")
    refs: dict[str, dict[str, Any]] = {}
    titles: set[str] = set()
    owners: list[tuple[str, str]] = []
    orchestrators = 0
    for index, session in enumerate(sessions):
        prefix = f"sessions[{index}]"
        blocked(not isinstance(session, dict), "INVALID_FIELD", prefix)
        ref = nonempty(session.get("ref"), f"{prefix}.ref")
        blocked(SESSION_REF_RE.fullmatch(ref) is None, "INVALID_SESSION_REF", ref)
        key = ref.casefold()
        blocked(key in refs, "SESSION_REF_COLLISION", ref)
        refs[key] = session
        title = nonempty(session.get("title"), f"{prefix}.title")
        title_key = title.casefold()
        blocked(title_key in titles, "SESSION_TITLE_COLLISION", title)
        titles.add(title_key)
        role = nonempty(session.get("role"), f"{prefix}.role")
        orchestrators += int(role == "program-orchestrator")
        nonempty(session.get("purpose"), f"{prefix}.purpose")
        nonempty(session.get("branch"), f"{prefix}.branch")
        nonempty(session.get("retirement_condition"), f"{prefix}.retirement_condition")
        blocked(session.get("persistent") is not True, "INVALID_FIELD", f"{prefix}.persistent")
        blocked(session.get("environment") not in {"local", "worktree"}, "INVALID_FIELD", f"{prefix}.environment")
        blocked(role == "program-orchestrator" and session.get("environment") != "local", "ORCHESTRATOR_MUST_USE_LOCAL_CHECKOUT")
        nonempty(session.get("model"), f"{prefix}.model")
        blocked(session.get("reasoning") not in REASONING, "INVALID_FIELD", f"{prefix}.reasoning")
        read_scopes = session.get("read_scope")
        blocked(not isinstance(read_scopes, list) or not read_scopes, "INVALID_FIELD", f"{prefix}.read_scope")
        session["read_scope"] = [normalized_read_scope(scope, f"{prefix}.read_scope") for scope in read_scopes]
        for field in ("durable_sources", "evidence_outputs"):
            paths = session.get(field)
            blocked(not isinstance(paths, list) or not paths, "INVALID_FIELD", f"{prefix}.{field}")
            session[field] = [normalized_scope(path, f"{prefix}.{field}") for path in paths]
        scopes = session.get("write_scope")
        blocked(not isinstance(scopes, list) or not scopes, "INVALID_FIELD", f"{prefix}.write_scope")
        normalized = [normalized_scope(scope, f"{prefix}.write_scope") for scope in scopes]
        session["write_scope"] = normalized
        for output in session["evidence_outputs"]:
            contained = any(output.casefold() == scope.casefold() or output.casefold().startswith(scope.casefold() + "/") for scope in normalized)
            blocked(not contained, "EVIDENCE_OUTPUT_OUTSIDE_WRITE_SCOPE", f"{ref}:{output}")
        owners.extend((ref, scope) for scope in normalized)

    blocked(orchestrators != 1, "PROGRAM_ORCHESTRATOR_COUNT", str(orchestrators))
    for left_index, (left_ref, left_scope) in enumerate(owners):
        for right_ref, right_scope in owners[left_index + 1 :]:
            if left_ref != right_ref and scopes_overlap(left_scope, right_scope):
                raise BlockedError("WRITE_SCOPE_OVERLAP", f"{left_ref}:{left_scope} <> {right_ref}:{right_scope}")

    domains = data.get("domains")
    blocked(not isinstance(domains, list), "INVALID_FIELD", "domains")
    domain_ids: set[str] = set()
    for index, domain in enumerate(domains):
        prefix = f"domains[{index}]"
        blocked(not isinstance(domain, dict), "INVALID_FIELD", prefix)
        domain_id = nonempty(domain.get("id"), f"{prefix}.id")
        blocked(SESSION_REF_RE.fullmatch(domain_id) is None, "INVALID_DOMAIN_ID", domain_id)
        key = domain_id.casefold()
        blocked(key in domain_ids, "DOMAIN_ID_COLLISION", domain_id)
        domain_ids.add(key)
        nonempty(domain.get("purpose"), f"{prefix}.purpose")
        steward_ref = nonempty(domain.get("steward_ref"), f"{prefix}.steward_ref")
        steward = refs.get(steward_ref.casefold())
        blocked(steward is None, "UNKNOWN_STEWARD", steward_ref)
        domain_scopes = domain.get("write_scope")
        blocked(not isinstance(domain_scopes, list) or not domain_scopes, "INVALID_FIELD", f"{prefix}.write_scope")
        normalized = [normalized_scope(scope, f"{prefix}.write_scope") for scope in domain_scopes]
        domain["write_scope"] = normalized
        steward_scopes = steward["write_scope"]
        for scope in normalized:
            contained = any(scope.casefold() == parent.casefold() or scope.casefold().startswith(parent.casefold() + "/") for parent in steward_scopes)
            blocked(not contained, "DOMAIN_SCOPE_OUTSIDE_STEWARD", f"{domain_id}:{scope}")

    assurance = data.get("assurance")
    blocked(not isinstance(assurance, dict), "INVALID_FIELD", "assurance")
    nonempty(assurance.get("timezone"), "assurance.timezone")
    for cadence in ("daily", "weekly", "milestone"):
        item = assurance.get(cadence)
        blocked(not isinstance(item, dict) or not isinstance(item.get("enabled"), bool), "INVALID_FIELD", f"assurance.{cadence}")
        if not item["enabled"]:
            continue
        nonempty(item.get("model"), f"assurance.{cadence}.model")
        blocked(item.get("reasoning") not in REASONING, "INVALID_FIELD", f"assurance.{cadence}.reasoning")
        nonempty(item.get("prompt"), f"assurance.{cadence}.prompt")
        blocked(item.get("cost_profile") not in {"low", "standard", "high"}, "INVALID_FIELD", f"assurance.{cadence}.cost_profile")
        blocked(not isinstance(item.get("fresh_context"), bool), "INVALID_FIELD", f"assurance.{cadence}.fresh_context")
        checks = item.get("checks")
        blocked(not isinstance(checks, list) or not checks, "INVALID_FIELD", f"assurance.{cadence}.checks")
        for check in checks:
            nonempty(check, f"assurance.{cadence}.checks")
    if assurance["daily"]["enabled"]:
        blocked(TIME_RE.fullmatch(str(assurance["daily"].get("local_time", ""))) is None, "INVALID_FIELD", "assurance.daily.local_time")
    if assurance["weekly"]["enabled"]:
        blocked(str(assurance["weekly"].get("day", "")).upper() not in DAYS, "INVALID_FIELD", "assurance.weekly.day")
        blocked(TIME_RE.fullmatch(str(assurance["weekly"].get("local_time", ""))) is None, "INVALID_FIELD", "assurance.weekly.local_time")
        blocked(assurance["weekly"].get("fresh_context") is not True, "FRESH_AUDITOR_REQUIRED", "weekly")
    if assurance["milestone"]["enabled"]:
        blocked(assurance["milestone"].get("fresh_context") is not True, "FRESH_AUDITOR_REQUIRED", "milestone")

    loop = data.get("loop_breaker")
    blocked(not isinstance(loop, dict), "INVALID_FIELD", "loop_breaker")
    warn_after = loop.get("warn_after")
    block_after = loop.get("block_after")
    blocked(not isinstance(warn_after, int) or warn_after < 2, "INVALID_FIELD", "loop_breaker.warn_after")
    blocked(not isinstance(block_after, int) or block_after <= warn_after, "INVALID_FIELD", "loop_breaker.block_after")
    return data


def run_git(root: Path, *args: str, check: bool = False) -> subprocess.CompletedProcess[str]:
    result = git_process(root, *args, text=True, capture_output=True)
    if check and result.returncode:
        raise BlockedError("GIT_ERROR")
    return result


def mutation_boundary(root: Path, target: Path) -> None:
    candidates: set[Path] = set()
    for endpoint in (root, target):
        current = Path(os.path.abspath(endpoint))
        while True:
            candidates.add(current)
            if current.parent == current:
                break
            current = current.parent
    try:
        for candidate in candidates:
            if not os.path.lexists(candidate):
                continue
            metadata = os.lstat(candidate)
            attributes = getattr(metadata, "st_file_attributes", 0)
            blocked(
                stat.S_ISLNK(metadata.st_mode)
                or bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)),
                "MUTATION_REPARSE_POINT",
            )
    except BlockedError:
        raise
    except OSError:
        raise BlockedError("MUTATION_BOUNDARY_UNREADABLE") from None


def ensure_git(root: Path, init_git: bool = False) -> None:
    probe = run_git(root, "rev-parse", "--show-toplevel")
    if probe.returncode == 0:
        top = Path(probe.stdout.strip()).resolve()
        blocked(top != root.resolve(), "GIT_ROOT_MISMATCH", str(top))
        return
    blocked(not init_git, "GIT_REQUIRED", str(root))
    mutation_boundary(root, root / ".git")
    result = git_process(root, "init", "-b", "main", ".", text=True, capture_output=True)
    blocked(result.returncode != 0, "GIT_INIT_FAILED")


def ensure_tracked_clean(root: Path, allowed_paths: set[str] | None = None) -> None:
    status = run_git(root, "status", "--porcelain", "--untracked-files=no", check=True).stdout.rstrip("\r\n")
    allowed = {path.casefold() for path in (allowed_paths or set())}
    unexpected = []
    for line in status.splitlines():
        path = line[3:].strip().replace("\\", "/")
        if " -> " in path or path.casefold() not in allowed:
            unexpected.append(path)
    blocked(bool(unexpected), "DIRTY_TRACKED_WORKTREE", ",".join(unexpected))


def ensure_worktree_clean(root: Path) -> None:
    status = run_git(root, "status", "--porcelain", "--untracked-files=all", check=True).stdout.rstrip("\r\n")
    blocked(bool(status), "WORKTREE_NOT_CLEAN")


def atomic_write(root: Path, path: Path, content: str, sensitive: bool = False) -> str:
    content = content.replace("\r\n", "\n").replace("\r", "\n")
    if not content.endswith("\n"):
        content += "\n"
    existed = path.exists()
    if existed and path.read_text(encoding="utf-8") == content:
        return "unchanged"
    mutation_boundary(root, path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_name: str | None = None
    try:
        prefix = ".session-registry." if sensitive else f".{path.name}."
        mutation_boundary(root, path)
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", newline="\n", delete=False, dir=path.parent, prefix=prefix, suffix=".tmp"
        ) as handle:
            handle.write(content)
            temp_name = handle.name
        mutation_boundary(root, path)
        os.replace(temp_name, path)
    finally:
        if temp_name:
            mutation_boundary(root, Path(temp_name))
            Path(temp_name).unlink(missing_ok=True)
    return "updated" if existed else "created"


def atomic_write_bytes(root: Path, path: Path, content: bytes, executable: bool = False) -> str:
    existed = path.exists()
    if existed and path.read_bytes() == content:
        result = "unchanged"
    else:
        mutation_boundary(root, path)
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_name: str | None = None
        try:
            mutation_boundary(root, path)
            with tempfile.NamedTemporaryFile("wb", delete=False, dir=path.parent, prefix=f".{path.name}.", suffix=".tmp") as handle:
                handle.write(content)
                temp_name = handle.name
            mutation_boundary(root, path)
            os.replace(temp_name, path)
        finally:
            if temp_name:
                mutation_boundary(root, Path(temp_name))
                Path(temp_name).unlink(missing_ok=True)
        result = "updated" if existed else "created"
    if executable:
        mutation_boundary(root, path)
        os.chmod(path, path.stat().st_mode | 0o111)
    return result


def git_worktree_inventory(root: Path, code: str) -> list[dict[str, str]]:
    result = run_git(root, "worktree", "list", "--porcelain", "-z")
    blocked(
        result.returncode != 0
        or bool(result.stderr)
        or not result.stdout.endswith("\0"),
        code,
    )
    records: list[dict[str, str]] = []
    paths: set[str] = set()
    allowed = {"worktree", "HEAD", "branch", "bare", "detached", "locked", "prunable"}
    for raw_record in [value for value in result.stdout.split("\0\0") if value]:
        fields = [value for value in raw_record.split("\0") if value]
        blocked(not fields or not fields[0].startswith("worktree "), code)
        record: dict[str, str] = {}
        for field in fields:
            key, separator, value = field.partition(" ")
            blocked(key not in allowed or key in record, code)
            if key in {"worktree", "HEAD", "branch"}:
                blocked(not separator or not value, code)
            elif key in {"bare", "detached"}:
                blocked(bool(separator or value), code)
            record[key] = value
        path = record.get("worktree", "")
        blocked(
            not path
            or path in paths
            or any(not character.isprintable() for character in path),
            code,
        )
        paths.add(path)
        records.append(record)
    blocked(not records, code)
    return records


def install_git_hooks(root: Path) -> list[str]:
    root = Path(os.path.abspath(root))
    git_dir_result = run_git(root, "rev-parse", "--absolute-git-dir")
    git_dir_lines = git_dir_result.stdout.splitlines() if git_dir_result.returncode == 0 else []
    blocked(
        git_dir_result.returncode != 0
        or bool(git_dir_result.stderr)
        or len(git_dir_lines) != 1
        or not git_dir_lines[0],
        "HOOKS_PATH_UNREADABLE",
    )
    git_dir = Path(git_dir_lines[0])
    blocked(not git_dir.is_absolute(), "HOOKS_PATH_UNREADABLE")
    mutation_boundary(root, git_dir)
    hooks_directory = git_dir / HOOKS_PATH
    configured_hooks_path = hooks_directory.as_posix()
    source = Path(__file__).resolve().parents[3] / "hooks/scope_guard.py"
    blocked(not source.is_file() or source.is_symlink(), "HOOK_SOURCE_UNREADABLE")
    try:
        guard = source.read_bytes()
    except OSError:
        raise BlockedError("HOOK_SOURCE_UNREADABLE") from None
    blocked(b'"""Advisory lifecycle and staged-scope guards' not in guard[:256], "HOOK_SOURCE_UNREADABLE")
    managed = (
        (git_dir / HOOK_GUARD_PATH, guard, False),
        (git_dir / PRE_COMMIT_PATH, PRE_COMMIT_WRAPPER, True),
    )
    for path, expected, _ in managed:
        mutation_boundary(root, path)
        blocked(path.exists() and not path.is_file(), "HOOK_INSTALL_CONFLICT")
        if path.exists():
            try:
                blocked(path.read_bytes() != expected, "HOOK_INSTALL_CONFLICT")
            except OSError:
                raise BlockedError("HOOK_INSTALL_CONFLICT") from None

    extension = run_git(root, "config", "--local", "--type=bool", "--get-all", "extensions.worktreeConfig")
    blocked(extension.returncode not in {0, 1} or bool(extension.stderr), "HOOKS_PATH_UNREADABLE")
    extension_values = extension.stdout.splitlines() if extension.returncode == 0 else []
    blocked(len(extension_values) > 1 or (extension_values and extension_values[0] != "true"), "HOOKS_PATH_CONFLICT")
    shared = run_git(root, "config", "--local", "--get-all", "core.hooksPath")
    blocked(shared.returncode not in {0, 1} or bool(shared.stderr), "HOOKS_PATH_UNREADABLE")
    shared_values = shared.stdout.splitlines() if shared.returncode == 0 else []
    blocked(bool(shared_values), "HOOKS_PATH_SHARED_CONFLICT")

    worktree_roots = [
        Path(record["worktree"])
        for record in git_worktree_inventory(root, "HOOKS_PATH_UNREADABLE")
    ]

    config_files: list[tuple[Path, Path]] = []
    for worktree_root in worktree_roots:
        config_path = run_git(worktree_root, "rev-parse", "--git-path", "config.worktree")
        lines = config_path.stdout.splitlines() if config_path.returncode == 0 else []
        blocked(
            config_path.returncode != 0
            or bool(config_path.stderr)
            or len(lines) != 1
            or not lines[0],
            "HOOKS_PATH_UNREADABLE",
        )
        config_file = Path(lines[0])
        if not config_file.is_absolute():
            config_file = worktree_root / config_file
        mutation_boundary(root, config_file)
        blocked(config_file.exists() and not config_file.is_file(), "HOOKS_PATH_UNREADABLE")
        config_files.append((worktree_root, config_file))
        if not extension_values and config_file.exists():
            dormant_entries = run_git(
                root,
                "config",
                "--file",
                str(config_file),
                "--includes",
                "--null",
                "--list",
            )
            blocked(
                dormant_entries.returncode not in {0, 1} or bool(dormant_entries.stderr),
                "HOOKS_PATH_UNREADABLE",
            )
            blocked(bool(dormant_entries.stdout), "HOOKS_WORKTREE_CONFIG_DORMANT")

    current = [
        config_file
        for worktree_root, config_file in config_files
        if worktree_root.resolve() == root.resolve()
    ]
    blocked(len(current) != 1, "HOOKS_PATH_UNREADABLE")
    config_file = current[0]
    configured = run_git(
        root,
        "config",
        "--file",
        str(config_file),
        "--includes",
        "--get-all",
        "core.hooksPath",
    )
    blocked(configured.returncode not in {0, 1} or bool(configured.stderr), "HOOKS_PATH_UNREADABLE")
    values = configured.stdout.splitlines() if configured.returncode == 0 else []
    blocked(len(values) > 1 or (values and values[0] != configured_hooks_path), "HOOKS_PATH_CONFLICT")

    common_path = run_git(root, "rev-parse", "--git-path", "config")
    common_lines = common_path.stdout.splitlines() if common_path.returncode == 0 else []
    blocked(
        common_path.returncode != 0
        or bool(common_path.stderr)
        or len(common_lines) != 1
        or not common_lines[0],
        "HOOKS_PATH_UNREADABLE",
    )
    common_file = Path(common_lines[0])
    if not common_file.is_absolute():
        common_file = root / common_file
    mutation_boundary(root, common_file)
    snapshots: dict[Path, tuple[bool, bytes, int]] = {}
    for path in [common_file, config_file, *(item[0] for item in managed)]:
        mutation_boundary(root, path)
        try:
            snapshots[path] = (
                path.exists(),
                path.read_bytes() if path.exists() else b"",
                path.stat().st_mode if path.exists() else 0,
            )
        except OSError:
            raise BlockedError("HOOKS_PATH_UNREADABLE") from None
    hooks_directory_existed = hooks_directory.exists()

    try:
        results = [
            atomic_write_bytes(root, path, content, executable=executable)
            for path, content, executable in managed
        ]
        if not extension_values:
            mutation_boundary(root, common_file)
            enabled = run_git(root, "config", "--local", "extensions.worktreeConfig", "true")
            blocked(enabled.returncode != 0 or bool(enabled.stderr), "HOOKS_PATH_UPDATE_FAILED")
        if not values:
            mutation_boundary(root, config_file)
            update = run_git(root, "config", "--worktree", "core.hooksPath", configured_hooks_path)
            blocked(update.returncode != 0 or bool(update.stderr), "HOOKS_PATH_UPDATE_FAILED")
        verified = run_git(root, "config", "--worktree", "--get-all", "core.hooksPath")
        blocked(
            verified.returncode != 0
            or bool(verified.stderr)
            or verified.stdout.splitlines() != [configured_hooks_path]
            or (git_dir / HOOK_GUARD_PATH).read_bytes() != guard,
            "HOOK_INSTALL_VERIFY_FAILED",
        )
        return results
    except Exception as failure:
        try:
            for path, (existed, content, mode) in snapshots.items():
                mutation_boundary(root, path)
                if existed:
                    atomic_write_bytes(root, path, content)
                    mutation_boundary(root, path)
                    os.chmod(path, mode)
                else:
                    path.unlink(missing_ok=True)
            if not hooks_directory_existed and hooks_directory.exists():
                mutation_boundary(root, hooks_directory)
                hooks_directory.rmdir()
        except Exception:
            raise BlockedError("HOOK_INSTALL_ROLLBACK_FAILED") from None
        if isinstance(failure, BlockedError):
            raise failure
        raise BlockedError("HOOK_INSTALL_UPDATE_FAILED") from None


def merge_lines(root: Path, path: Path, lines: list[str]) -> str:
    current = path.read_text(encoding="utf-8") if path.exists() else ""
    normalized = current.replace("\r\n", "\n").replace("\r", "\n")
    result = normalized.rstrip("\n")
    existing = set(normalized.splitlines())
    missing = [line for line in lines if line not in existing]
    if missing:
        result = (result + "\n" if result else "") + "\n".join(missing)
    return atomic_write(root, path, result)


def agents_block() -> str:
    return "\n".join(
        [
            MANAGED_START,
            "Read `.codex/orchestration.json` and `.codex/operating-model.md` before project work.",
            "Use Session Ref aliases in tracked text; actual task IDs belong only in the ignored local registry.",
            "Keep one writer per exact scope, use Work Items for bounded execution, and report missing evidence as UNKNOWN or BLOCKED.",
            "Run the bootstrap-project work-check start gate before bounded writes and its handoff gate before readback.",
            "Do not let structure-only checks stand in for semantic verification or independent audit.",
            MANAGED_END,
        ]
    )


def managed_agents(root: Path, path: Path) -> str:
    block = agents_block()
    current = path.read_text(encoding="utf-8") if path.exists() else "# Project Instructions\n"
    starts = current.count(MANAGED_START)
    ends = current.count(MANAGED_END)
    blocked(starts != ends or starts > 1, "MALFORMED_MANAGED_BLOCK", str(path))
    if starts == 1:
        before, tail = current.split(MANAGED_START, 1)
        _, after = tail.split(MANAGED_END, 1)
        desired = before.rstrip() + "\n\n" + block + after
    else:
        desired = current.rstrip() + "\n\n" + block
    return atomic_write(root, path, desired)


def render_operating_model(manifest: dict[str, Any]) -> str:
    rows = [
        "| Session Ref | Stable Title | Role | Branch | Environment | Write Scope |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    contracts: list[str] = []
    for session in manifest["sessions"]:
        rows.append(
            f"| {session['ref']} | {session['title']} | {session['role']} | {session['branch']} | "
            f"{session['environment']} | {', '.join(session['write_scope'])} |"
        )
        contracts.extend(
            [
                f"### {session['ref']}",
                "",
                f"- Read scope: {', '.join(session['read_scope'])}",
                f"- Durable sources: {', '.join(session['durable_sources'])}",
                f"- Evidence outputs: {', '.join(session['evidence_outputs'])}",
                f"- Retirement: {session['retirement_condition']}",
                "",
            ]
        )
    governance = manifest["governance"]
    assurance_rows = ["| Cadence | Enabled | Model | Reasoning | Fresh Context |", "| --- | --- | --- | --- | --- |"]
    for cadence in ("daily", "weekly", "milestone"):
        item = manifest["assurance"][cadence]
        assurance_rows.append(
            f"| {cadence} | {item['enabled']} | {item.get('model', '-')} | {item.get('reasoning', '-')} | "
            f"{item.get('fresh_context', '-')} |"
        )
    loop = manifest["loop_breaker"]
    return "\n".join(
        [
            "<!-- generated by bootstrap-project; edit .codex/orchestration.json instead -->",
            "# Operating Model",
            "",
            f"Project: {manifest['project']['name']}",
            f"Tooling: {manifest['tooling']['plugin']} {manifest['tooling']['version']}",
            f"Goal: {manifest['project']['goal']}",
            f"Risk: {manifest['project']['risk']}",
            "",
            "## Governance Sources",
            "",
            f"- Project Plan: {governance['project_plan']}",
            f"- Requirement Brief: {governance['requirement_brief']}",
            f"- Bootstrap Work Item: {governance['bootstrap_work_item']}",
            "",
            "## Persistent Sessions",
            "",
            *rows,
            "",
            "## Session Contracts",
            "",
            *contracts,
            "## Authority",
            "",
            "Current user instruction, Git, active plans, Work Items, contracts, tests, and independent audit evidence are authoritative. Wiki articles and session digests are memory layers, not execution authority.",
            "",
            "## Knowledge",
            "",
            f"Use project-local llm-wiki in {manifest['knowledge']['session_mode']} mode with redacted capture and raw transcripts disabled. Keep `.wiki/.sessions/` ignored and promote knowledge explicitly.",
            "",
            "## Assurance",
            "",
            *assurance_rows,
            "",
            "Daily checks report exceptions only. Weekly and milestone audits use fresh auditors. Auditors do not implement findings or approve their own remediation.",
            "",
            "## Loop Breaker",
            "",
            f"Warn at attempt {loop['warn_after']}; block before attempt {loop['block_after']} without measurable progress. Require a changed hypothesis or input after the first matching failure.",
        ]
    )


def registry_schema() -> str:
    return json.dumps(
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "x-generator": "bootstrap-project",
            "title": "Local Codex Session Registry",
            "type": "object",
            "required": ["schema_version", "sessions"],
            "additionalProperties": False,
            "properties": {
                "schema_version": {"const": 1},
                "sessions": {
                    "type": "object",
                    "propertyNames": {"pattern": SESSION_REF_RE.pattern},
                    "additionalProperties": {"type": "string", "pattern": TASK_ID_RE.pattern},
                },
            },
        },
        indent=2,
    )


def ensure_generated_destinations(root: Path) -> None:
    operating = root / ".codex/operating-model.md"
    if operating.exists():
        content = operating.read_text(encoding="utf-8")
        blocked(not content.startswith("<!-- generated by bootstrap-project;"), "UNMANAGED_PATH_CONFLICT", operating.as_posix())
    schema = root / ".codex/session-registry.schema.json"
    if schema.exists():
        content = load_json(schema)
        blocked(
            not isinstance(content, dict) or content.get("x-generator") != "bootstrap-project",
            "UNMANAGED_PATH_CONFLICT",
            schema.as_posix(),
        )


def apply_baseline(root: Path, init_git: bool = False, install_hooks: bool = False) -> dict[str, int]:
    root = Path(os.path.abspath(root))
    mutation_boundary(root, root)
    root.mkdir(parents=True, exist_ok=True)
    ensure_git(root, init_git)
    ensure_tracked_clean(root, BOOTSTRAP_MUTABLE_PATHS)
    manifest = validate_manifest(load_json(root / MANIFEST_PATH))
    ensure_generated_destinations(root)
    counts = {"updated": 0, "unchanged": 0}

    def record(result: str) -> None:
        counts[result] = counts.get(result, 0) + 1

    record(merge_lines(root, root / ".gitignore", [REGISTRY_PATH.as_posix(), SENSITIVE_TEMP_PATTERN, ".wiki/.sessions/"]))
    record(merge_lines(root, root / ".gitattributes", ["* text=auto eol=lf", "*.md text eol=lf", "*.json text eol=lf"]))
    editor = "root = true\n\n[*]\ncharset = utf-8\nend_of_line = lf\ninsert_final_newline = true\ntrim_trailing_whitespace = true\n\n[*.md]\ntrim_trailing_whitespace = false\n"
    if not (root / ".editorconfig").exists():
        record(atomic_write(root, root / ".editorconfig", editor))
    record(managed_agents(root, root / "AGENTS.md"))
    record(atomic_write(root, root / ".codex/operating-model.md", render_operating_model(manifest)))
    record(atomic_write(root, root / ".codex/session-registry.schema.json", registry_schema()))
    if not (root / ".codex/work/index.md").exists():
        record(
            atomic_write(
                root,
                root / ".codex/work/index.md",
                "# Work Items\n\n| Work Item | Owner Session Ref | Branch | Source / Dispatch | Write Scope | Status | Problem Key |\n"
                "| --- | --- | --- | --- | --- | --- | --- |",
            )
        )
    if not (root / ATTEMPTS_PATH).exists():
        record(atomic_write(root, root / ATTEMPTS_PATH, ""))
    if not (root / ".codex/audits/index.md").exists():
        record(atomic_write(root, root / ".codex/audits/index.md", "# Assurance\n\nDaily clean checks are local-only. Record exception findings, weekly reports, and milestone audits here."))
    if install_hooks:
        for result in install_git_hooks(root):
            record(result)
    return counts


def ignored(root: Path, path: str) -> bool:
    return run_git(root, "check-ignore", "-q", path).returncode == 0


def tracked(root: Path, path: str) -> bool:
    return run_git(root, "ls-files", "--error-unmatch", path).returncode == 0


def load_registry(root: Path, required: bool = True) -> dict[str, str]:
    path = root / REGISTRY_PATH
    if not path.exists():
        blocked(required, "REGISTRY_REQUIRED")
        return {}
    data = load_json(path)
    blocked(not isinstance(data, dict) or set(data) != {"schema_version", "sessions"}, "INVALID_REGISTRY")
    blocked(data.get("schema_version") != 1, "INVALID_REGISTRY")
    sessions = data.get("sessions")
    blocked(not isinstance(sessions, dict), "INVALID_REGISTRY")
    aliases: set[str] = set()
    values: set[str] = set()
    result: dict[str, str] = {}
    for alias, task_id in sessions.items():
        blocked(not isinstance(alias, str) or SESSION_REF_RE.fullmatch(alias) is None, "INVALID_SESSION_REF")
        folded = alias.casefold()
        blocked(folded in aliases, "SESSION_REF_COLLISION")
        aliases.add(folded)
        blocked(not isinstance(task_id, str) or TASK_ID_RE.fullmatch(task_id) is None, "INVALID_TASK_ID")
        blocked(task_id.casefold() in values, "DUPLICATE_TASK_MAPPING")
        values.add(task_id.casefold())
        result[alias] = task_id
    return result


def registry_guard(root: Path, required: bool = True) -> dict[str, str]:
    blocked(not ignored(root, str(REGISTRY_PATH).replace("\\", "/")), "REGISTRY_NOT_IGNORED")
    blocked(tracked(root, str(REGISTRY_PATH).replace("\\", "/")), "REGISTRY_TRACKED")
    return load_registry(root, required)


def registry_set(root: Path, alias: str, task_id: str) -> int:
    blocked(SESSION_REF_RE.fullmatch(alias) is None, "INVALID_SESSION_REF")
    blocked(TASK_ID_RE.fullmatch(task_id) is None, "INVALID_TASK_ID")
    registry_guard(root, required=False)
    path = root / REGISTRY_PATH
    current = load_registry(root, required=False)
    for existing_alias, existing_id in current.items():
        blocked(existing_alias.casefold() == alias.casefold() and existing_alias != alias, "SESSION_REF_COLLISION")
        blocked(existing_id.casefold() == task_id.casefold() and existing_alias != alias, "DUPLICATE_TASK_MAPPING")
    current[alias] = task_id
    atomic_write(
        root,
        path,
        json.dumps({"schema_version": 1, "sessions": dict(sorted(current.items()))}, indent=2),
        sensitive=True,
    )
    try:
        mutation_boundary(root, path)
        os.chmod(path, 0o600)
    except OSError:
        pass
    return len(current)


def known_id_leaks(root: Path, values: list[str]) -> list[str]:
    result = git_process(root, "ls-files", "-z", "--stage", capture_output=True)
    blocked(
        result.returncode != 0
        or bool(result.stderr)
        or (bool(result.stdout) and not result.stdout.endswith(b"\0")),
        "TRACKED_EVIDENCE_UNREADABLE",
    )
    leaks: list[str] = []
    known = [value.casefold().encode("ascii") for value in values]
    selected: list[tuple[str, Path, bool, str]] = []
    seen: set[str] = set()
    for record in filter(None, result.stdout.split(b"\0")):
        blocked(b"\t" not in record, "TRACKED_EVIDENCE_UNREADABLE")
        metadata, raw_path = record.split(b"\t", 1)
        fields = metadata.split()
        try:
            relative = raw_path.decode("utf-8")
            blob = fields[1].decode("ascii")
            stage = fields[2].decode("ascii")
        except (UnicodeDecodeError, IndexError):
            raise BlockedError("TRACKED_EVIDENCE_UNREADABLE") from None
        blocked(
            len(fields) != 3
            or re.fullmatch(rb"[0-7]{6}", fields[0]) is None
            or COMMIT_RE.fullmatch(blob) is None
            or stage != "0"
            or not relative
            or relative in seen,
            "TRACKED_EVIDENCE_UNREADABLE",
        )
        seen.add(relative)
        folded = relative.casefold()
        path = root / relative
        governance = folded == "agents.md" or folded.startswith((".codex/", ".wiki/"))
        text_like = governance or path.suffix.casefold() in TEXT_SUFFIXES or path.name in {".gitignore", ".gitattributes", ".editorconfig"}
        if not text_like:
            continue
        selected.append((relative, path, governance, blob))
    blob_ids = list(dict.fromkeys(blob for _, _, _, blob in selected))
    indexed, failures = read_git_blob_batch_progress(root, blob_ids)
    blocked(
        bool(failures)
        or set(indexed) != set(blob_ids)
        or set(indexed).intersection(failures),
        "TRACKED_EVIDENCE_UNREADABLE",
    )
    for relative, path, governance, blob in selected:
        try:
            working = path.read_bytes() if path.is_file() or path.is_symlink() else b""
        except OSError as exc:
            raise BlockedError("TRACKED_EVIDENCE_UNREADABLE", relative) from exc
        payloads = [
            working.lower(),
            indexed[blob].lower(),
            relative.casefold().encode("utf-8", errors="ignore"),
        ]
        known_match = any(value in payload for value in known for payload in payloads)
        generic_match = governance and any(TASK_ID_SEARCH_RE.search(payload) for payload in payloads)
        if known_match or generic_match:
            leaks.append(relative)
    return leaks


def ensure_paths_tracked(root: Path, paths: list[str]) -> None:
    tracked_paths = {path for path in run_git(root, "ls-files", "-z", check=True).stdout.split("\0") if path}
    missing = sorted(path for path in paths if path not in tracked_paths)
    blocked(bool(missing), "BASELINE_FILES_UNTRACKED", ",".join(missing))


def check_baseline(root: Path, ready: bool = False) -> dict[str, Any]:
    root = root.resolve()
    ensure_git(root)
    manifest = validate_manifest(load_json(root / MANIFEST_PATH))
    governance_files = list(manifest["governance"].values())
    required_files = [
        MANIFEST_PATH.as_posix(),
        *governance_files,
        "AGENTS.md",
        ".gitignore",
        ".gitattributes",
        ".editorconfig",
        ".codex/operating-model.md",
        ".codex/session-registry.schema.json",
        ".codex/work/index.md",
        ATTEMPTS_PATH.as_posix(),
        ".codex/audits/index.md",
    ]
    missing = [path for path in required_files if not (root / path).exists()]
    blocked(bool(missing), "BASELINE_FILES_MISSING", ",".join(missing))
    agents = (root / "AGENTS.md").read_text(encoding="utf-8")
    blocked(agents.count(MANAGED_START) != 1 or agents.count(MANAGED_END) != 1, "MANAGED_BLOCK_MISSING")
    _, tail = agents.split(MANAGED_START, 1)
    body, _ = tail.split(MANAGED_END, 1)
    blocked(MANAGED_START + body + MANAGED_END != agents_block(), "MANAGED_BLOCK_DRIFT")
    blocked(
        (root / ".codex/operating-model.md").read_text(encoding="utf-8") != render_operating_model(manifest) + "\n",
        "GENERATED_FILE_DRIFT",
        ".codex/operating-model.md",
    )
    blocked(
        (root / ".codex/session-registry.schema.json").read_text(encoding="utf-8") != registry_schema() + "\n",
        "GENERATED_FILE_DRIFT",
        ".codex/session-registry.schema.json",
    )
    blocked(not ignored(root, REGISTRY_PATH.as_posix()), "REGISTRY_NOT_IGNORED")
    blocked(not ignored(root, SENSITIVE_TEMP_PATTERN.replace("*", "probe")), "REGISTRY_TEMP_NOT_IGNORED")
    blocked(not ignored(root, ".wiki/.sessions/probe"), "WIKI_SESSIONS_NOT_IGNORED")
    registry = registry_guard(root, required=ready)
    leaks = known_id_leaks(root, list(registry.values()))
    blocked(bool(leaks), "TRACKED_TASK_ID_EXPOSURE", ",".join(leaks))
    if ready:
        required_aliases = {session["ref"] for session in manifest["sessions"]}
        missing_aliases = sorted(alias for alias in required_aliases if alias not in registry)
        blocked(bool(missing_aliases), "SESSION_ALIASES_MISSING", ",".join(missing_aliases))
        wiki_files = [".wiki/config.md", ".wiki/schema.md"]
        blocked(any(not (root / path).exists() for path in wiki_files), "LOCAL_WIKI_REQUIRED")
        blocked(run_git(root, "rev-parse", "HEAD").returncode != 0, "BASELINE_COMMIT_REQUIRED")
        ensure_paths_tracked(root, required_files + wiki_files)
        ensure_worktree_clean(root)
    return {
        "mode": "filesystem-ready" if ready else "structural",
        "sessions": len(manifest["sessions"]),
        "registry_aliases": len(registry),
        "limitations": ["live-sessions", "automations", "wiki-semantic-truth", "audit-closure"],
    }


def ensure_complete_git_history(root: Path, provenance_checked: bool = False) -> None:
    if not provenance_checked:
        ensure_provenance_integrity(root)
    result = run_git(root, "rev-parse", "--is-shallow-repository")
    blocked(
        result.returncode != 0
        or result.stdout.rstrip("\r\n") != "false"
        or bool(result.stderr),
        "GIT_HISTORY_INCOMPLETE",
    )


def ensure_provenance_integrity(root: Path) -> None:
    blocked(bool(os.environ.get("GIT_REPLACE_REF_BASE")), "GIT_PROVENANCE_REPLACED")
    replacements = run_git(root, "for-each-ref", "--format=%(refname)", "refs/replace/")
    blocked(
        replacements.returncode != 0
        or bool(replacements.stderr)
        or bool(replacements.stdout.rstrip("\r\n")),
        "GIT_PROVENANCE_REPLACED",
    )
    graft = run_git(root, "rev-parse", "--git-path", "info/grafts")
    blocked(
        graft.returncode != 0
        or bool(graft.stderr)
        or not graft.stdout.rstrip("\r\n"),
        "GIT_PROVENANCE_REPLACED",
    )
    graft_path = Path(graft.stdout.rstrip("\r\n"))
    if not graft_path.is_absolute():
        graft_path = root / graft_path
    try:
        graft_size = graft_path.stat().st_size if graft_path.exists() else 0
    except OSError as exc:
        raise BlockedError("GIT_PROVENANCE_REPLACED") from exc
    blocked(graft_size != 0, "GIT_PROVENANCE_REPLACED")


def snapshot_head(
    root: Path,
    reject_provenance_replacement: bool = False,
    verify_root: bool = True,
) -> str:
    root = root.resolve()
    if verify_root:
        probe = run_git(root, "rev-parse", "--show-toplevel")
        blocked(probe.returncode != 0, "GIT_REQUIRED")
        blocked(Path(probe.stdout.strip()).resolve() != root, "GIT_ROOT_MISMATCH")
    if reject_provenance_replacement:
        ensure_provenance_integrity(root)
    status = run_git(root, "status", "--porcelain=v2", "--branch", "--untracked-files=all")
    blocked(status.returncode != 0 or bool(status.stderr), "WORKTREE_NOT_CLEAN")
    lines = status.stdout.splitlines()
    oid_lines = [line.removeprefix("# branch.oid ") for line in lines if line.startswith("# branch.oid ")]
    blocked(len(oid_lines) != 1 or COMMIT_RE.fullmatch(oid_lines[0]) is None, "SNAPSHOT_HEAD_REQUIRED")
    blocked(any(not line.startswith("# ") for line in lines), "WORKTREE_NOT_CLEAN")
    return oid_lines[0]


def ensure_evaluation_state_unchanged(
    root: Path,
    expected_head: str,
    expected_registry: dict[str, str],
    expected_branch: str | None = None,
) -> None:
    try:
        current_head = snapshot_head(
            root, reject_provenance_replacement=True, verify_root=False
        )
        ensure_complete_git_history(root, provenance_checked=True)
        current_registry = load_registry(root)
        branch = (
            run_git(root, "symbolic-ref", "--quiet", "--short", "HEAD")
            if expected_branch is not None
            else None
        )
    except (BlockedError, OSError, UnicodeError, ValueError) as exc:
        raise BlockedError("EVALUATION_STATE_CHANGED") from exc
    blocked(
        current_head != expected_head
        or current_registry != expected_registry
        or (
            branch is not None
            and (
                branch.returncode != 0
                or bool(branch.stderr)
                or branch.stdout.rstrip("\r\n") != expected_branch
            )
        ),
        "EVALUATION_STATE_CHANGED",
    )


def snapshot_authority_paths(root: Path, revision: str) -> list[str]:
    result = git_process(
        root,
        "ls-tree", "-r", "-z", "--name-only", revision, "--",
            ".codex/docs/projects", ".codex/docs/requirements", ".codex/work/items",
        capture_output=True,
    )
    blocked(result.returncode != 0, "SNAPSHOT_SOURCE_UNREADABLE")
    paths: list[str] = []
    for raw in filter(None, result.stdout.split(b"\0")):
        try:
            relative = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise BlockedError("SNAPSHOT_SOURCE_UNREADABLE") from exc
        if any(pattern.fullmatch(relative) for pattern in (
            SNAPSHOT_PROJECT_PATH_RE,
            SNAPSHOT_REQUIREMENT_PATH_RE,
            SNAPSHOT_WORK_ITEM_DISCOVERY_RE,
        )):
            paths.append(relative)
    return sorted(paths)


def snapshot_safe_path(value: str, authority_path: str) -> str:
    blocked(any(not char.isprintable() for char in value), "SNAPSHOT_RECORD_MALFORMED")
    candidate = value.strip()
    if candidate.startswith("`") or candidate.endswith("`"):
        blocked(not (candidate.startswith("`") and candidate.endswith("`") and candidate.count("`") == 2), "SNAPSHOT_RECORD_MALFORMED", authority_path)
        candidate = candidate[1:-1].strip()
    parts = candidate.split("/")
    unsafe = (
        not candidate
        or "\\" in candidate
        or candidate.startswith(("/", "~"))
        or re.match(r"^[A-Za-z]:", candidate) is not None
        or any(part in {"", ".", ".."} for part in parts)
        or PurePosixPath(candidate).as_posix() != candidate
    )
    blocked(unsafe, "SNAPSHOT_RECORD_MALFORMED", authority_path)
    return candidate


def snapshot_field(
    text: str,
    field: str,
    authority_path: str,
    required: bool = True,
    preserve_raw: bool = False,
) -> str | None:
    values = re.findall(rf"^{re.escape(field)}:(.*)$", text, flags=re.MULTILINE)
    blocked(len(values) > 1 or (required and len(values) != 1), "SNAPSHOT_RECORD_MALFORMED", authority_path)
    if not values:
        return None
    value = values[0] if preserve_raw else values[0].strip()
    blocked(not value, "SNAPSHOT_RECORD_MALFORMED", authority_path)
    return value


def parse_snapshot_record(text: str, authority_path: str, revision: str, content_sha256: str) -> dict[str, Any]:
    path_match: re.Match[str] | None
    if path_match := SNAPSHOT_PROJECT_PATH_RE.fullmatch(authority_path):
        kind = "project-plan"
        heading_re = re.compile(r"# Project Plan (P\d{3}):[ \t]+(.+)")
        heading_prefix = "# Project Plan "
    elif path_match := SNAPSHOT_REQUIREMENT_PATH_RE.fullmatch(authority_path):
        kind = "requirement-brief"
        heading_re = re.compile(r"# Requirement Brief (P\d{3}-G\d{3}):[ \t]+(.+)")
        heading_prefix = "# Requirement Brief "
    elif path_match := SNAPSHOT_WORK_ITEM_PATH_RE.fullmatch(authority_path):
        kind = "work-item"
        heading_re = re.compile(r"# Work Item (WI-[^:\r\n]+):[ \t]+(.+)")
        heading_prefix = "# Work Item "
    else:
        raise BlockedError("SNAPSHOT_RECORD_MALFORMED", authority_path)

    headings = [line for line in text.splitlines() if line.startswith(heading_prefix)]
    blocked(len(headings) != 1, "SNAPSHOT_RECORD_MALFORMED", authority_path)
    heading = heading_re.fullmatch(headings[0])
    blocked(heading is None, "SNAPSHOT_RECORD_MALFORMED", authority_path)
    ref = heading.group(1)
    title = heading.group(2).strip()
    blocked(not title or ref != path_match.group(1), "SNAPSHOT_RECORD_MALFORMED", authority_path)
    status = snapshot_field(text, "Status", authority_path)
    blocked(status is None or SNAPSHOT_STATUS_RE.fullmatch(status) is None, "SNAPSHOT_RECORD_MALFORMED", authority_path)

    links: list[dict[str, str]] = []
    if kind == "requirement-brief":
        project_path = snapshot_safe_path(
            snapshot_field(text, "Project Plan", authority_path, preserve_raw=True) or "",
            authority_path,
        )
        project_match = SNAPSHOT_PROJECT_PATH_RE.fullmatch(project_path)
        blocked(project_match is None, "SNAPSHOT_RECORD_MALFORMED", authority_path)
        links.append({"kind": "project", "target": project_match.group(1)})
    elif kind == "work-item":
        project = snapshot_field(text, "Project", authority_path)
        requirement = snapshot_field(text, "Requirement", authority_path)
        blocked(project is None or re.fullmatch(r"P\d{3}", project) is None, "SNAPSHOT_RECORD_MALFORMED", authority_path)
        blocked(requirement is None or re.fullmatch(r"P\d{3}-G\d{3}", requirement) is None, "SNAPSHOT_RECORD_MALFORMED", authority_path)
        links.extend(({"kind": "project", "target": project}, {"kind": "requirement", "target": requirement}))
        evidence = snapshot_field(text, "Evidence Path", authority_path, required=False, preserve_raw=True)
        if evidence is not None:
            links.append({"kind": "evidence", "target": snapshot_safe_path(evidence, authority_path)})

    return {
        "kind": kind,
        "ref": ref,
        "title": title,
        "status": status,
        "authority_path": authority_path,
        "source_revision": revision,
        "content_sha256": content_sha256,
        "origin": "durable",
        "proof_level": "declared",
        "freshness": "current-at-source-revision",
        "links": sorted(links, key=lambda link: (link["kind"], link["target"])),
        "unknowns": sorted(SNAPSHOT_UNKNOWNS),
        "limitations": sorted(SNAPSHOT_RECORD_LIMITATIONS),
    }


def build_snapshot(root: Path) -> dict[str, Any]:
    root = root.resolve()
    revision = snapshot_head(root)
    records: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    requirement_project_paths: dict[str, str] = {}
    for authority_path in snapshot_authority_paths(root, revision):
        if TASK_ID_SEARCH_RE.search(authority_path.encode("utf-8")):
            raise BlockedError("SNAPSHOT_IDENTITY_EXPOSURE")
        snapshot_safe_path(authority_path, authority_path)
        try:
            content = committed_regular_file_bytes(root, revision, authority_path)
        except BlockedError as exc:
            raise BlockedError("SNAPSHOT_SOURCE_UNREADABLE", authority_path) from exc
        if TASK_ID_SEARCH_RE.search(content):
            raise BlockedError("SNAPSHOT_IDENTITY_EXPOSURE", authority_path)
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise BlockedError("SNAPSHOT_SOURCE_UNREADABLE", authority_path) from exc
        record = parse_snapshot_record(text, authority_path, revision, hashlib.sha256(content).hexdigest())
        key = (record["kind"], record["ref"])
        blocked(key in seen, "SNAPSHOT_DUPLICATE_REF", record["ref"])
        seen.add(key)
        records.append(record)
        if record["kind"] == "requirement-brief":
            requirement_project_paths[record["ref"]] = snapshot_safe_path(
                snapshot_field(text, "Project Plan", authority_path, preserve_raw=True) or "",
                authority_path,
            )

    project_paths = {
        record["ref"]: record["authority_path"]
        for record in records
        if record["kind"] == "project-plan"
    }
    requirement_refs = {record["ref"] for record in records if record["kind"] == "requirement-brief"}
    for record in records:
        for link in record["links"]:
            unresolved = (
                (link["kind"] == "project" and link["target"] not in project_paths)
                or (link["kind"] == "requirement" and link["target"] not in requirement_refs)
                or (
                    record["kind"] == "requirement-brief"
                    and link["kind"] == "project"
                    and project_paths.get(link["target"]) != requirement_project_paths[record["ref"]]
                )
            )
            blocked(unresolved, "SNAPSHOT_LINK_UNRESOLVED", link["target"])

    return {
        "schema_version": 1,
        "source_revision": revision,
        "records": sorted(records, key=lambda record: (record["kind"], record["ref"], record["authority_path"])),
        "live_overlay": {
            "status": "UNKNOWN",
            "observed_at": None,
            "limitations": sorted(SNAPSHOT_LIVE_LIMITATIONS),
        },
        "limitations": sorted(SNAPSHOT_LIMITATIONS),
    }


def snapshot_json(root: Path) -> str:
    output = json.dumps(build_snapshot(root), sort_keys=True)
    blocked(TASK_ID_SEARCH_RE.search(output.encode("utf-8")) is not None, "SNAPSHOT_IDENTITY_EXPOSURE")
    return output



def path_in_scope(path: str, scope: str, *, platform: str | None = None) -> bool:
    platform_name = os.name if platform is None else platform
    candidate = (path.casefold() if platform_name == "nt" else path).rstrip("/")
    parent = (scope.casefold() if platform_name == "nt" else scope).rstrip("/")
    return candidate == parent or candidate.startswith(parent + "/")


def work_item_relative(root: Path, work_item: Path) -> str:
    target = work_item if work_item.is_absolute() else root / work_item
    try:
        relative = target.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise BlockedError("WORK_ITEM_OUTSIDE_ROOT") from exc
    blocked(
        SNAPSHOT_WORK_ITEM_PATH_RE.fullmatch(relative) is None,
        "INVALID_WORK_ITEM_PATH",
        relative,
    )
    blocked(not (root / relative).is_file(), "WORK_ITEM_MISSING", relative)
    blocked(not tracked(root, relative), "WORK_ITEM_UNTRACKED", relative)
    return relative


def markdown_h2_section(text: str, heading: str, code: str) -> list[str] | None:
    lines = text.splitlines()
    headings = [index for index, line in enumerate(lines) if line == heading]
    blocked(len(headings) > 1, code)
    if not headings:
        return None
    start = headings[0] + 1
    end = next(
        (index for index in range(start, len(lines)) if lines[index].startswith("## ")),
        len(lines),
    )
    return [line for line in lines[start:end] if line.strip()]


def brief_handoff_contract_ids(text: str) -> list[str] | None:
    lines = markdown_h2_section(
        text, "## Handoff Contract v1", "HANDOFF_BRIEF_CONTRACT_MALFORMED"
    )
    if lines is None:
        return None
    ids: list[str] = []
    for line in lines:
        match = re.fullmatch(r"- `([^`]+)`:[ \t]+(.+)", line)
        blocked(
            match is None
            or HANDOFF_CONTRACT_ID_RE.fullmatch(match.group(1)) is None
            or not match.group(2).strip(),
            "HANDOFF_BRIEF_CONTRACT_MALFORMED",
        )
        ids.append(match.group(1))
    blocked(not ids, "HANDOFF_BRIEF_CONTRACT_MALFORMED")
    blocked(len(ids) != len(set(ids)), "HANDOFF_BRIEF_CONTRACT_DUPLICATE")
    return ids


def work_item_handoff_contract_ids(text: str) -> list[str]:
    lines = markdown_h2_section(
        text, "## Handoff Contract v1", "HANDOFF_CONTRACT_MALFORMED"
    )
    if lines is None:
        return []
    blocked(len(lines) != 1 or not lines[0].startswith("Contract IDs: "), "HANDOFF_CONTRACT_MALFORMED")
    ids = re.findall(r"`([^`]+)`", lines[0])
    blocked(
        not ids
        or lines[0] != "Contract IDs: " + ", ".join(f"`{value}`" for value in ids)
        or any(HANDOFF_CONTRACT_ID_RE.fullmatch(value) is None for value in ids),
        "HANDOFF_CONTRACT_MALFORMED",
    )
    blocked(len(ids) != len(set(ids)), "HANDOFF_CONTRACT_DUPLICATE")
    return ids


def validate_handoff_contract(brief_text: str, contract_ids: list[str]) -> None:
    if not contract_ids:
        return
    brief_ids = brief_handoff_contract_ids(brief_text)
    blocked(brief_ids is None, "HANDOFF_CONTRACT_BRIEF_MISSING")
    unknown = sorted(set(contract_ids) - set(brief_ids))
    blocked(bool(unknown), "HANDOFF_CONTRACT_UNKNOWN_ID", ",".join(unknown))


def validate_handoff_traceability(evidence: bytes, contract_ids: list[str]) -> None:
    if not contract_ids:
        return
    try:
        text = evidence.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise BlockedError("HANDOFF_TRACEABILITY_MALFORMED") from exc
    lines = markdown_h2_section(text, "## Traceability", "HANDOFF_TRACEABILITY_MALFORMED")
    blocked(
        lines is None
        or len(lines) < 3
        or lines[0] != "| Contract ID | Output | Verification | Evidence |"
        or lines[1] != "| --- | --- | --- | --- |",
        "HANDOFF_TRACEABILITY_MALFORMED",
    )
    rows: dict[str, tuple[str, str, str]] = {}
    for line in lines[2:]:
        match = re.fullmatch(r"\| `([^`]+)` \| ([^|]*) \| ([^|]*) \| ([^|]*) \|", line)
        blocked(
            match is None or HANDOFF_CONTRACT_ID_RE.fullmatch(match.group(1)) is None,
            "HANDOFF_TRACEABILITY_MALFORMED",
        )
        contract_id = match.group(1)
        blocked(contract_id in rows, "HANDOFF_TRACEABILITY_DUPLICATE", contract_id)
        cells = tuple(value.strip() for value in match.groups()[1:])
        blocked(any(not value for value in cells), "HANDOFF_TRACEABILITY_INCOMPLETE", contract_id)
        rows[contract_id] = cells
    expected = set(contract_ids)
    unknown = sorted(set(rows) - expected)
    missing = sorted(expected - set(rows))
    blocked(bool(unknown), "HANDOFF_TRACEABILITY_UNKNOWN_ID", ",".join(unknown))
    blocked(bool(missing), "HANDOFF_TRACEABILITY_MISSING_ID", ",".join(missing))


def work_item_authority(text: str, relative: str, code: str) -> dict[str, str]:
    path_match = SNAPSHOT_WORK_ITEM_PATH_RE.fullmatch(relative)
    headings = [line for line in text.splitlines() if line.startswith("# Work Item ")]
    heading = (
        re.fullmatch(r"# Work Item (WI-[^:\r\n]+):[ \t]+(.+)", headings[0])
        if len(headings) == 1
        else None
    )
    projects = re.findall(r"^Project:[ \t]*(.*?)[ \t]*$", text, flags=re.MULTILINE)
    requirements = re.findall(r"^Requirement:[ \t]*(.*?)[ \t]*$", text, flags=re.MULTILINE)
    blocked(
        path_match is None
        or heading is None
        or heading.group(1) != path_match.group(1)
        or not heading.group(2).strip()
        or len(projects) != 1
        or re.fullmatch(r"P[0-9]{3}", projects[0]) is None
        or len(requirements) != 1
        or re.fullmatch(r"P[0-9]{3}-G[0-9]{3}", requirements[0]) is None
        or not requirements[0].startswith(projects[0] + "-"),
        code,
    )
    return {"project": projects[0], "requirement": requirements[0]}


def parse_work_item(text: str, relative: str, expected_status: str = "active") -> dict[str, Any]:
    fields: dict[str, str] = {}
    for field in (
        "Status",
        "Project",
        "Requirement",
        "Owner Session Ref",
        "Branch",
        "Source Commit",
        "Problem Key",
        "Evidence Path",
    ):
        values = re.findall(rf"^{re.escape(field)}:[ \t]*(.*?)[ \t]*$", text, flags=re.MULTILINE)
        blocked(len(values) != 1, "WORK_ITEM_FIELD_REQUIRED", f"{relative}:{field}")
        fields[field] = nonempty(values[0], f"{relative}:{field}")
    blocked(
        fields["Status"] != expected_status,
        "WORK_ITEM_NOT_ACTIVE" if expected_status == "active" else "WORK_ITEM_STATUS_MISMATCH",
        relative,
    )
    owner = fields["Owner Session Ref"]
    blocked(SESSION_REF_RE.fullmatch(owner) is None, "INVALID_SESSION_REF", owner)
    project = fields["Project"]
    blocked(re.fullmatch(r"P[0-9]{3}", project) is None, "INVALID_WORK_ITEM_PROJECT", relative)
    requirement = fields["Requirement"]
    blocked(
        re.fullmatch(r"P[0-9]{3}-G[0-9]{3}", requirement) is None
        or not requirement.startswith(project + "-"),
        "INVALID_WORK_ITEM_REQUIREMENT",
        relative,
    )
    authority = work_item_authority(text, relative, "WORK_ITEM_AUTHORITY_INVALID")
    blocked(
        authority != {"project": project, "requirement": requirement},
        "WORK_ITEM_AUTHORITY_INVALID",
        relative,
    )
    source = fields["Source Commit"]
    blocked(COMMIT_RE.fullmatch(source) is None, "INVALID_SOURCE_COMMIT", relative)
    evidence = normalized_scope(fields["Evidence Path"], f"{relative}:Evidence Path")

    lines = text.splitlines()
    headings = [index for index, line in enumerate(lines) if line == "## Write Scope"]
    blocked(len(headings) != 1, "WRITE_SCOPE_REQUIRED", relative)
    start = headings[0] + 1
    end = next((index for index in range(start, len(lines)) if lines[index].startswith("## ")), len(lines))
    scope_lines = [line for line in lines[start:end] if line.strip()]
    scopes: list[str] = []
    for line in scope_lines:
        match = re.fullmatch(r"- `([^`]+)`", line)
        blocked(match is None, "INVALID_WRITE_SCOPE_ENTRY", f"{relative}:{line}")
        scopes.append(normalized_scope(match.group(1), f"{relative}:Write Scope"))
    blocked(not scopes, "WRITE_SCOPE_REQUIRED", relative)
    for index, left in enumerate(scopes):
        for right in scopes[index + 1 :]:
            blocked(scopes_overlap(left, right), "REDUNDANT_WRITE_SCOPE", f"{relative}:{left}<>{right}")
    blocked(not any(path_in_scope(evidence, scope) for scope in scopes), "EVIDENCE_OUTSIDE_WRITE_SCOPE", evidence)
    return {
        "relative": relative,
        "project": project,
        "requirement": requirement,
        "owner": owner,
        "branch": fields["Branch"],
        "source": source,
        "problem_key": fields["Problem Key"],
        "evidence": evidence,
        "scopes": scopes,
        "contract_ids": work_item_handoff_contract_ids(text),
    }


def active_work_items(root: Path, revision: str) -> list[dict[str, Any]]:
    tree = git_process(
        root,
            "ls-tree",
            "-r",
            "-z",
            "--name-only",
            revision,
            "--",
            WORK_ITEMS_PATH.as_posix(),
        capture_output=True,
    )
    blocked(tree.returncode != 0, "ACTIVE_WORK_ITEM_INVALID")
    values = tree.stdout.split(b"\0")
    blocked(values[-1] != b"" or any(not value for value in values[:-1]), "ACTIVE_WORK_ITEM_INVALID")
    work_items: list[str] = []
    for raw in values[:-1]:
        try:
            relative = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise BlockedError("ACTIVE_WORK_ITEM_INVALID") from exc
        blocked(
            not relative.startswith(WORK_ITEMS_PATH.as_posix() + "/"),
            "ACTIVE_WORK_ITEM_INVALID",
        )
        if not relative.endswith(".md"):
            continue
        blocked(SNAPSHOT_WORK_ITEM_PATH_RE.fullmatch(relative) is None, "ACTIVE_WORK_ITEM_INVALID")
        work_items.append(relative)
    blocked(work_items != sorted(set(work_items)), "ACTIVE_WORK_ITEM_INVALID")
    file_cache: CommittedFileCache = {}
    read_committed_file_stage(
        root,
        revision,
        [
            (path, "ACTIVE_WORK_ITEM_INVALID", "ACTIVE_WORK_ITEM_INVALID")
            for path in work_items
        ],
        file_cache,
    )
    items: list[dict[str, Any]] = []
    for relative in work_items:
        content, _ = committed_file_cache_get(
            file_cache, revision, relative, "ACTIVE_WORK_ITEM_INVALID"
        )
        blocked(SENSITIVE_TASK_ID_SEARCH_RE.search(content) is not None, "ACTIVE_WORK_ITEM_INVALID")
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise BlockedError("ACTIVE_WORK_ITEM_INVALID") from exc
        statuses = re.findall(r"^Status:[ \t]*(.*?)[ \t]*$", text, flags=re.MULTILINE)
        blocked(
            len(statuses) != 1 or SNAPSHOT_STATUS_RE.fullmatch(statuses[0]) is None,
            "ACTIVE_WORK_ITEM_INVALID",
        )
        if statuses[0] == "active":
            try:
                items.append(parse_work_item(text, relative))
            except BlockedError as exc:
                raise BlockedError("ACTIVE_WORK_ITEM_INVALID") from exc
    return items


def ensure_no_active_scope_collision(
    root: Path,
    revision: str,
    current: dict[str, Any],
) -> None:
    for other in active_work_items(root, revision):
        if other["relative"] == current["relative"]:
            continue
        for left in current["scopes"]:
            for right in other["scopes"]:
                if scopes_overlap(left, right):
                    raise BlockedError(
                        "ACTIVE_WRITE_SCOPE_OVERLAP",
                        f"{current['relative']}:{left}<>{other['relative']}:{right}",
                    )


def dispatch_project_plan_path(
    root: Path,
    revision: str,
    project: str,
    expected_path: str | None = None,
    authority_paths: list[str] | None = None,
    file_cache: CommittedFileCache | None = None,
) -> str:
    if authority_paths is None:
        try:
            authority_paths = snapshot_authority_paths(root, revision)
        except BlockedError as exc:
            raise BlockedError("DISPATCH_AUTHORITY_INVALID") from exc
    plans = [
        path for path in authority_paths
        if (match := SNAPSHOT_PROJECT_PATH_RE.fullmatch(path)) and match.group(1) == project
    ]
    blocked(
        plans != [expected_path] if expected_path is not None else len(plans) != 1,
        "DISPATCH_AUTHORITY_INVALID",
    )
    plan_path = plans[0]
    if file_cache is None:
        try:
            content, _ = committed_regular_file(
                root, revision, plan_path, "DISPATCH_AUTHORITY_INVALID", "DISPATCH_AUTHORITY_INVALID"
            )
        except BlockedError as exc:
            raise BlockedError("DISPATCH_AUTHORITY_INVALID") from exc
    else:
        read_committed_file_stage(
            root, revision, [(plan_path, "DISPATCH_AUTHORITY_INVALID", "DISPATCH_AUTHORITY_INVALID")], file_cache
        )
        content, _ = committed_file_cache_get(file_cache, revision, plan_path, "DISPATCH_AUTHORITY_INVALID")
    blocked(SENSITIVE_TASK_ID_SEARCH_RE.search(content) is not None, "DISPATCH_AUTHORITY_INVALID")
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise BlockedError("DISPATCH_AUTHORITY_INVALID") from exc
    assurance_project_authority(text, plan_path, project, "DISPATCH_AUTHORITY_INVALID")
    return plan_path


def dispatch_requirement_brief(
    root: Path,
    revision: str,
    requirement: str,
    project: str,
    project_plan: str,
    expected_path: str | None = None,
    expected_blob: str | None = None,
    authority_paths: list[str] | None = None,
    file_cache: CommittedFileCache | None = None,
) -> tuple[str, str]:
    if authority_paths is None:
        try:
            authority_paths = snapshot_authority_paths(root, revision)
        except BlockedError as exc:
            raise BlockedError("DISPATCH_AUTHORITY_INVALID") from exc
    briefs = [
        path for path in authority_paths
        if (match := SNAPSHOT_REQUIREMENT_PATH_RE.fullmatch(path))
        and match.group(1) == requirement
        and match.group(2) == project
    ]
    blocked(
        briefs != [expected_path] if expected_path is not None else len(briefs) != 1,
        "DISPATCH_AUTHORITY_INVALID",
    )
    brief_path = briefs[0]
    if file_cache is None:
        try:
            content, blob = committed_regular_file(
                root, revision, brief_path, "DISPATCH_AUTHORITY_INVALID", "DISPATCH_AUTHORITY_INVALID"
            )
        except BlockedError as exc:
            raise BlockedError("DISPATCH_AUTHORITY_INVALID") from exc
    else:
        read_committed_file_stage(
            root, revision, [(brief_path, "DISPATCH_AUTHORITY_INVALID", "DISPATCH_AUTHORITY_INVALID")], file_cache
        )
        content, blob = committed_file_cache_get(file_cache, revision, brief_path, "DISPATCH_AUTHORITY_INVALID")
    blocked(
        (expected_blob is not None and blob != expected_blob)
        or SENSITIVE_TASK_ID_SEARCH_RE.search(content) is not None,
        "DISPATCH_AUTHORITY_INVALID",
    )
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise BlockedError("DISPATCH_AUTHORITY_INVALID") from exc
    linked_plan = assurance_acceptance_authority(
        text,
        brief_path,
        requirement,
        project,
        "DISPATCH_AUTHORITY_INVALID",
    )
    blocked(linked_plan != project_plan, "DISPATCH_AUTHORITY_INVALID")
    return brief_path, blob


def dispatch_commit(
    root: Path,
    item: dict[str, Any],
    head: str,
    history_checked: bool = False,
    commit_graph: CommitGraph | None = None,
    file_cache: CommittedFileCache | None = None,
    authority_paths_cache: dict[str, list[str]] | None = None,
) -> str:
    if not history_checked:
        ensure_complete_git_history(root)
    source = item["source"]
    blocked(not commit_exists(root, source, commit_graph), "SOURCE_COMMIT_MISSING")
    blocked(not commit_is_ancestor(root, source, head, commit_graph), "SOURCE_NOT_ANCESTOR")
    result = run_git(
        root,
        "log",
        "--full-history",
        "--format=%H",
        f"{source}..{head}",
        "--",
        f":(literal){item['relative']}",
        check=True,
    )
    commits = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    blocked(not commits, "DISPATCH_COMMIT_MISSING", item["relative"])
    candidates = [
        commit for commit in commits
        if all(
            commit == other or commit_is_ancestor(root, commit, other, commit_graph)
            for other in commits
        )
    ]
    blocked(len(candidates) != 1, "DISPATCH_COMMIT_AMBIGUOUS", item["relative"])
    dispatch = candidates[0]
    blocked(
        not commit_is_ancestor(root, source, dispatch, commit_graph),
        "DISPATCH_AUTHORITY_INVALID",
    )
    dispatch_paths = git_path_set(
        root,
        "DISPATCH_AUTHORITY_INVALID",
        "log",
        "--full-history",
        "-m",
        "--name-only",
        "--format=",
        "--no-renames",
        f"{source}..{dispatch}",
    )
    file_cache = {} if file_cache is None else file_cache
    authority_paths_cache = {} if authority_paths_cache is None else authority_paths_cache
    try:
        for revision in (source, head):
            if revision not in authority_paths_cache:
                authority_paths_cache[revision] = snapshot_authority_paths(root, revision)
    except BlockedError as exc:
        raise BlockedError("DISPATCH_AUTHORITY_INVALID") from exc
    source_authority_paths = authority_paths_cache[source]
    project_plans = [
        path for path in source_authority_paths
        if (match := SNAPSHOT_PROJECT_PATH_RE.fullmatch(path)) and match.group(1) == item["project"]
    ]
    requirement_briefs = [
        path for path in source_authority_paths
        if (match := SNAPSHOT_REQUIREMENT_PATH_RE.fullmatch(path))
        and match.group(1) == item["requirement"]
        and match.group(2) == item["project"]
    ]
    blocked(len(project_plans) != 1 or len(requirement_briefs) != 1, "DISPATCH_AUTHORITY_INVALID")
    project_plan, requirement_brief = project_plans[0], requirement_briefs[0]
    requests = [
        (project_plan, "DISPATCH_AUTHORITY_INVALID", "DISPATCH_AUTHORITY_INVALID"),
        (requirement_brief, "DISPATCH_AUTHORITY_INVALID", "DISPATCH_AUTHORITY_INVALID"),
    ]
    read_committed_file_stage(root, source, requests, file_cache)
    read_committed_file_stage(root, head, requests, file_cache)
    dispatch_project_plan_path(
        root, source, item["project"], authority_paths=source_authority_paths, file_cache=file_cache
    )
    dispatch_project_plan_path(
        root, head, item["project"], project_plan, authority_paths_cache[head], file_cache
    )
    requirement_brief, requirement_blob = dispatch_requirement_brief(
        root,
        source,
        item["requirement"],
        item["project"],
        project_plan,
        authority_paths=source_authority_paths,
        file_cache=file_cache,
    )
    dispatch_requirement_brief(
        root,
        head,
        item["requirement"],
        item["project"],
        project_plan,
        requirement_brief,
        requirement_blob,
        authority_paths_cache[head],
        file_cache,
    )
    item["project_plan_path"] = project_plan
    item["requirement_brief_path"] = requirement_brief
    allowed_controls = {
        item["relative"],
        project_plan,
        ".codex/work/index.md",
        ".codex/work/current.md",
    }
    blocked(
        item["relative"] not in dispatch_paths
        or any(path not in allowed_controls for path in dispatch_paths),
        "DISPATCH_AUTHORITY_INVALID",
    )
    return dispatch



def committed_regular_file(
    root: Path,
    commit: str,
    relative: str,
    unreadable_code: str,
    not_regular_code: str,
) -> tuple[bytes, str]:
    tree = git_process(
        root, "ls-tree", "-z", commit, "--", f":(literal){relative}",
        capture_output=True,
    )
    blocked(tree.returncode != 0 or not tree.stdout, unreadable_code, relative)
    entries = [entry for entry in tree.stdout.split(b"\0") if entry]
    blocked(len(entries) != 1 or b"\t" not in entries[0], unreadable_code, relative)
    metadata, listed_path = entries[0].split(b"\t", 1)
    parts = metadata.split()
    blocked(
        len(parts) != 3 or parts[0] not in {b"100644", b"100755"} or parts[1] != b"blob",
        not_regular_code,
        relative,
    )
    blocked(listed_path.decode("utf-8", errors="surrogateescape") != relative, unreadable_code, relative)
    blob = git_process(root, "cat-file", "-p", parts[2], capture_output=True)
    blocked(blob.returncode != 0, unreadable_code, relative)
    return blob.stdout, parts[2].decode("ascii")


def committed_regular_file_bytes(root: Path, commit: str, relative: str) -> bytes:
    content, _ = committed_regular_file(
        root,
        commit,
        relative,
        "HANDOFF_EVIDENCE_UNREADABLE",
        "HANDOFF_EVIDENCE_NOT_REGULAR_FILE",
    )
    return content


def git_path_set(root: Path, code: str, *args: str) -> list[str]:
    result = git_process(root, *args, "-z", capture_output=True)
    blocked(result.returncode != 0, code)
    paths: list[str] = []
    for raw in filter(None, result.stdout.split(b"\0")):
        try:
            path = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise BlockedError(code) from exc
        blocked(
            path != path.strip()
            or any(not char.isprintable() for char in path)
            or "\\" in path
            or PurePosixPath(path).as_posix() != path,
            code,
        )
        paths.append(path)
    return sorted(set(paths))


def validate_handoff_delta(
    root: Path,
    item: dict[str, Any],
    dispatch: str,
    head: str,
    file_cache: CommittedFileCache | None = None,
) -> list[str]:
    blocked(head == dispatch, "HANDOFF_HAS_NO_COMMITTED_DELTA")
    item_history = run_git(
        root,
        "log",
        "--full-history",
        "--format=%H",
        f"{dispatch}..{head}",
        "--",
        f":(literal){item['relative']}",
        check=True,
    )
    blocked(bool(item_history.stdout.strip()), "WORK_ITEM_MUTATED_AFTER_DISPATCH", item["relative"])
    changed = git_path_set(root, "HANDOFF_DIFF_INVALID", "diff", "--name-only", "--no-renames", dispatch, head)
    blocked(not changed, "HANDOFF_HAS_NO_COMMITTED_DELTA")
    touched = git_path_set(
        root,
        "HANDOFF_HISTORY_INVALID",
        "log",
        "--full-history",
        "-m",
        "--name-only",
        "--format=",
        "--no-renames",
        f"{dispatch}..{head}",
    )
    outside = sorted(path for path in touched if not any(path_in_scope(path, scope) for scope in item["scopes"]))
    blocked(bool(outside), "HANDOFF_OUTSIDE_WRITE_SCOPE", ",".join(outside))
    evidence = item["evidence"]
    blocked(evidence not in changed, "HANDOFF_EVIDENCE_NOT_UPDATED", evidence)
    if file_cache is None:
        evidence_bytes = committed_regular_file_bytes(root, head, evidence)
    else:
        read_committed_file_stage(
            root,
            head,
            [(evidence, "HANDOFF_EVIDENCE_UNREADABLE", "HANDOFF_EVIDENCE_NOT_REGULAR_FILE")],
            file_cache,
        )
        evidence_bytes, _ = committed_file_cache_get(
            file_cache, head, evidence, "HANDOFF_EVIDENCE_UNREADABLE"
        )
    blocked(not evidence_bytes.strip(), "HANDOFF_EVIDENCE_EMPTY", evidence)
    validate_handoff_traceability(evidence_bytes, item["contract_ids"])
    blocked(run_git(root, "diff", "--check", dispatch, head).returncode != 0, "HANDOFF_DIFF_CHECK_FAILED")
    return changed


def ensure_allocation_slot(
    root: Path,
    item: dict[str, Any],
    head: str,
) -> dict[str, int]:
    records = git_worktree_inventory(root, "ALLOCATION_WORKTREE_UNREADABLE")
    target_ref = f"refs/heads/{item['branch']}"
    matches = [record for record in records if record.get("branch") == target_ref]
    blocked(not matches, "ALLOCATION_SLOT_MISSING")
    blocked(len(matches) > 1, "ALLOCATION_WORKTREE_CAP_EXCEEDED")
    slot = matches[0]
    blocked(
        any(flag in slot for flag in ("bare", "detached", "locked", "prunable")),
        "ALLOCATION_SLOT_UNSAFE",
    )
    try:
        slot_root = Path(slot["worktree"]).resolve()
    except (KeyError, OSError):
        raise BlockedError("ALLOCATION_WORKTREE_UNREADABLE") from None
    blocked(slot_root != root, "ALLOCATION_SLOT_MISMATCH")
    blocked(slot.get("HEAD") != head, "ALLOCATION_SLOT_STALE")
    unmerged = git_process(root, "ls-files", "--unmerged", "-z", capture_output=True)
    blocked(
        unmerged.returncode != 0 or bool(unmerged.stderr) or bool(unmerged.stdout),
        "ALLOCATION_INDEX_UNSAFE",
    )
    return {"slots": len(matches), "cap": 1}


def work_check(root: Path, phase: str, work_item: Path) -> dict[str, Any]:
    root = root.resolve()
    blocked(phase not in {"allocate", "start", "handoff"}, "INVALID_WORK_PHASE", phase)
    head = snapshot_head(root, reject_provenance_replacement=True)
    ensure_complete_git_history(root, provenance_checked=True)
    commit_graph = load_commit_graph(root, head)
    check_baseline(root)
    relative = work_item_relative(root, work_item)
    content, _ = committed_regular_file(
        root,
        head,
        relative,
        "WORK_ITEM_MISSING",
        "WORK_ITEM_NOT_REGULAR_FILE",
    )
    try:
        item_text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise BlockedError("WORK_ITEM_UNREADABLE") from exc
    item = parse_work_item(item_text, relative)
    registry = registry_guard(root)
    blocked(item["owner"] not in registry, "WORK_ITEM_OWNER_UNRESOLVED", item["owner"])
    branch_result = run_git(root, "symbolic-ref", "--quiet", "--short", "HEAD")
    blocked(branch_result.returncode != 0, "DETACHED_HEAD")
    branch = branch_result.stdout.strip()
    blocked(branch != item["branch"], "WORK_ITEM_BRANCH_MISMATCH", f"expected={item['branch']} actual={branch}")
    ensure_no_active_scope_collision(root, head, item)
    dispatch = dispatch_commit(
        root,
        item,
        head,
        history_checked=True,
        commit_graph=commit_graph,
    )
    if item["contract_ids"]:
        brief_content, _ = committed_regular_file(
            root,
            head,
            item["requirement_brief_path"],
            "HANDOFF_CONTRACT_BRIEF_UNREADABLE",
            "HANDOFF_CONTRACT_BRIEF_UNREADABLE",
        )
        try:
            brief_text = brief_content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise BlockedError("HANDOFF_CONTRACT_BRIEF_UNREADABLE") from exc
        validate_handoff_contract(brief_text, item["contract_ids"])

    if phase in {"allocate", "start"}:
        mismatch = "ALLOCATION_BASELINE_MISMATCH" if phase == "allocate" else "START_BASELINE_MISMATCH"
        blocked(head != dispatch, mismatch, f"expected={dispatch} actual={head}")
        result = {"phase": phase, "work_item": relative, "scopes": len(item["scopes"]), "changed": 0}
        if phase == "allocate":
            active = {candidate["relative"] for candidate in active_work_items(root, head)}
            blocked(relative not in active, "ALLOCATION_WORK_ITEM_NOT_ACTIVE")
            result.update(ensure_allocation_slot(root, item, head))
        ensure_evaluation_state_unchanged(root, head, registry, branch)
        return result

    changed = validate_handoff_delta(root, item, dispatch, head)
    blocked(not tracked(root, item["evidence"]), "HANDOFF_EVIDENCE_UNTRACKED", item["evidence"])
    result = {"phase": phase, "work_item": relative, "scopes": len(item["scopes"]), "changed": len(changed)}
    ensure_evaluation_state_unchanged(root, head, registry, branch)
    return result


def assurance_safe_path(value: str) -> str:
    try:
        candidate = snapshot_safe_path(value, "")
    except BlockedError as exc:
        raise BlockedError("ASSURANCE_RECORD_MALFORMED") from exc
    blocked(candidate != value or ":" in candidate, "ASSURANCE_RECORD_MALFORMED")
    return candidate


def assurance_relative(root: Path, path: Path, code: str) -> str:
    if not path.is_absolute():
        try:
            assurance_safe_path(path.as_posix())
        except BlockedError as exc:
            raise BlockedError(code) from exc
    target = path if path.is_absolute() else root / path
    try:
        relative = target.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise BlockedError(code) from exc
    try:
        return assurance_safe_path(relative)
    except BlockedError as exc:
        raise BlockedError(code) from exc


def parse_assurance_record(text: str, relative: str) -> dict[str, Any]:
    blocked("\r" in text or not text.endswith("\n"), "ASSURANCE_RECORD_MALFORMED")
    lines = text.splitlines()
    index = 0

    def take_line() -> str:
        nonlocal index
        blocked(index >= len(lines), "ASSURANCE_RECORD_MALFORMED")
        line = lines[index]
        index += 1
        return line

    def expect(expected: str) -> None:
        blocked(take_line() != expected, "ASSURANCE_RECORD_MALFORMED")

    def field(name: str) -> str:
        line = take_line()
        prefix = f"{name}: "
        blocked(not line.startswith(prefix), "ASSURANCE_RECORD_MALFORMED")
        value = line[len(prefix) :]
        blocked(not value or value != value.strip() or any(not char.isprintable() for char in value), "ASSURANCE_RECORD_MALFORMED")
        return value

    def section(name: str) -> list[str]:
        expect(f"## {name}")
        expect("")
        values: list[str] = []
        while index < len(lines) and lines[index].startswith("- "):
            values.append(take_line()[2:])
        blocked(not values, "ASSURANCE_RECORD_MALFORMED")
        return values

    heading = take_line()
    match = re.fullmatch(r"# Assurance Record (AR-[A-Z0-9]+(?:-[A-Z0-9]+)*)", heading)
    blocked(match is None, "ASSURANCE_RECORD_MALFORMED")
    record_id = match.group(1)
    expect("")
    schema = field("Schema Version")
    record_type = field("Record Type")
    record_path = field("Record Path")
    subject_work_item = field("Subject Work Item")
    subject_commit = field("Subject Commit")
    acceptance_path = field("Acceptance Path")
    acceptance_revision = field("Acceptance Revision")
    actor = field("Actor Session Ref")
    owner = field("Owner Session Ref")
    remediator = field("Remediator Session Ref")
    fresh_context = field("Fresh Context")
    runtime_fingerprint = field("Runtime Fingerprint")
    verdict = field("Verdict")
    p0 = field("P0 Findings")
    p1 = field("P1 Findings")
    p2 = field("P2 Findings")
    blocking_findings = field("Blocking Findings")
    adoption = field("Adoption")
    freshness = field("Freshness")
    expect("")
    evidence_lines = section("Evidence")
    expect("")
    criteria_lines = section("Criteria")
    expect("")
    limitations = section("Limitations")
    expect("")
    stale_triggers = section("Stale Triggers")
    blocked(index != len(lines), "ASSURANCE_RECORD_MALFORMED")

    canonical_path = f"{AUDITS_PATH.as_posix()}/{record_id}.md"
    blocked(schema != "1" or ASSURANCE_ID_RE.fullmatch(record_id) is None, "ASSURANCE_RECORD_MALFORMED")
    blocked(record_path != relative or record_path != canonical_path, "ASSURANCE_ID_PATH_MISMATCH")
    blocked(record_type not in ASSURANCE_RECORD_TYPES, "ASSURANCE_RECORD_MALFORMED")
    blocked(SNAPSHOT_WORK_ITEM_PATH_RE.fullmatch(assurance_safe_path(subject_work_item)) is None, "ASSURANCE_RECORD_MALFORMED")
    blocked(SNAPSHOT_REQUIREMENT_PATH_RE.fullmatch(assurance_safe_path(acceptance_path)) is None, "ASSURANCE_RECORD_MALFORMED")
    blocked(COMMIT_RE.fullmatch(subject_commit) is None or COMMIT_RE.fullmatch(acceptance_revision) is None, "ASSURANCE_COMMIT_INVALID")
    for alias in (actor, owner):
        blocked(SESSION_REF_RE.fullmatch(alias) is None, "ASSURANCE_RECORD_MALFORMED")
    blocked(remediator != "not-applicable" and SESSION_REF_RE.fullmatch(remediator) is None, "ASSURANCE_RECORD_MALFORMED")
    blocked(fresh_context not in {"true", "false"}, "ASSURANCE_RECORD_MALFORMED")
    blocked(re.fullmatch(r"sha256:[0-9a-f]{64}", runtime_fingerprint) is None, "ASSURANCE_RECORD_MALFORMED")
    blocked(verdict not in ASSURANCE_VERDICTS, "ASSURANCE_VERDICT_INVALID")
    blocked(adoption not in ASSURANCE_ADOPTION_STATES, "ASSURANCE_RECORD_MALFORMED")
    blocked(freshness not in {"current", "stale"}, "ASSURANCE_RECORD_MALFORMED")

    counts: list[int] = []
    for value in (p0, p1, p2, blocking_findings):
        blocked(ASSURANCE_COUNT_RE.fullmatch(value) is None, "ASSURANCE_RECORD_MALFORMED")
        try:
            counts.append(int(value))
        except ValueError as exc:
            raise BlockedError("ASSURANCE_RECORD_MALFORMED") from exc
    p0_count, p1_count, p2_count, blocking_count = counts
    total_findings = p0_count + p1_count + p2_count
    blocked(blocking_count != total_findings, "ASSURANCE_FINDING_COUNT_MISMATCH")
    blocked(verdict == "passed" and (blocking_count != 0 or freshness != "current"), "ASSURANCE_VERDICT_INVALID")
    blocked(verdict in {"failed", "blocked"} and (blocking_count == 0 or freshness != "current"), "ASSURANCE_VERDICT_INVALID")
    blocked(verdict == "stale" and freshness != "stale", "ASSURANCE_VERDICT_INVALID")
    blocked(verdict != "stale" and freshness == "stale", "ASSURANCE_VERDICT_INVALID")

    evidence: list[dict[str, str]] = []
    for line in evidence_lines:
        evidence_match = re.fullmatch(r"(.+) \| ([0-9a-f]{40}|[0-9a-f]{64})", line)
        blocked(evidence_match is None, "ASSURANCE_RECORD_MALFORMED")
        evidence.append({"path": assurance_safe_path(evidence_match.group(1)), "blob": evidence_match.group(2)})
    blocked(evidence != sorted(evidence, key=lambda item: item["path"]), "ASSURANCE_RECORD_MALFORMED")
    blocked(len({item["path"] for item in evidence}) != len(evidence), "ASSURANCE_RECORD_MALFORMED")

    criteria: list[dict[str, str]] = []
    for line in criteria_lines:
        criterion = re.fullmatch(r"([a-z0-9]+(?:-[a-z0-9]+)*) \| (passed|failed|blocked|stale)", line)
        blocked(criterion is None, "ASSURANCE_RECORD_MALFORMED")
        criteria.append({"ref": criterion.group(1), "verdict": criterion.group(2)})
    blocked(criteria != sorted(criteria, key=lambda item: item["ref"]), "ASSURANCE_RECORD_MALFORMED")
    blocked(len({item["ref"] for item in criteria}) != len(criteria), "ASSURANCE_RECORD_MALFORMED")
    criterion_verdicts = {item["verdict"] for item in criteria}
    aggregate = next(value for value in ("stale", "blocked", "failed", "passed") if value in criterion_verdicts)
    blocked(verdict != aggregate, "ASSURANCE_CRITERIA_MISMATCH")

    token_re = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    blocked(any(token_re.fullmatch(value) is None for value in limitations + stale_triggers), "ASSURANCE_RECORD_MALFORMED")
    blocked(limitations != sorted(set(limitations)) or stale_triggers != sorted(set(stale_triggers)), "ASSURANCE_RECORD_MALFORMED")
    blocked(ASSURANCE_LIMITATION not in limitations, "ASSURANCE_PROOF_LIMIT_MISSING")
    required_triggers = set(ASSURANCE_REQUIRED_STALE_TRIGGERS)
    if record_type == "independent-audit":
        required_triggers.add("independence-invalidated")
    blocked(not required_triggers.issubset(stale_triggers), "ASSURANCE_STALE_TRIGGER_MISSING")

    return {
        "type": record_type,
        "path": record_path,
        "subject_work_item": subject_work_item,
        "subject_commit": subject_commit,
        "acceptance_path": acceptance_path,
        "acceptance_revision": acceptance_revision,
        "actor": actor,
        "owner": owner,
        "remediator": remediator,
        "fresh_context": fresh_context == "true",
        "verdict": verdict,
        "blocking_findings": blocking_count,
        "adoption": adoption,
        "freshness": freshness,
        "evidence": evidence,
    }


def assurance_subject_authority(text: str, relative: str) -> dict[str, str]:
    return work_item_authority(text, relative, "ASSURANCE_SUBJECT_INVALID")


def assurance_authority_status(text: str, relative: str, code: str) -> str:
    try:
        status = snapshot_field(text, "Status", relative)
    except BlockedError as exc:
        raise BlockedError(code) from exc
    blocked(status is None or SNAPSHOT_STATUS_RE.fullmatch(status) is None, code)
    return status


def assurance_acceptance_authority(
    text: str,
    relative: str,
    requirement: str,
    project: str,
    code: str = "ASSURANCE_ACCEPTANCE_INVALID",
) -> str:
    headings = re.findall(r"^# Requirement Brief ([^:]+):", text, flags=re.MULTILINE)
    path_match = SNAPSHOT_REQUIREMENT_PATH_RE.fullmatch(relative)
    try:
        plan_field = snapshot_field(text, "Project Plan", relative)
        plan_path = snapshot_safe_path(plan_field or "", relative)
    except BlockedError as exc:
        raise BlockedError(code) from exc
    plan_match = SNAPSHOT_PROJECT_PATH_RE.fullmatch(plan_path)
    blocked(
        path_match is None
        or path_match.group(1) != requirement
        or path_match.group(2) != project
        or headings != [requirement]
        or plan_match is None
        or plan_match.group(1) != project,
        code,
    )
    assurance_authority_status(text, relative, code)
    return plan_path


def assurance_project_authority(text: str, relative: str, project: str, code: str) -> None:
    headings = re.findall(r"^# Project Plan ([^:]+):", text, flags=re.MULTILINE)
    path_match = SNAPSHOT_PROJECT_PATH_RE.fullmatch(relative)
    blocked(path_match is None or path_match.group(1) != project or headings != [project], code)
    assurance_authority_status(text, relative, code)


def validate_assurance_record_commit_scope(root: Path, relative: str, record_commit: str) -> None:
    record_delta = git_path_set(
        root,
        "ASSURANCE_RECORD_COMMIT_SCOPE_INVALID",
        "diff-tree",
        "--root",
        "-m",
        "--no-commit-id",
        "--name-only",
        "--no-renames",
        "-r",
        record_commit,
    )
    blocked(record_delta != [relative], "ASSURANCE_RECORD_COMMIT_SCOPE_INVALID")


def parse_commit_path_stream(raw: bytes, code: str) -> dict[str, set[str]]:
    blocks = raw.split(b"\x1e")
    blocked(blocks[0].strip(b"\0\r\n") != b"", code)
    paths_by_commit: dict[str, set[str]] = {}
    for block in blocks[1:]:
        values = block.split(b"\0")
        try:
            commit = values[0].decode("ascii")
        except UnicodeDecodeError as exc:
            raise BlockedError(code) from exc
        blocked(COMMIT_RE.fullmatch(commit) is None, code)
        paths = paths_by_commit.setdefault(commit, set())
        for value in values[1:]:
            if value.startswith(b"\n"):
                value = value[1:]
            if not value:
                continue
            try:
                paths.add(value.decode("utf-8"))
            except UnicodeDecodeError as exc:
                raise BlockedError(code) from exc
    return paths_by_commit


def parse_tree_entry_stream(raw: bytes, code: str) -> dict[str, tuple[str, str, str]]:
    if not raw:
        return {}
    values = raw.split(b"\0")
    blocked(values[-1] != b"" or any(not entry for entry in values[:-1]), code)
    entries: dict[str, tuple[str, str, str]] = {}
    for entry in values[:-1]:
        metadata, separator, raw_path = entry.partition(b"\t")
        parts = metadata.split(b" ")
        blocked(not separator or len(parts) != 3, code)
        try:
            mode = parts[0].decode("ascii")
            object_type = parts[1].decode("ascii")
            blob = parts[2].decode("ascii")
            path = raw_path.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise BlockedError(code) from exc
        blocked(
            re.fullmatch(r"[0-7]{6}", mode) is None
            or object_type not in {"blob", "tree", "commit"}
            or COMMIT_RE.fullmatch(blob) is None
            or not path
            or path in entries,
            code,
        )
        entries[path] = (mode, object_type, blob)
    return entries


def parse_assurance_tree(raw: bytes) -> dict[str, str]:
    blobs: dict[str, str] = {}
    for path, (mode, object_type, blob) in parse_tree_entry_stream(
        raw, "CLOSE_RECORD_SET_INVALID"
    ).items():
        if re.fullmatch(r"\.codex/audits/AR-[A-Z0-9]+(?:-[A-Z0-9]+)*\.md", path) is None:
            continue
        blocked(
            mode not in {"100644", "100755"}
            or object_type != "blob"
            or path in blobs,
            "CLOSE_RECORD_SET_INVALID",
        )
        blobs[path] = blob
    return blobs


def read_git_blob_batch(
    root: Path,
    blob_ids: list[str],
    code: str = "CLOSE_RECORD_SET_INVALID",
) -> dict[str, bytes]:
    blocked(
        blob_ids != list(dict.fromkeys(blob_ids))
        or any(COMMIT_RE.fullmatch(blob) is None for blob in blob_ids),
        code,
    )
    blobs, failures = read_git_blob_batch_progress(root, blob_ids)
    blocked(bool(failures), code)
    return blobs


def parse_git_blob_batch_progress(
    output: bytes,
    blob_ids: list[str],
) -> tuple[dict[str, bytes], list[str]]:
    if not blob_ids:
        return {}, []
    offset = 0
    blobs: dict[str, bytes] = {}
    for index, requested in enumerate(blob_ids):
        header_end = output.find(b"\n", offset)
        if header_end < 0:
            return blobs, blob_ids[index:]
        header = output[offset:header_end].split(b" ")
        if len(header) != 3:
            return blobs, blob_ids[index:]
        try:
            actual = header[0].decode("ascii")
            object_type = header[1].decode("ascii")
            size_text = header[2].decode("ascii")
        except UnicodeDecodeError:
            return blobs, blob_ids[index:]
        if (
            actual != requested
            or object_type != "blob"
            or GIT_OBJECT_SIZE_RE.fullmatch(size_text) is None
            or actual in blobs
        ):
            return blobs, blob_ids[index:]
        try:
            size = int(size_text)
        except ValueError:
            return blobs, blob_ids[index:]
        content_start = header_end + 1
        content_end = content_start + size
        if content_end >= len(output) or output[content_end:content_end + 1] != b"\n":
            return blobs, blob_ids[index:]
        blobs[actual] = output[content_start:content_end]
        offset = content_end + 1
    if offset != len(output):
        return {}, list(blob_ids)
    return blobs, []


def read_git_blob_batch_progress(
    root: Path,
    blob_ids: list[str],
) -> tuple[dict[str, bytes], list[str]]:
    if not blob_ids:
        return {}, []
    try:
        result = git_process(
            root, "cat-file", "--batch",
            input=("\n".join(blob_ids) + "\n").encode("ascii"),
            capture_output=True,
        )
    except OSError:
        return {}, list(blob_ids)
    if result.returncode != 0:
        return {}, list(blob_ids)
    return parse_git_blob_batch_progress(result.stdout, blob_ids)


def read_committed_file_stage(
    root: Path,
    revision: str,
    requests: list[tuple[str, str, str]],
    cache: CommittedFileCache,
    resolved_entries: dict[str, tuple[str, str, str]] | None = None,
) -> None:
    if not requests:
        return
    first_code = requests[0][1]
    ordered: dict[str, tuple[str, str]] = {}
    for path, unreadable_code, not_regular_code in requests:
        try:
            safe = assurance_safe_path(path)
        except BlockedError as exc:
            raise BlockedError(first_code) from exc
        blocked(safe != path, first_code)
        ordered.setdefault(path, (unreadable_code, not_regular_code))
    missing_cache = [path for path in ordered if (revision, path) not in cache]
    if not missing_cache:
        return

    if resolved_entries is None:
        pathspecs = [f":(literal){path}" for path in sorted(missing_cache)]
        result = git_process(
            root, "ls-tree", "-z", revision, "--", *pathspecs,
            capture_output=True,
        )
        blocked(result.returncode != 0, first_code)
        entries = parse_tree_entry_stream(result.stdout, first_code)
        blocked(any(path not in missing_cache for path in entries), first_code)
    else:
        entries = {path: resolved_entries[path] for path in missing_cache if path in resolved_entries}

    pending: dict[tuple[str, str], CommittedFileValue] = {}
    blobs_by_path: dict[str, str] = {}
    for path in missing_cache:
        unreadable_code, not_regular_code = ordered[path]
        if path not in entries:
            pending[(revision, path)] = DeferredFileFailure(unreadable_code)
            continue
        mode, object_type, blob = entries[path]
        if mode not in {"100644", "100755"} or object_type != "blob":
            pending[(revision, path)] = DeferredFileFailure(not_regular_code)
            continue
        blobs_by_path[path] = blob

    blob_ids = list(dict.fromkeys(blobs_by_path.values()))
    blob_contents, failed_blobs = read_git_blob_batch_progress(root, blob_ids)
    blocked(
        set(blob_contents).union(failed_blobs) != set(blob_ids)
        or set(blob_contents).intersection(failed_blobs),
        first_code,
    )
    for path, blob in blobs_by_path.items():
        if blob in blob_contents:
            pending[(revision, path)] = (blob_contents[blob], blob)
        else:
            pending[(revision, path)] = DeferredFileFailure(ordered[path][0])
    blocked(set(pending) != {(revision, path) for path in missing_cache}, first_code)
    cache.update(pending)


def committed_file_cache_get(
    cache: CommittedFileCache,
    revision: str,
    path: str,
    missing_code: str,
) -> tuple[bytes, str]:
    value = cache.get((revision, path))
    blocked(value is None, missing_code)
    if isinstance(value, DeferredFileFailure):
        raise BlockedError(value.code)
    return value


def validate_assurance_record_commit_scopes(root: Path, inventory: dict[str, str]) -> None:
    if not inventory:
        return
    commits = sorted(set(inventory.values()))
    result = git_process(
        root,
            "diff-tree",
            "--stdin",
            "--root",
            "-m",
            "--format=\x1e%H%x00",
            "--name-only",
            "--no-renames",
            "-r",
            "-z",
        input=("\n".join(commits) + "\n").encode("ascii"),
        capture_output=True,
    )
    blocked(result.returncode != 0, "ASSURANCE_RECORD_COMMIT_SCOPE_INVALID")
    paths_by_commit = parse_commit_path_stream(result.stdout, "ASSURANCE_RECORD_COMMIT_SCOPE_INVALID")
    blocked(set(paths_by_commit) != set(commits), "ASSURANCE_RECORD_COMMIT_SCOPE_INVALID")
    for relative, commit in inventory.items():
        blocked(paths_by_commit[commit] != {relative}, "ASSURANCE_RECORD_COMMIT_SCOPE_INVALID")


def assurance_unique_authority_path(
    root: Path,
    revision: str,
    pattern: re.Pattern[str],
    authority_ref: str,
    expected_path: str,
    code: str,
    cache: dict[str, list[str]] | None = None,
) -> None:
    if cache is not None and revision in cache:
        paths = cache[revision]
    else:
        try:
            paths = snapshot_authority_paths(root, revision)
        except BlockedError as exc:
            raise BlockedError(code) from exc
        if cache is not None:
            cache[revision] = paths
    matches = [path for path in paths if (match := pattern.fullmatch(path)) and match.group(1) == authority_ref]
    blocked(matches != [expected_path], code)


def assurance_work_item(
    root: Path,
    revision: str,
    relative: str,
    expected_status: str,
    file_cache: CommittedFileCache | None = None,
    authority_paths_cache: dict[str, list[str]] | None = None,
    history_checked: bool = False,
    commit_graph: CommitGraph | None = None,
) -> dict[str, Any]:
    if file_cache is None:
        content, _ = committed_regular_file(
            root, revision, relative, "ASSURANCE_SUBJECT_INVALID", "ASSURANCE_SUBJECT_INVALID"
        )
    else:
        read_committed_file_stage(
            root,
            revision,
            [(relative, "ASSURANCE_SUBJECT_INVALID", "ASSURANCE_SUBJECT_INVALID")],
            file_cache,
        )
        content, _ = committed_file_cache_get(
            file_cache, revision, relative, "ASSURANCE_SUBJECT_INVALID"
        )
    blocked(SENSITIVE_TASK_ID_SEARCH_RE.search(content) is not None, "ASSURANCE_IDENTITY_EXPOSURE")
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise BlockedError("ASSURANCE_SUBJECT_INVALID") from exc
    try:
        item = parse_work_item(text, relative, expected_status)
    except BlockedError as exc:
        raise BlockedError("ASSURANCE_SUBJECT_INVALID") from exc
    item.update(assurance_subject_authority(text, relative))
    item["committed_text"] = text
    if expected_status == "active":
        try:
            dispatch = dispatch_commit(
                root,
                item,
                revision,
                history_checked=history_checked,
                commit_graph=commit_graph,
                file_cache=file_cache,
                authority_paths_cache=authority_paths_cache,
            )
            validate_handoff_delta(root, item, dispatch, revision, file_cache)
        except BlockedError as exc:
            raise BlockedError("ASSURANCE_SUBJECT_INVALID") from exc
    return item


def validate_assurance_actor(record: dict[str, Any]) -> None:
    if record["type"] == "owner-verification":
        blocked(
            record["actor"] != record["owner"]
            or record["remediator"] != "not-applicable"
            or record["fresh_context"],
            "ASSURANCE_OWNER_INVALID",
        )
    else:
        blocked(
            not record["fresh_context"]
            or record["actor"] == record["owner"]
            or record["actor"] == record["remediator"],
            "ASSURANCE_INDEPENDENCE_INVALID",
        )


def validate_assurance_registry(
    record: dict[str, Any],
    registry: dict[str, str],
    missing_code: str,
    independence_code: str,
) -> None:
    aliases = [record["actor"], record["owner"]]
    if record["remediator"] != "not-applicable":
        aliases.append(record["remediator"])
    blocked(any(alias not in registry for alias in aliases), missing_code)
    if record["type"] == "independent-audit":
        actor_id = registry[record["actor"]]
        blocked(
            actor_id == registry[record["owner"]]
            or (
                record["remediator"] != "not-applicable"
                and actor_id == registry[record["remediator"]]
            ),
            independence_code,
        )


def load_assurance_record(
    root: Path,
    record: Path,
    head: str,
    registry: dict[str, str],
    record_commits: dict[str, str] | None = None,
    authority_paths: dict[str, list[str]] | None = None,
    subjects: dict[tuple[str, str], dict[str, Any]] | None = None,
    parsed_records: dict[str, dict[str, Any]] | None = None,
    record_contents: dict[str, bytes] | None = None,
    file_cache: CommittedFileCache | None = None,
    commit_graph: CommitGraph | None = None,
) -> dict[str, Any]:
    file_cache = {} if file_cache is None else file_cache
    relative = assurance_relative(root, record, "ASSURANCE_RECORD_PATH_INVALID")
    blocked(not relative.startswith(AUDITS_PATH.as_posix() + "/"), "ASSURANCE_RECORD_PATH_INVALID")
    blocked(not tracked(root, relative), "ASSURANCE_RECORD_UNTRACKED")
    if parsed_records is not None and relative in parsed_records:
        parsed = dict(parsed_records[relative])
    else:
        if record_contents is not None:
            blocked(relative not in record_contents, "ASSURANCE_RECORD_UNREADABLE")
            content = record_contents[relative]
        else:
            read_committed_file_stage(
                root,
                head,
                [(relative, "ASSURANCE_RECORD_UNREADABLE", "ASSURANCE_RECORD_UNREADABLE")],
                file_cache,
            )
            content, _ = committed_file_cache_get(
                file_cache, head, relative, "ASSURANCE_RECORD_UNREADABLE"
            )
        blocked(SENSITIVE_TASK_ID_SEARCH_RE.search(content) is not None, "ASSURANCE_IDENTITY_EXPOSURE")
        try:
            parsed = parse_assurance_record(content.decode("utf-8"), relative)
        except UnicodeDecodeError as exc:
            raise BlockedError("ASSURANCE_RECORD_MALFORMED") from exc
        if parsed_records is not None:
            parsed_records[relative] = dict(parsed)

    if record_commits is None:
        history = run_git(root, "log", "--full-history", "--format=%H", head, "--", f":(literal){relative}")
        commits = [line for line in history.stdout.splitlines() if line]
        blocked(history.returncode != 0 or len(commits) != 1, "ASSURANCE_RECORD_NOT_IMMUTABLE")
        record_commit = commits[0]
        validate_assurance_record_commit_scope(root, relative, record_commit)
    else:
        blocked(relative not in record_commits, "ASSURANCE_RECORD_NOT_IMMUTABLE")
        record_commit = record_commits[relative]
    for revision in (
        parsed["subject_commit"],
        parsed["acceptance_revision"],
    ):
        blocked(not commit_exists(root, revision, commit_graph), "ASSURANCE_COMMIT_INVALID")
    blocked(
        parsed["subject_commit"] == record_commit
        or not commit_is_ancestor(root, parsed["subject_commit"], record_commit, commit_graph),
        "ASSURANCE_SUBJECT_ORDER_INVALID",
    )
    blocked(
        not commit_is_ancestor(
            root,
            parsed["acceptance_revision"],
            parsed["subject_commit"],
            commit_graph,
        ),
        "ASSURANCE_ACCEPTANCE_INVALID",
    )

    validate_assurance_registry(
        parsed,
        registry,
        "ASSURANCE_ALIAS_UNRESOLVED",
        "ASSURANCE_INDEPENDENCE_INVALID",
    )

    subject_key = (parsed["subject_commit"], parsed["subject_work_item"])
    read_committed_file_stage(
        root,
        parsed["subject_commit"],
        [
            (
                parsed["subject_work_item"],
                "ASSURANCE_SUBJECT_INVALID",
                "ASSURANCE_SUBJECT_INVALID",
            ),
            *[
                (
                    evidence["path"],
                    "ASSURANCE_EVIDENCE_INVALID",
                    "ASSURANCE_EVIDENCE_INVALID",
                )
                for evidence in parsed["evidence"]
            ],
        ],
        file_cache,
    )
    if subjects is not None and subject_key in subjects:
        subject = subjects[subject_key]
    else:
        subject = assurance_work_item(
            root,
            *subject_key,
            "active",
            file_cache,
            authority_paths,
            history_checked=True,
            commit_graph=commit_graph,
        )
        if subjects is not None:
            subjects[subject_key] = subject
    authority_paths = {} if authority_paths is None else authority_paths
    blocked(subject["owner"] != parsed["owner"], "ASSURANCE_OWNER_MISMATCH")
    blocked(parsed["acceptance_revision"] != subject["source"], "ASSURANCE_ACCEPTANCE_INVALID")
    assurance_unique_authority_path(
        root,
        parsed["acceptance_revision"],
        SNAPSHOT_REQUIREMENT_PATH_RE,
        subject["requirement"],
        parsed["acceptance_path"],
        "ASSURANCE_ACCEPTANCE_INVALID",
        authority_paths,
    )
    source_authority_paths = authority_paths[parsed["acceptance_revision"]]
    plan_matches = [
        path for path in source_authority_paths
        if (match := SNAPSHOT_PROJECT_PATH_RE.fullmatch(path))
        and match.group(1) == subject["project"]
    ]
    staged_plan = plan_matches[0] if len(plan_matches) == 1 else None
    read_committed_file_stage(
        root,
        parsed["acceptance_revision"],
        [
            (
                parsed["acceptance_path"],
                "ASSURANCE_ACCEPTANCE_INVALID",
                "ASSURANCE_ACCEPTANCE_INVALID",
            ),
            *(
                [(staged_plan, "ASSURANCE_ACCEPTANCE_INVALID", "ASSURANCE_ACCEPTANCE_INVALID")]
                if staged_plan is not None
                else []
            ),
        ],
        file_cache,
    )
    acceptance, acceptance_blob = committed_file_cache_get(
        file_cache,
        parsed["acceptance_revision"],
        parsed["acceptance_path"],
        "ASSURANCE_ACCEPTANCE_INVALID",
    )
    blocked(SENSITIVE_TASK_ID_SEARCH_RE.search(acceptance) is not None, "ASSURANCE_IDENTITY_EXPOSURE")
    try:
        acceptance_text = acceptance.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise BlockedError("ASSURANCE_ACCEPTANCE_INVALID") from exc
    plan_path = assurance_acceptance_authority(
        acceptance_text,
        parsed["acceptance_path"],
        subject["requirement"],
        subject["project"],
    )
    blocked(plan_matches != [plan_path], "ASSURANCE_ACCEPTANCE_INVALID")
    plan, _ = committed_file_cache_get(
        file_cache, parsed["acceptance_revision"], plan_path, "ASSURANCE_ACCEPTANCE_INVALID"
    )
    blocked(SENSITIVE_TASK_ID_SEARCH_RE.search(plan) is not None, "ASSURANCE_IDENTITY_EXPOSURE")
    try:
        assurance_project_authority(
            plan.decode("utf-8"), plan_path, subject["project"], "ASSURANCE_ACCEPTANCE_INVALID"
        )
    except UnicodeDecodeError as exc:
        raise BlockedError("ASSURANCE_ACCEPTANCE_INVALID") from exc
    assurance_unique_authority_path(
        root,
        head,
        SNAPSHOT_REQUIREMENT_PATH_RE,
        subject["requirement"],
        parsed["acceptance_path"],
        "ASSURANCE_ACCEPTANCE_STALE",
        authority_paths,
    )
    assurance_unique_authority_path(
        root,
        head,
        SNAPSHOT_PROJECT_PATH_RE,
        subject["project"],
        plan_path,
        "ASSURANCE_ACCEPTANCE_STALE",
        authority_paths,
    )
    read_committed_file_stage(
        root,
        head,
        [
            (
                parsed["acceptance_path"],
                "ASSURANCE_ACCEPTANCE_STALE",
                "ASSURANCE_ACCEPTANCE_STALE",
            ),
            (plan_path, "ASSURANCE_ACCEPTANCE_STALE", "ASSURANCE_ACCEPTANCE_STALE"),
            *[
                (
                    evidence["path"],
                    "ASSURANCE_EVIDENCE_STALE",
                    "ASSURANCE_EVIDENCE_STALE",
                )
                for evidence in parsed["evidence"]
            ],
        ],
        file_cache,
    )
    current_acceptance, current_acceptance_blob = committed_file_cache_get(
        file_cache, head, parsed["acceptance_path"], "ASSURANCE_ACCEPTANCE_STALE"
    )
    current_plan, _ = committed_file_cache_get(
        file_cache, head, plan_path, "ASSURANCE_ACCEPTANCE_STALE"
    )
    blocked(SENSITIVE_TASK_ID_SEARCH_RE.search(current_plan) is not None, "ASSURANCE_IDENTITY_EXPOSURE")
    try:
        assurance_project_authority(
            current_plan.decode("utf-8"), plan_path, subject["project"], "ASSURANCE_ACCEPTANCE_STALE"
        )
    except UnicodeDecodeError as exc:
        raise BlockedError("ASSURANCE_ACCEPTANCE_STALE") from exc
    blocked(
        current_acceptance_blob != acceptance_blob or SENSITIVE_TASK_ID_SEARCH_RE.search(current_acceptance) is not None,
        "ASSURANCE_ACCEPTANCE_STALE",
    )

    blocked(subject["evidence"] not in {item["path"] for item in parsed["evidence"]}, "ASSURANCE_EVIDENCE_REQUIRED")
    for evidence in parsed["evidence"]:
        evidence_content, actual_blob = committed_file_cache_get(
            file_cache,
            parsed["subject_commit"],
            evidence["path"],
            "ASSURANCE_EVIDENCE_INVALID",
        )
        blocked(actual_blob != evidence["blob"], "ASSURANCE_EVIDENCE_MISMATCH")
        blocked(SENSITIVE_TASK_ID_SEARCH_RE.search(evidence_content) is not None, "ASSURANCE_IDENTITY_EXPOSURE")
        current_evidence, current_blob = committed_file_cache_get(
            file_cache, head, evidence["path"], "ASSURANCE_EVIDENCE_STALE"
        )
        blocked(current_blob != actual_blob, "ASSURANCE_EVIDENCE_STALE")
        blocked(SENSITIVE_TASK_ID_SEARCH_RE.search(current_evidence) is not None, "ASSURANCE_IDENTITY_EXPOSURE")

    validate_assurance_actor(parsed)
    parsed.update({"record_commit": record_commit, "subject": subject})
    return parsed


def assurance_check(root: Path, record: Path) -> dict[str, Any]:
    root = root.resolve()
    head = snapshot_head(root, reject_provenance_replacement=True)
    ensure_complete_git_history(root, provenance_checked=True)
    commit_graph = load_commit_graph(root, head)
    registry = registry_guard(root)
    result = load_assurance_record(
        root,
        record,
        head,
        registry,
        file_cache={},
        commit_graph=commit_graph,
    )
    ensure_evaluation_state_unchanged(root, head, registry)
    return result


def assurance_record_inventory(
    root: Path,
    head: str,
    record_contents: dict[str, bytes] | None = None,
    file_cache: CommittedFileCache | None = None,
) -> dict[str, str]:
    result = git_process(
        root, "ls-tree", "-r", "-z", head, "--", AUDITS_PATH.as_posix(),
        capture_output=True,
    )
    blocked(result.returncode != 0, "CLOSE_RECORD_SET_INVALID")
    current_blobs = parse_assurance_tree(result.stdout)
    current = sorted(current_blobs)
    blob_contents = read_git_blob_batch(root, sorted(set(current_blobs.values())))
    blocked(any(blob not in blob_contents for blob in current_blobs.values()), "CLOSE_RECORD_SET_INVALID")
    history = git_process(
        root,
            "log",
            "--full-history",
            "--diff-merges=combined",
            "--format=\x1e%H%x00",
            "--name-only",
            "--no-renames",
            "-z",
            head,
            "--",
            AUDITS_PATH.as_posix(),
        capture_output=True,
    )
    blocked(history.returncode != 0, "CLOSE_RECORD_SET_INVALID")
    all_touches = parse_commit_path_stream(history.stdout, "CLOSE_RECORD_SET_INVALID")
    touches: dict[str, set[str]] = {}
    for commit, paths in all_touches.items():
        for path in paths:
            if re.fullmatch(r"\.codex/audits/AR-[A-Z0-9]+(?:-[A-Z0-9]+)*\.md", path):
                touches.setdefault(path, set()).add(commit)
    blocked(current != sorted(touches), "CLOSE_RECORD_SET_INVALID")
    blocked(any(len(commits) != 1 for commits in touches.values()), "CLOSE_RECORD_SET_INVALID")
    inventory = {path: next(iter(touches[path])) for path in current}
    validate_assurance_record_commit_scopes(root, inventory)
    resolved_contents = {path: blob_contents[blob] for path, blob in current_blobs.items()}
    if record_contents is not None:
        record_contents.clear()
        record_contents.update(resolved_contents)
    if file_cache is not None:
        pending = {
            (head, path): (resolved_contents[path], current_blobs[path])
            for path in current
        }
        blocked(
            any(key in file_cache and file_cache[key] != value for key, value in pending.items()),
            "CLOSE_RECORD_SET_INVALID",
        )
        file_cache.update(pending)
    return inventory


def validate_reaudit(
    selected: dict[str, Any],
    previous: dict[str, Any],
) -> None:
    if selected["type"] == "independent-audit" and previous["verdict"] != "passed":
        blocked(
            selected["remediator"] == "not-applicable"
            or selected["actor"] == previous["actor"]
            or selected["remediator"] == previous["actor"],
            "CLOSE_REAUDIT_INVALID",
        )


def validate_audit_chain_identity(
    selected: dict[str, Any],
    previous: dict[str, Any],
    registry: dict[str, str],
) -> None:
    if selected["type"] != "independent-audit":
        return
    selected_actor = registry[selected["actor"]]
    previous_actor = registry[previous["actor"]]
    previous_remediator = (
        registry[previous["remediator"]]
        if previous["remediator"] != "not-applicable"
        else None
    )
    selected_remediator = (
        registry[selected["remediator"]]
        if selected["remediator"] != "not-applicable"
        else None
    )
    blocked(
        selected_actor == previous_actor
        or (previous_remediator is not None and selected_actor == previous_remediator)
        or (selected_remediator is not None and selected_remediator == previous_actor),
        "CLOSE_REAUDIT_INVALID",
    )


def ensure_latest_assurance_record(
    root: Path,
    head: str,
    inventory: dict[str, str],
    registry: dict[str, str],
    selected: dict[str, Any],
    parsed_records: dict[str, dict[str, Any]],
    record_contents: dict[str, bytes],
    commit_graph: CommitGraph | None = None,
) -> None:
    identity = (
        selected["type"],
        selected["subject_work_item"],
        selected["subject_commit"],
        selected["acceptance_path"],
        selected["acceptance_revision"],
    )
    for relative, record_commit in inventory.items():
        if relative == selected["path"]:
            continue
        if relative in parsed_records:
            candidate = dict(parsed_records[relative])
        else:
            blocked(relative not in record_contents, "CLOSE_RECORD_SET_INVALID")
            content = record_contents[relative]
            blocked(SENSITIVE_TASK_ID_SEARCH_RE.search(content) is not None, "ASSURANCE_IDENTITY_EXPOSURE")
            try:
                candidate = parse_assurance_record(content.decode("utf-8"), relative)
            except (UnicodeDecodeError, BlockedError) as exc:
                raise BlockedError("CLOSE_RECORD_SET_INVALID") from exc
            parsed_records[relative] = dict(candidate)
        candidate_identity = (
            candidate["type"],
            candidate["subject_work_item"],
            candidate["subject_commit"],
            candidate["acceptance_path"],
            candidate["acceptance_revision"],
        )
        if candidate_identity != identity:
            continue
        blocked(candidate["owner"] != selected["owner"], "CLOSE_RECORD_SET_INVALID")
        try:
            validate_assurance_actor(candidate)
        except BlockedError as exc:
            raise BlockedError("CLOSE_RECORD_SET_INVALID") from exc
        validate_assurance_registry(
            candidate,
            registry,
            "CLOSE_REAUDIT_INVALID",
            "CLOSE_REAUDIT_INVALID",
        )
        blocked(
            record_commit == selected["record_commit"]
            or not commit_is_ancestor(
                root,
                record_commit,
                selected["record_commit"],
                commit_graph,
            ),
            "CLOSE_RECORD_NOT_LATEST",
        )
        validate_audit_chain_identity(selected, candidate, registry)
        if selected["type"] == "independent-audit" and candidate["verdict"] != "passed":
            validate_reaudit(selected, candidate)


def validate_close_records(
    relative: str,
    current: dict[str, Any],
    owner: dict[str, Any],
    audit: dict[str, Any],
) -> None:
    blocked(owner["type"] != "owner-verification" or audit["type"] != "independent-audit", "CLOSE_RECORD_TYPE_INVALID")
    pinned_subject = (relative, owner["subject_commit"])
    blocked((owner["subject_work_item"], owner["subject_commit"]) != pinned_subject, "CLOSE_SUBJECT_MISMATCH")
    blocked((audit["subject_work_item"], audit["subject_commit"]) != pinned_subject, "CLOSE_SUBJECT_MISMATCH")
    blocked(
        (owner["acceptance_path"], owner["acceptance_revision"])
        != (audit["acceptance_path"], audit["acceptance_revision"]),
        "CLOSE_ACCEPTANCE_MISMATCH",
    )
    blocked(
        owner["owner"] != current["owner"]
        or audit["owner"] != current["owner"]
        or owner["subject"]["requirement"] != current["requirement"]
        or audit["subject"]["requirement"] != current["requirement"],
        "CLOSE_OWNER_MISMATCH",
    )
    blocked(owner["blocking_findings"] != 0 or audit["blocking_findings"] != 0, "CLOSE_FINDINGS_OPEN")
    blocked(
        owner["verdict"] != "passed" or audit["verdict"] != "passed"
        or owner["freshness"] != "current" or audit["freshness"] != "current",
        "CLOSE_VERIFICATION_NOT_PASSED",
    )
    blocked(
        owner["adoption"] != audit["adoption"]
        or owner["adoption"] not in {"not-required", "adopted"}
        or audit["adoption"] not in {"not-required", "adopted"},
        "CLOSE_ADOPTION_BLOCKED",
    )


def ensure_close_subject_current(
    root: Path,
    head: str,
    subject_commit: str,
    work_item: str,
    scopes: list[str],
) -> None:
    touched = git_path_set(
        root,
        "CLOSE_SUBJECT_STALE",
        "log",
        "--full-history",
        "-m",
        "--name-only",
        "--format=",
        "--no-renames",
        f"{subject_commit}..{head}",
    )
    stale = [
        path for path in touched
        if path != work_item
        and re.fullmatch(r"\.codex/audits/AR-[A-Z0-9]+(?:-[A-Z0-9]+)*\.md", path) is None
        and any(path_in_scope(path, scope) for scope in scopes)
    ]
    blocked(bool(stale), "CLOSE_SUBJECT_STALE")


def close_check(root: Path, work_item: Path, owner_record: Path, audit_record: Path) -> dict[str, Any]:
    root = root.resolve()
    head = snapshot_head(root, reject_provenance_replacement=True)
    ensure_complete_git_history(root, provenance_checked=True)
    commit_graph = load_commit_graph(root, head)
    registry = registry_guard(root)
    record_contents: dict[str, bytes] = {}
    file_cache: CommittedFileCache = {}
    inventory = assurance_record_inventory(root, head, record_contents, file_cache)
    authority_paths: dict[str, list[str]] = {}
    subjects: dict[tuple[str, str], dict[str, Any]] = {}
    parsed_records: dict[str, dict[str, Any]] = {}
    owner = load_assurance_record(
        root,
        owner_record,
        head,
        registry,
        inventory,
        authority_paths,
        subjects,
        parsed_records,
        record_contents,
        file_cache,
        commit_graph,
    )
    audit = load_assurance_record(
        root,
        audit_record,
        head,
        registry,
        inventory,
        authority_paths,
        subjects,
        parsed_records,
        record_contents,
        file_cache,
        commit_graph,
    )
    relative = assurance_relative(root, work_item, "CLOSE_WORK_ITEM_INVALID")
    blocked(SNAPSHOT_WORK_ITEM_PATH_RE.fullmatch(relative) is None, "CLOSE_WORK_ITEM_INVALID")
    current = assurance_work_item(
        root,
        head,
        relative,
        "handed-off",
        file_cache,
        commit_graph=commit_graph,
    )

    validate_close_records(relative, current, owner, audit)
    ensure_latest_assurance_record(
        root,
        head,
        inventory,
        registry,
        owner,
        parsed_records,
        record_contents,
        commit_graph,
    )
    ensure_latest_assurance_record(
        root,
        head,
        inventory,
        registry,
        audit,
        parsed_records,
        record_contents,
        commit_graph,
    )
    expected_handoff = re.sub(
        r"^(Status:[ \t]*)active([ \t]*)$",
        r"\g<1>handed-off\g<2>",
        owner["subject"]["committed_text"],
        count=1,
        flags=re.MULTILINE,
    )
    blocked(current["committed_text"] != expected_handoff, "CLOSE_WORK_ITEM_MUTATED")
    lifecycle = run_git(
        root,
        "log",
        "--full-history",
        "--reverse",
        "--format=%H",
        f"{owner['subject_commit']}..{head}",
        "--",
        f":(literal){relative}",
    )
    lifecycle_commits = [line for line in lifecycle.stdout.splitlines() if line]
    blocked(lifecycle.returncode != 0 or len(lifecycle_commits) != 1, "CLOSE_WORK_ITEM_MUTATED")
    blocked(
        lifecycle_commits[0] == owner["record_commit"]
        or not commit_is_ancestor(
            root,
            lifecycle_commits[0],
            owner["record_commit"],
            commit_graph,
        ),
        "CLOSE_OWNER_ORDER_INVALID",
    )
    ensure_close_subject_current(
        root,
        head,
        owner["subject_commit"],
        relative,
        owner["subject"]["scopes"],
    )
    blocked(
        owner["record_commit"] == audit["record_commit"]
        or not commit_is_ancestor(
            root,
            owner["record_commit"],
            audit["record_commit"],
            commit_graph,
        ),
        "CLOSE_AUDIT_ORDER_INVALID",
    )
    result = {"work_item": relative, "owner_record": owner["path"], "audit_record": audit["path"]}
    ensure_evaluation_state_unchanged(root, head, registry)
    return result


def load_attempts(root: Path) -> list[dict[str, Any]]:
    path = root / ATTEMPTS_PATH
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise BlockedError("MALFORMED_ATTEMPT_LOG", f"line {line_number}") from exc
        blocked(not isinstance(record, dict), "MALFORMED_ATTEMPT_LOG", f"line {line_number}")
        records.append(record)
    return records


def attempt_state(records: list[dict[str, Any]], problem_key: str, signature: str) -> tuple[int, bool]:
    failures = 0
    resolved_before = False
    for record in records:
        if record.get("problem_key") != problem_key:
            continue
        if record.get("outcome") == "resolved":
            resolved_before = True
            failures = 0
        elif record.get("outcome") == "failed" and record.get("failure_signature") == signature:
            failures += 1
    return failures, resolved_before


def attempt_gate(root: Path, problem_key: str, signature: str, change_delta: str) -> str:
    manifest = validate_manifest(load_json(root / MANIFEST_PATH))
    problem_key = nonempty(problem_key, "problem_key")
    signature = nonempty(signature, "failure_signature")
    failures, resolved_before = attempt_state(load_attempts(root), problem_key, signature)
    if resolved_before:
        return "BLOCKED RECURRENCE_REVIEW_REQUIRED"
    if failures >= 1 and not change_delta.strip():
        return "BLOCKED HYPOTHESIS_DELTA_REQUIRED"
    next_attempt = failures + 1
    loop = manifest["loop_breaker"]
    if next_attempt >= loop["block_after"]:
        return "BLOCKED LOOP_THRESHOLD_FRESH_DIAGNOSIS_REQUIRED"
    if next_attempt >= loop["warn_after"]:
        return "WARN LOOP_RISK"
    return "ALLOW"


def validate_attempt_record(record: Any) -> dict[str, Any]:
    blocked(not isinstance(record, dict), "INVALID_ATTEMPT_RECORD")
    for field in ("timestamp", "work_item", "problem_key", "failure_signature", "hypothesis", "outcome", "evidence"):
        nonempty(record.get(field), field)
    blocked(record.get("outcome") not in OUTCOMES, "INVALID_ATTEMPT_OUTCOME")
    delta = record.get("change_delta", "")
    blocked(not isinstance(delta, str), "INVALID_FIELD", "change_delta")
    for forbidden in ("task_id", "thread_id", "native_session_id"):
        blocked(forbidden in record, "IDENTITY_FIELD_FORBIDDEN", forbidden)
    return record


def attempt_record(root: Path, record: dict[str, Any]) -> str:
    record = validate_attempt_record(record)
    manifest = validate_manifest(load_json(root / MANIFEST_PATH))
    records = load_attempts(root)
    failures, resolved_before = attempt_state(records, record["problem_key"], record["failure_signature"])
    if record["outcome"] == "failed" and failures >= 1 and not record.get("change_delta", "").strip():
        return "BLOCKED HYPOTHESIS_DELTA_REQUIRED"
    if record["outcome"] == "failed" and resolved_before:
        return "BLOCKED RECURRENCE"
    count = failures + 1
    loop = manifest["loop_breaker"]
    if record["outcome"] == "failed" and count >= loop["block_after"]:
        return "BLOCKED LOOP_THRESHOLD_FRESH_DIAGNOSIS_REQUIRED"
    path = root / ATTEMPTS_PATH
    mutation_boundary(root, path)
    path.parent.mkdir(parents=True, exist_ok=True)
    mutation_boundary(root, path)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")
    if record["outcome"] != "failed":
        return "RECORDED"
    if count >= loop["warn_after"]:
        return "WARN LOOP_RISK"
    return "RECORDED"


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    apply_cmd = sub.add_parser("apply")
    apply_cmd.add_argument("--root", required=True, type=Path)
    apply_cmd.add_argument("--init-git", action="store_true")
    apply_cmd.add_argument("--install-hooks", action="store_true")
    check_cmd = sub.add_parser("check")
    check_cmd.add_argument("--root", required=True, type=Path)
    check_cmd.add_argument("--ready", action="store_true")
    set_cmd = sub.add_parser("registry-set")
    set_cmd.add_argument("--root", required=True, type=Path)
    set_cmd.add_argument("--alias", required=True)
    registry_check_cmd = sub.add_parser("registry-check")
    registry_check_cmd.add_argument("--root", required=True, type=Path)
    work_cmd = sub.add_parser("work-check")
    work_cmd.add_argument("--root", required=True, type=Path)
    work_cmd.add_argument("--phase", choices=("allocate", "start", "handoff"), required=True)
    work_cmd.add_argument("--work-item", required=True, type=Path)
    snapshot_cmd = sub.add_parser("snapshot")
    snapshot_cmd.add_argument("--root", required=True, type=Path)
    snapshot_cmd.add_argument("--json", action="store_true", required=True)
    assurance_cmd = sub.add_parser("assurance-check")
    assurance_cmd.add_argument("--root", required=True, type=Path)
    assurance_cmd.add_argument("--record", required=True, type=Path)
    close_cmd = sub.add_parser("close-check")
    close_cmd.add_argument("--root", required=True, type=Path)
    close_cmd.add_argument("--work-item", required=True, type=Path)
    close_cmd.add_argument("--owner-record", required=True, type=Path)
    close_cmd.add_argument("--audit-record", required=True, type=Path)
    gate_cmd = sub.add_parser("attempt-gate")
    gate_cmd.add_argument("--root", required=True, type=Path)
    gate_cmd.add_argument("--problem-key", required=True)
    gate_cmd.add_argument("--failure-signature", required=True)
    gate_cmd.add_argument("--change-delta", default="")
    record_cmd = sub.add_parser("attempt-record")
    record_cmd.add_argument("--root", required=True, type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    try:
        root = Path(os.path.abspath(args.root))
        if args.command not in {"apply", "registry-set", "attempt-record"}:
            root = root.resolve()
        if args.command == "apply":
            result = apply_baseline(root, args.init_git, args.install_hooks)
            print(
                f"APPLY_OK created={result.get('created', 0)} "
                f"updated={result.get('updated', 0)} unchanged={result.get('unchanged', 0)}"
            )
        elif args.command == "check":
            result = check_baseline(root, args.ready)
            print(
                f"CHECK_OK mode={result['mode']} sessions={result['sessions']} "
                f"registry_aliases={result['registry_aliases']} limitations={','.join(result['limitations'])}"
            )
        elif args.command == "registry-set":
            task_id = sys.stdin.readline().strip()
            count = registry_set(root, args.alias, task_id)
            print(f"REGISTRY_OK aliases={count}")
        elif args.command == "registry-check":
            count = len(registry_guard(root))
            print(f"REGISTRY_OK aliases={count} values=hidden")
        elif args.command == "work-check":
            result = work_check(root, args.phase, args.work_item)
            allocation = (
                f" slots={result['slots']} cap={result['cap']} host_live_state=UNKNOWN"
                if result["phase"] == "allocate"
                else ""
            )
            print(
                f"WORK_CHECK_OK phase={result['phase']} work_item={result['work_item']} "
                f"scopes={result['scopes']} changed={result['changed']}{allocation} "
                "limitation=structural-and-local-evidence-only"
            )
        elif args.command == "snapshot":
            print(snapshot_json(root))
        elif args.command == "assurance-check":
            result = assurance_check(root, args.record)
            print(
                f"ASSURANCE_CHECK_OK record={result['path']} type={result['type']} verdict={result['verdict']} "
                f"limitation={ASSURANCE_LIMITATION}"
            )
        elif args.command == "close-check":
            result = close_check(root, args.work_item, args.owner_record, args.audit_record)
            print(
                f"CLOSE_CHECK_OK work_item={result['work_item']} "
                f"limitation={ASSURANCE_LIMITATION}"
            )
        elif args.command == "attempt-gate":
            result = attempt_gate(root, args.problem_key, args.failure_signature, args.change_delta)
            print(result)
            return 2 if result.startswith("BLOCKED") else 0
        elif args.command == "attempt-record":
            record = json.loads(sys.stdin.read())
            result = attempt_record(root, record)
            print(result)
            return 2 if result.startswith("BLOCKED") else 0
        return 0
    except BlockedError as exc:
        print(f"BLOCKED {exc.code}", file=sys.stderr)
        return 2
    except json.JSONDecodeError:
        print("BLOCKED MALFORMED_JSON", file=sys.stderr)
        return 2
    except Exception:
        print("BLOCKED INTERNAL_ERROR", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

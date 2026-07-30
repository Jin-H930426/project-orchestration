#!/usr/bin/env python3
"""Advisory lifecycle and staged-scope guards for project-orchestration."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath
from typing import Any

PLUGIN_NAME = "project-orchestration"
PLUGIN_VERSION = "0.2.0"
MANIFEST_PATH = ".codex/orchestration.json"
WORK_ITEMS_PATH = ".codex/work/items"
MAX_INPUT_BYTES = 1_000_000
MAX_AUTHORITY_BLOB_BYTES = 1_000_000
MAX_STAGED_PATHS = 1_024
MAX_STAGED_BLOB_BYTES = 1_000_000
MAX_STAGED_AGGREGATE_BYTES = 8_000_000
MAX_STAGED_INDEX_BYTES = 8_000_000
GIT_TIMEOUT_SECONDS = 15
WORK_ITEM_PATH_RE = re.compile(r"^\.codex/work/items/(WI-[A-Za-z0-9][A-Za-z0-9._-]{0,126})\.md$")
COMMIT_RE = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
SESSION_REF_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$")
STATUS_RE = re.compile(r"^[a-z][a-z0-9-]*$")
WINDOWS_DEVICE_RE = re.compile(
    r"(?i)^(?:CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³]|CONIN\$|CONOUT\$)(?:\..*)?$"
)
NATIVE_ID_RE = re.compile(
    rb"(?i)(?<![0-9a-f])[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}(?![0-9a-f])"
)


class GuardError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def require(condition: bool, code: str) -> None:
    if not condition:
        raise GuardError(code)


def git_environment() -> dict[str, str]:
    environment = {
        name: value for name, value in os.environ.items() if not name.startswith("GIT_")
    }
    if "GIT_INDEX_FILE" in os.environ:
        environment["GIT_INDEX_FILE"] = os.environ["GIT_INDEX_FILE"]
    environment.update(
        {
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_NO_REPLACE_OBJECTS": "1",
            "GIT_TERMINAL_PROMPT": "0",
        }
    )
    return environment


def git(
    root: Path,
    *args: str,
    binary: bool = False,
    input_data: bytes | None = None,
) -> subprocess.CompletedProcess[Any]:
    try:
        return subprocess.run(
            ["git", "-c", "core.fsmonitor=false", "-C", str(root), *args],
            capture_output=True,
            text=not binary,
            input=input_data,
            env=git_environment(),
            timeout=GIT_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        raise GuardError("GIT_TIMEOUT") from None
    except OSError:
        raise GuardError("GIT_EXECUTION_FAILED") from None


def git_context(cwd: str | None = None) -> tuple[Path, str, str]:
    start = Path(cwd) if cwd else Path.cwd()
    result = git(start, "rev-parse", "--show-toplevel", "HEAD", "--abbrev-ref=strict", "HEAD")
    lines = result.stdout.splitlines() if result.returncode == 0 else []
    require(
        len(lines) == 3
        and COMMIT_RE.fullmatch(lines[1]) is not None
        and lines[2] != "HEAD"
        and safe_token(lines[2], 160),
        "GIT_AUTHORITY_MISSING",
    )
    root = Path(lines[0]).resolve()
    try:
        start.resolve().relative_to(root)
    except ValueError as exc:
        raise GuardError("GIT_ROOT_MISMATCH") from exc
    return root, lines[1], lines[2]


def current_head_branch(root: Path) -> tuple[str, str]:
    _, head, branch = git_context(str(root))
    return head, branch


def safe_token(value: str, limit: int) -> bool:
    return bool(value) and len(value) <= limit and all(char.isprintable() for char in value) and not NATIVE_ID_RE.search(
        value.encode("utf-8", errors="ignore")
    )


def safe_label(value: str, limit: int) -> bool:
    return safe_token(value, limit) and not value.startswith(("/", "~")) and "\\" not in value and "/" not in value and re.match(
        r"^[A-Za-z]:", value
    ) is None


def committed_authority_blobs(root: Path, revision: str) -> dict[str, bytes]:
    tree = git(
        root,
        "ls-tree",
        "-r",
        "-z",
        revision,
        "--",
        MANIFEST_PATH,
        WORK_ITEMS_PATH,
        binary=True,
    )
    require(tree.returncode == 0 and tree.stdout.endswith(b"\0"), "AUTHORITY_UNREADABLE")
    entries: list[tuple[str, str]] = []
    for raw in [value for value in tree.stdout.split(b"\0") if value]:
        require(b"\t" in raw, "AUTHORITY_UNREADABLE")
        metadata, listed = raw.split(b"\t", 1)
        fields = metadata.split()
        try:
            relative = listed.decode("utf-8")
            oid = fields[2].decode("ascii")
        except (UnicodeDecodeError, IndexError) as exc:
            raise GuardError("AUTHORITY_UNREADABLE") from exc
        require(
            len(fields) == 3
            and fields[0] in {b"100644", b"100755"}
            and fields[1] == b"blob"
            and (relative == MANIFEST_PATH or relative.startswith(WORK_ITEMS_PATH + "/")),
            "AUTHORITY_UNREADABLE",
        )
        entries.append((relative, oid))
    require(sum(relative == MANIFEST_PATH for relative, _ in entries) == 1, "MANIFEST_INVALID")

    batch = git(
        root,
        "cat-file",
        "--batch",
        binary=True,
        input_data=b"".join(oid.encode("ascii") + b"\n" for _, oid in entries),
    )
    require(batch.returncode == 0, "AUTHORITY_UNREADABLE")
    offset = 0
    blobs: dict[str, bytes] = {}
    for relative, expected_oid in entries:
        header_end = batch.stdout.find(b"\n", offset)
        require(header_end >= 0, "AUTHORITY_UNREADABLE")
        header = batch.stdout[offset:header_end].split()
        require(
            len(header) == 3
            and header[0].decode("ascii", errors="ignore") == expected_oid
            and header[1] == b"blob"
            and header[2].isdigit(),
            "AUTHORITY_UNREADABLE",
        )
        size = int(header[2])
        require(size <= MAX_AUTHORITY_BLOB_BYTES, "AUTHORITY_UNREADABLE")
        start = header_end + 1
        end = start + size
        require(end < len(batch.stdout) and batch.stdout[end : end + 1] == b"\n", "AUTHORITY_UNREADABLE")
        content = batch.stdout[start:end]
        require(not NATIVE_ID_RE.search(content), "AUTHORITY_UNREADABLE")
        blobs[relative] = content
        offset = end + 1
    require(offset == len(batch.stdout), "AUTHORITY_UNREADABLE")
    return blobs


def normalized_path(value: Any, code: str = "PATH_INVALID") -> str:
    require(isinstance(value, str) and bool(value) and value == value.strip(), code)
    require(
        "\\" not in value
        and ":" not in value
        and not value.startswith(("/", "~"))
        and re.match(r"^[A-Za-z]:", value) is None
        and not any(char in value for char in "*?[]{}")
        and all(char.isprintable() for char in value),
        code,
    )
    path = PurePosixPath(value.removeprefix("./"))
    require(
        ".." not in path.parts
        and str(path) not in {"", "."}
        and all(not part.endswith((".", " ")) and WINDOWS_DEVICE_RE.fullmatch(part) is None for part in path.parts),
        code,
    )
    normalized = path.as_posix().rstrip("/")
    require(normalized == value.removeprefix("./").rstrip("/"), code)
    return normalized


def path_in_scope(path: str, scope: str, *, platform: str | None = None) -> bool:
    platform_name = os.name if platform is None else platform
    candidate = (path.casefold() if platform_name == "nt" else path).rstrip("/")
    parent = (scope.casefold() if platform_name == "nt" else scope).rstrip("/")
    return candidate == parent or candidate.startswith(parent + "/")


def reserved_path(path: str) -> bool:
    folded = path.casefold()
    return (
        folded == ".codex/session-registry.local.json"
        or folded == ".wiki/.sessions"
        or folded.startswith(".wiki/.sessions/")
        or (
            folded.startswith(".codex/.session-registry.")
            and folded.endswith(".tmp")
        )
    )


def validate_targets(root: Path, values: list[str]) -> list[str]:
    require(bool(values), "PATCH_PATHLESS")
    targets: list[str] = []
    for value in values:
        relative = normalized_path(value)
        require(not reserved_path(relative), "RESERVED_LOCAL_PATH")
        lexical = root.resolve().joinpath(*PurePosixPath(relative).parts)
        try:
            resolved = lexical.resolve(strict=False)
            resolved.relative_to(root.resolve())
        except (OSError, RuntimeError, ValueError) as exc:
            raise GuardError("PATH_OUTSIDE_ROOT") from exc
        require(resolved == lexical, "PATH_SYMLINK_ESCAPE")
        if relative not in targets:
            targets.append(relative)
    return targets


def work_item(text: str, relative: str) -> dict[str, Any]:
    path_match = WORK_ITEM_PATH_RE.fullmatch(relative)
    headings = [line for line in text.splitlines() if line.startswith("# Work Item ")]
    heading = re.fullmatch(r"# Work Item (WI-[^:\r\n]+):[ \t]+(.+)", headings[0]) if len(headings) == 1 else None
    require(path_match is not None and heading is not None and heading.group(1) == path_match.group(1), "WORK_ITEM_INVALID")
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
        require(len(values) == 1 and safe_token(values[0], 240), "WORK_ITEM_INVALID")
        fields[field] = values[0]
    require(
        fields["Status"] == "active"
        and re.fullmatch(r"P[0-9]{3}", fields["Project"]) is not None
        and re.fullmatch(r"P[0-9]{3}-G[0-9]{3}", fields["Requirement"]) is not None
        and fields["Requirement"].startswith(fields["Project"] + "-")
        and SESSION_REF_RE.fullmatch(fields["Owner Session Ref"]) is not None
        and COMMIT_RE.fullmatch(fields["Source Commit"]) is not None,
        "WORK_ITEM_INVALID",
    )
    evidence = normalized_path(fields["Evidence Path"], "WORK_ITEM_INVALID")
    lines = text.splitlines()
    headings_at = [index for index, line in enumerate(lines) if line == "## Write Scope"]
    require(len(headings_at) == 1, "WORK_ITEM_INVALID")
    start = headings_at[0] + 1
    end = next((index for index in range(start, len(lines)) if lines[index].startswith("## ")), len(lines))
    scope_lines = [line for line in lines[start:end] if line.strip()]
    scopes: list[str] = []
    for line in scope_lines:
        match = re.fullmatch(r"- `([^`]+)`", line)
        require(match is not None, "WORK_ITEM_INVALID")
        scope = normalized_path(match.group(1), "WORK_ITEM_INVALID")
        require(not any(path_in_scope(scope, other) or path_in_scope(other, scope) for other in scopes), "WORK_ITEM_INVALID")
        scopes.append(scope)
    require(bool(scopes), "WORK_ITEM_INVALID")
    require(any(path_in_scope(evidence, scope) for scope in scopes), "WORK_ITEM_INVALID")
    return {"relative": relative, "branch": fields["Branch"], "scopes": scopes}


def active_work_items(root: Path, revision: str, blobs: dict[str, bytes] | None = None) -> list[dict[str, Any]]:
    blobs = blobs if blobs is not None else committed_authority_blobs(root, revision)
    items: list[dict[str, Any]] = []
    for relative, content in sorted(blobs.items()):
        if not relative.startswith(WORK_ITEMS_PATH + "/"):
            continue
        if not relative.endswith(".md"):
            continue
        require(WORK_ITEM_PATH_RE.fullmatch(relative) is not None, "WORK_ITEM_INVALID")
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise GuardError("WORK_ITEM_INVALID") from exc
        statuses = re.findall(r"^Status:[ \t]*(.*?)[ \t]*$", text, flags=re.MULTILINE)
        require(len(statuses) == 1 and STATUS_RE.fullmatch(statuses[0]) is not None, "WORK_ITEM_INVALID")
        if statuses[0] == "active":
            items.append(work_item(text, relative))
    return items


def committed_manifest(root: Path, revision: str, content: bytes | None = None) -> dict[str, Any]:
    try:
        raw = content if content is not None else committed_authority_blobs(root, revision)[MANIFEST_PATH]
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GuardError("MANIFEST_INVALID") from exc
    require(isinstance(data, dict), "MANIFEST_INVALID")
    tooling = data.get("tooling")
    project = data.get("project")
    sessions = data.get("sessions")
    require(
        isinstance(tooling, dict)
        and tooling.get("plugin") == PLUGIN_NAME
        and tooling.get("version") == PLUGIN_VERSION
        and isinstance(project, dict)
        and safe_label(project.get("name", ""), 120)
        and isinstance(sessions, list),
        "MANIFEST_INVALID",
    )
    parsed_sessions: list[dict[str, Any]] = []
    for session in sessions:
        require(isinstance(session, dict), "MANIFEST_INVALID")
        branch = session.get("branch")
        scopes = session.get("write_scope")
        require(
            session.get("persistent") is True
            and isinstance(branch, str)
            and safe_token(branch, 160)
            and isinstance(scopes, list)
            and bool(scopes),
            "MANIFEST_INVALID",
        )
        parsed_sessions.append(
            {"branch": branch, "scopes": [normalized_path(scope, "MANIFEST_INVALID") for scope in scopes]}
        )
    return {"project": project["name"], "sessions": parsed_sessions}


def authority(
    root: Path,
    targets: list[str] | None = None,
    head: str | None = None,
    branch: str | None = None,
) -> dict[str, Any]:
    if head is None or branch is None:
        head, branch = current_head_branch(root)
    blobs = committed_authority_blobs(root, head)
    manifest = committed_manifest(root, head, blobs[MANIFEST_PATH])
    items = [item for item in active_work_items(root, head, blobs) if item["branch"] == branch]
    require(len(items) <= 1, "AUTHORITY_AMBIGUOUS")
    if items:
        item = items[0]
        if targets is not None:
            require(all(any(path_in_scope(path, scope) for scope in item["scopes"]) for path in targets), "OUTSIDE_WRITE_SCOPE")
        return {
            "head": head,
            "branch": branch,
            "kind": "active-work-item",
            "work_item": item["relative"],
            "scopes": item["scopes"],
            "project": manifest["project"],
        }
    if targets is not None:
        require(not any(path_in_scope(path, ".wiki") for path in targets), "WIKI_WORK_ITEM_REQUIRED")
    sessions = [
        session
        for session in manifest["sessions"]
        if session["branch"] == branch
        and (targets is None or all(any(path_in_scope(path, scope) for scope in session["scopes"]) for path in targets))
    ]
    require(len(sessions) == 1, "AUTHORITY_AMBIGUOUS" if len(sessions) > 1 else "AUTHORITY_MISSING")
    return {
        "head": head,
        "branch": branch,
        "kind": "persistent-session",
        "work_item": "UNKNOWN",
        "scopes": sessions[0]["scopes"],
        "project": manifest["project"],
    }


def extract_patch_targets(command: str) -> list[str]:
    require(bool(command) and len(command.encode("utf-8")) <= MAX_INPUT_BYTES, "PATCH_MALFORMED")
    require(not NATIVE_ID_RE.search(command.encode("utf-8", errors="ignore")), "NATIVE_IDENTITY")
    lines = command.splitlines()
    require(len(lines) >= 2 and lines[0] == "*** Begin Patch" and lines[-1] == "*** End Patch", "PATCH_MALFORMED")
    targets: list[str] = []
    operation: str | None = None
    moved = False
    for line in lines[1:-1]:
        match = re.fullmatch(r"\*\*\* (Add|Update|Delete) File: (.+)", line)
        if match:
            operation = match.group(1)
            moved = False
            targets.append(match.group(2))
            continue
        move = re.fullmatch(r"\*\*\* Move to: (.+)", line)
        if move:
            require(operation == "Update" and not moved, "PATCH_MALFORMED")
            targets.append(move.group(1))
            moved = True
            continue
        require(not line.startswith("*** ") or line == "*** End of File", "PATCH_MALFORMED")
    require(bool(targets), "PATCH_PATHLESS")
    return targets


def pre_tool_use(payload: Any) -> str | None:
    try:
        require(isinstance(payload, dict), "HOOK_INPUT_INVALID")
        require(payload.get("hook_event_name") == "PreToolUse" and payload.get("tool_name") == "apply_patch", "HOOK_INPUT_INVALID")
        tool_input = payload.get("tool_input")
        require(isinstance(tool_input, dict) and isinstance(tool_input.get("command"), str), "HOOK_INPUT_INVALID")
        root, head, branch = git_context(payload.get("cwd") if isinstance(payload.get("cwd"), str) else None)
        targets = validate_targets(root, extract_patch_targets(tool_input["command"]))
        authority(root, targets, head, branch)
        return None
    except GuardError as exc:
        return exc.code
    except Exception:
        return "GUARD_FAILURE"


def wiki_baseline(root: Path, head: str) -> tuple[str, str]:
    result = git(
        root,
        "rev-parse",
        "--revs-only",
        "refs/heads/main^{commit}",
        "refs/heads/main:.wiki",
        f"{head}:.wiki",
    )
    lines = result.stdout.splitlines() if result.returncode == 0 else []
    revision = lines[0][:12] if lines and COMMIT_RE.fullmatch(lines[0]) is not None else "UNKNOWN"
    if len(lines) != 3 or any(COMMIT_RE.fullmatch(value) is None for value in lines):
        return revision, "UNKNOWN"
    return revision, "MATCH" if lines[1] == lines[2] else "SOURCE_DRIFT"


def session_context(payload: Any) -> str:
    try:
        require(isinstance(payload, dict), "HOOK_INPUT_INVALID")
        require(payload.get("hook_event_name") == "SessionStart", "HOOK_INPUT_INVALID")
        require(payload.get("source") in {"startup", "resume", "clear", "compact"}, "HOOK_INPUT_INVALID")
        root, head, branch = git_context(payload.get("cwd") if isinstance(payload.get("cwd"), str) else None)
        selected = authority(root, head=head, branch=branch)
        revision, wiki = wiki_baseline(root, selected["head"])
        command = (
            "python skills/bootstrap-project/scripts/bootstrap_project.py work-check --root . --phase start "
            f"--work-item {selected['work_item']}"
            if selected["work_item"] != "UNKNOWN"
            else "python skills/bootstrap-project/scripts/bootstrap_project.py check --root ."
        )
        lines = [
            "PROJECT_ORCHESTRATION_CONTEXT",
            f"project={selected['project']}",
            f"branch={selected['branch']}",
            f"authority={selected['kind']}",
            f"work_item={selected['work_item']}",
            f"scope_count={len(selected['scopes'])}",
            f"wiki_baseline={revision}",
            f"wiki_tree={wiki}",
            f"authoritative_command={command}",
            "limitations=advisory-hooks;structural-only;semantic-and-audit-closure-not-proven",
        ]
        if wiki == "SOURCE_DRIFT":
            lines.append("wiki_action=request-knowledge-steward-readback")
        output = "\n".join(lines)
        require(len(output.encode("utf-8")) <= 1600 and not NATIVE_ID_RE.search(output.encode("utf-8")), "OUTPUT_UNSAFE")
        return output
    except GuardError as exc:
        return (
            "PROJECT_ORCHESTRATION_CONTEXT\nproject=UNKNOWN\nbranch=UNKNOWN\nauthority=UNKNOWN\n"
            "work_item=UNKNOWN\nscope_count=0\nwiki_baseline=UNKNOWN\nwiki_tree=UNKNOWN\n"
            "authoritative_command=work-check-required\n"
            "limitations=advisory-hooks;structural-only;semantic-and-audit-closure-not-proven\n"
            f"warning=UNKNOWN_{exc.code}"
        )
    except Exception:
        return (
            "PROJECT_ORCHESTRATION_CONTEXT\nproject=UNKNOWN\nbranch=UNKNOWN\nauthority=UNKNOWN\n"
            "work_item=UNKNOWN\nscope_count=0\nwiki_baseline=UNKNOWN\nwiki_tree=UNKNOWN\n"
            "authoritative_command=work-check-required\n"
            "limitations=advisory-hooks;structural-only;semantic-and-audit-closure-not-proven\n"
            "warning=UNKNOWN_GUARD_FAILURE"
        )


def staged_paths(root: Path) -> list[tuple[str, str]]:
    result = git(
        root,
        "diff",
        "--cached",
        "--name-status",
        "--no-renames",
        "--diff-filter=ACDMRT",
        "-z",
        binary=True,
    )
    require(result.returncode == 0 and len(result.stdout) <= MAX_INPUT_BYTES, "STAGED_DIFF_INVALID")
    if not result.stdout:
        return []
    require(result.stdout.endswith(b"\0"), "STAGED_DIFF_INVALID")
    values = result.stdout[:-1].split(b"\0")
    require(len(values) % 2 == 0, "STAGED_DIFF_INVALID")
    entries: list[tuple[str, str]] = []
    seen: set[str] = set()
    for index in range(0, len(values), 2):
        try:
            status = values[index].decode("ascii")
            relative = values[index + 1].decode("utf-8")
        except UnicodeDecodeError as exc:
            raise GuardError("STAGED_DIFF_INVALID") from exc
        require(status in {"A", "C", "D", "M", "R", "T"} and relative not in seen, "STAGED_DIFF_INVALID")
        seen.add(relative)
        entries.append((status, relative))
    require(len(entries) <= MAX_STAGED_PATHS, "STAGED_PATH_LIMIT")
    return entries


def contains_native_identity(content: bytes) -> bool:
    if NATIVE_ID_RE.search(content):
        return True
    if content.startswith((b"\xff\xfe", b"\xfe\xff")):
        try:
            decoded = content.decode("utf-16")
        except UnicodeDecodeError:
            raise GuardError("STAGED_ENCODING_INVALID") from None
        return NATIVE_ID_RE.search(decoded.encode("utf-8")) is not None
    return False


def staged_identity_guard(root: Path, entries: list[tuple[str, str]]) -> None:
    present = [relative for status, relative in entries if status != "D"]
    if not present:
        return
    index = git(
        root,
        "ls-files",
        "--stage",
        "-z",
        binary=True,
    )
    require(
        index.returncode == 0
        and len(index.stdout) <= MAX_STAGED_INDEX_BYTES
        and index.stdout.endswith(b"\0"),
        "STAGED_DIFF_INVALID",
    )
    by_path: dict[str, str] = {}
    for value in [item for item in index.stdout.split(b"\0") if item]:
        require(b"\t" in value, "STAGED_DIFF_INVALID")
        metadata, listed = value.split(b"\t", 1)
        fields = metadata.split()
        try:
            relative = listed.decode("utf-8")
            oid = fields[1].decode("ascii")
        except (UnicodeDecodeError, IndexError) as exc:
            raise GuardError("STAGED_DIFF_INVALID") from exc
        if relative not in present:
            continue
        require(
            len(fields) == 3
            and fields[0] in {b"100644", b"100755"}
            and fields[2] == b"0"
            and relative not in by_path,
            "STAGED_NONREGULAR",
        )
        by_path[relative] = oid
    require(set(by_path) == set(present), "STAGED_DIFF_INVALID")

    for relative in present:
        require(not contains_native_identity(relative.encode("utf-8")), "NATIVE_IDENTITY")
    oids = list(dict.fromkeys(by_path[relative] for relative in present))
    batch_input = b"".join(oid.encode("ascii") + b"\n" for oid in oids)
    sizes = git(root, "cat-file", "--batch-check", binary=True, input_data=batch_input)
    require(sizes.returncode == 0, "STAGED_DIFF_INVALID")
    size_by_oid: dict[str, int] = {}
    lines = sizes.stdout.splitlines()
    require(len(lines) == len(oids), "STAGED_DIFF_INVALID")
    for expected_oid, line in zip(oids, lines, strict=True):
        fields = line.split()
        require(
            len(fields) == 3
            and fields[0].decode("ascii", errors="ignore") == expected_oid
            and fields[1] == b"blob"
            and fields[2].isdigit(),
            "STAGED_DIFF_INVALID",
        )
        size = int(fields[2])
        require(size <= MAX_STAGED_BLOB_BYTES, "STAGED_BLOB_LIMIT")
        size_by_oid[expected_oid] = size
    require(
        sum(size_by_oid[by_path[relative]] for relative in present)
        <= MAX_STAGED_AGGREGATE_BYTES,
        "STAGED_AGGREGATE_LIMIT",
    )

    blobs = git(root, "cat-file", "--batch", binary=True, input_data=batch_input)
    require(blobs.returncode == 0, "STAGED_DIFF_INVALID")
    offset = 0
    for expected_oid in oids:
        header_end = blobs.stdout.find(b"\n", offset)
        require(header_end >= 0, "STAGED_DIFF_INVALID")
        header = blobs.stdout[offset:header_end].split()
        require(
            len(header) == 3
            and header[0].decode("ascii", errors="ignore") == expected_oid
            and header[1] == b"blob"
            and header[2].isdigit()
            and int(header[2]) == size_by_oid[expected_oid],
            "STAGED_DIFF_INVALID",
        )
        start = header_end + 1
        end = start + size_by_oid[expected_oid]
        require(end < len(blobs.stdout) and blobs.stdout[end : end + 1] == b"\n", "STAGED_DIFF_INVALID")
        require(not contains_native_identity(blobs.stdout[start:end]), "NATIVE_IDENTITY")
        offset = end + 1
    require(offset == len(blobs.stdout), "STAGED_DIFF_INVALID")


def pre_commit(root: Path | None = None) -> None:
    root, head, branch = git_context(str(root.resolve()) if root else None)
    entries = staged_paths(root)
    if not entries:
        return
    targets = validate_targets(root, [relative for _, relative in entries])
    authority(root, targets, head, branch)
    staged_identity_guard(
        root,
        [(status, relative) for (status, _), relative in zip(entries, targets, strict=True)],
    )
    whitespace = git(root, "diff", "--cached", "--check")
    require(whitespace.returncode == 0, "STAGED_WHITESPACE")


def read_payload() -> Any:
    raw = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
    require(len(raw) <= MAX_INPUT_BYTES, "HOOK_INPUT_INVALID")
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GuardError("HOOK_INPUT_INVALID") from exc


def deny(code: str) -> None:
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": f"BLOCKED {code}",
                }
            },
            separators=(",", ":"),
        )
    )


def main(argv: list[str] | None = None) -> int:
    command = (argv or sys.argv[1:])[0] if (argv or sys.argv[1:]) else ""
    if command == "session-start":
        try:
            payload = read_payload()
        except GuardError as exc:
            payload = {"hook_event_name": "invalid", "error": exc.code}
        print(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "SessionStart",
                        "additionalContext": session_context(payload),
                    }
                },
                separators=(",", ":"),
            )
        )
        return 0
    if command == "pre-tool-use":
        try:
            payload = read_payload()
            code = pre_tool_use(payload)
        except GuardError as exc:
            code = exc.code
        if code:
            deny(code)
        return 0
    if command == "pre-commit":
        try:
            pre_commit()
            return 0
        except GuardError as exc:
            print(f"BLOCKED {exc.code}", file=sys.stderr)
            return 1
        except Exception:
            print("BLOCKED GUARD_FAILURE", file=sys.stderr)
            return 1
    print("BLOCKED INVALID_MODE", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

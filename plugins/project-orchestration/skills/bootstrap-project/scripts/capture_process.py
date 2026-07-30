from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


def positive_number(value: str) -> float:
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("must be a positive number")
    return number


def parse_args(argv: list[str]) -> tuple[Path, float, list[str]]:
    parser = argparse.ArgumentParser(prog="capture_process.py")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--timeout-seconds", required=True, type=positive_number)
    try:
        separator = argv.index("--")
    except ValueError:
        parser.error("literal command must follow --")
    args = parser.parse_args(argv[:separator])
    command = argv[separator + 1 :]
    if not command:
        parser.error("executable is required after --")
    return args.output_dir, args.timeout_seconds, command


def durable_write_new(path: Path, content: bytes) -> None:
    with path.open("xb") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())


def publish_terminal(output_dir: Path, terminal: dict[str, Any]) -> None:
    temporary = output_dir / "terminal.json.tmp"
    durable_write_new(
        temporary,
        (json.dumps(terminal, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8"),
    )
    os.replace(temporary, output_dir / "terminal.json")


def read_terminal(output_dir: Path) -> dict[str, Any]:
    try:
        terminal = json.loads((output_dir / "terminal.json").read_bytes())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise ValueError("invalid terminal record") from None
    if (
        not isinstance(terminal, dict)
        or set(terminal) != {"exit_code", "state"}
        or type(terminal["exit_code"]) is not int
        or terminal["state"] not in {"completed", "timeout"}
        or (terminal["state"] == "timeout" and terminal["exit_code"] != 124)
    ):
        raise ValueError("invalid terminal record")
    return terminal


def capture(output_dir: Path, timeout_seconds: float, command: list[str]) -> int:
    if not command or not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError("invalid capture arguments")
    output_dir.mkdir(parents=True, exist_ok=False)
    try:
        completed = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_seconds,
            shell=False,
        )
        stdout = completed.stdout
        stderr = completed.stderr
        terminal = {"exit_code": completed.returncode, "state": "completed"}
    except subprocess.TimeoutExpired as error:
        stdout = error.stdout or b""
        stderr = error.stderr or b""
        terminal = {"exit_code": 124, "state": "timeout"}
    durable_write_new(output_dir / "stdout.bin", stdout)
    durable_write_new(output_dir / "stderr.bin", stderr)
    publish_terminal(output_dir, terminal)
    return read_terminal(output_dir)["exit_code"]


def main(argv: list[str] | None = None) -> int:
    output_dir, timeout_seconds, command = parse_args(argv or sys.argv[1:])
    try:
        return capture(output_dir, timeout_seconds, command)
    except FileExistsError:
        print("capture_process: output directory already exists", file=sys.stderr)
    except (OSError, ValueError):
        print("capture_process: capture failed", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

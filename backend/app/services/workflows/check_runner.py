"""Deterministic execution of persisted workflow check contracts."""
from __future__ import annotations

import asyncio
import json
import os
import signal
from dataclasses import asdict, dataclass
from pathlib import Path

_MAX_OUTPUT_BYTES = 16_000


@dataclass(frozen=True)
class CheckResult:
    """One recorded command's bounded execution outcome."""

    command: str
    cwd: str
    passed: bool
    exit_code: int | None
    timed_out: bool
    stdout: str
    stderr: str


@dataclass(frozen=True)
class CheckReport:
    """All deterministic check outcomes for one coder round."""

    results: list[CheckResult]

    def passed(self) -> bool:
        """Return whether every recorded command completed successfully."""
        return all(result.passed for result in self.results)

    def to_json(self) -> str:
        """Render this report as a stable, structured artifact."""
        return json.dumps(
            {"version": 1, "results": [asdict(item) for item in self.results]},
            indent=2,
        ) + "\n"


def _failed_contract(detail: str) -> CheckReport:
    """Return one failed result for a contract that cannot be executed."""
    return CheckReport([
        CheckResult(
            command="(check contract)",
            cwd=".",
            passed=False,
            exit_code=None,
            timed_out=False,
            stdout="",
            stderr=detail,
        )
    ])


def _contract_commands(contract_path: Path) -> list[dict] | None:
    """Read the version-one command list, rejecting malformed artifacts."""
    try:
        data = json.loads(contract_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    commands = data.get("commands") if isinstance(data, dict) else None
    if (
        not isinstance(data, dict)
        or data.get("version") != 1
        or not isinstance(commands, list)
    ):
        return None
    if not all(isinstance(command, dict) for command in commands):
        return None
    return commands


def _command_directory(workspace: Path, command: dict) -> Path | None:
    """Resolve a command's relative directory without leaving ``workspace``."""
    cwd = command.get("cwd")
    if not isinstance(cwd, str) or not cwd:
        return None
    candidate = (workspace / cwd).resolve()
    try:
        candidate.relative_to(workspace)
    except ValueError:
        return None
    return candidate if candidate.is_dir() else None


async def _capture(stream: asyncio.StreamReader) -> str:
    """Read a process stream while retaining only a bounded UTF-8 excerpt."""
    captured = bytearray()
    truncated = False
    while chunk := await stream.read(4096):
        if len(captured) < _MAX_OUTPUT_BYTES:
            captured.extend(chunk[:_MAX_OUTPUT_BYTES - len(captured)])
        truncated |= len(captured) == _MAX_OUTPUT_BYTES
    suffix = b"\n...[output truncated]" if truncated else b""
    return (bytes(captured) + suffix).decode("utf-8", errors="replace")


async def _run_command(command: dict, directory: Path) -> CheckResult:
    """Execute one shell command with a timeout and bounded output."""
    text = command.get("command")
    timeout = command.get("timeout_seconds")
    if (
        not isinstance(text, str)
        or not text
        or not isinstance(timeout, int)
        or isinstance(timeout, bool)
        or timeout <= 0
    ):
        return _failed_contract("Malformed check command.").results[0]
    try:
        process = await asyncio.create_subprocess_shell(
            text,
            cwd=directory,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
    except OSError as error:
        return CheckResult(
            text, str(directory), False, None, False, "", str(error)
        )
    assert process.stdout is not None
    assert process.stderr is not None
    stdout_task = asyncio.create_task(_capture(process.stdout))
    stderr_task = asyncio.create_task(_capture(process.stderr))
    timed_out = False
    try:
        await asyncio.wait_for(process.wait(), timeout=timeout)
    except TimeoutError:
        timed_out = True
        os.killpg(process.pid, signal.SIGTERM)
        await process.wait()
    stdout, stderr = await asyncio.gather(stdout_task, stderr_task)
    exit_code = process.returncode
    return CheckResult(
        command=text,
        cwd=str(directory),
        passed=not timed_out and exit_code == 0,
        exit_code=exit_code,
        timed_out=timed_out,
        stdout=stdout,
        stderr=stderr,
    )


async def run_recorded_checks(workspace: str, artifact_dir: str) -> CheckReport:
    """Run the persisted check contract once, without agent participation.

    Invalid contracts and directories produce failed evidence rather than
    raising. Legacy runs without an artifact directory have no contract.
    """
    root = Path(workspace).resolve()
    if not artifact_dir:
        return CheckReport([])
    contract_path = root / artifact_dir / "check-contract.json"
    if not contract_path.is_file():
        return CheckReport([])
    commands = _contract_commands(contract_path)
    if commands is None:
        return _failed_contract("Malformed or missing check-contract.json.")
    results: list[CheckResult] = []
    for command in commands:
        directory = _command_directory(root, command)
        if directory is None:
            results.extend(
                _failed_contract("Check working directory is invalid.").results
            )
            continue
        results.append(await _run_command(command, directory))
    return CheckReport(results)

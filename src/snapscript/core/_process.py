"""Bound process capture without buffering arbitrary child output in memory."""

import os
from pathlib import Path
import subprocess
import tempfile
import time
from typing import BinaryIO


class CaptureLimitExceeded(Exception):
    def __init__(self, stdout: str, stderr: str) -> None:
        super().__init__("Execution output exceeded the capture limit")
        self.stdout = stdout
        self.stderr = stderr


def run_process(
    command: list[str], *, timeout: float, max_capture_bytes: int = 65536,
    cwd: Path | None = None, env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        with subprocess.Popen(command, cwd=cwd, env=env, stdout=stdout, stderr=stderr) as process:
            failure = _wait(process, stdout, stderr, timeout, max_capture_bytes)
            if failure:
                process.kill()
                process.wait()
            output, error = _read(stdout, max_capture_bytes), _read(stderr, max_capture_bytes)
            if failure == "timeout":
                raise subprocess.TimeoutExpired(command, timeout, output=output, stderr=error)
            if failure == "capture":
                raise CaptureLimitExceeded(output, error)
            return subprocess.CompletedProcess(command, process.returncode, output, error)


def _wait(
    process: subprocess.Popen, stdout: BinaryIO, stderr: BinaryIO,
    timeout: float, limit: int,
) -> str | None:
    deadline = time.monotonic() + timeout
    while True:
        if any(os.fstat(handle.fileno()).st_size > limit for handle in (stdout, stderr)):
            return "capture"
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return "timeout"
        try:
            process.wait(timeout=min(remaining, 0.05))
        except subprocess.TimeoutExpired:
            continue
        return "capture" if any(
            os.fstat(handle.fileno()).st_size > limit for handle in (stdout, stderr)
        ) else None


def _read(handle: BinaryIO, limit: int) -> str:
    handle.seek(0)
    return handle.read(limit).decode("utf-8", errors="replace")

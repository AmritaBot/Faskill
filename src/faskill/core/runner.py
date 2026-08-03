"""Script runner abstraction for sandboxed execution.

This module defines the ``Runner`` abstract base class and a default
``HostRunner`` that executes scripts directly on the host machine.

The runner abstraction allows swapping in sandboxed backends (Docker,
Firecracker, gVisor, etc.) without changing the rest of the codebase.

Usage::

    # Default: bare host execution (warns once)
    executor = ScriptExecutor(runner=HostRunner())

    # Custom sandbox runner
    executor = ScriptExecutor(runner=DockerRunner(image="python:3.12"))

Classes:
    Runner: Abstract base class for script execution backends
    HostRunner: Default runner — runs scripts directly on the host
"""

from __future__ import annotations

import logging
import signal as signal_module
import subprocess
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict

logger = logging.getLogger(__name__)


class Runner(ABC):
    """Abstract base class for script execution backends.

    Subclasses implement ``run()`` to execute a script via a specific
    environment (host, Docker, Firecracker, etc.).

    Subclassing guide::

        class MyRunner(Runner):
            def run(self, interpreter, script_path, arguments_json, env, cwd, timeout):
                # launch script in your sandbox
                return (exit_code, stdout, stderr, signal_name, signal_number)
    """

    @abstractmethod
    def run(
        self,
        interpreter: str,
        script_path: Path,
        arguments_json: str,
        env: Dict[str, str],
        cwd: Path,
        timeout: int,
    ) -> tuple[int, str, str, str | None, int | None]:
        """Execute a script.

        Args:
            interpreter: Interpreter command (e.g. ``"python3"``).
            script_path: Absolute path to the script file.
            arguments_json: JSON-serialised arguments to pass via stdin.
            env: Environment variables dict.
            cwd: Working directory.
            timeout: Max execution time in seconds.

        Returns:
            Tuple of ``(exit_code, stdout, stderr, signal_name, signal_number)``.

        Raises:
            subprocess.TimeoutExpired: If execution exceeds timeout.
            OSError: If the interpreter cannot be launched.
        """
        ...


class HostRunner(Runner):
    """Run scripts directly on the host machine via ``subprocess.run``.

    **Security note**: This runner executes scripts on the bare host with
    the same privileges as the calling process.  A one-time warning is
    logged on first use.  For untrusted scripts, use a sandboxed runner
    (Docker, etc.).

    The warning is emitted only once per process lifetime (tracked by a
    class-level ``_warned`` flag).
    """

    _warned: bool = False

    def run(
        self,
        interpreter: str,
        script_path: Path,
        arguments_json: str,
        env: Dict[str, str],
        cwd: Path,
        timeout: int,
    ) -> tuple[int, str, str, str | None, int | None]:
        """Execute a script via ``subprocess.run`` on the host.

        Emits a one-time security warning on first invocation.
        """
        if not HostRunner._warned:
            logger.warning(
                "HostRunner: executing scripts directly on the host machine. "
                "This is UNSAFE for untrusted scripts. "
                "Consider using a sandboxed runner (Docker, Firecracker, etc.) "
                "for production deployments. "
                "This warning appears once per process."
            )
            HostRunner._warned = True

        try:
            result = subprocess.run(
                [interpreter, str(script_path)],
                input=arguments_json,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=str(cwd),
                shell=False,  # CRITICAL: command injection prevention
                check=False,
                env=env,
            )

            signal_name: str | None = None
            signal_number: int | None = None

            if result.returncode < 0:
                signal_number = -result.returncode
                try:
                    signal_name = signal_module.Signals(signal_number).name
                except ValueError:
                    signal_name = f"UNKNOWN_SIGNAL_{signal_number}"

            return (result.returncode, result.stdout, result.stderr, signal_name, signal_number)

        except subprocess.TimeoutExpired as e:
            logger.warning(
                f"Script execution timed out after {timeout}s - "
                f"script={script_path.name}, timeout={timeout}s"
            )

            stdout = e.stdout.decode("utf-8", errors="replace") if e.stdout else ""
            stderr = e.stderr.decode("utf-8", errors="replace") if e.stderr else ""

            return (
                124,  # Conventional timeout exit code
                stdout,
                stderr + "\nTimeout",
                None,
                None,
            )

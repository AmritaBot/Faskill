"""Tests for the Runner abstraction and HostRunner warning behavior."""

import logging
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from faskill.core.runner import HostRunner, Runner


class TestRunnerABC:
    """Tests for the Runner abstract base class."""

    def test_runner_is_abstract(self):
        """Runner cannot be instantiated directly."""
        with pytest.raises(TypeError):
            Runner()  # type: ignore[abstract]

    def test_host_runner_is_runner(self):
        """HostRunner is a Runner subclass."""
        runner = HostRunner()
        assert isinstance(runner, Runner)


class TestHostRunnerWarning:
    """Tests for HostRunner one-time security warning."""

    def test_first_run_emits_warning(self, caplog):
        """First call to HostRunner.run() emits a security warning."""
        caplog.set_level(logging.WARNING)
        runner = HostRunner()

        # Reset class state for isolated test
        HostRunner._warned = False

        runner.run(
            interpreter="python3",
            script_path=Path("/nonexistent/test.py"),
            arguments_json="{}",
            env=os.environ.copy(),
            cwd=Path("/tmp"),
            timeout=5,
        )

        assert len(caplog.records) >= 1
        warning_messages = [r.message for r in caplog.records if r.levelno == logging.WARNING]
        assert any("HostRunner" in msg for msg in warning_messages)
        assert any("UNSAFE" in msg for msg in warning_messages)

    def test_second_run_suppresses_warning(self, caplog):
        """Second call does NOT emit the warning again."""
        caplog.set_level(logging.WARNING)
        runner = HostRunner()

        # Reset class state
        HostRunner._warned = False

        # First run — should warn
        runner.run(
            interpreter="python3",
            script_path=Path("/nonexistent/test.py"),
            arguments_json="{}",
            env=os.environ.copy(),
            cwd=Path("/tmp"),
            timeout=5,
        )

        warning_count_before = sum(1 for r in caplog.records if "HostRunner" in r.message)

        # Second run — should NOT warn
        runner.run(
            interpreter="python3",
            script_path=Path("/nonexistent/test.py"),
            arguments_json="{}",
            env=os.environ.copy(),
            cwd=Path("/tmp"),
            timeout=5,
        )

        warning_count_after = sum(1 for r in caplog.records if "HostRunner" in r.message)

        # Warning count should not increase
        assert warning_count_after == warning_count_before

    def test_warned_flag_set_after_first_run(self):
        """_warned class flag is True after first invocation."""
        HostRunner._warned = False
        runner = HostRunner()

        assert HostRunner._warned is False

        runner.run(
            interpreter="python3",
            script_path=Path("/nonexistent/test.py"),
            arguments_json="{}",
            env=os.environ.copy(),
            cwd=Path("/tmp"),
            timeout=5,
        )

        assert HostRunner._warned is True

    def test_different_instances_share_warned_flag(self):
        """Different HostRunner instances share the same class-level flag."""
        HostRunner._warned = False

        runner1 = HostRunner()
        runner2 = HostRunner()

        runner1.run(
            interpreter="python3",
            script_path=Path("/nonexistent/a.py"),
            arguments_json="{}",
            env=os.environ.copy(),
            cwd=Path("/tmp"),
            timeout=5,
        )

        # Both should see the flag as True
        assert HostRunner._warned is True

        # Second runner should NOT emit a warning on first call
        with patch.object(logging.getLogger("faskill.core.runner"), "warning") as mock_warn:
            runner2.run(
                interpreter="python3",
                script_path=Path("/nonexistent/b.py"),
                arguments_json="{}",
                env=os.environ.copy(),
                cwd=Path("/tmp"),
                timeout=5,
            )
            # No HostRunner warning calls from runner2
            hostrunner_calls = [c for c in mock_warn.call_args_list if "HostRunner" in str(c)]
            assert len(hostrunner_calls) == 0


class TestHostRunnerExecution:
    """Tests for HostRunner execution behavior."""

    def test_run_executes_command(self, tmp_path):
        """HostRunner actually runs the command."""
        script = tmp_path / "hello.py"
        script.write_text("print('hello from host runner')")

        runner = HostRunner()
        # Force warned to True to avoid test noise
        HostRunner._warned = True

        exit_code, stdout, stderr, sig_name, sig_num = runner.run(
            interpreter="python3",
            script_path=script,
            arguments_json="{}",
            env=os.environ.copy(),
            cwd=tmp_path,
            timeout=10,
        )

        assert exit_code == 0
        assert "hello from host runner" in stdout
        assert sig_name is None
        assert sig_num is None

    def test_run_passes_stdin_json(self, tmp_path):
        """Arguments JSON is passed to the script via stdin."""
        script = tmp_path / "echo_args.py"
        script.write_text("import sys, json; d=json.load(sys.stdin); print(d.get('key'))")

        runner = HostRunner()
        HostRunner._warned = True

        exit_code, stdout, stderr, sig_name, sig_num = runner.run(
            interpreter="python3",
            script_path=script,
            arguments_json='{"key": "stdin_value"}',
            env=os.environ.copy(),
            cwd=tmp_path,
            timeout=10,
        )

        assert exit_code == 0
        assert "stdin_value" in stdout

    def test_run_returns_error_on_failure(self, tmp_path):
        """Non-zero exit code is returned correctly."""
        script = tmp_path / "fail.py"
        script.write_text("import sys; sys.exit(42)")

        runner = HostRunner()
        HostRunner._warned = True

        exit_code, stdout, stderr, sig_name, sig_num = runner.run(
            interpreter="python3",
            script_path=script,
            arguments_json="{}",
            env=os.environ.copy(),
            cwd=tmp_path,
            timeout=10,
        )

        assert exit_code == 42

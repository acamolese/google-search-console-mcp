"""The CLI is what users type when the MCP client will not start."""

from __future__ import annotations

import os
import subprocess
import sys

import pytest

ENTRY = [sys.executable, "-m", "google_search_console_mcp"]


def run(args, env_overrides=None, cwd=None, timeout=60):
    """Run the CLI with every credential source pointed somewhere empty."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GSC_")}
    env["GOOGLE_APPLICATION_CREDENTIALS"] = "/nonexistent/adc.json"
    env.update(env_overrides or {})
    return subprocess.run(  # noqa: S603 - fixed argv, no shell
        ENTRY + args,
        capture_output=True,
        text=True,
        env=env,
        # config.legacy_creds_dir() resolves against the CWD, so never run from the repo.
        cwd=str(cwd) if cwd else None,
        timeout=timeout,
        check=False,
    )


def test_help_exits_cleanly_and_lists_the_commands():
    result = run(["--help"])
    assert result.returncode == 0
    for command in ("serve", "auth", "doctor", "version"):
        assert command in result.stdout


def test_version_prints_the_package_version():
    from google_search_console_mcp import __version__

    result = run(["version"])
    assert result.returncode == 0
    assert result.stdout.strip() == __version__


def test_an_unknown_command_fails_with_usage():
    result = run(["nonsense"])
    assert result.returncode != 0
    assert "usage" in result.stderr.lower()


@pytest.mark.skipif(sys.platform == "win32", reason="XDG paths are POSIX-only")
def test_doctor_without_credentials_exits_one_and_names_the_three_options(tmp_path):
    result = run(["doctor"], env_overrides={"XDG_CONFIG_HOME": str(tmp_path)}, cwd=tmp_path)

    assert result.returncode == 1
    assert "mcp-google-search-console" in result.stdout
    assert "Auth" in result.stdout
    assert "GSC_REFRESH_TOKEN" in result.stderr
    assert "GSC_SERVICE_ACCOUNT_FILE" in result.stderr
    assert "mcp-google-search-console auth" in result.stderr


@pytest.mark.skipif(sys.platform == "win32", reason="XDG paths are POSIX-only")
def test_doctor_reports_the_defaults_even_when_broken(tmp_path):
    result = run(["doctor"], env_overrides={"XDG_CONFIG_HOME": str(tmp_path)}, cwd=tmp_path)

    assert "data_state" in result.stdout
    assert "report_language" in result.stdout
    assert "config_dir" in result.stdout

"""The manifests ship the plugin, the bundle and the registry entry.

2.0.3 went out with pyproject saying 2.0.3 and PyPI at 2.0.2, which the MCP
registry rejects. There are five manifests now, so this is checked, not eyeballed.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE = REPO_ROOT / "src" / "google_search_console_mcp"

MANIFESTS = (
    "server.json",
    ".claude-plugin/plugin.json",
    ".claude-plugin/marketplace.json",
    ".cursor-plugin/plugin.json",
    "mcpb/manifest.json",
    ".mcp.json",
)

SKILLS_DIR = REPO_ROOT / "skills"
EXPECTED_SKILLS = {
    "gsc-weekly-report",
    "gsc-cannibalization-check",
    "gsc-indexing-audit",
    "gsc-content-opportunities",
    "gsc-client-audit",
}

FRONTMATTER = re.compile(r"^---\n(.*?)\n---\n", re.S)


def load(relative: str) -> dict:
    return json.loads((REPO_ROOT / relative).read_text(encoding="utf-8"))


@pytest.mark.parametrize("relative", MANIFESTS)
def test_every_manifest_is_valid_json(relative):
    assert isinstance(load(relative), dict)


def test_every_manifest_declares_the_same_version():
    result = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [sys.executable, str(REPO_ROOT / "scripts" / "sync_versions.py")],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_the_declared_version_matches_the_package():
    from google_search_console_mcp import __version__

    assert load("server.json")["version"] == __version__


def test_the_registry_description_fits_the_hundred_character_limit():
    assert len(load("server.json")["description"]) <= 100


def test_the_registry_entry_marks_the_secrets_as_secret():
    declared = load("server.json")["packages"][0]["environmentVariables"]
    variables = {entry["name"]: entry for entry in declared}
    assert variables["GSC_CLIENT_SECRET"]["isSecret"] is True
    assert variables["GSC_REFRESH_TOKEN"]["isSecret"] is True
    assert variables["GSC_CLIENT_ID"].get("isSecret") is not True


def test_the_plugin_points_at_an_mcp_config_that_exists():
    plugin = load(".claude-plugin/plugin.json")
    # removeprefix, not lstrip: the target is ".mcp.json" and lstrip eats the dot.
    referenced = REPO_ROOT / plugin["mcpServers"].removeprefix("./")
    assert referenced.exists()


def test_the_plugin_marks_the_secrets_as_sensitive():
    config = load(".claude-plugin/plugin.json")["userConfig"]
    assert config["client_secret"]["sensitive"] is True
    assert config["refresh_token"]["sensitive"] is True
    assert config["report_language"]["default"] == "en"


def test_the_mcp_config_maps_user_config_to_the_environment():
    env = load(".mcp.json")["mcpServers"]["google-search-console"]["env"]
    assert env["GSC_CLIENT_ID"] == "${user_config.client_id}"
    assert env["GSC_REFRESH_TOKEN"] == "${user_config.refresh_token}"
    assert load(".mcp.json")["mcpServers"]["google-search-console"]["command"] == "uvx"


def test_the_marketplace_points_at_this_repository():
    marketplace = load(".claude-plugin/marketplace.json")
    assert marketplace["description"]
    entry = marketplace["plugins"][0]
    assert entry["name"] == load(".claude-plugin/plugin.json")["name"]
    assert (REPO_ROOT / entry["source"]).is_dir()


def test_the_bundle_manifest_lists_every_registered_tool():
    import asyncio

    from google_search_console_mcp._compat import FastMCP
    from google_search_console_mcp.tools import register_all

    server = FastMCP("packaging-test")
    register_all(server)
    registered = {tool.name for tool in asyncio.run(server.list_tools())}
    declared = {tool["name"] for tool in load("mcpb/manifest.json")["tools"]}

    assert declared == registered


def test_the_bundle_ships_an_icon():
    icon = REPO_ROOT / "mcpb" / load("mcpb/manifest.json")["icon"]
    assert icon.exists()
    assert icon.stat().st_size > 0


def test_the_bundle_documents_that_uv_is_required():
    manifest = load("mcpb/manifest.json")
    assert manifest["server"]["mcp_config"]["command"] == "uvx"
    assert "uv" in manifest["long_description"].lower()


@pytest.mark.parametrize("name", sorted(EXPECTED_SKILLS))
def test_every_skill_has_usable_frontmatter(name):
    path = SKILLS_DIR / name / "SKILL.md"
    assert path.exists()

    text = path.read_text(encoding="utf-8")
    match = FRONTMATTER.match(text)
    assert match, f"{name} has no frontmatter"

    fields = dict(
        line.split(":", 1) for line in match.group(1).splitlines() if ":" in line and not line.startswith(" ")
    )
    assert fields["name"].strip() == name
    description = fields["description"].strip()
    assert len(description) > 60, "a description this short will not match a user's request"
    assert "use when" in description.lower()


def test_no_skill_is_long_enough_to_crowd_the_context():
    for name in EXPECTED_SKILLS:
        text = (SKILLS_DIR / name / "SKILL.md").read_text(encoding="utf-8")
        # Roughly four characters per token.
        assert len(text) < 6_000, f"{name} is {len(text)} characters"


def test_skills_only_name_tools_that_exist():
    import asyncio

    from google_search_console_mcp._compat import FastMCP
    from google_search_console_mcp.tools import register_all

    server = FastMCP("packaging-test")
    register_all(server)
    registered = {tool.name for tool in asyncio.run(server.list_tools())}

    for name in EXPECTED_SKILLS:
        text = (SKILLS_DIR / name / "SKILL.md").read_text(encoding="utf-8")
        mentioned = set(re.findall(r"`(gsc_[a-z_]+)`", text))
        assert mentioned <= registered, f"{name} names unknown tools: {mentioned - registered}"


def test_the_wheel_carries_the_data_files_the_report_needs():
    """A missing template or translation only shows up after publishing."""
    for relative in (
        "templates/report.html.j2",
        "static/chart.umd.min.js",
        "static/CHART_LICENSE",
        "i18n/en.json",
        "i18n/it.json",
        "branding.json",
    ):
        assert (PACKAGE / relative).exists(), relative


def test_the_docker_image_runs_as_a_non_root_user():
    dockerfile = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "USER gsc" in dockerfile
    assert "MCP_TRANSPORT=streamable-http" in dockerfile

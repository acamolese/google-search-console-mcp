"""Contract checks on the tool surface itself."""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "google_search_console_mcp"

# The stdio transport owns stdout; only the CLI and the interactive OAuth flow
# are allowed to write there.
STDOUT_ALLOWED = {"__main__.py", "oauth.py"}

EXPECTED_TOOLS = {
    "gsc_alerts",
    "gsc_audit",
    "gsc_cannibalization",
    "gsc_compare_periods",
    "gsc_content_decay",
    "gsc_ctr_gaps",
    "gsc_doctor",
    "gsc_indexing_issues",
    "gsc_inspect_url",
    "gsc_performance_overview",
    "gsc_portfolio",
    "gsc_query",
    "gsc_quick_wins",
    "gsc_site_details",
    "gsc_sitemaps",
    "gsc_sites",
    "gsc_traffic_drops",
}


async def test_every_expected_tool_is_registered(server):
    names = {tool.name for tool in await server.list_tools()}
    assert names >= EXPECTED_TOOLS


def hint(annotations, name: str):
    """Field names are camelCase on mcp 1.x and snake_case on 2.x."""
    snake = "".join("_" + c.lower() if c.isupper() else c for c in name)
    for candidate in (name, snake):
        if hasattr(annotations, candidate):
            return getattr(annotations, candidate)
    raise AssertionError(f"no {name} on {annotations!r}")


async def test_every_tool_is_annotated_read_only_with_a_title(server):
    for tool in await server.list_tools():
        annotations = tool.annotations
        assert annotations is not None, f"{tool.name} has no annotations"
        assert annotations.title, f"{tool.name} has no title"
        assert hint(annotations, "readOnlyHint") is True, tool.name
        assert hint(annotations, "destructiveHint") is False, tool.name
        assert hint(annotations, "openWorldHint") is True, tool.name
        assert hint(annotations, "idempotentHint") is True, tool.name


async def test_every_tool_has_a_description_within_the_context_budget(server):
    for tool in await server.list_tools():
        assert tool.description, f"{tool.name} has no description"
        assert len(tool.description) < 1200, f"{tool.name} description is {len(tool.description)} chars"


async def test_every_tool_documents_its_required_arguments(server):
    for tool in await server.list_tools():
        # The field is camelCase on mcp 1.x and snake_case on 2.x.
        schema = getattr(tool, "inputSchema", None) or tool.input_schema
        for name in schema.get("properties", {}):
            assert name.islower() or "_" in name, f"{tool.name}.{name} is not snake_case"


async def test_the_server_instructions_stay_short():
    from google_search_console_mcp.server import INSTRUCTIONS

    assert len(INSTRUCTIONS) <= 900
    assert "sc-domain:" in INSTRUCTIONS
    assert "28 days" in INSTRUCTIONS


def _writes_to_stdout(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    offenders = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "print":
            offenders.append(f"{path.name}:{node.lineno}")
        if isinstance(node, ast.Attribute) and node.attr == "write":
            value = node.value
            if isinstance(value, ast.Attribute) and value.attr == "stdout":
                offenders.append(f"{path.name}:{node.lineno}")
    return offenders


def test_no_module_on_the_server_path_writes_to_stdout():
    offenders = []
    for path in sorted(SRC.rglob("*.py")):
        if path.name in STDOUT_ALLOWED:
            continue
        offenders.extend(_writes_to_stdout(path))
    assert offenders == []

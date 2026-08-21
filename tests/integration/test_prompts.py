"""Prompts have to list, interpolate and name tools that exist."""

from __future__ import annotations

import re

import pytest

EXPECTED = {"gsc_weekly_report", "gsc_indexing_audit", "gsc_content_opportunities"}


@pytest.fixture
def prompt_server():
    from google_search_console_mcp._compat import FastMCP
    from google_search_console_mcp.prompts import register_all
    from google_search_console_mcp.tools import register_all as register_tools

    server = FastMCP("google-search-console-test")
    register_tools(server)
    register_all(server)
    return server


async def get_prompt_text(server, name, arguments):
    result = await server.get_prompt(name, arguments)
    return "\n".join(getattr(message.content, "text", "") for message in getattr(result, "messages", []))


async def test_all_three_prompts_are_listed_with_their_argument(prompt_server):
    prompts = await prompt_server.list_prompts()
    by_name = {prompt.name: prompt for prompt in prompts}

    assert set(by_name) == EXPECTED
    for prompt in prompts:
        assert prompt.description
        assert [argument.name for argument in prompt.arguments or []] == ["site_url"]


@pytest.mark.parametrize("name", sorted(EXPECTED))
async def test_the_property_is_interpolated_into_the_prompt(prompt_server, name):
    text = await get_prompt_text(prompt_server, name, {"site_url": "sc-domain:example.com"})
    assert "sc-domain:example.com" in text


@pytest.mark.parametrize("name", sorted(EXPECTED))
async def test_prompts_only_name_tools_that_exist(prompt_server, name):
    text = await get_prompt_text(prompt_server, name, {"site_url": "sc-domain:example.com"})
    registered = {tool.name for tool in await prompt_server.list_tools()}

    mentioned = set(re.findall(r"`(gsc_[a-z_]+)`", text))
    assert mentioned, f"{name} names no tool"
    assert mentioned <= registered, f"{name} names unknown tools: {mentioned - registered}"


async def test_the_weekly_review_tells_the_model_not_to_invent_causes(prompt_server):
    text = await get_prompt_text(prompt_server, "gsc_weekly_report", {"site_url": "sc-domain:example.com"})
    assert "do not invent" in text.lower()
    assert "diagnosis" in text.lower()

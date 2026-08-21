"""`gsc_doctor`: what is configured, what works, and what is missing."""

from __future__ import annotations

import os
import platform

from .. import config
from .._compat import MCP_MAJOR, mcp_version
from ..errors import GSCError
from ..models import Doctor
from ._common import annotations, client, tool_errors


def collect(transport: str = "stdio") -> Doctor:
    """The offline half of the report: no API call, so it never raises."""
    from .. import __version__

    settings = config.Settings.from_env()
    gsc = client()

    return Doctor(
        package_version=__version__,
        mcp_version=mcp_version(),
        mcp_major=MCP_MAJOR,
        python_version=platform.python_version(),
        platform=f"{platform.system()} {platform.release()} ({platform.machine()})",
        transport=transport,
        auth=gsc.provider.describe(),
        properties={"status": "not_checked"},
        cache=gsc.stats(),
        defaults={
            "data_state": settings.data_state,
            "report_language": settings.report_language,
            "cache_ttl_seconds": settings.cache_ttl_seconds,
            "inspect_concurrency": settings.inspect_concurrency,
            "default_days": 28,
        },
        paths={
            "config_dir": str(config.config_dir()),
            "token_file": str(config.token_file_path()),
            "token_file_exists": config.token_file_path().exists(),
        },
    )


async def collect_async(transport: str = "stdio") -> Doctor:
    """The full report: adds the property count, which needs one API call."""
    doctor = collect(transport)
    if doctor.auth.get("status") != "ok":
        doctor.properties = {"status": "skipped", "detail": "no usable credentials"}
        return doctor
    try:
        doctor.properties = {"status": "ok", "accessible": len(await client().list_sites())}
    except GSCError as exc:
        doctor.properties = {"status": "error", "detail": str(exc)}
    # Re-read the counters so they include the probe above.
    doctor.cache = client().stats()
    return doctor


def as_text(doctor: Doctor) -> str:
    """The same report as plain text, for the CLI."""
    lines = [
        f"mcp-google-search-console {doctor.package_version}",
        f"  mcp SDK        {doctor.mcp_version} (major {doctor.mcp_major})",
        f"  Python         {doctor.python_version}",
        f"  Platform       {doctor.platform}",
        f"  Transport      {doctor.transport}",
        "",
        "Auth",
    ]
    for key, value in doctor.auth.items():
        lines.append(f"  {key:<14} {value}")
    lines.extend(["", "Properties"])
    for key, value in doctor.properties.items():
        lines.append(f"  {key:<14} {value}")
    lines.extend(["", "Defaults"])
    for key, value in doctor.defaults.items():
        lines.append(f"  {key:<14} {value}")
    lines.extend(["", "Paths"])
    for key, value in doctor.paths.items():
        lines.append(f"  {key:<14} {value}")
    return "\n".join(lines)


def register(mcp) -> None:
    @mcp.tool(annotations=annotations("Server diagnostics"))
    @tool_errors
    async def gsc_doctor() -> Doctor:
        """Report the server's configuration and whether Search Console answers.

        Call this first when something fails: it names the auth mode in use, when the
        token expires, how many properties the account can read, the cache state and
        the defaults every other tool applies. Secrets are masked.
        """
        return await collect_async(os.environ.get("MCP_TRANSPORT", "stdio"))

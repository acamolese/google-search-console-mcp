# Architecture

## Layers

```
tools/            MCP surface: argument validation, formatting, error mapping
  ├── analytics, inspection, sitemaps, sites   the API, one module per area
  ├── insights                                 one tool per analysis rule
  ├── audit                                    the HTML report
  └── diagnostics                              gsc_doctor
insights/         pure functions over normalized rows. No I/O, no HTTP, no dates
audit/            collect → issues → strategy → render
i18n/             one JSON per language, same keys, translation at render time
client.py         the only place that talks to Google: retries, cache, semaphore
auth/             credentials once per process, refreshed under a lock
dates.py          period names and the 16-month window, resolved in UTC
formatting.py     TSV and JSON, the `# meta ...` header, rounding
errors.py         Google's error body → a message the caller can act on
_compat.py        the only module that knows mcp 1.x from 2.x
```

The direction of dependency is one-way: `tools/` knows about `insights/`, never
the reverse. `insights/` does no I/O at all, which is why its tests need no HTTP
mock and run on synthetic data.

## Why the analysis is not in the tools

Every rule is used twice: once by its own tool and once by the audit report. If
the logic lived in the tool, the report would need a second copy, and the two
would drift. Putting the rules in pure functions means a threshold change lands
in both at once, and a test can pin the exact numbers a rule produces without
standing up a server.

## Why the report emits keys, not sentences

The 2.x report was Italian-only because the copy was written into the detection
code. Rules now return `("issue.http_pages", {"n": 3, "clicks": 812})`, and the
renderer resolves that against the requested language. Adding a third language is
one JSON file, not a fork of the analysis.

## What the client owns

Every Google call goes through `GSCClient`, so retries, caching, quota handling
and the inspection concurrency cap are implemented once. Tools never construct a
URL or a header. This is also what makes `respx` sufficient to test the whole
stack: mock the transport and everything above it is real code.

## Transport and stdout

The stdio transport uses stdout for the protocol, so any stray `print()` in the
server path corrupts the stream in a way that surfaces as an unexplained
disconnect. Logging goes to stderr, and a test walks the AST of every module to
prove nothing prints. The two exceptions, `__main__.py` and `auth/oauth.py`, only
run as CLI commands, never while serving.

## SDK compatibility

`mcp` 2.0.0 renamed the high-level server class and moved its module. `_compat.py`
resolves that once and re-exports under a single name; nothing else imports
`mcp.server.*`. CI runs the full suite against both majors, which is the only way
to know the shim still holds.

## Caching

Search Console data changes once a day at best, and Google explicitly asks
clients not to repeat identical queries. Responses are cached in memory for six
hours, keyed on method, URL and body; inspections get one hour, because a fix and
a re-check inside the same session is a normal thing to do. `no_cache=true`
bypasses it per call, and the meta line of every response says whether the answer
came from the cache.

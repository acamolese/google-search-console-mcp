# Build the wheel in one stage so the runtime image carries no build tooling.
FROM python:3.12-slim AS build

WORKDIR /src
RUN pip install --no-cache-dir build
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN python -m build --wheel --outdir /dist

FROM python:3.12-slim

LABEL org.opencontainers.image.title="mcp-google-search-console" \
      org.opencontainers.image.description="MCP server for Google Search Console: performance queries, indexing checks and white-label SEO audits." \
      org.opencontainers.image.source="https://github.com/acamolese/google-search-console-mcp" \
      org.opencontainers.image.licenses="MIT"

COPY --from=build /dist/*.whl /tmp/
RUN pip install --no-cache-dir /tmp/*.whl && rm -f /tmp/*.whl

# Credentials arrive as environment variables, so the container never needs a
# writable home for tokens. Reports go to the mounted volume.
RUN useradd --create-home --uid 10001 gsc \
    && mkdir -p /reports \
    && chown gsc:gsc /reports
USER gsc
WORKDIR /home/gsc
VOLUME ["/reports"]

ENV MCP_TRANSPORT=streamable-http \
    MCP_HOST=0.0.0.0 \
    MCP_PORT=8765 \
    PYTHONUNBUFFERED=1
EXPOSE 8765

ENTRYPOINT ["mcp-google-search-console"]
CMD ["serve"]
